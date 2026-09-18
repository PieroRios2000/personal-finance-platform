---
type: decision
phase: 2
status: accepted
date: 2026-09-17
---

# ADR 0021: CI invokes the pipeline through Dagster, not `pfp ingest`/`dbt build` directly

## Context

T21 wraps the existing `pfp ingest` + `dbt build` sequence as one Dagster DAG
(`orchestration/definitions.py`: the `bronze` asset plus `dbt_models`, one Dagster
asset per dbt node via `dagster-dbt`) — see
[dagster](../components/dagster.md). `tasks/todo-phase2.md`'s own T21 acceptance
criteria ask for more than the DAG existing: `ephemeral-integration` (T17) must
be updated to invoke the Dagster job itself where it currently calls `pfp
ingest`/`dbt build` directly, so CI proves the path a real install actually
uses, not a bypass of it. What was left for this task: how to fold that
switch into `ephemeral-integration` without silently regressing anything it
already guarantees — the twice-run idempotency proof (T17) and ADR 0008's
impact-based `state:modified+` build selection both still had to survive, and
turned out to need real fixes, not just a find-and-replace of the command.

## Decision

**One `dagster asset materialize --select '*'` call replaces the old separate
`pfp ingest` and `dbt build` steps**, run twice (`ephemeral-integration`'s
existing "must add 0 new rows" proof, now over the whole pipeline — bronze
and every dbt node together — not bronze alone). This is the literal command
a real install runs for the whole pipeline in one shot, matching this ADR's
own reason to exist rather than an arbitrary split preserved for its own
sake.

