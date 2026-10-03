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
        if name.startswith(("Reconciliation", "Upload")):  # not per month
            assert chart[3]["adhoc_filters"] == []
            continue
        ranges = [
            f
            for f in chart[3]["adhoc_filters"]
            if f.get("operator") == "TEMPORAL_RANGE"
        ]
        assert [f["subject"] for f in ranges] in (["date"], ["month_start"]), name


def test_the_timeseries_axes_show_the_full_date() -> None:
    # `smart_date` prints a January 1st as just the year: it read as a yearly total.
    series = [
        c
        for c in _builder().CHARTS
        if c[2].startswith("echarts_timeseries") and "time_grain_sqla" in c[3]
    ]

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
    metrics = {
        m["label"]: m["sqlExpression"]
        for m in _charts()["Cash flow summary"][3]["metrics"]
    }
    for label in ("money_in", "money_out", "net"):
        assert "signed_amount" in metrics[label], label
        assert "is_internal_transfer" not in metrics[label], label


def test_balances_use_the_signed_closing_balance_so_debt_is_negative() -> None:
    charts = _charts()
    line = charts["Balance per month (debt is negative)"][3]
    summary = charts["Net position summary"]

    assert line["metrics"][0]["sqlExpression"] == "SUM(signed_closing_balance)"
    assert "account_kind" not in json.dumps(line)  # debts are in, not filtered out
    # The card is capital minus debt, carried forward like every holding.
    assert summary[0] == "rpt_capital" and "net_position" in json.dumps(summary[3])
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
    prefixes = [
        p
        for row in builder.LAYOUT
        for p, _, _ in row
        if p != builder.NOTE and not p.startswith(builder.SECTION)
    ]

    for name in names:
        assert sum(name.startswith(p) for p in prefixes) == 1, name
    for prefix in prefixes:
        assert sum(n.startswith(prefix) for n in names) == 1, prefix


def test_categories_are_their_own_section_of_the_dashboard() -> None:
    """The classification (T51-T54) is a section with its own title, after the cash
    flow and before the investments, made of the four `Categories:` charts."""
    builder = _builder()
    rows = [[p for p, _, _ in row] for row in builder.LAYOUT]
    title = next(
        i for i, row in enumerate(rows) if row == [f"{builder.SECTION}Categories"]
    )
    cells = [p for row in rows[title + 1 : title + 4] for p in row]

    assert len(cells) == 4
    assert all(p.startswith("Categories:") for p in cells)
    names = [c[1] for c in builder.CHARTS if c[1].startswith("Categories:")]
    assert len(names) == 4

    layout = builder._position(
        list(range(len(builder.CHARTS))),
        [c[1] for c in builder.CHARTS],
        ["u"] * len(builder.CHARTS),
    )
    header = layout[f"HEADER-{title}"]
    assert header["meta"]["text"] == "Categories"
    assert header["parents"] == ["ROOT_ID", "GRID_ID"]
    assert f"HEADER-{title}" in layout["GRID_ID"]["children"]


def test_the_category_charts_cover_spending_only() -> None:
    """Categories answer "where did the money go": only expenses (`egreso`: money out
    of an account, a charge on a card, ADR 0020), never income or card credits, and
    never a move between your own accounts (ADR 0017)."""
    charts = [c for c in _builder().CHARTS if c[1].startswith("Categories:")]

    for _, name, _, params in charts:
        filters = json.dumps(params["adhoc_filters"])
        assert "flow_type = 'egreso'" in filters, name
        assert "NOT is_internal_transfer" in filters, name


def test_the_review_table_lists_only_what_nobody_confirmed() -> None:
    """A guess is never a label (ADR 0043): the table to review shows the movements
    whose category is a model guess or missing, never the owner's own."""
    table = next(c for c in _builder().CHARTS if "movements to review" in c[1])[3]

    assert "NOT category_confirmed" in json.dumps(table["adhoc_filters"])
    assert "category" in table["all_columns"]


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


