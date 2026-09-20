"""Run a CI job's own steps locally, the way CI runs them.

    uv run python -m scripts.ci_local [--full] [--allow-dirty] [--keep] [JOB ...]

`make ci-local` runs the fast jobs (lint-types, tests, architecture, floor-guard);
`make ci-local-full` adds ephemeral-integration (needs Docker, and the ports its
SeaweedFS and Postgres use free).

What makes it the same as CI, not a lookalike:
- The steps and the environment come **from `.github/workflows/ci.yml` itself**
  (its `run:` scripts and its `env:`), so there is one definition, not two.
- They run in a **clean clone of what is committed** (no `dbt/target`, no
  `dbt_packages`, no `.env`, nothing untracked), with `env -i`-style isolation:
  only HOME and PATH plus that job's own variables. A job with no Postgres
  variables runs without them.
- Uncommitted changes are refused: CI would not see them.

That gap is why this exists: the `tests` job once failed because it has no
PFP_PG_* variables and a fresh checkout has no `dbt/target`, while every local
run had both.

Skipped, with a printed reason: steps with a condition (`if:`) other than
`always()`, and steps that need `sudo`. `uses:` steps (checkout, setup-uv, ...)
are what this tool replaces. GitHub expressions it cannot evaluate make the job
refuse to run rather than guess.
"""

import argparse
import os
import re
import socket
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_JOBS = ("lint-types", "tests", "architecture", "floor-guard")
FULL_JOBS = ("ephemeral-integration",)
# Fixed by the workflow's own environment for ephemeral-integration.
_FULL_JOB_PORTS = (8333, 5432)
_EXPRESSION = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")


class UnsupportedExpression(Exception):
    """A `${{ ... }}` the tool cannot evaluate locally."""


@dataclass(frozen=True)
class Step:
    name: str
    script: str
    continue_on_error: bool
    always: bool


@dataclass
class Plan:
    environment: dict[str, str]
    steps: list[Step]
    skipped: list[tuple[str, str]] = field(default_factory=list)


def resolve(text: str, *, workspace: Path, run_id: str) -> str:
    known = {
        "github.workspace": str(workspace),
        "github.run_id": run_id,
        "github.event.pull_request.number || github.run_id": run_id,
        "github.event.pull_request.base.ref || 'develop'": "develop",
        "needs.changes.outputs.dbt_select": "all",
    }

    def replace(match: "re.Match[str]") -> str:
        expression = match.group(1)
        if expression not in known:
            raise UnsupportedExpression(
                f"cannot evaluate ${{{{ {expression} }}}} locally"
            )
        return known[expression]

    return _EXPRESSION.sub(replace, text)


def plan(workflow: Path, job: str, *, workspace: Path, run_id: str) -> Plan:
    loaded: dict[str, Any] = yaml.safe_load(workflow.read_text())
    spec: dict[str, Any] = loaded["jobs"][job]
    raw_env: dict[str, Any] = {**(loaded.get("env") or {}), **(spec.get("env") or {})}
    environment = {
        name: resolve(str(value), workspace=workspace, run_id=run_id)
        for name, value in raw_env.items()
    }

    steps: list[Step] = []
    skipped: list[tuple[str, str]] = []
    for raw in spec.get("steps", []):
        script = raw.get("run")
        if not script:
            continue
        name = raw.get("name") or script.strip().splitlines()[0][:60]
        condition = str(raw["if"]).strip() if "if" in raw else None
        if condition not in (None, "always()"):
            skipped.append((name, f"conditional step ({condition})"))
            continue
        if "sudo " in script:
            skipped.append((name, "needs sudo: install it yourself if it is missing"))
            continue
        steps.append(
            Step(
                name=name,
                script=resolve(script, workspace=workspace, run_id=run_id),
                continue_on_error=raw.get("continue-on-error") is True,
                always=condition == "always()",
            )
        )
    ordered = [s for s in steps if not s.always] + [s for s in steps if s.always]
    return Plan(environment=environment, steps=ordered, skipped=skipped)


