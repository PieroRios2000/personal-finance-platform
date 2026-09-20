"""Author PFP's Superset dashboards through its REST API and export them (T32).

The dashboards are code: `bi/assets/` is Superset's own export format (YAML), committed,
and `make bi-up` imports it (bi/start.sh). This script is how that export was made; run
it (`make bi-export`) only to change the dashboards, against a Superset started with an
empty `bi/assets/` (a fresh `make bi-reset bi-up`). It then rewrites `bi/assets/`.

    uv run python bi/build_dashboards.py [--host http://localhost:8088]

Reads `PFP_BI_ADMIN_PASSWORD` (the Superset login) and `PFP_PG_BI_PASSWORD` (the
read-only role the connection uses) from the environment. Stdlib only.
"""

import argparse
import http.cookiejar
import io
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ASSETS = Path(__file__).resolve().parent / "assets"
DATABASE_NAME = "PFP gold (read-only)"
DASHBOARD_SLUG = "pfp-finance"
# `smart_date` (the default) prints a January 1st as just the year, which reads as a
# yearly total; the full date is unambiguous at any grain.
_DATE_FORMAT = "%Y-%m-%d"


def _sql_metric(expression: str, label: str) -> dict[str, Any]:
    return {"expressionType": "SQL", "sqlExpression": expression, "label": label}


def _time_range(column: str) -> dict[str, Any]:
    """The chart's time-range filter on `column`, unbounded until a dashboard filter
    narrows it: Superset's Date range filter only acts on a chart that has one."""
    return {
        "expressionType": "SIMPLE",
        "subject": column,
        "operator": "TEMPORAL_RANGE",
        "comparator": "No filter",
        "clause": "WHERE",
    }


def _where(expression: str) -> dict[str, Any]:
    return {"expressionType": "SQL", "sqlExpression": expression, "clause": "WHERE"}


# (dataset, chart name, viz type, params). `datasource` and `viz_type` are added later.
CHARTS: list[tuple[str, str, str, dict[str, Any]]] = [
    (
        "fact_transactions",
        "Monthly cash flow: income and spending (no internal transfers)",
        "echarts_timeseries_bar",
        {
            "x_axis": "date",
            "time_grain_sqla": "P1M",
            # Spending is negative on asset accounts and positive on liabilities
            # (ADR 0015): ABS() puts every movement on one scale, and flow_type says
            # which way it went. Currencies are never added together.
            "metrics": [_sql_metric("SUM(ABS(amount))", "Amount")],
            "groupby": ["flow_type", "currency"],
            "adhoc_filters": [
                _time_range("date"),
                _where("NOT is_internal_transfer"),
                _where("flow_type IN ('ingreso', 'egreso')"),
            ],
            "x_axis_time_format": _DATE_FORMAT,
            "row_limit": 10000,
            "orientation": "vertical",
            "show_legend": True,
        },
    ),
    (
        "fct_account_balance_monthly",
        "Savings balance per month (asset accounts)",
        "echarts_timeseries_line",
        {
            "x_axis": "month_start",
            "time_grain_sqla": "P1M",
            "metrics": [_sql_metric("SUM(closing_balance)", "Closing balance")],
            "groupby": ["bank", "currency"],
            "adhoc_filters": [
                _time_range("month_start"),
                _where("account_kind = 'asset'"),
            ],
            "x_axis_time_format": _DATE_FORMAT,
            "row_limit": 10000,
            "show_legend": True,
        },
    ),
    (
        "fct_investment_monthly",
        "Investments: return and how each month closed",
        "table",
        {
            "query_mode": "raw",
            "adhoc_filters": [_time_range("month_start")],
            # closing_basis sits right next to the return: `valuation` is a real
            # month-end value, `last_movement` only the balance at the last movement.
            "all_columns": [
                "month_start",
                "place",
                "currency",
                "return_pct",
                "closing_basis",
                "is_return_reliable",
                "gain",
                "closing_balance",
            ],
            "order_by_cols": ['["month_start", false]'],
            "row_limit": 1000,
            "include_search": True,
        },
    ),
    (
        "fct_investment_monthly",
        "Investments: return per fund over time",
        "echarts_timeseries_line",
        {
            "x_axis": "month_start",
            "time_grain_sqla": "P1M",
            "metrics": [_sql_metric("MAX(return_pct)", "Return")],
            "groupby": ["place", "currency"],
            "adhoc_filters": [
                _time_range("month_start"),
                _where("is_return_reliable"),
            ],
            "y_axis_format": ".2%",
            "x_axis_time_format": _DATE_FORMAT,
            "row_limit": 10000,
            "show_legend": True,
        },
    ),
    (
        "fact_transactions",
        "Movements (check against your statements)",
        "table",
        {
            "query_mode": "raw",
            "adhoc_filters": [_time_range("date")],
            "all_columns": [
                "date",
                "bank",
                "account_last4",
                "currency",
                "flow_type",
                "amount",
                "is_internal_transfer",
                "description",
            ],
            "order_by_cols": ['["date", false]'],
            "row_limit": 1000,
            "include_search": True,
        },
    ),
    (
        "fct_account_balance_monthly",
        "Statement balances (check against your statements)",
        "table",
        {
            "query_mode": "raw",
            "adhoc_filters": [_time_range("month_start")],
            "all_columns": [
                "month_start",
                "closing_date",
                "bank",
                "account_last4",
                "account_kind",
                "currency",
                "closing_balance",
            ],
            "order_by_cols": ['["closing_date", false]'],
            "row_limit": 1000,
            "include_search": True,
        },
    ),
]


