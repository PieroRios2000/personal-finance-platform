---
type: component
phase: 2
status: built
task: T22
---

# Elementary

dbt-native data quality and observability — anomaly detection and column-level lineage, as a
dbt package (`elementary-data/elementary`) alongside silver and gold, no new infrastructure.
Chosen over Great Expectations for exactly this (`tasks/plan-phase2.md`'s own Architecture
decisions table). Design decisions in
[ADR 0022](../decisions/0022-elementary-anomaly-detection-and-warn-mode.md).

## Pieces

| Piece | What it does |
|---|---|
| [`dbt/packages.yml`](../../dbt/packages.yml) | Pins `elementary-data/elementary` (0.26.0), installed by `dbt deps`. `dbt/package-lock.yml` (committed, like `uv.lock`) records the resolved version, including its own transitive `dbt-labs/dbt_utils` dependency |
| `elementary: +schema: "elementary"` in [`dbt/dbt_project.yml`](../../dbt/dbt_project.yml) | Elementary's own metadata/monitoring models (`dbt_run_results`, `elementary_test_results`, `data_monitoring_metrics`, …) land in their own `elementary` schema, the same `generate_schema_name.sql` override [dbt gold](dbt-gold.md) already uses for `gold` |
| `on-run-end: - "{{ elementary.on_run_end() }}"` in `dbt_project.yml` | After every `dbt build`/`dbt run`/`dbt test`, uploads that invocation's own results into Elementary's tables — what `edr report` reads |
| `vars: disable_tracking: true` and `vars: clean_elementary_temp_tables: false` in `dbt_project.yml` | The first opts the dbt package out of its own anonymous usage reporting (ADR 0004's privacy stance, applied to any telemetry this project doesn't control). The second works around a real, reproducible crash — see "Known issue" below |
| [`dbt/models/silver/schema.yml`](../../dbt/models/silver/schema.yml)'s `elementary.volume_anomalies` test on `transactions` | The one real anomaly test T22's acceptance criteria ask for: a row-count anomaly, bucketed by day on `date`, `severity: warn` |
| [`dbt/profiles.yml`](../../dbt/profiles.yml)'s `elementary:` profile | The `edr` CLI runs its own internal dbt project against a connection profile literally named `elementary` (confirmed directly — `edr report` fails with "Could not find profile named 'elementary'" without it), pointed at the same DuckDB file and S3 secrets as `personal_finance_platform`'s own profile, `schema: elementary` (not `silver`) so `edr` finds where the models above actually landed |
| [`dbt/.edr/config.yml`](../../dbt/.edr/config.yml) (committed) | `anonymous_usage_tracking: false` — without it, `edr report`'s generated HTML embeds a PostHog project key that would let the report itself phone home when opened in a browser |
| `elementary-data` in `pyproject.toml`'s dev deps | The `edr` CLI (`edr report`/`edr monitor`) — a Python package, `uv add --dev`'d, separate from the dbt package above (which `dbt deps` installs) |

## The anomaly test: row-count on `silver.transactions`, by day

```yaml
- elementary.volume_anomalies:
    name: elementary_volume_anomalies_silver_transactions
    arguments:
      timestamp_column: "date"
      time_bucket: { period: day, count: 1 }
      min_training_set_size: 5
    config:
      severity: warn
```

Every default left in place except `min_training_set_size` (Elementary's own default is 7;
dropped to 5 to match the shortest training window the verification test seeds — a real
z-score isn't defined below two training points regardless, so this floor was already the
binding constraint, not a project-specific tuning choice). `severity: warn` is this task's own
scoping of CONSTRAINTS.md's warn-then-block pattern to a single dbt test config, not a
CI-level `continue-on-error` — see [ADR 0022](../decisions/0022-elementary-anomaly-detection-and-warn-mode.md)
for why, and for the CI step that also surfaces it in its own log.

**`date`, not `ingested_at`.** The bank's own posting date is what a "sudden row-count spike"
question is actually about (did an unusual number of movements happen on some day), not when
bronze happened to write the row.

