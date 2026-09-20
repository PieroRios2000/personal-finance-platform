"""Tests for scripts.openmetadata_sync: dbt artifacts -> OpenMetadata (T24, ADR 0023).

Pure logic only -- tiny hand-built manifest/catalog/lineage documents, no OpenMetadata
server and no S3. The live behaviour (a real column-level lineage response from a
running server) is what the PR's verification section shows; these tests pin the
transformations that make it possible, each of which fails without the code under test.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from scripts import openmetadata_sync as om

_SILVER = "model.personal_finance_platform.transactions"
_GOLD = "model.personal_finance_platform.fact_transactions"
_ELEMENTARY = "model.elementary.dbt_run_results"
_BRONZE = "source.personal_finance_platform.bronze.transactions"


def _manifest() -> dict[str, Any]:
    return {
        "nodes": {
            _SILVER: {
                "package_name": "personal_finance_platform",
                "compiled_code": "select amount from delta_scan('s3://lakehouse/bronze/transactions')",
                "raw_code": "select amount from {{ source('bronze', 'transactions') }}",
            },
            _GOLD: {
                "package_name": "personal_finance_platform",
                "compiled_code": 'select amount from "pfp"."silver"."transactions"',
            },
            _ELEMENTARY: {"package_name": "elementary", "compiled_code": "select 1"},
        },
        "sources": {
            _BRONZE: {
                "database": "pfp",
                "schema": "bronze",
                "identifier": "transactions",
                "relation_name": "delta_scan('s3://lakehouse/bronze/transactions')",
            }
        },
    }


def _catalog() -> dict[str, Any]:
    def node(schema: str, name: str, *columns: tuple[str, str]) -> dict[str, Any]:
        return {
            "metadata": {"schema": schema, "name": name, "database": "pfp"},
            "columns": {
                col: {"name": col, "type": typ, "index": i}
                for i, (col, typ) in enumerate(columns, start=1)
            },
        }

    return {
        "nodes": {
            _SILVER: node("silver", "transactions", ("amount", "DECIMAL(18,2)")),
            _GOLD: node(
                "gold",
                "fact_transactions",
                ("amount", "DECIMAL(18,2)"),
                ("flow_type", "VARCHAR"),
            ),
            _ELEMENTARY: node("elementary", "dbt_run_results", ("id", "VARCHAR")),
        }
    }


def test_om_column_maps_decimal_with_precision_and_scale() -> None:
    column = om.om_column("amount", "DECIMAL(18,2)", 5)
    assert column == {
        "name": "amount",
        "dataType": "DECIMAL",
        "dataTypeDisplay": "DECIMAL(18,2)",
        "ordinalPosition": 5,
        "precision": 18,
        "scale": 2,
    }


def test_om_column_varchar_gets_the_length_openmetadata_requires() -> None:
    assert om.om_column("bank", "VARCHAR", 1)["dataLength"] == 1


def test_om_column_timestamp_with_time_zone_is_a_timestamp() -> None:
    column = om.om_column("ingested_at", "TIMESTAMP WITH TIME ZONE", 2)
    assert column["dataType"] == "TIMESTAMP"
    assert column["dataTypeDisplay"] == "TIMESTAMP WITH TIME ZONE"


def test_om_column_unknown_type_fails_loudly_instead_of_guessing() -> None:
    with pytest.raises(ValueError, match="GEOMETRY"):
        om.om_column("shape", "GEOMETRY", 1)


def test_bronze_tables_come_from_the_lakehouse_schema_not_from_dbt() -> None:
    # dbt's catalog can't see bronze (delta_scan() isn't a DuckDB relation), so the
    # columns come from the pyarrow schema bronze is written with.
    tables = om.bronze_tables(_manifest())
    assert [(t.schema, t.name) for t in tables] == [("bronze", "transactions")]
    amount = next(c for c in tables[0].columns if c["name"] == "amount")
    assert (amount["dataType"], amount["precision"], amount["scale"]) == (
        "DECIMAL",
        18,
        2,
    )


def test_bronze_tables_rejects_a_source_the_lakehouse_does_not_define() -> None:
    manifest = _manifest()
    manifest["sources"][_BRONZE]["identifier"] = "not_a_bronze_table"
    with pytest.raises(ValueError, match="not_a_bronze_table"):
        om.bronze_tables(manifest)


def test_resolve_sources_swaps_the_physical_path_for_the_logical_name() -> None:
    resolved = om.resolve_sources(_manifest())
    assert (
        resolved["nodes"][_SILVER]["compiled_code"]
        == 'select amount from "pfp"."bronze"."transactions"'
    )


def test_resolve_sources_touches_only_compiled_code_and_leaves_the_input_alone() -> (
    None
):
    manifest = _manifest()
    resolved = om.resolve_sources(manifest)
    assert (
        resolved["nodes"][_SILVER]["raw_code"] == manifest["nodes"][_SILVER]["raw_code"]
    )
    assert resolved["nodes"][_GOLD] == manifest["nodes"][_GOLD]
    assert "delta_scan" in manifest["nodes"][_SILVER]["compiled_code"]


def test_workflow_config_points_at_the_mounted_artifacts_and_scopes_the_schemas() -> (
    None
):
    config = om.workflow_config(service="pfp_postgres", database="pfp", token="tok")
    source_config = config["source"]["sourceConfig"]["config"]
    assert config["source"]["serviceName"] == "pfp_postgres"
    assert source_config["dbtConfigSource"] == {
        "dbtConfigType": "local",
        "dbtManifestFilePath": "/opt/pfp-artifacts/manifest.json",
        "dbtCatalogFilePath": "/opt/pfp-artifacts/catalog.json",
    }
    assert source_config["schemaFilterPattern"] == {
        "includes": ["^bronze$", "^silver$", "^gold$"]
    }
    assert config["workflowConfig"]["openMetadataServerConfig"]["securityConfig"] == {
        "jwtToken": "tok"
    }


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def put(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("PUT", path, body))
        return {}


_POSTGRES = {"host_port": "postgres:5432", "user": "pfp", "password": "s3cret"}


def test_postgres_service_is_a_native_connection_not_a_custom_one() -> None:
    body = om.postgres_service("pfp_postgres", database="pfp", **_POSTGRES)
    assert body["serviceType"] == "Postgres"
    assert body["connection"]["config"] == {
        "type": "Postgres",
        "hostPort": "postgres:5432",
        "username": "pfp",
        "authType": {"password": "s3cret"},
        "database": "pfp",
    }


def test_postgres_workflow_ingests_only_silver_and_gold_with_the_native_connector() -> (
    None
):
    config = om.postgres_workflow(
        "pfp_postgres", database="pfp", token="tok", **_POSTGRES
    )
    source = config["source"]
    assert source["type"] == "postgres"
    assert source["serviceName"] == "pfp_postgres"
    assert source["serviceConnection"]["config"]["hostPort"] == "postgres:5432"
    # Bronze is not in Postgres: leaving it out of the filter keeps the connector from
    # touching (or marking deleted) the tables `sync` registered for it.
    assert source["sourceConfig"]["config"]["schemaFilterPattern"] == {
        "includes": ["^silver$", "^gold$"]
    }
    assert config["workflowConfig"]["openMetadataServerConfig"]["securityConfig"] == {
        "jwtToken": "tok"
    }


def test_register_bronze_puts_service_database_schema_then_tables() -> None:
    client = _FakeClient()
    tables = om.bronze_tables(_manifest())
    service = om.postgres_service("pfp_postgres", database="pfp", **_POSTGRES)
    om.register_bronze(client, service=service, database="pfp", tables=tables)
    assert [(path, body["name"]) for _, path, body in client.calls] == [
        ("/services/databaseServices", "pfp_postgres"),
        ("/databases", "pfp"),
        ("/databaseSchemas", "bronze"),
        ("/tables", "transactions"),
    ]
    assert client.calls[-1][2]["databaseSchema"] == "pfp_postgres.pfp.bronze"


def _lineage() -> dict[str, Any]:
    """The shape `GET /api/v1/lineage/getLineage` really returns (2.0.2)."""

    def edge(src: str, dst: str, *pairs: tuple[str, str]) -> dict[str, Any]:
        return {
            "fromEntity": {"id": f"id-{src}"},
            "toEntity": {"id": f"id-{dst}"},
            "columns": [{"fromColumns": [a], "toColumn": b} for a, b in pairs],
        }

    return {
        "nodes": {
            name: {"entity": {"id": f"id-{name}"}} for name in ("b.t", "s.t", "g.t")
        },
        "upstreamEdges": {
            "s->g": edge("s.t", "g.t", ("s.t.amount", "g.t.amount")),
            "b->s": edge("b.t", "s.t", ("b.t.amount", "s.t.amount")),
        },
    }


def test_column_paths_walks_every_hop_back_to_the_root_column() -> None:
    assert om.column_paths(_lineage(), "g.t.amount") == [
        ["b.t.amount", "s.t.amount", "g.t.amount"]
    ]


def test_column_paths_stops_where_the_column_lineage_stops() -> None:
    lineage = _lineage()
    lineage["upstreamEdges"]["b->s"]["columns"] = []
    assert om.column_paths(lineage, "g.t.amount") == [["s.t.amount", "g.t.amount"]]


def test_column_paths_returns_nothing_for_an_unrelated_column() -> None:
    assert om.column_paths(_lineage(), "g.t.flow_type") == []


class _FakeServer(_FakeClient):
    """Stands in for `om.OpenMetadata`: records PUTs, serves a canned lineage."""

    lineage: dict[str, Any] = {}

    def __init__(self, host: str) -> None:
        super().__init__()
        self.host = host

    def login(self) -> str:
        return "tok"

    def upstream_lineage(self, table_fqn: str) -> dict[str, Any]:
        return self.lineage


def _write_artifacts(target: Path) -> None:
    target.mkdir()
    (target / "manifest.json").write_text(json.dumps(_manifest()))
    (target / "catalog.json").write_text(json.dumps(_catalog()))


@pytest.fixture(autouse=True)
def _postgres_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PFP_PG_USER", "pfp")
    monkeypatch.setenv("PFP_PG_PASSWORD", "s3cret")


def test_sync_writes_the_ingestion_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(om, "OpenMetadata", _FakeServer)
    _write_artifacts(tmp_path / "target")
    out = tmp_path / "artifacts"
    assert (
        om.main(["sync", "--target-path", str(tmp_path / "target"), "--out", str(out)])
        == 0
    )
    manifest = json.loads((out / "manifest.json").read_text())
    assert "delta_scan" not in manifest["nodes"][_SILVER]["compiled_code"]
    assert json.loads((out / "catalog.json").read_text()) == _catalog()
    config = json.loads((out / "dbt-workflow.yaml").read_text())
    assert config["workflowConfig"]["openMetadataServerConfig"]["securityConfig"] == {
        "jwtToken": "tok"
    }
    postgres = json.loads((out / "postgres-workflow.yaml").read_text())
    assert postgres["source"]["type"] == "postgres"
    assert postgres["source"]["serviceConnection"]["config"]["authType"] == {
        "password": "s3cret"
    }


def test_sync_without_the_postgres_credentials_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PFP_PG_PASSWORD")
    monkeypatch.setattr(om, "OpenMetadata", _FakeServer)
    _write_artifacts(tmp_path / "target")
    assert om.main(["sync", "--target-path", str(tmp_path / "target")]) == 2


def test_sync_without_dbt_artifacts_exits_2(tmp_path: Path) -> None:
    assert om.main(["sync", "--target-path", str(tmp_path / "missing")]) == 2


def _bronze_to_gold_lineage() -> dict[str, Any]:
    prefix = "pfp_postgres.pfp."
    return {
        "upstreamEdges": {
            "edge": {
                "columns": [
                    {
                        "fromColumns": [f"{prefix}bronze.transactions.amount"],
                        "toColumn": f"{prefix}gold.fact_transactions.amount",
                    }
                ]
            }
        }
    }


def test_check_passes_when_column_lineage_reaches_bronze(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_FakeServer, "lineage", _bronze_to_gold_lineage())
    monkeypatch.setattr(om, "OpenMetadata", _FakeServer)
    assert om.main(["check"]) == 0


def test_check_fails_when_the_column_chain_stops_short_of_bronze(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lineage = _bronze_to_gold_lineage()
    lineage["upstreamEdges"]["edge"]["columns"][0]["fromColumns"] = [
        "pfp_postgres.pfp.silver.transactions.amount"
    ]
    monkeypatch.setattr(_FakeServer, "lineage", lineage)
    monkeypatch.setattr(om, "OpenMetadata", _FakeServer)
    assert om.main(["check"]) == 1


def test_sync_with_a_malformed_artifact_exits_2_not_a_traceback(tmp_path: Path) -> None:
    target = tmp_path / "target"
    _write_artifacts(target)
    (target / "manifest.json").write_text("{not json")
    assert om.main(["sync", "--target-path", str(target)]) == 2


def test_sync_with_a_manifest_that_has_no_sources_exits_2(tmp_path: Path) -> None:
    target = tmp_path / "target"
    _write_artifacts(target)
    manifest = _manifest()
    manifest["sources"] = {}
    (target / "manifest.json").write_text(json.dumps(manifest))
    assert om.main(["sync", "--target-path", str(target)]) == 2


def test_column_paths_terminates_on_a_lineage_cycle() -> None:
    lineage = {
        "upstreamEdges": {
            "a": {"columns": [{"fromColumns": ["t.b"], "toColumn": "t.a"}]},
            "b": {"columns": [{"fromColumns": ["t.a"], "toColumn": "t.b"}]},
        }
    }
    assert om.column_paths(lineage, "t.a") == [["t.b", "t.a"]]


def test_check_fails_when_lineage_is_table_level_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_FakeServer, "lineage", {"upstreamEdges": {"edge": {}}})
    monkeypatch.setattr(om, "OpenMetadata", _FakeServer)
    assert om.main(["check"]) == 1


def test_check_exits_2_when_the_server_reply_is_not_usable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Broken(_FakeServer):
        def upstream_lineage(self, table_fqn: str) -> dict[str, Any]:
            raise ValueError("not json")

    monkeypatch.setattr(om, "OpenMetadata", _Broken)
    assert om.main(["check"]) == 2
