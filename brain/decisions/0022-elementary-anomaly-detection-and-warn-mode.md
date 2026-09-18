---
type: decision
phase: 2
status: accepted
date: 2026-09-18
---

# ADR 0022: Elementary's anomaly test, warn-mode scoping, and where `dbt deps` had to go

## Context

T22 asks for Elementary (chosen over Great Expectations, `tasks/plan-phase2.md`) wired in as a
dbt package, with at least one real anomaly test on `silver.transactions`, a real local
`edr report`, and CI running the test in warn-mode "mirroring how Phase 1's own numeric rules
started in warn mode" (CONSTRAINTS.md). The package choice itself, and *why* Elementary over
Great Expectations, are already settled in `tasks/plan-phase2.md`'s own Architecture decisions
table — what this ADR records is what was actually decided while building it: which anomaly
check, on which column, with which parameters; how "warn-mode" gets scoped without either
silently blocking `ephemeral-integration`'s already-required build or doing nothing at all; and
three real problems only found by running this for real against live local S3 (deltalake and
`pfp ingest`'s own exit-134 quirk taught this session to expect exactly this kind of thing).

## Decision

**`elementary.volume_anomalies` on `silver.transactions`, bucketed by day on `date`,
`severity: warn`.** Row-count anomaly detection is the acceptance criteria's own suggested
example, and `date` (the bank's own posting date, not `ingested_at`) is what "a sudden spike in
transactions" actually means to a person reading this project's data, not an artifact of when
bronze happened to write a row. Every parameter left at Elementary's own default
(`days_back: 14`, `backfill_days: 2`, `anomaly_sensitivity: 3`) except `min_training_set_size`
(7 → 5, to match the 10-day training window this task's own verification test seeds — a real
z-score isn't defined below two training points regardless, so 5 vs. 7 changes nothing about
what actually gets caught, only how early a still-thin dataset stops silently skipping the
test).

**`severity: warn` at the dbt-test level is this task's own "warn-mode," not a CI-level
`continue-on-error` alone.** The test already runs inside `ephemeral-integration`'s existing,
required `dagster asset materialize --select '*'` step (Elementary's own models build there
too, T22's first acceptance criterion) — that step has no `continue-on-error` and isn't going
to get one, since it's the one proof this job exists to give. A dbt test that fires with
`severity: error` there would fail a currently-required check on a real anomaly, which is
exactly not what "warn-mode initially" asks for. `severity: warn` is dbt's own first-class
mechanism for precisely this: the test still runs, still shows up as `WARN` in the build's own
output and in `elementary.elementary_test_results`, but never turns `dbt build`'s exit code
non-zero. `ephemeral-integration` gets one more thing on top: a dedicated
`continue-on-error: true` step that re-selects and re-runs just this one test
(`--select tag:elementary-tests` — every `elementary.*_anomalies` test macro tags itself with
this automatically, confirmed directly with `dbt ls`), the same "own labeled step" shape as
this file's other still-warning checks (diff-cover, pip-audit, bandit, import-linter,
CONSTRAINTS.md) — so an anomaly is visible in its own step/log here, not only buried inside a
much larger materialize log.

**`dbt deps` had to be added in three places, not one — confirmed by reproducing each
independently, not assumed:**

1. **Nowhere new for the Dagster-invoked path itself.** `dagster-dbt`'s own
   `DbtProject.prepare()` already runs `dbt deps --quiet` the first time
   `orchestration/assets/dbt_project.py` is imported with no manifest present (confirmed by
   reading `dagster_dbt/dbt_project.py`, and reproduced directly: a fresh checkout with no
   `dbt/dbt_packages/` at all, `pytest` alone collecting `test_dagster_dbt_build_args.py`,
   ends up with `dbt/dbt_packages/elementary` installed with zero explicit `dbt deps` step
   anywhere). `ephemeral-integration`'s own `dagster asset materialize` steps and CI's `tests`
   job (which imports the same module at collection time for several `test_dagster_*.py`
   files) both get this for free.
2. **`ephemeral-integration`'s own base-ref worktree.** The `state:modified+` selection step
   runs a bare `uv run dbt parse --project-dir /tmp/pfp-base-ref/dbt ...` against a *second*
   checkout ([ADR 0013](0013-dbt-state-comparison-via-a-base-ref-worktree.md)) — a plain
   dbt-CLI call, never routed through `dagster-dbt`, so it gets none of point 1's free install.
   A no-op today (this branch's base, `develop`, has no `dbt/packages.yml` yet) and
   load-bearing the moment a future dbt-only PR takes this same code path against a `develop`
   that does.
3. **The whole `pr-data-diff` job.** It never imports `orchestration` at all — `pfp ingest` +
   bare `dbt build` by hand, on both the base-ref worktree and the PR's own checkout. Both of
   its `dbt build` calls needed an explicit `dbt deps` first, or they'd fail outright the
   moment `dbt/packages.yml` exists on `develop`.

**`edr` needs its own `elementary` connection profile, distinct from this project's own
`personal_finance_platform` one — confirmed directly, not assumed from its docs.** `edr report`
runs its own internal, bundled dbt project against whichever profile is literally named
`elementary` in `--profiles-dir`; without one, it fails outright
(`Could not find profile named 'elementary'`), even though `dbt build` had already populated
every `elementary.*` table it needed. Added as a second top-level block in `dbt/profiles.yml`,
same DuckDB file and S3 secrets as the main profile, `schema: elementary` — not `silver` — so
`edr`'s own "where do your Elementary tables live" resolution (logged as
`Elementary's database and schema: '<db>.<schema>'`) matches where `dbt_project.yml`'s own
`elementary: +schema: "elementary"` config actually put them (confirmed directly: `edr report`
looked for `silver.elementary_test_results` and failed until this matched). Reused the existing
`personal_finance_platform` block's own connection settings via a YAML merge key
(`<<: *duckdb_output`) rather than a second, hand-copied block — `edr`'s own profile differs
from the main one in exactly one field (`schema`), so a merge key is what keeps that difference
visible and everything else guaranteed identical, with nothing to drift out of sync by hand.

**`PFP_DUCKDB_PATH` must be an absolute path for `edr` specifically, confirmed by reproducing
the failure both ways.** Every other command in this project (`dbt build`, `dbt test`,
`sqlfluff lint`) runs from the repository root, so `profiles.yml`'s relative default
(`dbt/pfp.duckdb`) already resolves correctly against it. `edr report` is different: it shells
out to *its own* internal, bundled dbt project, installed inside `elementary`'s own Python
package directory, and runs that subprocess from there — the identical relative path then
resolves against the wrong directory entirely (`.../site-packages/elementary/.../dbt/pfp.duckdb`,
confirmed in the actual error) and `edr` can't find the database `dbt build` just wrote. Neither
`profiles.yml` nor `dbt_project.yml` can fix this generally (an absolute default would need
knowing the repo root, which a static Jinja default can't), so this project's own docs
(SETUP.md, this component's own "How to use it") and CI's own `edr report` step both export
`PFP_DUCKDB_PATH` as an absolute path immediately before calling `edr`, never relying on its
default.

**`dbt/.edr/config.yml` (committed) sets `anonymous_usage_tracking: false`.** Confirmed by
reading `elementary/monitor/data_monitoring/report/data_monitoring_report.py`: when this
config is on (its own default), the generated report embeds a live PostHog project API key in
its own data payload, which the bundled PostHog JS uses to phone home when the report is
opened in a browser. With tracking off, that key is omitted from the payload and the bundled
script never initializes. Same privacy stance ADR 0004 already applies to this project's own
telemetry choices, extended to a dependency's — `dbt_project.yml`'s own `disable_tracking: true`
var covers the dbt-package side of Elementary; this covers the CLI/report side, a separate
mechanism (confirmed: setting one without the other left the other's own tracking config
untouched).

**`vars: clean_elementary_temp_tables: false` works around a real, reproducible crash.**
Elementary's own `on-run-end` cleanup of its per-invocation temp tables
(`elementary.clean_elementary_temp_tables()`) throws `Catalog Error: Table ... does not
exist!` on this stack (dbt-duckdb 1.11.0, elementary 0.26.0) — 100% reproducible, always
*after* every real result is already computed and printed (`Done. PASS=... WARN=... ERROR=0`),
so it never hides a genuine failure, only `dbt build`'s own exit code on the way out. The exact
same shape as `deltalake==1.6.3`'s own exit-134 quirk this project already documents
(`SETUP.md`'s known issues) — an upstream cleanup-step bug, not a correctness issue — so it
gets the same treatment: disable the one step that crashes (Elementary's own documented
config for this), not work around the process's exit code downstream.

## Alternatives considered

- **`severity: error` (Elementary's own default) plus excluding the test from the main
  `dagster asset materialize --select '*'` build via a dbt tag, running it only in a separate,
  `continue-on-error`-wrapped step.** Rejected: needs a `--exclude tag:...` threaded through
  `orchestration/assets/dbt_project.py`'s own `_dbt_build_args()`
  ([ADR 0021](0021-ci-invokes-the-dagster-pipeline.md)), which would also silently exclude the
  test from every *local* `dbt build`/`make poc` run, not just CI's blocking one — the test
  would then only ever fire inside CI's own extra step, never for a developer running the
  platform by hand. `severity: warn` keeps the test identically present everywhere dbt already
  runs, with no selector logic to keep in sync.
- **A CI-level `continue-on-error: true` on the Dagster materialize step itself, instead of
  dbt-level `severity: warn`.** Rejected: that step also runs the real idempotency proof
  (`scripts/count_bronze_statements.py`'s row-count diff) and every other silver/gold test —
  making the whole step non-blocking to accommodate one warn-mode test would silently stop
  `ephemeral-integration` from catching an unrelated real regression too.
- **Skip the dedicated CI step; rely on the anomaly test's `WARN` already appearing once,
  inside the main materialize step's log.** Considered, since `severity: warn` alone already
  satisfies "CI runs the test in warn-mode." Kept the dedicated step anyway: that log is large
  (124+ nodes across silver/gold/Elementary's own models) and a single `WARN` line inside it is
  easy to miss; a named, separate step makes the anomaly's own status the first thing visible
  without reading the whole materialize log, matching this file's own existing pattern for
  every other still-warning check.
- **Point `edr report` at `~/.dbt/profiles.yml` (dbt's own default search path) instead of a
  second block inside this project's own `dbt/profiles.yml`.** Rejected: this project's
  connection config has always lived inside the project directory
  (`profiles.yml`'s own top comment, T16), specifically so it travels with the repo and needs
  no per-machine setup step; a second, un-committed profile elsewhere would break that for
  exactly the tool this task adds.

## Consequences

- A future PR that adds another Elementary anomaly test inherits the same `severity: warn`
  pattern by default unless it deliberately opts out — reviewed the same way any other
  CONSTRAINTS.md warn-mode addition is, at PR time.
- `dbt/.edr/config.yml` and `dbt/package-lock.yml` are now committed, project-tracked files
  (`dbt/dbt_packages/` itself stays gitignored, same as before) — a reviewer diffing a future
  `packages.yml` bump should expect `package-lock.yml`'s hash to move with it.
- Any future CI job that adds a bare `dbt build`/`dbt parse`/`sqlfluff lint` call outside the
  Dagster-invoked path needs its own `dbt deps` first, the same three-places lesson this ADR
  records — `orchestration/assets/dbt_project.py`'s own lazy-`prepare()` mechanism only covers
  code paths that actually import it.
- If `clean_elementary_temp_tables: false` is ever removed (e.g. after an Elementary/dbt-duckdb
  upgrade fixes the underlying crash), it should be verified the same way this ADR did: a real
  `dbt build` against live local S3, not just re-reading Elementary's changelog.

## Related

- [Elementary](../components/elementary.md) — every piece this ADR explains, in one place.
- [CI](../components/ci.md) — `ephemeral-integration`'s own updated step list.
- [ADR 0004: Real PDFs never leave your machine](0004-real-pdfs-never-leave-your-machine.md) —
  the privacy stance `disable_tracking`/`anonymous_usage_tracking: false` both extend.
- [ADR 0007: Ephemeral per-PR environments](0007-ephemeral-per-pr-environments.md)
- [ADR 0008: Impact-based CI](0008-impact-based-ci.md)
- [ADR 0013: dbt state comparison via a base-ref worktree](0013-dbt-state-comparison-via-a-base-ref-worktree.md)
  — the worktree that needed its own `dbt deps`.
- [ADR 0014: pr-data-diff shared instance, full build](0014-pr-data-diff-shared-instance-full-build.md)
  — the job whose two bare `dbt build` calls both needed it too.
- [ADR 0021: CI invokes the pipeline through Dagster](0021-ci-invokes-the-dagster-pipeline.md) —
  why the main build gets `dbt deps` for free and these three places don't.
- [Quality bar](../components/quality-bar.md) — CONSTRAINTS.md's warn-then-block pattern this
  task's own scoping is modeled on.
