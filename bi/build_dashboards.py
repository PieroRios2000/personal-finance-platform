"""Author PFP's Superset dashboards through its REST API and export them (T32).

The dashboards are code: `bi/assets/` is Superset's own export format (YAML), committed,
and `make bi-up` imports it (bi/start.sh). This script is how that export was made; run
it (`make bi-export`) only to change the dashboards, against a Superset started with an
empty `bi/assets/` (a fresh `make bi-reset bi-up`). It then rewrites `bi/assets/`.

    uv run python bi/build_dashboards.py [--host http://localhost:8088]

Reads `PFP_BI_ADMIN_PASSWORD` (the Superset login) and `PFP_PG_BI_PASSWORD` (the
read-only role the connection uses) from the environment. Needs PyYAML, already a
dependency.
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
import uuid
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

ASSETS = Path(__file__).resolve().parent / "assets"
DATABASE_NAME = "PFP gold (read-only)"
DASHBOARD_SLUG = "pfp-finance"
# `smart_date` (the default) prints a January 1st as just the year, which reads as a
# yearly total; day, month and year together are unambiguous at any grain.
_DATE_FORMAT = "%d %b %Y"


def _sql_metric(expression: str, label: str) -> dict[str, Any]:
    return {"expressionType": "SQL", "sqlExpression": expression, "label": label}


def _sql_column(expression: str, label: str) -> dict[str, Any]:
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


_GREEN, _RED, _AMBER = "#1f9d6b", "#e5484d", "#f5a524"


# Dashboard-wide CSS (Superset stores it on the dashboard) and the KPI strips:
# Handlebars charts, HTML and CSS of our own over the query's single row
# (bi/templates/). Numbers are formatted in SQL (to_char), so templates stay plain.
_TEMPLATES = Path(__file__).resolve().parent / "templates"
DASHBOARD_CSS = (_TEMPLATES / "dashboard.css").read_text()
_KPI_STYLE = (_TEMPLATES / "kpi.css").read_text()
_CASH_FLOW_KPI = (_TEMPLATES / "cash_flow_kpi.hbs").read_text()
_BALANCE_KPI = (_TEMPLATES / "balance_kpi.hbs").read_text()
_CAPITAL_KPI = (_TEMPLATES / "capital_kpi.hbs").read_text()
_RANGE_KPI = (_TEMPLATES / "range_kpi.hbs").read_text()
_DEBT_KPI = (_TEMPLATES / "debt_kpi.hbs").read_text()


# Money in and out are read from `signed_amount` (ADR 0031): the effect on you, the same
# on every bank. Movements between your own accounts count too (out on one side, in on
# the other), so a fee or an exchange difference between banks shows up.
_MONEY_IN = "COALESCE(SUM(signed_amount) FILTER (WHERE signed_amount > 0), 0)"
_MONEY_OUT = "COALESCE(-SUM(signed_amount) FILTER (WHERE signed_amount < 0), 0)"
_MONEY = "'FM999,999,999,990.00'"
_NET = "COALESCE(SUM(signed_amount), 0)"


def _balance_at(recency: int) -> str:
    return f"COALESCE(SUM(net_position) FILTER (WHERE month_recency = {recency}), 0)"


def _or_dash(expression: str) -> str:
    """A dash instead of a number when the filters leave out the latest month, so the
    card never shows a misleading 0.00."""
    return (
        "CASE WHEN COUNT(*) FILTER (WHERE month_recency = 1) = 0 THEN '-' "
        f"ELSE {expression} END"
    )


def _capital(column: str) -> str:
    """One of rpt_capital's balances at the latest month, formatted (or a dash)."""
    latest = f"COALESCE(SUM({column}) FILTER (WHERE month_recency = 1), 0)"
    return _or_dash(f"to_char({latest}, {_MONEY})")


_CHANGE = f"({_balance_at(1)} - {_balance_at(2)})"


