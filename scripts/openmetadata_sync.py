"""dbt artifacts -> OpenMetadata: tables, columns and lineage (T24, ADR 0023).

OpenMetadata 2.0.2 has no DuckDB connector, and its dbt workflow only *enriches* tables
that already exist in the catalog, so this script covers the two gaps around it:

1. `sync` registers what a database connector would have: a service, the `pfp`
   database, the bronze/silver/gold schemas and their tables with typed columns.
   Silver and gold come from dbt's `catalog.json` (DuckDB's own information schema,
   read by `dbt docs generate`); bronze comes from the pyarrow schemas
   `lakehouse.bronze` writes with, because `delta_scan()` isn't a DuckDB relation and
   dbt's catalog can't see it. Elementary's own models are left out: they're its
   monitoring tables, not project data.
2. `sync` also writes what the ingestion container reads: a copy of `manifest.json`
   whose compiled SQL says `"pfp"."bronze"."transactions"` instead of
   `delta_scan('s3://.../bronze/transactions')` (OpenMetadata's SQL parser can't resolve
   a table function to a table, so without this the bronze -> silver column lineage is
   never derived), `catalog.json`, and the ingestion workflow config.

The lineage itself is still OpenMetadata's own: `metadata ingest` parses each model's
compiled SQL. `check` then asks the running server for `gold.fact_transactions.amount`'s
upstream lineage and fails unless it reaches `bronze.transactions.amount` column by
column.

    uv run python -m scripts.openmetadata_sync sync    # after `dbt docs generate`
    docker compose -f openmetadata/docker-compose.yml -p pfp-om exec ingestion \\
        metadata ingest -c /opt/pfp-artifacts/dbt-workflow.yaml
    uv run python -m scripts.openmetadata_sync check

`make om-sync` runs the three in order. Exit codes: 0 done, 1 `check` found no column
lineage, 2 could not reach OpenMetadata or read the artifacts.
"""

import argparse
import base64
import copy
import json
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import duckdb
import pyarrow as pa

from lakehouse import bronze

SERVICE = "pfp_duckdb"
SCHEMAS = ("bronze", "silver", "gold")
# The ingestion container mounts openmetadata/artifacts read-only at this path
# (openmetadata/docker-compose.yml).
CONTAINER_ARTIFACTS = "/opt/pfp-artifacts"
# The stack's own local-development admin (upstream default, see the compose file).
_ADMIN_EMAIL = "admin@open-metadata.org"
_ADMIN_PASSWORD = "admin"

# DuckDB type name (parameters stripped) -> OpenMetadata `dataType`.
_OM_TYPES = {
    "BIGINT": "BIGINT",
    "BOOLEAN": "BOOLEAN",
    "DATE": "DATE",
    "DECIMAL": "DECIMAL",
    "DOUBLE": "DOUBLE",
    "INTEGER": "INT",
    "TIMESTAMP": "TIMESTAMP",
    "TIMESTAMP WITH TIME ZONE": "TIMESTAMP",
    "VARCHAR": "VARCHAR",
}


@dataclass(frozen=True)
class Table:
    schema: str
    name: str
    columns: list[dict[str, Any]]


class Client(Protocol):
    def put(self, path: str, body: dict[str, Any]) -> dict[str, Any]: ...


def om_column(name: str, duckdb_type: str, position: int) -> dict[str, Any]:
    """One OpenMetadata column from a DuckDB column type such as `DECIMAL(18,2)`."""
    base = re.sub(r"\(.*\)$", "", duckdb_type)
    if base not in _OM_TYPES:
        raise ValueError(
            f"no OpenMetadata type for DuckDB type {duckdb_type!r} ({name})"
        )
    column: dict[str, Any] = {
        "name": name,
        "dataType": _OM_TYPES[base],
        "dataTypeDisplay": duckdb_type,
        "ordinalPosition": position,
    }
    if base == "VARCHAR":
        # OpenMetadata requires a length; DuckDB's VARCHAR is unbounded.
        column["dataLength"] = 1
    if base == "DECIMAL":
        precision, scale = re.findall(r"\d+", duckdb_type)
        column["precision"], column["scale"] = int(precision), int(scale)
    return column


