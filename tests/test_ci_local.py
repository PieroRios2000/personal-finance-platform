"""`make ci-local`: run a CI job's own steps, from `.github/workflows/ci.yml`, in a
clean clone of what is committed and with only that job's environment.

Why it exists: the CI job `tests` broke once because it has no PFP_PG_* variables and
a fresh checkout has no `dbt/target`, while every local run had both. The tool runs
the very same steps, so the differences stop being a surprise (tasks/backlog.md).
"""

import subprocess
from pathlib import Path

import pytest

from scripts import ci_local

_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW = _ROOT / ".github" / "workflows" / "ci.yml"
_CLONE = Path("/tmp/pfp-ci-clone")


def _plan(job: str) -> ci_local.Plan:
    return ci_local.plan(_WORKFLOW, job, workspace=_CLONE, run_id="42")


def test_the_tests_job_runs_with_only_its_own_variables() -> None:
    """The minimal environment is the point: no Postgres, no S3 credentials beyond
    the dummies, so a variable a parse needs but does not have shows up here."""
    environment = _plan("tests").environment

    assert environment["LAKEHOUSE_URI"] == "s3://lakehouse"
    assert not [name for name in environment if name.startswith("PFP_PG_")]
    assert environment["UV_VERSION"]  # the workflow-level variables apply too


def test_the_ephemeral_job_gets_its_own_variables_with_expressions_resolved() -> None:
    environment = _plan("ephemeral-integration").environment

    assert environment["PFP_PG_DATABASE"] == "pfp"
    assert environment["COMPOSE_PROJECT"] == "pfp-pr-42"
    assert (
        environment["PFP_ELEMENTARY_DUCKDB_PATH"] == f"{_CLONE}/dbt/elementary.duckdb"
    )
    assert environment["DBT_SELECT"] == "all"


def test_only_run_steps_are_planned_and_uses_steps_are_left_out() -> None:
    steps = _plan("lint-types").steps

    assert steps and all(step.script for step in steps)
    assert any("ruff check" in step.script for step in steps)


def test_steps_that_only_make_sense_on_github_are_skipped_with_a_reason() -> None:
    plan = _plan("tests")

    assert any("sudo" in reason for _, reason in plan.skipped)


def test_a_conditional_step_is_skipped_but_an_always_step_runs_last() -> None:
    plan = _plan("ephemeral-integration")

    scripts = [step.script for step in plan.steps]
    assert any(
        "compute the dbt build selection" in reason for _, reason in plan.skipped
    ) or not any("state:modified" in s for s in scripts)
    assert "docker compose" in scripts[-1] and "down -v" in scripts[-1]
    assert plan.steps[-1].always


def test_an_unknown_github_expression_is_refused_not_guessed() -> None:
    with pytest.raises(ci_local.UnsupportedExpression, match=r"github\.actor"):
        ci_local.resolve("${{ github.actor }}", workspace=_CLONE, run_id="1")


def test_known_expressions_are_resolved() -> None:
    assert (
        ci_local.resolve("${{ github.workspace }}/x", workspace=_CLONE, run_id="1")
        == f"{_CLONE}/x"
    )
    assert (
        ci_local.resolve(
            "pfp-pr-${{ github.event.pull_request.number || github.run_id }}",
            workspace=_CLONE,
            run_id="7",
        )
        == "pfp-pr-7"
    )
    assert (
        ci_local.resolve(
            "${{ github.event.pull_request.base.ref || 'develop' }}",
            workspace=_CLONE,
            run_id="1",
        )
        == "develop"
    )


def test_every_job_the_tool_offers_can_be_planned_from_the_real_workflow() -> None:
    for job in ci_local.DEFAULT_JOBS + ci_local.FULL_JOBS:
        assert _plan(job).steps, job


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.test")
    _git(repo, "config", "user.name", "t")
    (repo / "committed.txt").write_text("in git\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def test_the_clone_holds_what_is_committed_and_nothing_left_lying_around(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    (repo / "untracked.txt").write_text("not committed\n")
    (repo / "dbt" / "target").mkdir(parents=True)
    (repo / "dbt" / "target" / "manifest.json").write_text("{}")

    clone = ci_local.clone_head(repo, tmp_path / "clone")

    assert (clone / "committed.txt").exists()
    assert not (clone / "untracked.txt").exists()
    assert not (clone / "dbt" / "target").exists()


def test_uncommitted_changes_are_reported_because_ci_would_not_see_them(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    assert ci_local.uncommitted(repo) == []

    (repo / "committed.txt").write_text("changed\n")
    (repo / "new.txt").write_text("new\n")

    assert sorted(ci_local.uncommitted(repo)) == ["committed.txt", "new.txt"]


def test_the_clone_points_at_the_real_origin_so_fetches_see_the_real_base(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    _git(repo, "remote", "add", "origin", "https://example.test/real.git")

    clone = ci_local.clone_head(repo, tmp_path / "clone")

    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=clone,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert remote == "https://example.test/real.git"


def test_a_failing_step_stops_the_job_but_the_always_steps_still_run() -> None:
    plan = ci_local.Plan(
        environment={},
        steps=[
            ci_local.Step("one", "one", False, False),
            ci_local.Step("two", "two", False, False),
            ci_local.Step("teardown", "teardown", False, True),
        ],
        skipped=[],
    )
    ran: list[str] = []

    def runner(step: ci_local.Step) -> int:
        ran.append(step.script)
        return 1 if step.script == "one" else 0

    ok = ci_local.execute(plan, runner)

    assert not ok
    assert ran == ["one", "teardown"]


def test_a_continue_on_error_step_does_not_fail_the_job() -> None:
    plan = ci_local.Plan(
        environment={},
        steps=[
            ci_local.Step("warn", "warn", True, False),
            ci_local.Step("after", "after", False, False),
        ],
        skipped=[],
    )
    ran: list[str] = []

    def runner(step: ci_local.Step) -> int:
        ran.append(step.script)
        return 1 if step.script == "warn" else 0

    assert ci_local.execute(plan, runner)
    assert ran == ["warn", "after"]


def test_a_busy_port_is_reported_so_full_runs_do_not_collide_with_a_stack() -> None:
    import socket

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        busy_port = listener.getsockname()[1]

        assert ci_local.ports_in_use((busy_port,)) == [busy_port]

    assert ci_local.ports_in_use((busy_port,)) == []


def test_make_has_the_fast_and_the_full_targets() -> None:
    import re

    makefile = (_ROOT / "Makefile").read_text()

    assert re.search(r"^ci-local:\n\t.*scripts\.ci_local\s*$", makefile, re.M)
    assert re.search(r"^ci-local-full:\n\t.*scripts\.ci_local --full", makefile, re.M)


def test_the_files_github_gives_every_step_exist_locally_too(tmp_path: Path) -> None:
    """Scripts write to `$GITHUB_STEP_SUMMARY` (and `$GITHUB_ENV`, `$GITHUB_OUTPUT`):
    unset, `>> "$GITHUB_STEP_SUMMARY"` fails with 'No such file or directory'."""
    variables = ci_local.github_files(tmp_path)

    assert set(variables) == {"GITHUB_STEP_SUMMARY", "GITHUB_ENV", "GITHUB_OUTPUT"}
    for path in variables.values():
        with Path(path).open("a") as handle:
            handle.write("x\n")
