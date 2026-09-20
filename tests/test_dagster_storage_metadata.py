"""T31: the storage metadata added to each dbt model's materialization must never be
able to fail the build, and must not replace the metadata dagster-dbt already set."""

import dagster as dg
import pytest

from orchestration.assets import dbt_project

_KEY = dg.AssetKey(["gold", "fact_transactions"])


def test_the_table_is_reported_even_when_the_row_count_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unreachable(schema: str, table: str) -> int:
        raise OSError("postgres is down")

    monkeypatch.setattr(dbt_project, "_postgres_row_count", unreachable)
    monkeypatch.setenv("PFP_DBT_TARGET", "postgres")

    metadata = dbt_project._storage_metadata(_KEY, log=lambda message: None)

    assert metadata == {"dagster/table_name": "gold.fact_transactions"}


def test_the_failed_row_count_is_logged_not_swallowed_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unreachable(schema: str, table: str) -> int:
        raise OSError("postgres is down")

    monkeypatch.setattr(dbt_project, "_postgres_row_count", unreachable)
    monkeypatch.setenv("PFP_DBT_TARGET", "postgres")
    logged: list[str] = []

    dbt_project._storage_metadata(_KEY, log=logged.append)

    assert len(logged) == 1 and "gold.fact_transactions" in logged[0]


def test_the_local_target_reports_only_the_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PFP_DBT_TARGET", "local")

    assert dbt_project._storage_metadata(_KEY, log=lambda message: None) == {
        "dagster/table_name": "gold.fact_transactions"
    }


def test_a_key_that_is_not_a_project_model_gets_no_metadata() -> None:
    assert dbt_project._storage_metadata(dg.AssetKey("nope"), log=print) == {}