## Known issue: `clean_elementary_temp_tables` crashes `dbt build`'s own exit code

Reproduced directly, 100% of the time on this stack (dbt-duckdb 1.11.0, elementary 0.26.0):
Elementary's own `on-run-end` step that drops its per-invocation temp tables
(`elementary.clean_elementary_temp_tables()`) throws `Catalog Error: Table ... does not
exist!`, *after* every real model/test result is already computed and printed (`Done. PASS=...
WARN=... ERROR=0`) — so it never hides a real failure, only dbt's own exit code on the way out.
The same shape as `deltalake==1.6.3`'s own exit-134 quirk (`SETUP.md`'s known issues): a real
upstream bug in a cleanup step, not a correctness issue. `vars: clean_elementary_temp_tables:
false` (Elementary's own escape hatch for exactly this) avoids it; see SETUP.md's Known issues
table for the exact symptom to search for.

## How to use it and how to verify it

Needs SeaweedFS up and `.env` exported, same as silver/gold (SETUP.md section 6):

```bash
make poc-up
set -a && source .env && set +a
uv run dbt deps --project-dir dbt --profiles-dir dbt    # once, or after packages.yml changes
uv run dbt build --project-dir dbt --profiles-dir dbt   # builds Elementary's own models + runs the anomaly test
export PFP_DUCKDB_PATH="$PWD/dbt/pfp.duckdb"            # must be absolute for edr -- see SETUP.md
uv run edr report --project-dir dbt --profiles-dir dbt --config-dir dbt/.edr \
  --file-path dbt/elementary_report.html                # local HTML report
```

- [`tests/test_elementary_anomaly_integration.py`](../../tests/test_elementary_anomaly_integration.py)
  (T22) proves, against real local S3: a normal day's transaction count doesn't fire the
  anomaly test (`PASS`, checked both in `dbt build`'s own console output and by querying
  `elementary.elementary_test_results` directly); a sudden 8x spike does (`WARN`, same two
  checks); and Elementary's own models land in the same `dbt build` as silver and gold.
  `integration`-marked and deselected by default, like the rest of the dbt integration suite;
  see `CONSTRAINTS.md`'s exceptions table for its own approved row.
- A spike seeded on the *current* calendar day never fires — Elementary excludes the
  not-yet-elapsed "today" bucket from detection entirely (confirmed empirically, not assumed);
  the test seeds its detection day as yesterday instead.
- CI (`ephemeral-integration`) runs the anomaly test a second time on its own, in a dedicated
  `continue-on-error: true` step, and generates the report as a workflow artifact — see
  [CI](ci.md) and [ADR 0022](../decisions/0022-elementary-anomaly-detection-and-warn-mode.md).

## Not built here, on purpose

- **Column-level lineage.** `tasks/plan-phase2.md` names it as part of why Elementary was
  chosen; T24 (OpenMetadata) is this project's dedicated catalog/lineage task, ingesting from
  dbt's own manifest. Elementary's own lineage view (`edr report`'s "Lineage" tab) exists
  automatically once the package is installed, with nothing further to build here.
- **More anomaly tests** (freshness, schema-change, other tables). T22's acceptance criteria
  ask for "at least one real anomaly test" as the proof the mechanism works end to end; adding
  more before there's real operating history to calibrate against would be schema speculation
  ahead of the model, the same discipline `dbt gold` applies to a not-yet-needed `dim_category`.

## Related

- [ADR 0022: Elementary anomaly detection and warn-mode scoping](../decisions/0022-elementary-anomaly-detection-and-warn-mode.md) —
  every design call here, with the alternatives.
- [dbt silver](dbt-silver.md) — the model the anomaly test runs against.
- [dbt gold](dbt-gold.md) — the `+schema:` override pattern this component reuses.
- [CI](ci.md) — `ephemeral-integration`'s own Elementary steps.
- [Quality bar](quality-bar.md) — CONSTRAINTS.md's warn-then-block pattern this task's own
  scoping is modeled on.
- [Phase 1](../phases/phase-1.md)
