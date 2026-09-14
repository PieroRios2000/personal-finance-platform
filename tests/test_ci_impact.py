"""Tests for scripts.ci_impact: CI's impact map (T15, ADR 0008).

These are what makes the `changes` job's decision reviewable without a live
GitHub Actions run: each test feeds a synthetic `git diff --name-only` file
list and asserts which way the decision goes.
"""

import io

import pytest

from scripts import ci_impact

DOCS_ONLY = [
    "brain/decisions/0008-impact-based-ci.md",
    "brain/phases/phase-1.md",
    "tasks/todo.md",
    "README.md",
]


def test_a_docs_only_change_does_not_run_benchmarks() -> None:
    assert ci_impact.runs_benchmarks(DOCS_ONLY) is False


def test_a_change_under_ingestion_runs_benchmarks() -> None:
    assert ci_impact.runs_benchmarks(["ingestion/parsers/bcp.py"]) is True


def test_a_change_under_lakehouse_runs_benchmarks() -> None:
    assert ci_impact.runs_benchmarks(["lakehouse/bronze.py"]) is True


@pytest.mark.parametrize(
    "path",
    ["pyproject.toml", "uv.lock", "docker-compose.yml", ".github/workflows/ci.yml"],
)
def test_a_change_to_the_dependencies_or_the_pipeline_runs_benchmarks(
    path: str,
) -> None:
    """The impact map can't see inside these, so they run everything
    (tasks/plan.md's "Impact-based CI" table)."""
    assert ci_impact.runs_benchmarks([path]) is True


def test_a_change_to_the_benchmarks_themselves_runs_benchmarks() -> None:
    assert ci_impact.runs_benchmarks(["tests/benchmarks/test_parsing.py"]) is True


def test_one_affected_file_among_docs_is_enough() -> None:
    assert ci_impact.runs_benchmarks([*DOCS_ONLY, "lakehouse/storage.py"]) is True


def test_an_empty_diff_does_not_run_benchmarks() -> None:
    assert ci_impact.runs_benchmarks([]) is False


def test_the_prefixes_are_anchored_to_a_whole_directory() -> None:
    """A path that merely starts with the same letters isn't a match: only a
    real `ingestion/` or `lakehouse/` directory entry is."""
    assert ci_impact.runs_benchmarks(["tasks/ingestion-notes.md"]) is False
    assert ci_impact.runs_benchmarks(["lakehouse-notes.md"]) is False


def test_a_docs_only_change_does_not_run_the_integration_environment() -> None:
    assert ci_impact.runs_integration(DOCS_ONLY) is False


@pytest.mark.parametrize(
    "path",
    [
        "ingestion/cli.py",
        "lakehouse/bronze.py",
        "dbt/models/silver/transactions.sql",
        "docker-compose.yml",
        "Makefile",
        "pyproject.toml",
        "uv.lock",
        ".github/workflows/ci.yml",
    ],
)
def test_what_the_ephemeral_environment_runs_or_is_made_of(path: str) -> None:
    """The code the job exercises (`pfp ingest`, bronze, dbt), plus the files
    that define the environment and the job itself."""
    assert ci_impact.runs_integration([path]) is True


def test_an_integration_test_itself_runs_the_environment() -> None:
    """This job is the only place the `integration`-marked tests run at all."""
    assert ci_impact.runs_integration(["tests/test_bronze_integration.py"]) is True
    assert ci_impact.runs_integration(["tests/test_dbt_silver_integration.py"]) is True


def test_an_ordinary_test_does_not_run_the_environment() -> None:
    """Only `tests/*_integration.py` does; spinning up SeaweedFS to run a
    parser's unit test would be minutes spent to learn nothing."""
    assert ci_impact.runs_integration(["tests/parsers/test_bcp.py"]) is False
    assert ci_impact.runs_integration(["tests/benchmarks/test_parsing.py"]) is False


def test_an_empty_diff_does_not_run_the_environment() -> None:
    assert ci_impact.runs_integration([]) is False


def test_the_two_signals_are_independent_questions_about_one_diff() -> None:
    """They overlap on the shared trigger paths and diverge elsewhere: a dbt
    model changes what the environment builds and nothing the benchmarks
    measure; a benchmark's own code is the other way round."""
    dbt_only = ["dbt/models/silver/transactions.sql"]
    assert ci_impact.runs_integration(dbt_only) is True
    assert ci_impact.runs_benchmarks(dbt_only) is False

    benchmarks_only = ["tests/benchmarks/test_parsing.py"]
    assert ci_impact.runs_integration(benchmarks_only) is False
    assert ci_impact.runs_benchmarks(benchmarks_only) is True

    shared = ["lakehouse/bronze.py"]
    assert ci_impact.runs_integration(shared) is True
    assert ci_impact.runs_benchmarks(shared) is True


def test_a_dbt_only_change_builds_just_what_changed() -> None:
    assert ci_impact.dbt_selection(["dbt/models/silver/transactions.sql"]) == (
        "state:modified+"
    )


def test_docs_alongside_a_dbt_change_still_build_just_what_changed() -> None:
    """Every PR here updates `brain/` and `tasks/`; a note about a model is not
    a reason to rebuild every model."""
    assert ci_impact.dbt_selection([*DOCS_ONLY, "dbt/tests/x.sql"]) == (
        "state:modified+"
    )


@pytest.mark.parametrize(
    "path", ["ingestion/parsers/bcp.py", "lakehouse/bronze.py", "uv.lock"]
)
def test_a_change_outside_dbt_builds_everything(path: str) -> None:
    """A parser, the bronze writer or a dependency can change what the data
    looks like without touching a model, and no state comparison would see it."""
    assert (
        ci_impact.dbt_selection([path, "dbt/models/silver/transactions.sql"]) == "all"
    )
    assert ci_impact.dbt_selection([path]) == "all"


def test_a_diff_that_affects_nothing_builds_everything() -> None:
    """Unreachable in CI (the job doesn't run at all), and `all` either way:
    the narrowing only ever applies to a diff that is dbt and nothing else."""
    assert ci_impact.dbt_selection(DOCS_ONLY) == "all"
    assert ci_impact.dbt_selection([]) == "all"


def test_main_writes_the_github_actions_outputs_for_an_affected_change(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("ingestion/parsers/bcp.py\n"))

    assert ci_impact.main() == 0
    assert capsys.readouterr().out.splitlines() == [
        "benchmarks=true",
        "integration=true",
        "dbt_select=all",
    ]


def test_main_writes_the_github_actions_outputs_for_a_docs_only_change(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(DOCS_ONLY) + "\n"))

    assert ci_impact.main() == 0
    assert capsys.readouterr().out.splitlines() == [
        "benchmarks=false",
        "integration=false",
        "dbt_select=all",
    ]


def test_main_writes_the_narrowed_dbt_selection(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sys.stdin", io.StringIO("dbt/models/silver/transactions.sql\n")
    )

    assert ci_impact.main() == 0
    assert capsys.readouterr().out.splitlines() == [
        "benchmarks=false",
        "integration=true",
        "dbt_select=state:modified+",
    ]