def execute(job_plan: Plan, runner: Callable[[Step], int]) -> bool:
    """Run the steps in order; stop at the first failure (unless the step
    continues on error), but always run the `always()` steps at the end."""
    ok = True
    for step in job_plan.steps:
        if step.always:
            runner(step)
            continue
        if not ok:
            continue
        if runner(step) != 0 and not step.continue_on_error:
            ok = False
    return ok


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def uncommitted(repo: Path) -> list[str]:
    # Not through `_git`: it strips the first line's leading status column.
    lines = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return [line[3:].split(" -> ")[-1] for line in lines if line.strip()]


def clone_head(repo: Path, destination: Path) -> Path:
    """A clean clone of the commit `repo` is at: only what is committed."""
    sha = _git(repo, "rev-parse", "HEAD")
    subprocess.run(
        ["git", "clone", "-q", str(repo), str(destination)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "checkout", "-q", sha], cwd=destination, check=True, capture_output=True
    )
    try:
        origin = _git(repo, "remote", "get-url", "origin")
    except subprocess.CalledProcessError:
        return destination
    # The clone's own origin is the local repo, whose branches may be stale:
    # steps that `git fetch origin <base>` must see the real one.
    _git(destination, "remote", "set-url", "origin", origin)
    return destination


def ports_in_use(ports: tuple[int, ...]) -> list[int]:
    busy = []
    for port in ports:
        with socket.socket() as probe:
            probe.settimeout(0.3)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                busy.append(port)
    return busy


def _runner(job_plan: Plan, clone: Path, job: str) -> Callable[[Step], int]:
    base = {
        name: os.environ[name]
        for name in ("HOME", "PATH", "LANG")
        if name in os.environ
    }

    def run(step: Step) -> int:
        print(f"\n==> [{job}] {step.name}", flush=True)
        return subprocess.run(
            ["bash", "-e", "-c", step.script],
            cwd=clone,
            env={**base, **job_plan.environment},
            check=False,
        ).returncode

    return run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ci_local")
    parser.add_argument("jobs", nargs="*", help="jobs to run (default: the fast ones)")
    parser.add_argument(
        "--full", action="store_true", help="also ephemeral-integration"
    )
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--keep", action="store_true", help="keep the clean clone")
    args = parser.parse_args(argv)

    repo = Path(__file__).resolve().parent.parent
    jobs = tuple(args.jobs) or (DEFAULT_JOBS + (FULL_JOBS if args.full else ()))
    changes = uncommitted(repo)
    if changes and not args.allow_dirty:
        print("ci-local: CI only sees what is committed. Uncommitted:", file=sys.stderr)
        for path in changes[:10]:
            print(f"  {path}", file=sys.stderr)
        print(
            "Commit first, or pass --allow-dirty to test the last commit.",
            file=sys.stderr,
        )
        return 2
    if set(jobs) & set(FULL_JOBS):
        busy = ports_in_use(_FULL_JOB_PORTS)
        if busy:
            print(
                f"ci-local: ports {busy} are in use (your `make poc-up` stack?): "
                "ephemeral-integration binds them. `make poc-down` first.",
                file=sys.stderr,
            )
            return 2

    workspace = Path(tempfile.mkdtemp(prefix="pfp-ci-local-")) / "checkout"
    clone = clone_head(repo, workspace)
    results: dict[str, bool] = {}
    try:
        for job in jobs:
            job_plan = plan(
                clone / ".github" / "workflows" / "ci.yml",
                job,
                workspace=clone,
                run_id="local",
            )
            for name, reason in job_plan.skipped:
                print(f"    [{job}] skipped: {name} ({reason})")
            results[job] = execute(job_plan, _runner(job_plan, clone, job))
            summary = (clone.parent / "github_step_summary").read_text().strip()
            if summary:
                print(f"\n-- [{job}] step summary --\n{summary}")
            (clone.parent / "github_step_summary").write_text("")
    finally:
        if args.keep:
            print(f"\nclean clone kept at {clone}")
        else:
            subprocess.run(["rm", "-rf", str(clone.parent)], check=False)

    print("\n== ci-local summary ==")
    for job, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {job}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
