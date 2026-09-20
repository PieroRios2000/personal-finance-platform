"""Static checks on the Superset stack and its committed dashboards (T32, ADR 0030).
The live behaviour (import, connection as the read-only role, sample rows) is the PR's
verification; these keep the configuration from drifting."""

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parent.parent
_BI = _ROOT / "bi"


_DATASETS = {
    "fact_transactions": 2,
    "fct_investment_monthly": 1,
    "fct_account_balance_monthly": 3,
}


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


def test_the_return_table_shows_closing_basis_right_beside_the_return() -> None:
    (chart,) = [
        c for c in _builder().CHARTS if c[1].startswith("Investments: return and")
    ]
    columns = chart[3]["all_columns"]

    assert columns.index("closing_basis") == columns.index("return_pct") + 1


def test_the_cash_flow_chart_excludes_internal_transfers_and_splits_currencies() -> (
    None
):
    cash_flow = _builder().CHARTS[0][3]

    filters = [f["sqlExpression"] for f in cash_flow["adhoc_filters"]]
    assert "NOT is_internal_transfer" in filters
    assert "currency" in cash_flow["groupby"]


def test_every_chart_reads_a_gold_table_the_dashboard_exports() -> None:
    exported = {p.stem for p in (_BI / "assets" / "datasets").rglob("*.yaml")}

    assert {c[0] for c in _builder().CHARTS} == exported


def test_the_dashboard_has_filters_for_dates_grain_bank_currency_and_fund() -> None:
    filters = _builder().native_filters(_DATASETS)

    by_name = {f["name"]: f for f in filters}
    assert by_name["Date range"]["filterType"] == "filter_time"
    assert by_name["Time grain"]["filterType"] == "filter_timegrain"
    assert by_name["Bank"]["targets"][0]["column"]["name"] == "bank"
    assert by_name["Currency"]["targets"][0]["column"]["name"] == "currency"
    assert by_name["Fund"]["targets"][0]["column"]["name"] == "place"


def test_the_time_grain_starts_monthly_and_the_axis_shows_the_full_date() -> None:
    builder = _builder()
    grain = next(
        f for f in builder.native_filters(_DATASETS) if f["name"] == "Time grain"
    )

    assert grain["defaultDataMask"]["extraFormData"] == {"time_grain_sqla": "P1M"}
    # `smart_date` prints a January 1st as just the year: it read as a yearly total.
    timeseries = [c for c in builder.CHARTS if c[2].startswith("echarts_timeseries")]
    assert timeseries and all(
        c[3]["x_axis_time_format"] == "%Y-%m-%d" for c in timeseries
    )


def test_there_are_filters_to_slice_movements_for_validation() -> None:
    by_name = {f["name"]: f for f in _builder().native_filters(_DATASETS)}

    assert by_name["Flow type"]["targets"][0]["column"]["name"] == "flow_type"
    assert by_name["Internal transfer"]["targets"][0]["column"]["name"] == (
        "is_internal_transfer"
    )
    assert by_name["Account"]["targets"][0]["column"]["name"] == "account_last4"


def test_the_movements_and_balances_tables_exist_to_check_against_the_statements() -> (
    None
):
    tables = {c[1]: c for c in _builder().CHARTS if c[2] == "table"}

    movements = tables["Movements (check against your statements)"]
    assert movements[0] == "fact_transactions"
    assert {"date", "bank", "currency", "flow_type", "amount", "description"} <= set(
        movements[3]["all_columns"]
    )
    balances = tables["Statement balances (check against your statements)"]
    assert balances[0] == "fct_account_balance_monthly"
    assert {"closing_date", "account_last4", "closing_balance"} <= set(
        balances[3]["all_columns"]
    )


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


def test_every_dated_chart_has_a_time_range_filter_for_the_date_range() -> None:
    """Superset's Date range filter only narrows a chart that already has a time-range
    (TEMPORAL_RANGE) filter on its date column; without one it silently does nothing."""
    builder = _builder()
    date_columns = {"date", "month_start"}

    for _, name, _, params in builder.CHARTS:
        column = params.get("x_axis") or next(
            (c for c in params.get("all_columns", []) if c in date_columns), None
        )
        assert column, name
        ranges = [
            f for f in params["adhoc_filters"] if f.get("operator") == "TEMPORAL_RANGE"
        ]
        assert [f["subject"] for f in ranges] == [column], name


def test_the_time_grain_filter_names_a_dataset_to_take_its_options_from() -> None:
    grain = next(
        f for f in _builder().native_filters(_DATASETS) if f["name"] == "Time grain"
    )

    # Without a dataset the filter has no grains to offer and shows blank values.
    assert grain["targets"] == [{"datasetId": _DATASETS["fact_transactions"]}]
