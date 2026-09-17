"""Tests for `BronzeSourceDbtTranslator` (T21).

`dbt/models/sources.yml` declares `bronze.transactions` and `bronze.statements`
as two dbt sources; `dagster-dbt`'s own default translator would turn those
into two separate stub assets (`bronze/transactions`, `bronze/statements`, its
own default source-key rule -- see `dagster_dbt.asset_utils.default_asset_key_fn`).
But both tables are written by one call, `lakehouse.bronze.write_statement()`,
inside the single `bronze` Dagster asset (`orchestration/assets/bronze.py`) --
so `BronzeSourceDbtTranslator` collapses both dbt sources onto that one real
upstream asset instead, matching the actual data flow (bronze -> silver).

These are plain dict fixtures, the shape one node's entry in a parsed
`manifest.json` takes (`resource_type`/`source_name`/`name`) -- no real dbt
project, manifest or `dbt parse` needed, so this stays a fast unit test rather
than joining `tests/test_dbt_silver_integration.py`'s own `integration` mark.
"""

from typing import Any

import dagster as dg
from orchestration.assets.dbt_project import BronzeSourceDbtTranslator

from orchestration.assets.bronze import bronze


def _source(table_name: str, source_name: str = "bronze") -> dict[str, Any]:
    return {"resource_type": "source", "source_name": source_name, "name": table_name}


def _model(name: str) -> dict[str, Any]:
    return {"resource_type": "model", "name": name, "config": {}}


def test_bronze_transactions_source_maps_to_the_bronze_asset() -> None:
    translator = BronzeSourceDbtTranslator()

    assert translator.get_asset_key(_source("transactions")) == bronze.key


def test_bronze_statements_source_maps_to_the_bronze_asset_too() -> None:
    """Both of `bronze`'s tables collapse onto the one asset that writes them
    together, so the graph shows a single real edge, not two stubs for a
    table Dagster never separately produces."""
    translator = BronzeSourceDbtTranslator()

    assert translator.get_asset_key(_source("statements")) == bronze.key


def test_a_source_from_a_different_dbt_source_group_is_not_remapped() -> None:
    """Only the `bronze` source group is ours to remap; anything else falls
    through to dagster-dbt's own default behavior unchanged."""
    translator = BronzeSourceDbtTranslator()
    key = translator.get_asset_key(_source("orders", source_name="other"))

    assert key == dg.AssetKey(["other", "orders"])


def test_a_dbt_model_is_not_remapped() -> None:
    translator = BronzeSourceDbtTranslator()
    key = translator.get_asset_key(_model("transactions"))

    assert key == dg.AssetKey(["transactions"])
