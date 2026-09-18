"""Tests for `_dbt_build_args()` (T21, ADR 0021).

CI's own impact-based `dbt build --select state:modified+ --state <path>` (ADR
0008) narrows a build to a dbt-only change's own modified models and their
descendants, compared against a manifest parsed from the base branch. That
selection logic itself doesn't move here -- computing `DBT_STATE_PATH` (the
base manifest) still needs the same git-worktree-and-`dbt parse` dance
`.github/workflows/ci.yml` already does, unrelated to Dagster. This is only
the one piece that *does* move: what args the now-Dagster-invoked `dbt build`
call receives, read from the same `DBT_SELECT`/`DBT_STATE_PATH` env vars CI
already sets, so the exact same optimization survives the CLI subprocess ->
Dagster asset switch.

Plain unit tests: no live dbt project, no manifest, no SeaweedFS.
"""

import pytest

from orchestration.assets.dbt_project import _dbt_build_args


def test_no_dbt_select_env_var_is_a_plain_unnarrowed_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DBT_SELECT", raising=False)
    monkeypatch.delenv("DBT_STATE_PATH", raising=False)

    assert _dbt_build_args() == ["build"]


def test_dbt_select_all_is_also_a_plain_unnarrowed_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CI's own `changes` job outputs the literal string "all", not an unset
    var, for any change outside `dbt/` (ADR 0008) -- both must mean the
    same thing: build everything."""
    monkeypatch.setenv("DBT_SELECT", "all")
    monkeypatch.delenv("DBT_STATE_PATH", raising=False)

    assert _dbt_build_args() == ["build"]


def test_state_modified_plus_narrows_the_build_with_its_state_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DBT_SELECT", "state:modified+")
    monkeypatch.setenv("DBT_STATE_PATH", "/tmp/pfp-base-manifest")

    assert _dbt_build_args() == [
        "build",
        "--select",
        "state:modified+",
        "--state",
        "/tmp/pfp-base-manifest",
    ]


def test_a_narrowing_select_with_no_state_path_is_passed_through_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not a scenario CI's own `changes` job produces today (`state:modified+`
    always comes with a state path) -- but `--select` without `--state` is a
    legitimate dbt invocation in its own right (e.g. selecting one model by
    name), so this function doesn't invent a requirement dbt itself doesn't
    have."""
    monkeypatch.setenv("DBT_SELECT", "silver.transactions+")
    monkeypatch.delenv("DBT_STATE_PATH", raising=False)

    assert _dbt_build_args() == ["build", "--select", "silver.transactions+"]
