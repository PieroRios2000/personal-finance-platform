---
type: component
phase: 1
status: in-progress
task: T5, T15, T17, T17b, T19-follow-up
---

# CI

Automated GitHub Actions checks on every PR. Branch policy, quality gates, impact-based
benchmarks, the ephemeral per-PR environment and the base-vs-PR data diff are all built
(details in the [plan](../../tasks/plan.md)); what's left across all of them is a live
GitHub Actions PR run to confirm the wiring itself, since this session can't trigger one
(see each piece's own pending notes in `tasks/todo.md`).

## Pieces

| Piece | Status | What it does |
|---|---|---|
| [`branch-policy.yml`](../../.github/workflows/branch-policy.yml) | Built | Only `develop` from this repo may open PRs into `main`; the `check-source-branch` check is required in the `main` and `develop` ruleset |
| [`ci.yml`](../../.github/workflows/ci.yml) (T5) | Built | Five jobs: `lint-types`, `tests` (+ diff-cover), `security` (gitleaks, pip-audit, bandit), `architecture` (import-linter), `floor-guard`; all five required in the ruleset |
| `changes` job (T15, T17, [ADR 0008](../decisions/0008-impact-based-ci.md)) | Built | Pipes `git diff --name-only origin/<base>...HEAD` into [`scripts/ci_impact.py`](../../scripts/ci_impact.py) and publishes the affected areas (`benchmarks`, `integration`, `dbt_select`) as job outputs; expensive jobs carry their own `if` |
| `benchmarks` job (T15) | Built | Measures the base branch and the PR on the same runner (only `ingestion/` and `lakehouse/` swapped between the two runs), `--benchmark-compare-fail=mean:20%`; warns until 2026-09-26 |
| `ephemeral-integration` job (T17, [ADR 0007](../decisions/0007-ephemeral-per-pr-environments.md); [ADR 0021](../decisions/0021-ci-invokes-the-dagster-pipeline.md); [ADR 0022](../decisions/0022-elementary-anomaly-detection-and-warn-mode.md)) | Built | Local S3 up under a per-run project name, `dagster asset materialize --select '*'` (T21: bronze + dbt build together, impact-narrowed per ADR 0008/0021 — Elementary's own models and its `silver.transactions` anomaly test run inside this same build too, T22) twice (idempotency, checked via `scripts/count_bronze_statements.py`'s real row count — a multi-asset materialize doesn't stream a step's own log text to stdout), `sqlfluff lint`, the `integration`-marked tests, a dedicated `continue-on-error: true` re-run of just the Elementary anomaly test (T22, warn-mode) and `edr report` (also `continue-on-error: true`, uploaded as an artifact), then always torn down; logs, dbt's artifacts and the Elementary report saved first |
| `ephemeral-integration-gate` job ([ADR 0019](../decisions/0019-ephemeral-integration-required-via-gate-job.md)) | Built | The job the ruleset actually requires — always runs (`if: always()`), turns `ephemeral-integration`'s own `success`/`skipped` conclusion into a pass and `failure`/`cancelled` into a fail, since a ruleset-required check left "skipped" isn't reliably accepted as satisfied |
| `make poc` (T17) | Built | The same flow, once, locally, against Piero's real PDFs; prints only pass/fail and reconciliation *counts* (ADR 0004) |
| `pr-data-diff` job (T17b, [ADR 0014](../decisions/0014-pr-data-diff-shared-instance-full-build.md)) | Built | Ingest + `dbt build` run twice against the base branch's commit and the PR's, isolated by a `LAKEHOUSE_URI` prefix and a Postgres database (`pfp_diff_base` / `pfp_diff_pr`, created by [`scripts/pg_databases.py`](../../scripts/pg_databases.py)) on one shared SeaweedFS and Postgres; [`scripts/data_diff.py`](../../scripts/data_diff.py) attaches both databases read-only, diffs `silver` and `gold`, and posts Markdown to the job summary. Warn-only, gated on the same `integration` output as `ephemeral-integration` but runs in parallel with it |

## Details that must not break

- `branch-policy` uses `pull_request_target`: it runs the workflow version already in the repo,
  so a PR cannot edit it to approve itself; it never checks out the PR's code or gets any permissions.
- **A required job's own `if:` should never be able to skip it — GitHub's documented "a
  skipped job counts as successful even when required" isn't reliably true for repository
  rulesets (confirmed directly, not assumed; see [ADR 0019](../decisions/0019-ephemeral-integration-required-via-gate-job.md)).**
  `changes` and `benchmarks` stay unrequired for their own, unrelated reasons (`changes` is
  purely informational, `benchmarks` is warn-only by design, ADR 0008/CONSTRAINTS.md) — but
  `ephemeral-integration`, which *should* gate a merge, is required only through
  `ephemeral-integration-gate`, a wrapper job with no conditional skip path of its own.
- **CI does not run OpenMetadata (T24, [ADR 0023](../decisions/0023-openmetadata-catalog-and-column-lineage-from-dbt-artifacts.md)).**
  `openmetadata/docker-compose.yml` is optional local infrastructure (~4.6 GiB of containers at
  idle); nothing in `.github/` references it, deliberately, so a PR never pays that RAM cost.
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
- **Every command that reads a bronze Delta table in this job is piped (`| tee ...`), never
  redirected alone (`> file`).** A known, pre-existing `deltalake==1.6.3` bug aborts the
  process during interpreter shutdown *after* it already printed its real output (exit 134,
  `SETUP.md`'s known issues, [Dispatcher and CLI](cli.md)) — piping to a second command means
  this job's shell (no `pipefail`) reports the pipeline's exit code as the last command's, not
  the crashing one's. Don't "simplify" one of these into a plain `>` redirect without checking
  this first.
- Its project name is `pfp-pr-<PR number, or the run id on a non-PR event>`
  (`docker compose -p`): unique per concurrent job, so two PRs' environments (or a push to
  `develop` and a PR, both in flight) never share a bucket or a volume.
- When `changes` narrows `dbt_select` to `state:modified+`, the job checks out the base ref
  into a second worktree (`git worktree add --detach`) and runs `dbt parse` there to produce
  the comparison manifest, entirely inside the same job — see
  [ADR 0013](../decisions/0013-dbt-state-comparison-via-a-base-ref-worktree.md) for why, and
  its known limit: a *singular* dbt test with no `ref()` to the model it checks (like
  `assert_statement_continuity`) isn't dbt's idea of a descendant, so a narrowed build can
  miss it — bounded the same way ADR 0008 bounds every other miss, by the push-to-`develop`
  and weekly full run.
- `pr-data-diff` (T17b, ADR 0014) shares its `LAKEHOUSE_URI` bucket and SeaweedFS instance
  between the two runs it needs — isolation is a URI prefix (`pr-diff-base` / `pr-diff-pr`)
  and a `PFP_DUCKDB_PATH`, not a second `docker compose -p` — with `PFP_DBT_TARGET=local` since
  T27 (the default target is now Postgres and this job has none until T29) — and always runs a **full**
  `dbt build` on both sides, never `DBT_SELECT`'s `state:modified+`: that narrowing only
  makes sense against a persisted target, and both runs here start from an empty `.duckdb`
  file. It carries `continue-on-error: true` at the **job** level and is never added to the
  ruleset's required checks, so a real base-vs-PR difference — or even a broken base-branch
  build — can never block a merge the way `ephemeral-integration` itself does.

## Reproducing CI locally

`make ci-local` (`scripts/ci_local.py`) runs a job's own `run:` steps, read from `ci.yml`, in a
clean clone of the last commit with only that job's variables (`make ci-local-full` adds
`ephemeral-integration`). It exists because CI's `tests` job once failed on a variable that only a
job without Postgres lacks and on files a fresh checkout does not have, both invisible locally:
run against that failing commit it reports the same error. Uncommitted changes are refused, `if:`
steps other than `always()` and `sudo` steps are skipped with a printed reason, and a GitHub
expression it cannot evaluate makes the job refuse to run. It is part of the Definition of Done.