def catalog_tables(manifest: dict[str, Any], catalog: dict[str, Any]) -> list[Table]:
    """Silver and gold tables from `catalog.json`, minus Elementary's own models."""
    tables = []
    for unique_id, node in catalog["nodes"].items():
        if manifest["nodes"][unique_id]["package_name"] == "elementary":
            continue
        columns = sorted(node["columns"].values(), key=lambda c: c["index"])
        tables.append(
            Table(
                schema=node["metadata"]["schema"],
                name=node["metadata"]["name"],
                columns=[om_column(c["name"], c["type"], c["index"]) for c in columns],
            )
        )
    return tables


def bronze_tables(manifest: dict[str, Any]) -> list[Table]:
    """Every dbt source, typed from the pyarrow schema bronze is written with."""
    schemas = {
        "transactions": bronze._TRANSACTIONS_SCHEMA,
        "statements": bronze._STATEMENTS_SCHEMA,
    }
    tables = []
    for source in manifest["sources"].values():
        name = source["identifier"]
        if name not in schemas:
            raise ValueError(
                f"dbt source {name!r} has no bronze schema in lakehouse.bronze"
            )
        # DuckDB's own view of the arrow schema: the types delta_scan() hands to dbt.
        relation = duckdb.from_arrow(pa.Table.from_pylist([], schema=schemas[name]))
        tables.append(
            Table(
                schema=source["schema"],
                name=name,
                columns=[
                    om_column(col, str(typ), i)
                    for i, (col, typ) in enumerate(
                        zip(relation.columns, relation.types, strict=True), start=1
                    )
                ],
            )
        )
    return tables


def resolve_sources(manifest: dict[str, Any]) -> dict[str, Any]:
    """A copy of `manifest` whose compiled SQL names each source, not its Delta path."""
    resolved = copy.deepcopy(manifest)
    for source in resolved["sources"].values():
        db, schema, name = source["database"], source["schema"], source["identifier"]
        for node in resolved["nodes"].values():
            if node.get("compiled_code"):
                node["compiled_code"] = node["compiled_code"].replace(
                    source["relation_name"], f'"{db}"."{schema}"."{name}"'
                )
    return resolved


def workflow_config(service: str, database: str, token: str) -> dict[str, Any]:
    """The `metadata ingest` config for the dbt workflow, with the container's paths."""
    return {
        "source": {
            "type": "dbt",
            "serviceName": service,
            "sourceConfig": {
                "config": {
                    "type": "DBT",
                    "dbtConfigSource": {
                        "dbtConfigType": "local",
                        "dbtManifestFilePath": f"{CONTAINER_ARTIFACTS}/manifest.json",
                        "dbtCatalogFilePath": f"{CONTAINER_ARTIFACTS}/catalog.json",
                    },
                    "dbtUpdateDescriptions": True,
                    "overrideLineage": True,
                    "databaseFilterPattern": {"includes": [f"^{database}$"]},
                    "schemaFilterPattern": {"includes": [f"^{s}$" for s in SCHEMAS]},
                }
            },
        },
        "sink": {"type": "metadata-rest", "config": {}},
        "workflowConfig": {
            "loggerLevel": "INFO",
            "openMetadataServerConfig": {
                "hostPort": "http://openmetadata-server:8585/api",
                "authProvider": "openmetadata",
                "securityConfig": {"jwtToken": token},
            },
        },
    }


def register(
    client: Client, service: str, database: str, tables: Sequence[Table]
) -> None:
    """Create-or-update the service, database, schemas and tables (idempotent PUTs)."""
    client.put(
        "/services/databaseServices",
        {
            "name": service,
            "serviceType": "CustomDatabase",
            "connection": {
                "config": {"type": "CustomDatabase", "sourcePythonClass": "not.used"}
            },
        },
    )
    client.put("/databases", {"name": database, "service": service})
    seen: set[str] = set()
    for table in tables:
        if table.schema not in seen:
            seen.add(table.schema)
            client.put(
                "/databaseSchemas",
                {"name": table.schema, "database": f"{service}.{database}"},
            )
        client.put(
            "/tables",
            {
                "name": table.name,
                "databaseSchema": f"{service}.{database}.{table.schema}",
                "columns": table.columns,
            },
        )