def test_the_capital_card_adds_savings_and_investments_from_one_dataset() -> None:
    """Total capital combines savings accounts and investments, which are two different
    facts: one reporting table (rpt_capital) has both, so a chart can show the sum."""
    chart = _charts()["Capital summary"]
    text = json.dumps(chart[3])

    assert chart[0] == "rpt_capital"
    for column in ("total_capital", "savings_balance", "investments_balance"):
        assert column in text
    assert "month_recency = 1" in text
    assert '"{{total}}"' not in text  # the template, not the metric, shows the value
    assert "{{savings}}" in chart[3]["handlebarsTemplate"]
    assert "{{investments}}" in chart[3]["handlebarsTemplate"]


def test_the_range_and_debt_cards_follow_the_selected_period() -> None:
    charts = _charts()
    period = json.dumps(charts["Period analysed"][3])
    debt = charts["Debt at the end of the period"]

    assert "MIN(date)" in period and "MAX(date)" in period
    assert debt[0] == "rpt_capital" and "SUM(debt_balance)" in json.dumps(debt[3])
    # The debt is the latest month left after the filters, not the global latest.
    assert debt[3]["order_desc"] is True and debt[3]["row_limit"] == 1
    assert "month_recency" not in json.dumps(debt[3])


def test_the_reconciliation_table_shows_the_difference_and_flags_a_non_zero_one() -> (
    None
):
    table = _charts()[
        "Reconciliation: opening + movements = balance (difference must be 0)"
    ]

    assert table[0] == "rpt_reconciliation"
    assert {"opening_balance", "net_movements", "closing_balance", "difference"} <= set(
        table[3]["all_columns"]
    )
    assert {f["column"] for f in table[3]["conditional_formatting"]} == {"difference"}


def test_the_savings_rate_is_net_over_real_income_without_transfers() -> None:
    """% saved = net / income. The income in the denominator leaves out movements
    between your own accounts (they would inflate it: money in on one side of every
    transfer), and a period with no income shows a dash, not a division by zero."""
    card = _charts()["Cash flow summary"]
    metrics = {m["label"]: m["sqlExpression"] for m in card[3]["metrics"]}
    rate = metrics["savings_rate"]

    assert "SUM(signed_amount)" in rate  # the net, the same amount the Net card shows
    assert "flow_type = 'ingreso'" in rate and "NOT is_internal_transfer" in rate
    assert "= 0 THEN '-'" in rate
    template = card[3]["handlebarsTemplate"]
    assert "{{savings_rate}}" in template
    assert "% saved" in template and "income" in template.lower()


def test_the_dashboard_starts_with_a_link_to_the_upload_portal() -> None:
    """T44 (ADR 0040): an account with no data sees a message and a button, one with
    data a slim link. The count goes through row-level security, so it is 0 exactly for
    an account nobody has loaded anything for."""
    builder = _builder()
    chart = next(c for c in builder.CHARTS if c[1] == "Upload your files")
    asset = yaml.safe_load(
        next((_BI / "assets" / "charts").glob("Upload_your_files_*.yaml")).read_text()
    )
    dashboard = yaml.safe_load(
        next((_BI / "assets" / "dashboards").glob("*.yaml")).read_text()
    )
    first_row = dashboard["position"]["GRID_ID"]["children"][0]
    first_chart = dashboard["position"][dashboard["position"][first_row]["children"][0]]

    assert builder.LAYOUT[0][0][0] == "Upload your files"
    assert first_chart["meta"]["sliceName"] == "Upload your files"
    assert asset["params"]["metrics"] == chart[3]["metrics"]
    assert asset["params"]["handlebarsTemplate"] == chart[3]["handlebarsTemplate"]
    # No date filter: it counts what the account may see, not what the filters leave.
    assert chart[3]["adhoc_filters"] == []


def test_the_link_is_the_portals_address_from_the_environment() -> None:
    metrics = [
        m["sqlExpression"]
        for m in _builder().CHARTS[-1][3]["metrics"]
        if "upload_url" in m["sqlExpression"]
    ]
    template = (_BI / "templates" / "upload_prompt.hbs").read_text()
    config = (_BI / "superset_config.py").read_text()
    environment = _compose()["services"]["superset"]["environment"]

    assert metrics == ["'{{ upload_url() }}'::text"]  # a constant: it survives 0 rows
    assert 'href="{{upload_url}}"' in template and "{{#if movements}}" in template
    assert '"upload_url": lambda: os.environ.get("PFP_UPLOAD_URL", "")' in config
    assert environment["PFP_UPLOAD_URL"].startswith("${PFP_UPLOAD_PUBLIC_URL:-http://")
