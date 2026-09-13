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


def test_main_writes_a_true_github_actions_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("ingestion/parsers/bcp.py\n"))

    assert ci_impact.main() == 0
    assert capsys.readouterr().out.strip() == "benchmarks=true"


def test_main_writes_a_false_github_actions_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(DOCS_ONLY) + "\n"))

    assert ci_impact.main() == 0
    assert capsys.readouterr().out.strip() == "benchmarks=false"