class Superset:
    """The few REST calls this script needs (login, CSRF, JSON in and out)."""

    def __init__(self, host: str) -> None:
        self._api = f"{host.rstrip('/')}/api/v1"
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        self._headers = {"Content-Type": "application/json"}

    def _call(self, method: str, path: str, body: Any = None) -> bytes:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            self._api + path, data=data, headers=self._headers, method=method
        )
        try:
            with self._opener.open(request, timeout=120) as response:
                content: bytes = response.read()
        except urllib.error.HTTPError as error:
            raise RuntimeError(
                f"{method} {path}: {error.code} {error.read()[:400]!r}"
            ) from error
        return content

    def json(self, method: str, path: str, body: Any = None) -> dict[str, Any]:
        result: dict[str, Any] = json.loads(self._call(method, path, body))
        return result

    def login(self, password: str) -> None:
        token = self.json(
            "POST",
            "/security/login",
            {"username": "admin", "password": password, "provider": "db"},
        )["access_token"]
        self._headers["Authorization"] = f"Bearer {token}"
        self._headers["X-CSRFToken"] = self.json("GET", "/security/csrf_token/")[
            "result"
        ]
        self._headers["Referer"] = self._api

    def raw(self, path: str) -> bytes:
        return self._call("GET", path)


def native_filters(datasets: dict[str, int]) -> list[dict[str, Any]]:
    """The dashboard's filter bar: dates, time grain (month by default), bank,
    currency and fund. Each applies to every chart that has the column."""

    def base(name: str, filter_type: str, target: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": f"NATIVE_FILTER-{name.lower().replace(' ', '-')}",
            "name": name,
            "filterType": filter_type,
            "targets": [target],
            "controlValues": {},
            "defaultDataMask": {"filterState": {}, "extraFormData": {}},
            "cascadeParentIds": [],
            "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
            "type": "NATIVE_FILTER",
        }

    def select(name: str, table: str, column: str) -> dict[str, Any]:
        item = base(
            name,
            "filter_select",
            {"datasetId": datasets[table], "column": {"name": column}},
        )
        item["controlValues"] = {
            "multiSelect": True,
            "enableEmptyFilter": False,
            "defaultToFirstItem": False,
            "searchAllOptions": False,
            "inverseSelection": False,
        }
        return item

    # The dataset is where the filter takes its grains from; without one it is blank.
    grain = base(
        "Time grain",
        "filter_timegrain",
        {"datasetId": datasets["fact_transactions"]},
    )
    grain["defaultDataMask"] = {
        "filterState": {"value": ["P1M"]},
        "extraFormData": {"time_grain_sqla": "P1M"},
    }
    return [
        base("Date range", "filter_time", {}),
        grain,
        select("Bank", "fact_transactions", "bank"),
        select("Account", "fact_transactions", "account_last4"),
        select("Currency", "fact_transactions", "currency"),
        select("Flow type", "fact_transactions", "flow_type"),
        select("Internal transfer", "fact_transactions", "is_internal_transfer"),
        select("Fund", "fct_investment_monthly", "place"),
    ]


def _position(
    chart_ids: Sequence[int], names: Sequence[str], uuids: Sequence[str]
) -> dict[str, Any]:
    """A two-column grid, two charts per row, in the order given."""
    layout: dict[str, Any] = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {
            "type": "GRID",
            "id": "GRID_ID",
            "children": [],
            "parents": ["ROOT_ID"],
        },
        "HEADER_ID": {
            "type": "HEADER",
            "id": "HEADER_ID",
            "meta": {"text": "PFP finance"},
        },
    }
    # Charts two to a row; the tables for checking against statements get a whole row.
    rows: list[list[int]] = []
    for i, name in enumerate(names):
        if (
            "check against" in name
            or not rows
            or len(rows[-1]) == 2
            or ("check against" in names[rows[-1][0]])
        ):
            rows.append([])
        rows[-1].append(i)
    for row_number, members in enumerate(rows):
        row_id = f"ROW-{row_number}"
        layout["GRID_ID"]["children"].append(row_id)
        for i in members:
            layout[f"CHART-{i}"] = {
                "type": "CHART",
                "id": f"CHART-{i}",
                "children": [],
                "parents": ["ROOT_ID", "GRID_ID", row_id],
                "meta": {
                    "width": 12 if len(members) == 1 else 6,
                    "height": 60 if len(members) == 1 else 50,
                    "chartId": chart_ids[i],
                    "uuid": uuids[i],
                    "sliceName": names[i],
                },
            }
        layout[row_id] = {
            "type": "ROW",
            "id": row_id,
            "children": [f"CHART-{i}" for i in members],
            "parents": ["ROOT_ID", "GRID_ID"],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }
    return layout


