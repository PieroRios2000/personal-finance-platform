---
type: component
phase: 1
status: in-progress
task: T5, T15, T17
---

# CI

Automated GitHub Actions checks on every PR. Branch policy, quality gates, impact-based
benchmarks and the ephemeral per-PR environment are built; T17b's base-vs-PR data diff is
still open (details in the [plan](../../tasks/plan.md)).

## Pieces

| Piece | Status | What it does |
|---|---|---|
| [`branch-policy.yml`](../../.github/workflows/branch-policy.yml) | Built | Only `develop` from this repo may open PRs into `main`; the `check-source-branch` check is required in the `main` and `develop` ruleset |
| [`ci.yml`](../../.github/workflows/ci.yml) (T5) | Built | Five jobs: `lint-types`, `tests` (+ diff-cover), `security` (gitleaks, pip-audit, bandit), `architecture` (import-linter), `floor-guard`; all five required in the ruleset |
| `changes` job (T15, T17, [ADR 0008](../decisions/0008-impact-based-ci.md)) | Built | Pipes `git diff --name-only origin/<base>...HEAD` into [`scripts/ci_impact.py`](../../scripts/ci_impact.py) and publishes the affected areas (`benchmarks`, `integration`, `dbt_select`) as job outputs; expensive jobs carry their own `if` |
| `benchmarks` job (T15) | Built | Measures the base branch and the PR on the same runner (only `ingestion/` and `lakehouse/` swapped between the two runs), `--benchmark-compare-fail=mean:20%`; warns until 2026-09-26 |
| `ephemeral-integration` job (T17, [ADR 0007](../decisions/0007-ephemeral-per-pr-environments.md)) | Built | Local S3 up under a per-run project name, the synthetic fixture ingested twice (idempotency), `dbt build` (impact-narrowed per ADR 0008), `sqlfluff lint`, the `integration`-marked tests, then always torn down; logs and dbt's artifacts saved first |
| `make poc` (T17) | Built | The same flow, once, locally, against Piero's real PDFs; prints only pass/fail and reconciliation *counts* (ADR 0004) |
| T17b base-vs-PR data diff | Planned | Same run against base and PR compared with `scripts/data_diff.py`, published to the job summary |

## Details that must not break

- `branch-policy` uses `pull_request_target`: it runs the workflow version already in the repo,
  so a PR cannot edit it to approve itself; it never checks out the PR's code or gets any permissions.
- Never skip a required job with `if`: a skipped job counts as successful even when required.
  That's why `changes` and `benchmarks` are deliberately **not** required in the ruleset —
  `benchmarks` skips itself by design (ADR 0008).
- No `paths` filters on workflows with required checks: they leave the check in "Pending" and
  block the merge. Impact-based skipping is per job (`if: needs.changes.outputs.…`), never
  a workflow-level filter.
- `ci.yml` also runs on a push to `develop` and weekly (Mondays 06:00 UTC), where everything
  runs regardless of the impact map. There's no PR base on those events, so the workflow-level
  `PFP_BASE_REF` defaults to `develop` for the diff-based steps (diff-cover, floor-guard): they
  compare `develop` against itself, an empty diff they pass trivially. The name is prefixed on
  purpose — a plain `BASE_REF` in the workflow's env is picked up by gitleaks-action as its own
  scan range and breaks the `security` job.
- `ci.yml`'s numeric-rule steps (`diff-cover`, `pip-audit`, `bandit`, `import-linter`, and
  T15's benchmark comparison) carry `continue-on-error: true` until 2026-09-26 (per
  [Quality bar](quality-bar.md)); the job stays required in the ruleset the whole time (except
  `benchmarks`, which isn't required), but only starts actually blocking once T19 removes that
  flag.
- All third-party actions are pinned to a full commit SHA (repo setting
  `sha_pinning_required` enforces this); ruff annotates lines via `--output-format=github`,
  mypy via the problem matcher in `.github/matchers/mypy.json`.
- `ephemeral-integration` uses no GitHub secrets: SeaweedFS's identity (`AWS_ACCESS_KEY_ID`/
  `AWS_SECRET_ACCESS_KEY`) is a fixed, non-real value hardcoded in the job's own `env:`, the
  same shape as every developer's own `.env` — this is what lets the job run the same way on
  a PR from a fork (ADR 0007).
- Its project name is `pfp-pr-<PR number, or the run id on a non-PR event>`
  (`docker compose -p`): unique per concurrent job, so two PRs' environments (or a push to
  `develop` and a PR, both in flight) never share a bucket or a volume.
- When `changes` narrows `dbt_select` to `state:modified+`, the job checks out the base ref
  into a second worktree (`git worktree add --detach`) and runs `dbt parse` there to produce
  the comparison manifest, entirely inside the same job — see
  [ADR 0012](../decisions/0012-dbt-state-comparison-via-a-base-ref-worktree.md) for why, and
  its known limit: a *singular* dbt test with no `ref()` to the model it checks (like
  `assert_statement_continuity`) isn't dbt's idea of a descendant, so a narrowed build can
  miss it — bounded the same way ADR 0008 bounds every other miss, by the push-to-`develop`
  and weekly full run.

## How to use it and how to verify it

`gh pr checks <n>` and `gh run view <run_id> --log-failed`; see "Reviewing CI" in
[SETUP.md](../../SETUP.md). For `ephemeral-integration` itself: after it finishes, `docker ps
-a` and `docker volume ls` should show nothing under its project name, win or lose; a failed
run's `docker compose logs`, `dbt/target/run_results.json` and `dbt/logs/dbt.log` are on the
run's **Artifacts** panel (`ephemeral-integration-logs`, kept 3 days). Locally, the same flow
against real data is `make poc` (`make poc-up` first if you want to poke at the environment
afterwards instead of it tearing itself down).

## Related

- [Python project](python-project.md) — what CI validates.
- [Security guards](security-guards.md) — the local hooks CI will make mandatory.
- [ADR 0007: Ephemeral per-PR environments](../decisions/0007-ephemeral-per-pr-environments.md)
  — why the environment exists and is always torn down.
- [ADR 0008: Impact-based CI](../decisions/0008-impact-based-ci.md) — why expensive jobs skip,
  and what stops the map from hiding a real failure.
- [ADR 0012: dbt state comparison via a base-ref worktree](../decisions/0012-dbt-state-comparison-via-a-base-ref-worktree.md)
  — how the narrowed `dbt build` gets a manifest to compare against.
- [Phase 1](../phases/phase-1.md)
