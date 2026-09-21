"""Static checks on the Superset stack and its committed dashboards (T32, ADR 0030).
The live behaviour (import, connection as the read-only role, sample rows) is the PR's
verification; these keep the configuration from drifting."""

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parent.parent
_BI = _ROOT / "bi"


_DATASETS = {"rpt_movements": 2, "rpt_investments": 1, "rpt_balances": 3}


def _compose() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load((_BI / "docker-compose.yml").read_text())
    return loaded


def _builder() -> Any:
    spec = importlib.util.spec_from_file_location(
        "build_dashboards", _BI / "build_dashboards.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_dashboards"] = module
    spec.loader.exec_module(module)
    return module


def test_superset_is_only_reachable_from_this_machine() -> None:
    ports = _compose()["services"]["superset"]["ports"]

    assert all(str(p).startswith("127.0.0.1:") for p in ports)


def test_no_credential_is_hardcoded_in_the_stack() -> None:
    environment = {
        **_compose()["services"]["superset"]["environment"],
        **_compose()["services"]["bi-init"]["environment"],
    }
    secrets = [v for k, v in environment.items() if "PASSWORD" in k or "SECRET" in k]

    assert secrets and all(str(v).startswith("${") for v in secrets)


def test_the_image_is_pinned_to_an_exact_version() -> None:
    dockerfile = (_BI / "Dockerfile").read_text()

    assert re.search(r"^FROM apache/superset:\d+\.\d+\.\d+$", dockerfile, re.M)
    assert re.search(r"psycopg2-binary==\d", dockerfile)


def test_the_committed_export_holds_no_password_but_the_masked_one() -> None:
    database = next((_BI / "assets" / "databases").glob("*.yaml"))
    uri = yaml.safe_load(database.read_text())["sqlalchemy_uri"]

    assert uri.startswith("postgresql+psycopg2://pfp_bi:XXXXXXXXXX@")


def test_the_dashboard_connects_as_the_read_only_role_to_gold_only() -> None:
    for dataset in (_BI / "assets" / "datasets").rglob("*.yaml"):
        assert yaml.safe_load(dataset.read_text())["schema"] == "gold"


def _charts() -> dict[str, tuple[str, str, str, dict[str, Any]]]:
    return {c[1]: c for c in _builder().CHARTS}


def _filters() -> dict[str, dict[str, Any]]:
    return {f["name"]: f for f in _builder().native_filters(_DATASETS)}


def test_the_dashboard_has_calendar_and_slicing_filters() -> None:
    filters = _filters()

    assert filters["Date range"]["filterType"] == "filter_time"
    assert filters["Time grain"]["filterType"] == "filter_timegrain"
    columns = {
        name: f["targets"][0]["column"]["name"]
        for name, f in filters.items()
        if f["filterType"] == "filter_select"
    }
    assert columns == {
        "Currency": "currency",
        "Year": "calendar_year",
        "Quarter": "calendar_quarter",
        "Month": "calendar_month",
        "Bank": "bank",
        "Account": "account_last4",
        "Flow type": "flow_type",
        "Internal transfer": "is_internal_transfer",
        "Fund": "place",
    }


def test_currency_is_one_value_at_a_time_and_starts_on_soles() -> None:
    """Currencies are never added: the filter is single-select, required, PEN first."""
    currency = _filters()["Currency"]

    assert currency["controlValues"]["multiSelect"] is False
    assert currency["controlValues"]["enableEmptyFilter"] is True
    assert currency["defaultDataMask"]["filterState"]["value"] == ["PEN"]


def test_the_time_grain_starts_monthly_and_takes_its_options_from_a_dataset() -> None:
    grain = _filters()["Time grain"]

    assert grain["defaultDataMask"]["extraFormData"] == {"time_grain_sqla": "P1M"}
    # Without a dataset the filter has no grains to offer and shows blank values.
    assert grain["targets"] == [{"datasetId": _DATASETS["rpt_movements"]}]


def test_every_chart_reads_a_reporting_table_the_dashboard_exports() -> None:
    exported = {p.stem for p in (_BI / "assets" / "datasets").rglob("*.yaml")}
    used = {c[0] for c in _builder().CHARTS}

    assert used == exported
    assert all(name.startswith("rpt_") for name in used)


def test_every_dated_chart_has_a_time_range_filter_for_the_date_range() -> None:
    """Superset's Date range filter only narrows a chart that already has a time-range
    (TEMPORAL_RANGE) filter on its date column; without one it does nothing."""
    for name, chart in _charts().items():
        ranges = [
            f
            for f in chart[3]["adhoc_filters"]
            if f.get("operator") == "TEMPORAL_RANGE"
        ]
        assert [f["subject"] for f in ranges] in (["date"], ["month_start"]), name


def test_the_timeseries_axes_show_the_full_date() -> None:
    # `smart_date` prints a January 1st as just the year: it read as a yearly total.
    series = [c for c in _builder().CHARTS if c[2].startswith("echarts_timeseries")]

    assert series
    assert all(c[3]["x_axis_time_format"] == "%d %b %Y" for c in series)