## Cost, and where it goes

`ephemeral-integration` is the slow job: about 20 minutes when it runs, of which 17 are
`pytest -m integration` (39 tests, each running a real `dbt build`). The end-to-end Dagster passes
take under 2 minutes. The impact map ([ADR 0008](../decisions/0008-impact-based-ci.md)) decides
whether the job runs, but once it does, every integration test runs. The integration tests now run on four
pytest-xdist workers (`-n 4`), each with its own test lake (`_lake_suffix` in
`tests/test_dbt_silver_integration.py`); narrowing the set and making each `dbt build` cheaper is tracked in [`tasks/backlog.md`](../../tasks/backlog.md)
("CI speed"). The job's timeout is 30 minutes (raised from 20 after a cancelled run in #82).

## How to use it and how to verify it

`gh pr checks <n>` and `gh run view <run_id> --log-failed`; see "Reviewing CI" in
[SETUP.md](../../SETUP.md). For `ephemeral-integration` itself: after it finishes, `docker ps
-a` and `docker volume ls` should show nothing under its project name, win or lose; a failed
run's `docker compose logs`, `dbt/target/run_results.json` and `dbt/logs/dbt.log` are on the
run's **Artifacts** panel (`ephemeral-integration-logs`, kept 3 days). Locally, the same flow
against real data is `make poc` (`make poc-up` first if you want to poke at the environment
afterwards instead of it tearing itself down). For `pr-data-diff`: its comparison is on the
run's own **Summary** tab, not a separate artifact; `scripts/data_diff.py` itself can be run
directly against two Postgres databases (`--base-database A --pr-database B`) or any two
`.duckdb` files (`--base BASE.duckdb --pr PR.duckdb`); `tests/test_data_diff.py` exercises the
file form against two small hand-built files, without a live SeaweedFS, Postgres or dbt build.

## Related

- [Python project](python-project.md) — what CI validates.
- [Security guards](security-guards.md) — the local hooks CI will make mandatory.
- [ADR 0007: Ephemeral per-PR environments](../decisions/0007-ephemeral-per-pr-environments.md)
  — why the environment exists and is always torn down.
- [ADR 0008: Impact-based CI](../decisions/0008-impact-based-ci.md) — why expensive jobs skip,
  and what stops the map from hiding a real failure.
- [ADR 0019: `ephemeral-integration` required via a gate job](../decisions/0019-ephemeral-integration-required-via-gate-job.md)
  — why the job that actually blocks a merge isn't the impact-gated one directly.
- [ADR 0013: dbt state comparison via a base-ref worktree](../decisions/0013-dbt-state-comparison-via-a-base-ref-worktree.md)
  — how the narrowed `dbt build` gets a manifest to compare against.
- [ADR 0014: pr-data-diff isolates by URI prefix, not by environment, and always builds in full](../decisions/0014-pr-data-diff-shared-instance-full-build.md)
  — why the two runs share one SeaweedFS instance, and why the narrowing ADR 0013 built
  doesn't apply here.
- [ADR 0022: Elementary anomaly detection and warn-mode scoping](../decisions/0022-elementary-anomaly-detection-and-warn-mode.md)
  — why the anomaly test's own warn-mode is a dbt-level `severity: warn`, not a CI-level
  `continue-on-error` alone, and why `dbt deps` had to be added in three places, not one.
- [Elementary](elementary.md) — the component this job's own Elementary steps build and verify.
- [Phase 1](../phases/phase-1.md)