# (dataset, chart name, viz type, params). `datasource` and `viz_type` are added later.
CHARTS: list[tuple[str, str, str, dict[str, Any]]] = [
    (
        "rpt_movements",
        "Cash flow summary",
        "handlebars",
        {
            "query_mode": "aggregate",
            "groupby": [],
            "metrics": [
                _sql_metric("MAX(currency)", "currency"),
                _sql_metric(f"to_char({_MONEY_IN}, {_MONEY})", "money_in"),
                _sql_metric(f"to_char({_MONEY_OUT}, {_MONEY})", "money_out"),
                _sql_metric(f"to_char({_NET}, {_MONEY})", "net"),
                _sql_metric(f"CASE WHEN {_NET} >= 0 THEN 1 ELSE 0 END", "net_positive"),
                _sql_metric("to_char(COUNT(*), 'FM999,999,990')", "movements"),
            ],
            "adhoc_filters": [_time_range("date")],
            "row_limit": 1,
            "handlebarsTemplate": _CASH_FLOW_KPI,
            "styleTemplate": _KPI_STYLE,
        },
    ),
    (
        "rpt_movements",
        "Period analysed",
        "handlebars",
        {
            "query_mode": "aggregate",
            "groupby": [],
            # From the first to the last movement left after the filters, and how many
            # closed months that spans.
            "metrics": [
                _sql_metric("to_char(MIN(date), 'DD Mon YYYY')", "from"),
                _sql_metric("to_char(MAX(date), 'DD Mon YYYY')", "to"),
                _sql_metric("COUNT(DISTINCT calendar_month)", "months"),
            ],
            "adhoc_filters": [_time_range("date")],
            "row_limit": 1,
            "handlebarsTemplate": _RANGE_KPI,
            "styleTemplate": _KPI_STYLE,
        },
    ),
    (
        "rpt_capital",
        "Debt at the end of the period",
        "handlebars",
        {
            "query_mode": "aggregate",
            # One row per month, the latest month left after the filters on top: the
            # debt you carry where the selected range ends.
            "groupby": ["calendar_month"],
            "metrics": [
                _sql_metric("MAX(currency)", "currency"),
                _sql_metric(f"to_char(SUM(debt_balance), {_MONEY})", "debt"),
                _sql_metric("MAX(month_start)", "sort_key"),
            ],
            "timeseries_limit_metric": _sql_metric("MAX(month_start)", "sort_key"),
            "order_desc": True,
            "adhoc_filters": [_time_range("month_start")],
            "row_limit": 1,
            "handlebarsTemplate": _DEBT_KPI,
            "styleTemplate": _KPI_STYLE,
        },
    ),
    (
        "rpt_capital",
        "Capital summary",
        "handlebars",
        {
            "query_mode": "aggregate",
            "groupby": [],
            # Total capital = savings (asset accounts) plus investments (funds), at
            # the latest month: rpt_capital carries each balance forward.
            "metrics": [
                _sql_metric("MAX(currency)", "currency"),
                _sql_metric(_capital("total_capital"), "total"),
                _sql_metric(_capital("savings_balance"), "savings"),
                _sql_metric(_capital("investments_balance"), "investments"),
                _sql_metric(
                    "to_char(MAX(month_start) FILTER "
                    "(WHERE month_recency = 1), 'Mon YYYY')",
                    "month",
                ),
            ],
            "adhoc_filters": [_time_range("month_start")],
            "row_limit": 1,
            "handlebarsTemplate": _CAPITAL_KPI,
            "styleTemplate": _KPI_STYLE,
        },
    ),
    (
        "rpt_capital",
        "Net position summary",
        "handlebars",
        {
            "query_mode": "aggregate",
            "groupby": [],
            "metrics": [
                _sql_metric("MAX(currency)", "currency"),
                _sql_metric(
                    _or_dash(f"to_char({_balance_at(1)}, {_MONEY})"), "balance"
                ),
                _sql_metric(
                    "to_char(MAX(month_start) FILTER "
                    "(WHERE month_recency = 1), 'Mon YYYY')",
                    "month",
                ),
                _sql_metric(_or_dash(f"to_char(ABS({_CHANGE}), {_MONEY})"), "change"),
                _sql_metric(
                    f"CASE WHEN {_CHANGE} >= 0 THEN 1 ELSE 0 END", "change_positive"
                ),
            ],
            "adhoc_filters": [_time_range("month_start")],
            "row_limit": 1,
            "handlebarsTemplate": _BALANCE_KPI,
            "styleTemplate": _KPI_STYLE,
        },
    ),
    (
        "rpt_movements",
        "Cash flow: money in and out",
        "echarts_timeseries_bar",
        {
            "x_axis": "date",
            "time_grain_sqla": "P1M",
            # `signed_amount` (ADR 0031): in is positive, out is negative, the same on
            # every bank, and movements between your own accounts count on both sides.
            # One currency at a time (the Currency filter).
            "metrics": [_sql_metric("SUM(signed_amount)", "Amount")],
            "groupby": [
                _sql_column(
                    "CASE WHEN signed_amount >= 0 THEN 'in' ELSE 'out' END",
                    "direction",
                )
            ],
            "adhoc_filters": [_time_range("date")],
            "label_colors": {"in": _GREEN, "out": _RED},
            "stack": "Stack",
            "x_axis_time_format": _DATE_FORMAT,
            "y_axis_format": ",.0f",
            "rich_tooltip": True,
            "row_limit": 10000,
            "orientation": "vertical",
            "show_legend": True,
        },
    ),
    (
        "rpt_balances",
        "Balance per month (debt is negative)",
        "echarts_timeseries_line",
        {
            "x_axis": "month_start",
            "time_grain_sqla": "P1M",
            # `signed_closing_balance`: a credit card's debt is negative, so the lines
            # add up to what you have.
            "metrics": [_sql_metric("SUM(signed_closing_balance)", "Closing balance")],
            "groupby": ["bank", "account_last4"],
            "adhoc_filters": [_time_range("month_start")],
            "area": True,
            "opacity": 0.25,
            "markerEnabled": True,
            "markerSize": 6,
            "seriesType": "smooth",
            "x_axis_time_format": _DATE_FORMAT,
            "y_axis_format": ",.0f",
            "rich_tooltip": True,
            "row_limit": 10000,
            "show_legend": True,
        },
    ),
    (
        "rpt_investments",
        "Investments: return and how each month closed",
        "handlebars",
        {
            "query_mode": "aggregate",
            # Formatted in SQL so the template stays plain. `closing_basis` sits next
            # to the return: `valuation` is a real month-end value, `last_movement`
            # only the balance at the last movement.
            "groupby": [
                "calendar_month",
                "place",
                "currency",
                "closing_basis",
                "is_return_reliable",
                _sql_column(
                    "COALESCE(to_char(return_pct * 100, 'FM990.00') || '%', '-')",
                    "return_pct",
                ),
                _sql_column(f"to_char(gain, {_MONEY})", "gain"),
                _sql_column(f"to_char(closing_balance, {_MONEY})", "closing_balance"),
            ],
            "metrics": [_sql_metric("MAX(month_start)", "sort_key")],
            "timeseries_limit_metric": _sql_metric("MAX(month_start)", "sort_key"),
            "order_desc": True,
            "adhoc_filters": [_time_range("month_start")],
            "row_limit": 500,
            "handlebarsTemplate": (_TEMPLATES / "investments_table.hbs").read_text(),
            "styleTemplate": (_TEMPLATES / "investments_table.css").read_text(),
        },
    ),
    (
        "rpt_investments",
        "Investments: return per fund over time",
        "echarts_timeseries_line",
        {
            "x_axis": "month_start",
            "time_grain_sqla": "P1M",
            "metrics": [_sql_metric("MAX(return_pct)", "Return")],
            "groupby": ["place"],
            "adhoc_filters": [
                _time_range("month_start"),
                _where("is_return_reliable"),
            ],
            "markerEnabled": True,
            "seriesType": "smooth",
            "y_axis_format": ".2%",
            "x_axis_time_format": _DATE_FORMAT,
            "rich_tooltip": True,
            "row_limit": 10000,
            "show_legend": True,
        },
    ),
    (
        "rpt_movements",
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
                "signed_amount",
                "is_internal_transfer",
                "description",
            ],
            "order_by_cols": ['["date", false]'],
            # `amount` is as the bank prints it (matches the PDF; a credit card charge
            # is positive there). `signed_amount` is the effect on you, the same on
            # every bank: money in and debt paid down positive, money out and new debt
            # negative.
            "column_config": {
                "amount": {
                    "d3NumberFormat": ",.2f",
                    "horizontalAlign": "right",
                    "customColumnName": "amount (as in the PDF)",
                },
                "signed_amount": {
                    "d3NumberFormat": ",.2f",
                    "horizontalAlign": "right",
                    "customColumnName": "effect on you",
                },
            },
            # Only numeric columns can be coloured: what improves your position is
            # green, what worsens it red.
            "conditional_formatting": [
                {
                    "colorScheme": "#c6f0dc",
                    "column": "signed_amount",
                    "operator": ">",
                    "targetValue": 0,
                },
                {
                    "colorScheme": "#fbd0d2",
                    "column": "signed_amount",
                    "operator": "<",
                    "targetValue": 0,
                },
            ],
            "row_limit": 1000,
            "include_search": True,
        },
    ),
    (
        "rpt_balances",
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
                "signed_closing_balance",
            ],
            "order_by_cols": ['["closing_date", false]'],
            "column_config": {
                "closing_balance": {
                    "d3NumberFormat": ",.2f",
                    "horizontalAlign": "right",
                },
                "signed_closing_balance": {
                    "d3NumberFormat": ",.2f",
                    "horizontalAlign": "right",
                },
            },
            "row_limit": 1000,
            "include_search": True,
        },
    ),
    (
        "rpt_reconciliation",
        "Reconciliation: opening + movements = balance (difference must be 0)",
        "table",
        {
            "query_mode": "raw",
            # Per account, over every closed month loaded (no calendar filter applies):
            # the first statement's opening balance plus the movements equals the
            # balance. A non-zero difference is a movement missing or read twice. Debt
            # is negative, like everywhere else.
            "adhoc_filters": [],
            "all_columns": [
                "bank",
                "account_last4",
                "currency",
                "account_kind",
                "first_month",
                "last_month",
                "opening_balance",
                "net_movements",
                "closing_balance",
                "difference",
            ],
            "order_by_cols": ['["bank", true]'],
            "column_config": {
                name: {"d3NumberFormat": ",.2f", "horizontalAlign": "right"}
                for name in (
                    "opening_balance",
                    "net_movements",
                    "closing_balance",
                    "difference",
                )
            },
            "conditional_formatting": [
                {
                    "colorScheme": "#fbd0d2",
                    "column": "difference",
                    "operator": op,
                    "targetValue": 0,
                }
                for op in (">", "<")
            ],
            "row_limit": 200,
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

    def raw(self, path: str, method: str = "GET") -> bytes:
        return self._call(method, path)


def native_filters(datasets: dict[str, int]) -> list[dict[str, Any]]:
    """The dashboard's filter bar. The calendar filters (date range, time grain, year,
    quarter, month) and bank, account, currency, flow type and fund. A filter applies
    to every chart whose dataset has the column, and the reporting tables share the
    same `calendar_*` and `currency` column names. Currency is one value at a time
    (PEN by default): currencies are never added together."""

    movements = datasets["rpt_movements"]

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

    def select(
        name: str, table: str, column: str, *, multi: bool = True
    ) -> dict[str, Any]:
        item = base(
            name,
            "filter_select",
            {"datasetId": datasets[table], "column": {"name": column}},
        )
        item["controlValues"] = {
            "multiSelect": multi,
            "enableEmptyFilter": not multi,
            "defaultToFirstItem": False,
            "searchAllOptions": False,
            "inverseSelection": False,
        }
        return item

    # The dataset is where the filter takes its grains from; without one it is blank.
    grain = base("Time grain", "filter_timegrain", {"datasetId": movements})
    grain["defaultDataMask"] = {
        "filterState": {"value": ["P1M"]},
        "extraFormData": {"time_grain_sqla": "P1M"},
    }
    currency = select("Currency", "rpt_movements", "currency", multi=False)
    currency["defaultDataMask"] = {
        "filterState": {"value": ["PEN"]},
        "extraFormData": {"filters": [{"col": "currency", "op": "IN", "val": ["PEN"]}]},
    }
    return [
        currency,
        base("Date range", "filter_time", {}),
        grain,
        select("Year", "rpt_movements", "calendar_year"),
        select("Quarter", "rpt_movements", "calendar_quarter"),
        select("Month", "rpt_movements", "calendar_month"),
        select("Bank", "rpt_movements", "bank"),
        select("Account", "rpt_movements", "account_last4"),
        select("Flow type", "rpt_movements", "flow_type"),
        select("Internal transfer", "rpt_movements", "is_internal_transfer"),
        select("Fund", "rpt_investments", "place"),
    ]


# A text cell in the grid (Markdown), next to the investments chart: how to read it.
NOTE = "@note"
NOTE_TEXT = (
    "### How to read the returns\n\n"
    "- **valuation**: the month closed at a real month-end value.\n"
    "- **last_movement**: only the balance at the last movement; the return is shown "
    "but trust it less.\n\n"
    "A return is shown only for a *reliable* month (`is_return_reliable`); the gain "
    "and the balances are always there.\n\n"
    "One currency at a time: use the **Currency** filter."
)

# The grid: (chart name prefix, width out of 12, height) per cell, row by row.
LAYOUT: list[list[tuple[str, int, int]]] = [
    [("Cash flow summary", 12, 22)],
    [("Period analysed", 6, 22), ("Debt at the end", 6, 22)],
    [("Capital summary", 6, 22), ("Net position summary", 6, 22)],
    [("Cash flow: money", 6, 50), ("Balance per month", 6, 50)],
    [("Investments: return and", 12, 32)],
    [("Investments: return per", 8, 50), (NOTE, 4, 50)],
    [("Movements", 12, 60)],
    [("Statement balances", 12, 60)],
    [("Reconciliation", 12, 40)],
]


def _position(
    chart_ids: Sequence[int], names: Sequence[str], uuids: Sequence[str]
) -> dict[str, Any]:
    """The dashboard grid, from LAYOUT: each cell finds its chart by name prefix."""
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
    for row_number, cells in enumerate(LAYOUT):
        row_id = f"ROW-{row_number}"
        layout["GRID_ID"]["children"].append(row_id)
        children = []
        for prefix, width, height in cells:
            if prefix == NOTE:
                layout["MARKDOWN-note"] = {
                    "type": "MARKDOWN",
                    "id": "MARKDOWN-note",
                    "children": [],
                    "parents": ["ROOT_ID", "GRID_ID", row_id],
                    "meta": {"width": width, "height": height, "code": NOTE_TEXT},
                }
                children.append("MARKDOWN-note")
                continue
            i = next(n for n, name in enumerate(names) if name.startswith(prefix))
            cell_id = f"CHART-{i}"
            children.append(cell_id)
            layout[cell_id] = {
                "type": "CHART",
                "id": cell_id,
                "children": [],
                "parents": ["ROOT_ID", "GRID_ID", row_id],
                "meta": {
                    "width": width,
                    "height": height,
                    "chartId": chart_ids[i],
                    "uuid": uuids[i],
                    "sliceName": names[i],
                },
            }
        layout[row_id] = {
            "type": "ROW",
            "id": row_id,
            "children": children,
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
        "metrics": [] if columns else params.get("metrics", []),
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


def _reset(client: Superset) -> None:
    """Delete what a previous run made (our dashboard, its charts and datasets and the
    connection), so the script can be run again on the same Superset."""

    def ids(kind: str, column: str, operator: str, value: str) -> list[int]:
        query = (
            f"(columns:!(id),filters:!((col:{column},opr:{operator},value:'{value}')))"
        )
        return [
            row["id"]
            for row in client.json("GET", f"/{kind}/?q={quote(query, safe='')}")[
                "result"
            ]
        ]

    for dashboard in ids("dashboard", "slug", "eq", DASHBOARD_SLUG):
        client.raw(f"/dashboard/{dashboard}", method="DELETE")
    for database in ids("database", "database_name", "eq", DATABASE_NAME):
        datasets = ids("dataset", "database", "rel_o_m", str(database))
        for dataset in datasets:
            charts = ids("chart", "datasource_id", "eq", str(dataset))
            if charts:
                client.raw(
                    f"/chart/?q=!({','.join(map(str, charts))})", method="DELETE"
                )
            client.raw(f"/dataset/{dataset}", method="DELETE")
        client.raw(f"/database/{database}", method="DELETE")


def build(client: Superset, bi_password: str) -> int:
    _reset(client)
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
                {
                    "native_filter_configuration": native_filters(datasets),
                    # Series colours are a dashboard setting in Superset, by label.
                    "label_colors": {"in": _GREEN, "out": _RED},
                }
            ),
            "css": DASHBOARD_CSS,
        },
    )
    return int(dashboard)


