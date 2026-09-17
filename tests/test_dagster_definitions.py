"""Tests for the top-level Dagster `Definitions` (T21).

Loading `orchestration.definitions` is what `uv run dagster asset materialize
--select '*'` does first (via `pyproject.toml`'s `[tool.dagster] module_name`,
see `tests/test_dagster_cli_discovery.py` for that wiring specifically). These
tests check the shape of the resulting asset graph -- in particular the real
bronze -> silver dependency edge this task's acceptance criteria ask for --
without materializing anything (that needs a real or ephemeral lake; see
`tests/test_dagster_pipeline_integration.py`, `integration`-marked).
"""

import dagster as dg
from orchestration.definitions import defs

from orchestration.assets.bronze import bronze


def test_defs_is_a_definitions_object() -> None:
    assert isinstance(defs, dg.Definitions)


def test_the_bronze_asset_and_every_dbt_node_are_registered() -> None:
    asset_graph = defs.resolve_asset_graph()
    keys = asset_graph.get_all_asset_keys()

    assert bronze.key in keys
    # The dbt DAG as it stands today (T16, T18b): silver.transactions and its
    # three internal-transfer models. Not an exhaustive list on purpose --
    # whatever gold models T23 adds should show up here with no change to
    # this test, which is the whole point of selecting the dbt project's
    # default `fqn:*` rather than one hardcoded model (see
    # orchestration/assets/dbt_project.py).
    for model in (
        "transactions",
        "internal_transfer_matches",
        "internal_transfers",
        "unmatched_transfers",
    ):
        assert dg.AssetKey([model]) in keys


def test_silver_transactions_depends_on_the_bronze_asset() -> None:
    """The real data-flow edge this task's own acceptance criteria ask for:
    `silver.transactions` reads `bronze.transactions`/`bronze.statements`
    (dbt/models/sources.yml), both of which collapse onto the one Python
    `bronze` asset that writes them (BronzeSourceDbtTranslator)."""
    asset_graph = defs.resolve_asset_graph()

    upstream = asset_graph.get(dg.AssetKey(["transactions"])).parent_keys

    assert bronze.key in upstream
