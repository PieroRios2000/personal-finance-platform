"""Tests for scripts.openmetadata_sync: dbt artifacts -> OpenMetadata (T24, ADR 0023).

Pure logic only -- tiny hand-built manifest/catalog/lineage documents, no OpenMetadata
server and no S3. The live behaviour (a real column-level lineage response from a
running server) is what the PR's verification section shows; these tests pin the
transformations that make it possible, each of which fails without the code under test.
"""

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


def test_catalog_tables_keeps_project_models_and_drops_elementarys_own() -> None:
    tables = om.catalog_tables(_manifest(), _catalog())
    assert [(t.schema, t.name) for t in tables] == [
        ("silver", "transactions"),
        ("gold", "fact_transactions"),
    ]
    assert [c["name"] for c in tables[1].columns] == ["amount", "flow_type"]
    assert [c["ordinalPosition"] for c in tables[1].columns] == [1, 2]


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
    config = om.workflow_config(service="pfp_duckdb", database="pfp", token="tok")
    source_config = config["source"]["sourceConfig"]["config"]
    assert config["source"]["serviceName"] == "pfp_duckdb"
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


def test_register_creates_service_database_schemas_then_tables_in_that_order() -> None:
    client = _FakeClient()
    tables = om.catalog_tables(_manifest(), _catalog())
    om.register(client, service="pfp_duckdb", database="pfp", tables=tables)
    assert [(path, body["name"]) for _, path, body in client.calls] == [
        ("/services/databaseServices", "pfp_duckdb"),
        ("/databases", "pfp"),
        ("/databaseSchemas", "silver"),
        ("/tables", "transactions"),
        ("/databaseSchemas", "gold"),
        ("/tables", "fact_transactions"),
    ]
    table_call = client.calls[-1][2]
    assert table_call["databaseSchema"] == "pfp_duckdb.pfp.gold"


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