# Fixed namespace for the uuids below (any constant will do; it must never change).
_UUID_NAMESPACE = uuid.UUID("6f1d0c0e-5b1e-4d55-9b0c-2f6d1f0a7e11")
_NAME_KEYS = {
    "charts": "slice_name",
    "dashboards": "slug",
    "databases": "database_name",
    "datasets": "table_name",
}


def stable_uuid_map(files: dict[str, str]) -> dict[str, str]:
    """{uuid Superset made: uuid from the object's kind and name}, for every object in
    an export. Superset gives every object a new random uuid on each run of this
    script; importing that export then created new charts beside the old ones instead
    of updating them (30 charts on the dashboard, 8 wanted). A uuid derived from the
    name is the same every time, so an import overwrites the same objects."""
    mapping: dict[str, str] = {}
    for path, text in files.items():
        kind = Path(path).parts[0]
        if kind not in _NAME_KEYS:
            continue
        document = yaml.safe_load(text)
        name = document[_NAME_KEYS[kind]]
        mapping[str(document["uuid"])] = str(
            uuid.uuid5(_UUID_NAMESPACE, f"{kind}:{name}")
        )
    return mapping


def export(client: Superset, dashboard: int) -> None:
    bundle = zipfile.ZipFile(
        io.BytesIO(client.raw(f"/dashboard/export/?q=!({dashboard})"))
    )
    files = {
        str(Path(*Path(name).parts[1:])): bundle.read(name).decode()
        for name in bundle.namelist()
        if not name.endswith("/") and len(Path(name).parts) > 1
    }
    mapping = stable_uuid_map(files)
    shutil.rmtree(ASSETS, ignore_errors=True)
    for relative, text in files.items():
        # In the object's own file and in every reference to it.
        for old, new in mapping.items():
            text = text.replace(old, new)
        target = ASSETS / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
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
