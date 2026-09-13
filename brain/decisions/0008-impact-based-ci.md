---
type: decision
phase: 1
status: accepted
date: 2026-09-13
---

# ADR 0008: Impact-based CI

## Context

CI's five jobs (T5) all run on every PR and take seconds to a couple of minutes, which is
fine. What comes next isn't: T15's benchmarks measure the base branch *and* the PR on the
same runner (two full runs), and T17's ephemeral environment spins up SeaweedFS, ingests
synthetic data and runs `dbt build` on top of that. Running all of it on a PR that only
edits `brain/` notes would trade minutes of waiting for no information at all — and a slow
pipeline is one people learn to ignore or bypass.

The obvious lever, a workflow-level `paths:` filter, is the one thing this repo can't use:
a required check whose workflow is filtered out never reports, so the PR sits on "Expected —
Waiting for status to be reported" and can't be merged (already written down in
[CI](../components/ci.md)'s "details that must not break").

The real risk in skipping anything is the opposite mistake: skipping a job that *would* have
caught something, because the map doesn't know that A depends on B.

## Decision

**Cheap checks always run in full; expensive ones run only when the change can affect them,
and everything runs in full on a schedule anyway.**

- **Always, on every PR, whole project:** ruff, mypy, unit pytest, gitleaks, pip-audit,
  bandit, import-linter, floor-guard. They take seconds, and mypy in particular *needs* the
  whole project — seeing that a change breaks whoever imports it is exactly the indirect
  effect a file-path map can't see.
- **Only when affected:** benchmarks (T15) today; the ephemeral environment and `dbt build`
  (T17, ADR 0007) next.
- **The map is code, not YAML** — [`scripts/ci_impact.py`](../../scripts/ci_impact.py).
  `runs_benchmarks(changed_files)` is True if any changed path is under `ingestion/`,
  `lakehouse/`, `tests/benchmarks/` or `.github/`, or is `docker-compose.yml`,
  `pyproject.toml` or `uv.lock`: the code the benchmarks measure, the benchmarks themselves,
  and the things no map can see inside (the dependency set, the platform, the pipeline
  definition). Everything else — `*.md`, `brain/`, `tasks/`, other tests — doesn't run them.
- **How a job gets skipped:** a `changes` job pipes `git diff --name-only
  origin/<base>...HEAD` into that script and publishes the answer as a job output; each
  expensive job carries its own `if: needs.changes.outputs.<area> == 'true'`. Never a
  workflow-level `paths:` filter, and never an `if` on a control like `branch-policy` or on
  a floor check: a skipped job reports success, so only what the change genuinely doesn't
  affect may be skipped.
- **Safety net:** a push to `develop` and a weekly schedule (Mondays 06:00 UTC) run
  everything, without consulting the map. The `changes` job answers `true` outright for
  those events.

## Alternatives considered

- **A `paths:` filter on the workflow**: the one option that's actually forbidden here —
  required checks never report and the PR can't merge. This is why the decision is "a
  `changes` job plus per-job `if`", not "filter the workflow".
- **[`dorny/paths-filter`](https://github.com/dorny/paths-filter) or
  `tj-actions/changed-files`**: does the same job as a third-party action. A dependency to
  pin and audit, a YAML dialect to learn, and — the thing that decided it — no way to check
  the decision without pushing a commit and watching Actions. A 40-line stdlib script is
  testable from `pytest` in both directions (`tests/test_ci_impact.py`) and runs with the
  runner's own `python3`, before `uv sync`.
- **Running everything, always**: simplest, and what the repo does today. Rejected for what
  T15 and T17 add, not for what exists now: a docs PR would spend minutes spinning up
  containers to tell us nothing about a Markdown edit.
- **Skipping the cheap checks too (lint/types/tests by path)**: rejected. They're seconds,
  and they're precisely what catches breakage *between* modules — the class of indirect
  effect a file-path map is blind to. Narrowing them would trade the map's only real weak
  spot for nothing.

## Consequences

- A docs-only PR runs the five original jobs and skips the benchmarks; a PR touching
  `ingestion/` or `lakehouse/` runs them. Both verified locally against real diffs from this
  repo's history (`git diff --name-only <commit>^ <commit> | python3 scripts/ci_impact.py`).
- **The map can be wrong, and the failure mode is silence** — a skipped job looks like a
  green one. Three things bound that: the cheap checks never skip, anything opaque
  (dependencies, compose, `.github/`) runs everything, and the weekly run plus every push to
  `develop` re-runs the lot. A miss costs at most a week of not knowing, never a permanent
  blind spot.
- `benchmarks` and `changes` are deliberately **not** required checks in the ruleset: they're
  skippable by design, and a required check that's usually skipped teaches nobody anything.
  The five original jobs stay required and never skip.
- Adding an area later (T17's environment) is one more prefix list and one more output in
  the same script, with its own tests — not a new mechanism.
- A scheduled run uses whatever branch GitHub gives a `schedule` event, which is the
  repository's default branch (`main`), not `develop`. Accepted as-is: `main` only ever
  receives `develop`, so the weekly run still exercises the whole pipeline end to end, and
  every push to `develop` already covers `develop` itself.
- The diff-based jobs (`tests`' diff-cover, `floor-guard`) needed a base to compare against
  outside a PR, where `github.event.pull_request.base.ref` is empty: a workflow-level
  `PFP_BASE_REF` defaults them to `develop`, which on a push to `develop` means comparing it
  against itself — an empty diff they pass trivially, while the full test, lint, security and
  benchmark runs still happen. The prefix isn't decoration: a plain `BASE_REF` in the
  workflow's env is read by gitleaks-action as *its* scan range, which turned the `security`
  job red on this very PR (`fatal: ambiguous argument 'develop^..<sha>'`).
- **A benchmark has to measure the same work every round, not the same call.** The first CI run
  flagged the bronze append at +26% on code the PR never touched: every round appended to the
  same lake, so each one paid for a longer Delta log, and pytest-benchmark's auto-calibrated
  round count (57 against 71) turned that into a systematic difference between the two runs.
  Each round now writes into its own empty lake. Worth remembering for T17's benchmarks: any
  measured operation that leaves state behind will drift the same way.

## Related

- [ADR 0007: Ephemeral per-PR environments](0007-ephemeral-per-pr-environments.md) — the
  next expensive job this map gates (T17).
- [CI](../components/ci.md) — the workflow this describes, and the rules it must not break.
- [Quality bar](../components/quality-bar.md) — the performance rule the `benchmarks` job
  enforces (warns until 2026-09-26).
- [Phase 1](../phases/phase-1.md) — "Impact-based CI (ADR 0008)" in
  [tasks/plan.md](../../tasks/plan.md).