def test_cash_flow_uses_signed_amount_and_counts_transfers_between_accounts() -> None:
    """Money in and out is `signed_amount` (ADR 0031), the same on every bank; movements
    between your own accounts count on both sides, so a fee between banks shows."""
    chart = _charts()["Cash flow: money in and out"][3]
    text = json.dumps(chart)

    assert chart["metrics"][0]["sqlExpression"] == "SUM(signed_amount)"
    assert "is_internal_transfer" not in text
    assert "flow_type" not in text
    assert chart["label_colors"] == {"in": "#1f9d6b", "out": "#e5484d"}
    summary = json.dumps(_charts()["Cash flow summary"][3])
    assert "signed_amount" in summary and "is_internal_transfer" not in summary


def test_balances_use_the_signed_closing_balance_so_debt_is_negative() -> None:
    charts = _charts()
    line = charts["Balance per month (debt is negative)"][3]
    summary = json.dumps(charts["Balance summary"][3])

    assert line["metrics"][0]["sqlExpression"] == "SUM(signed_closing_balance)"
    assert "account_kind" not in json.dumps(line)  # debts are in, not filtered out
    assert "signed_closing_balance" in summary and "account_kind" not in summary
    table = charts["Statement balances (check against your statements)"][3]
    assert {"closing_balance", "signed_closing_balance"} <= set(table["all_columns"])


def test_the_investments_table_shows_closing_basis_right_beside_the_return() -> None:
    table = _charts()["Investments: return and how each month closed"][3]
    template = table["handlebarsTemplate"]

    assert "closing_basis" in table["groupby"]
    assert template.index("{{return_pct}}") < template.index("{{closing_basis}}")
    assert template.index("{{closing_basis}}") < template.index("{{gain}}")


def test_the_movements_and_balances_tables_exist_to_check_against_the_statements() -> (
    None
):
    charts = _charts()

    movements = charts["Movements (check against your statements)"]
    assert movements[0] == "rpt_movements"
    assert {
        "date",
        "bank",
        "currency",
        "flow_type",
        "amount",
        "signed_amount",
        "description",
    } <= set(movements[3]["all_columns"])
    # Colours follow the effect on you, not each bank's own sign.
    assert {f["column"] for f in movements[3]["conditional_formatting"]} == {
        "signed_amount"
    }
    balances = charts["Statement balances (check against your statements)"]
    assert balances[0] == "rpt_balances"
    assert {"closing_date", "account_last4", "closing_balance"} <= set(
        balances[3]["all_columns"]
    )


def test_no_sql_expression_uses_a_sub_query_which_superset_refuses() -> None:
    for name, chart in _charts().items():
        text = json.dumps(chart[3]).lower()
        assert "(select" not in text, name


def test_every_chart_has_a_cell_in_the_layout() -> None:
    builder = _builder()
    names = [c[1] for c in builder.CHARTS]
    prefixes = [p for row in builder.LAYOUT for p, _, _ in row if p != builder.NOTE]

    for name in names:
        assert sum(name.startswith(p) for p in prefixes) == 1, name
    for prefix in prefixes:
        assert sum(n.startswith(prefix) for n in names) == 1, prefix


def test_every_chart_in_the_layout_is_tied_to_its_chart_by_uuid() -> None:
    """Without the uuid, the import cannot map a layout cell to its imported chart and
    Superset appends every chart again in an extra row at the bottom."""
    builder = _builder()
    names = [c[1] for c in builder.CHARTS]
    uuids = [f"uuid-{i}" for i in range(len(names))]

    layout = builder._position(list(range(len(names))), names, uuids)

    cells = [v for k, v in layout.items() if k.startswith("CHART-")]
    assert len(cells) == len(names)
    assert {c["meta"]["uuid"] for c in cells} == set(uuids)


def test_exported_uuids_depend_on_the_names_not_on_the_run() -> None:
    """Every regeneration used to give every object a new uuid, so importing it created
    new charts beside the old ones (30 charts, 8 wanted). The uuid now comes from the
    object's kind and name, so an import updates the same objects."""
    builder = _builder()
    first = {
        "charts/a.yaml": "slice_name: Cash flow\nuuid: 1111\n",
        "dashboards/d.yaml": "dashboard_title: PFP\nslug: pfp\nuuid: 2222\n"
        "position:\n  meta: {uuid: 1111}\n",
    }
    second = {
        "charts/other_name.yaml": "slice_name: Cash flow\nuuid: 9999\n",
        "dashboards/x.yaml": "dashboard_title: PFP\nslug: pfp\nuuid: 8888\n"
        "position:\n  meta: {uuid: 9999}\n",
    }

    a, b = builder.stable_uuid_map(first), builder.stable_uuid_map(second)

    assert sorted(a.values()) == sorted(b.values())
    assert len(set(a.values())) == 2
    assert set(a) == {"1111", "2222"}