def _chart_uuids(client: Superset, chart_ids: Sequence[int]) -> list[str]:
    """The uuid of each chart, in the order of `chart_ids` (the layout ties its cells to
    charts by uuid; the chart's own show endpoint does not return it, the list does)."""
    listed = client.json("GET", "/chart/?q=(columns:!(id,uuid),page_size:100)")
    by_id = {row["id"]: row["uuid"] for row in listed["result"]}
    return [by_id[chart_id] for chart_id in chart_ids]


def _sample_rows(client: Superset, dataset: int, params: dict[str, Any]) -> int:
    """How many rows the chart's columns and filters return from its dataset. A chart
    that reads nothing is a broken query (or an unbuilt table), not an empty chart."""
    columns = [
        column
        for column in [
            params.get("x_axis"),
            *params.get("groupby", []),
            *params.get("all_columns", []),
        ]
        if column
    ]
    where = " AND ".join(
        f["sqlExpression"]
        for f in params.get("adhoc_filters", [])
        if f["expressionType"] == "SQL"
    )
    query = {
        "columns": columns,
        "metrics": [],
        "orderby": [],
        "row_limit": 5,
        "extras": {"where": where},
    }
    result = client.json(
        "POST",
        "/chart/data",
        {
            "datasource": {"id": dataset, "type": "table"},
            "queries": [query],
            "result_format": "json",
            "result_type": "full",
        },
    )["result"][0]
    return int(result["rowcount"])


def build(client: Superset, bi_password: str) -> int:
    database = client.json(
        "POST",
        "/database/",
        {
            "database_name": DATABASE_NAME,
            "sqlalchemy_uri": f"postgresql+psycopg2://pfp_bi:{bi_password}@postgres:5432/pfp",
            "expose_in_sqllab": True,
        },
    )["id"]

    datasets: dict[str, int] = {}
    for table in dict.fromkeys(chart[0] for chart in CHARTS):
        datasets[table] = client.json(
            "POST",
            "/dataset/",
            {"database": database, "schema": "gold", "table_name": table},
        )["id"]

    dashboard = client.json(
        "POST",
        "/dashboard/",
        {"dashboard_title": "PFP finance", "slug": DASHBOARD_SLUG, "published": True},
    )["id"]

    chart_ids: list[int] = []
    for table, name, viz_type, params in CHARTS:
        params = {
            **params,
            "datasource": f"{datasets[table]}__table",
            "viz_type": viz_type,
        }
        chart_id = client.json(
            "POST",
            "/chart/",
            {
                "slice_name": name,
                "viz_type": viz_type,
                "datasource_id": datasets[table],
                "datasource_type": "table",
                "params": json.dumps(params),
                "dashboards": [dashboard],
            },
        )["id"]
        rows = _sample_rows(client, datasets[table], params)
        print(f"{name}: {rows} sample row(s)")
        if not rows:
            raise RuntimeError(
                f"{name!r} reads no data: check the gold tables are built"
            )
        chart_ids.append(chart_id)

    client.json(
        "PUT",
        f"/dashboard/{dashboard}",
        {
            "position_json": json.dumps(
                _position(
                    chart_ids,
                    [chart[1] for chart in CHARTS],
                    _chart_uuids(client, chart_ids),
                )
            ),
            "json_metadata": json.dumps(
                {"native_filter_configuration": native_filters(datasets)}
            ),
        },
    )
    return int(dashboard)


def export(client: Superset, dashboard: int) -> None:
    bundle = zipfile.ZipFile(
        io.BytesIO(client.raw(f"/dashboard/export/?q=!({dashboard})"))
    )
    shutil.rmtree(ASSETS, ignore_errors=True)
    for name in bundle.namelist():
        relative = Path(*Path(name).parts[1:])  # drop the archive's root folder
        if name.endswith("/") or not relative.parts:
            continue
        target = ASSETS / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(bundle.read(name))
    print(f"exported to {ASSETS}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="http://localhost:8088")
    args = parser.parse_args(argv)
    client = Superset(args.host)
    client.login(os.environ["PFP_BI_ADMIN_PASSWORD"])
    export(client, build(client, os.environ["PFP_PG_BI_PASSWORD"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