**Idempotency is checked by reading bronze.statements' real row count
(`scripts/count_bronze_statements.py`), not by grepping the CLI's stdout for
the bronze asset's report text** (the mechanism the pre-T21 `pfp
ingest`-based check used, `grep -q "Bronze: 0 statement(s) written"`).
Reproduced directly before choosing this: a single-asset `dagster asset
materialize --select bronze` does stream a step's own `context.log.info()`
output to stdout, but the multi-asset `--select '*'` this job actually uses
does not — confirmed both with the CLI's default multiprocess executor and
with `--config-json` forcing `in_process`, so it isn't an executor setting to
tune around. Comparing real data survives however Dagster's own log-capture
behavior changes across versions; a stdout-text check would not.

**Every command that reads a bronze Delta table in this job is piped
(`| tee ...`), never redirected alone (`> file`).** A known, pre-existing
`deltalake==1.6.3` bug aborts the process during interpreter shutdown *after*
it already printed its real output (exit 134 — `SETUP.md`'s known issues,
[Dispatcher and CLI](../components/cli.md), predates T21). Confirmed this
job's own `dagster asset materialize`/`scripts.count_bronze_statements`
invocations hit the exact same bug directly (reproducible, not assumed from
the CLI's own history), and that piping — this job's shell has no
`pipefail` — makes the pipeline report the last command's exit code, the
same accidental-but-load-bearing property the pre-T21 `pfp ingest | tee ...`
steps already relied on. Not a new workaround invented for T21.

**ADR 0008's impact-based `state:modified+` build selection moves, unchanged
in what it computes, into an env var `_dbt_build_args()`
(`orchestration/assets/dbt_project.py`) reads and forwards.** Computing the
base manifest (the git-worktree-plus-`dbt parse` dance) stays exactly where
it was, in the CI YAML itself — that logic has nothing to do with Dagster.
Only *where* the resulting `--select`/`--state` args get applied moved, from
a bare `dbt build ...` subprocess to `dbt_models`' own `DbtCliResource.cli()`
call. This step now runs once, before both materializations (not only before
a `dbt build` step that used to come after two ingests), so the narrowed
build's own idempotency gets proven too, not just an unnarrowed one.

**`DAGSTER_MODULE_NAME=orchestration.definitions`, not `pyproject.toml`'s own
`[tool.dagster]` block, is what makes `dagster asset materialize`/`dagster
asset list` resolve their target with no `-m`/`-f` flag.** Read `dagster`'s
own CLI source before relying on this (`dagster/_cli/asset.py`,
`dagster_shared/cli/__init__.py`): `asset materialize`/`asset list` use
`PythonPointerOpts`, a different code path from the `WorkspaceOpts`-based
commands (`dagster dev`) that `pyproject.toml`'s `[tool.dagster] module_name`
block actually drives — confirmed directly (reproduced the bare command
failing with "Invalid set of CLI arguments" despite that block already being
present, from an earlier T21 commit's own now-corrected claim that it was
sufficient), not assumed from either command's own `--help` text, which
doesn't mention `pyproject.toml` at all.

## Alternatives considered

- **Keep `ephemeral-integration`'s old `pfp ingest`/`dbt build` steps
  untouched, add a separate Dagster-only smoke step.** Rejected: this is
  exactly the "bypass" T21's own acceptance criteria call out — CI would
  keep proving the pre-Dagster path works and only optionally check the new
  one, the opposite of the goal.
- **Grep `dagster asset materialize`'s stdout for the bronze report text,
  same as before.** Rejected after reproducing it directly: unreliable for a
  multi-asset selection regardless of executor config (see Decision above).
- **Force the `in_process` executor via `--config-json` and keep the
  stdout-grep.** Tried first; still didn't stream the report text for a
  multi-asset selection (only single-asset selections do). Reading the real
  data instead of chasing Dagster's own internal log-capture behavior is
  also the more robust choice going forward, independent of this specific
  finding.
- **Translate `state:modified+` into Dagster's own `AssetSelection` syntax
  on the CLI (`--select`), instead of an env var `_dbt_build_args()` reads.**
  Rejected: Dagster's CLI `--select` flag selects *Dagster* asset keys, a
  different concept from a dbt selector string compared against a base
  manifest; `dagster_dbt.build_dbt_asset_selection` can bridge the two in
  Python but only inside a job/asset definition, not as a plain CLI string —
  adding that indirection for one CI job's own selective-build optimization
  was not worth the extra surface when forwarding the exact same
  already-computed dbt selector string through an env var does the same job
  with no new translation layer to keep correct.
- **`os.environ` mutation for `PFP_DUCKDB_PATH` inside
  `orchestration/assets/dbt_project.py` (needed regardless of this ADR, to
  fix a real crash — see [dagster](../components/dagster.md) and T21's own
  commit history) done as an explicit override instead of `setdefault`.**
  Rejected: an explicit override would silently replace a test's own
  `tmp_path`-scoped value or an operator's own exported `PFP_DUCKDB_PATH`;
  `setdefault` only supplies a value when none exists.

## Consequences

- `ephemeral-integration`'s own log/dbt-artifact-saving step now globs for
  `dbt/target/dbt_models-*/run_results.json` instead of
  `dbt/target/run_results.json` directly: `dagster-dbt` runs each dbt
  invocation in its own per-invocation subdirectory under `dbt/target/`,
  confirmed by inspecting a real run's output, not assumed from
  `dagster-dbt`'s own docs.
- A future CI job that reads a bronze Delta table and is not already piped
  through another command needs the same `| tee`-not-`>` treatment this ADR
  documents, until `deltalake` is upgraded past whatever version fixes the
  underlying exit-134 bug (`SETUP.md`'s own note: unresolved, first thing to
  try is an upgrade).
- `make poc` and the raw `pfp ingest`/`pfp parse`/`dbt build` CLI commands
  are untouched by this ADR — Dagster owns the DAG'd, CI-proven path; the
  manual one (Piero's own masked-dump debugging loop, ADR 0004) still needs
  no DAG in the way, per T21's own acceptance criteria.

## Related

- [dagster](../components/dagster.md) — the component this ADR's CI wiring invokes.
- [CI](../components/ci.md) — `ephemeral-integration`'s full step list, this ADR's edits included.
- [ADR 0007: Ephemeral per-PR environments](0007-ephemeral-per-pr-environments.md)
- [ADR 0008: Impact-based CI](0008-impact-based-ci.md) — the `state:modified+` selection this ADR carries through unchanged.
- [ADR 0019: `ephemeral-integration` required via gate job](0019-ephemeral-integration-required-via-gate-job.md)
