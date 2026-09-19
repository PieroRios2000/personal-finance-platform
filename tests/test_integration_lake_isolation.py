"""The integration suite can run on several pytest-xdist workers at once (CI
speed, tasks/backlog.md): every worker needs its own test lake, or two tests
would wipe each other's bronze tables mid-run."""

from tests.test_dbt_silver_integration import _lake_suffix


def test_without_xdist_the_lake_keeps_its_original_name() -> None:
    assert _lake_suffix(None) == "_t16_dbt_tests"


def test_each_xdist_worker_gets_its_own_lake() -> None:
    assert _lake_suffix("gw0") == "_t16_dbt_tests_gw0"
    assert _lake_suffix("gw1") == "_t16_dbt_tests_gw1"
    assert _lake_suffix("gw0") != _lake_suffix("gw1")
