---
type: decision
phase: 1
status: accepted
date: 2026-09-14
---

# ADR 0013: dbt state comparison via a base-ref worktree, in the same job

## Context

ADR 0008 already decided *that* T17's `ephemeral-integration` job should narrow `dbt build`
to `state:modified+` when the diff is confined to `dbt/`, and `scripts/ci_impact.py`'s
`dbt_selection()` already decides *when*. What neither settled is *how* the job gets a
manifest to compare against: dbt's `state:modified` selector needs a previous manifest.json
on disk (`--state <dir>`), and the only one that means anything here is the base branch's —
the PR's own `dbt/` directory, freshly checked out, has no prior manifest of its own.

## Decision

**One job, two dbt projects on disk, no second CI job.** `ephemeral-integration` fetches the
base ref, adds a second, detached worktree of it (`git worktree add --detach
/tmp/pfp-base-ref origin/$PFP_BASE_REF`), and runs `dbt parse --project-dir
/tmp/pfp-base-ref/dbt --profiles-dir dbt --target-path /tmp/pfp-base-manifest` — the
`--profiles-dir` stays the PR's own (`dbt/profiles.yml` is connection config, not modeling,
and identical either side of almost every real change). That manifest is then `dbt build`'s
`--state` for the PR's own `--select state:modified+` run, still in the same job, same
checkout, same already-running SeaweedFS.

- **A worktree, not a second `actions/checkout`, a second job, or `git stash` gymnastics**:
  the repository is already cloned (this job's own `actions/checkout` step) and the base ref
  is already reachable (`git fetch origin "$PFP_BASE_REF"`, the same line `changes` and
  `benchmarks` use) — a worktree is one command, reuses that clone's objects, and needs no
  second `uv sync` or a second SeaweedFS.
- **One job, not two**: splitting "parse base" and "build PR" into separate jobs would need
  an `actions/upload-artifact` / `download-artifact` round trip just to move a manifest
  between them, for a step that takes seconds. The whole point of ADR 0008's narrowing is to
  save time; adding two artifact transfers to save a `dbt parse` is a net loss.
- **Only when narrowed**: when `dbt_select` is `all` (anything outside `dbt/` changed, or the
  diff affects nothing dbt cares about), the job skips this whole branch and runs a plain
  `dbt build` — the worktree and the extra `dbt parse` are pure overhead a full build gets
  nothing from.

## Alternatives considered

- **A separate `dbt-state` job that uploads the base manifest as an artifact, consumed by
  `ephemeral-integration`**: the "textbook" cross-job data-passing pattern, rejected for the
  reason above — two artifact round trips and a second `uv sync` to save one `dbt parse`
  that runs in seconds against an unmodeled base project.
  - **`git checkout origin/$PFP_BASE_REF -- dbt` into the same working tree** (the pattern
    `benchmarks` already uses for `ingestion`/`lakehouse`): rejected specifically for dbt,
    unlike `benchmarks`' case. `benchmarks` swaps code, measures, and restores before doing
    anything else with the tree; here, the *next* step needs the PR's own `dbt/` back in place
    to actually build it, and `dbt parse` also writes `dbt/target/`-shaped output next to
    whatever's checked out — safer to keep the base ref in a directory of its own than to
    swap the working tree twice and rely on getting the restore right every time.
- **Committing a manifest.json in the repo, refreshed on every merge to `develop`**: the more
  common approach for a *shared, long-lived* warehouse (Slim CI against a persistent prod
  manifest), rejected because it doesn't fit this project at all: there is no persistent dbt
  target here to keep a manifest in sync with — every environment is ephemeral by ADR 0007's
  own decision, torn down at the end of the job that created it.

## Consequences

- The job needs `fetch-depth: 0` (already has it, matching `changes` and `benchmarks`) so
  `origin/$PFP_BASE_REF` is a real, fetchable ref, not a shallow stub.
- **Known miss**: dbt's `state:modified` walks the DAG through `ref()`/`source()` edges. A
  *singular* test with no `ref()` to the model it checks — `assert_statement_continuity`
  (T16) reads `bronze.statements` directly, not through `ref('transactions')` — isn't dbt's
  idea of a descendant of `transactions`, so a change confined to that model narrows the build
  to the model and its generic (`not_null`/`accepted_values`) tests, but not the continuity
  test. Confirmed against a real diff while building this job (a one-line comment added to
  `transactions.sql`, `dbt build --select state:modified+` picked up the model and 11
  generic tests, not the continuity test). This is exactly the class of miss ADR 0008 already
  accepts and bounds: a docs-adjacent gap the push-to-`develop` and weekly full run catch
  within a week, never a permanent blind spot — not something to special-case in the selector
  for one test.
- The worktree is created under `/tmp`, never inside the repo checkout, so nothing it produces
  can be mistaken for part of the PR's own tree or accidentally get staged.

## Related

- [ADR 0007: Ephemeral per-PR environments](0007-ephemeral-per-pr-environments.md) — the job
  this selection runs inside, and why it's torn down after every run regardless.
- [ADR 0008: Impact-based CI](0008-impact-based-ci.md) — decides *whether* and *how narrow*;
  this ADR only decides how the comparison manifest is produced.
- [CI](../components/ci.md) — the workflow this describes.