def column_paths(lineage: dict[str, Any], column: str) -> list[list[str]]:
    """Every column-level path ending at `column`, oldest ancestor first.

    `lineage` is `GET /api/v1/lineage/getLineage`'s response. A path always has at least
    one hop; an unrelated column, or one with no column-level upstream, gives `[]`.
    """
    upstream: dict[str, list[str]] = {}
    for edge in lineage["upstreamEdges"].values():
        for pair in edge.get("columns") or []:
            upstream.setdefault(pair["toColumn"], []).extend(pair["fromColumns"])

    def walk(target: str) -> list[list[str]]:
        parents = upstream.get(target, [])
        if not parents:
            return [[target]]
        return [path + [target] for parent in parents for path in walk(parent)]

    return [path for path in walk(column) if len(path) > 1]


class OpenMetadata:
    """The few REST calls this script needs, on the stdlib (no extra dependency)."""

    def __init__(self, host: str) -> None:
        self._api = f"{host.rstrip('/')}/api/v1"
        self._token = ""

    def _request(self, method: str, path: str, body: dict[str, Any] | None) -> Any:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            self._api + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            raise RuntimeError(
                f"{method} {path}: {error.code} {error.read()[:300]!r}"
            ) from error

    def login(self) -> str:
        encoded = base64.b64encode(_ADMIN_PASSWORD.encode()).decode()
        response = self._request(
            "POST", "/users/login", {"email": _ADMIN_EMAIL, "password": encoded}
        )
        self._token = str(response["accessToken"])
        return self._token

    def put(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = self._request("PUT", path, body)
        return result

    def upstream_lineage(self, table_fqn: str) -> dict[str, Any]:
        result: dict[str, Any] = self._request(
            "GET",
            f"/lineage/getLineage?fqn={table_fqn}&type=table&upstreamDepth=10&downstreamDepth=0",
            None,
        )
        return result


def _sync(args: argparse.Namespace) -> int:
    manifest = json.loads((args.target_path / "manifest.json").read_text())
    catalog_path = args.target_path / "catalog.json"
    catalog = json.loads(catalog_path.read_text())
    database = next(iter(manifest["sources"].values()))["database"]

    client = OpenMetadata(args.host)
    token = client.login()
    tables = bronze_tables(manifest) + catalog_tables(manifest, catalog)
    register(client, SERVICE, database, tables)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "manifest.json").write_text(json.dumps(resolve_sources(manifest)))
    (args.out / "catalog.json").write_text(catalog_path.read_text())
    # JSON is valid YAML, and it's what `metadata ingest -c` reads.
    (args.out / "dbt-workflow.yaml").write_text(
        json.dumps(workflow_config(SERVICE, database, token), indent=2)
    )
    print(f"registered {len(tables)} tables in {SERVICE}.{database}")
    print(f"ingestion inputs written to {args.out}")
    return 0


def _check(args: argparse.Namespace) -> int:
    client = OpenMetadata(args.host)
    client.login()
    table = f"{SERVICE}.pfp.gold.fact_transactions"
    paths = column_paths(client.upstream_lineage(table), f"{table}.amount")
    root = f"{SERVICE}.pfp.bronze.transactions.amount"
    reaching_bronze = [p for p in paths if p[0] == root]
    for path in paths:
        print(" -> ".join(path))
    if not reaching_bronze:
        print(
            f"FAIL: no column-level path from {root} to {table}.amount", file=sys.stderr
        )
        return 1
    print(f"OK: {len(reaching_bronze)} column-level path(s) from {root}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="http://localhost:8585")
    commands = parser.add_subparsers(dest="command", required=True)
    sync = commands.add_parser(
        "sync", help="register tables, write the ingestion inputs"
    )
    sync.add_argument("--target-path", type=Path, default=Path("dbt/target"))
    sync.add_argument("--out", type=Path, default=Path("openmetadata/artifacts"))
    sync.set_defaults(run=_sync)
    check = commands.add_parser(
        "check", help="fail unless column lineage reaches bronze"
    )
    check.set_defaults(run=_check)
    args = parser.parse_args(argv)
    try:
        return int(args.run(args))
    except (OSError, RuntimeError, KeyError) as error:
        print(f"could not run: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
