# Implementation plan — Phase 2: Orchestration + Governance

> Master spec: [`PROJECT.md`](../PROJECT.md). Detailed tasks: [`tasks/todo-phase2.md`](todo-phase2.md).
> Phase 1 plan: [`tasks/plan.md`](plan.md). Status: **draft**, pending Piero's approval
> (mirrors how Phase 1's plan needed its own sign-off, PR #6, before any task started).

## Summary

Phase 1 leaves a platform that runs end-to-end locally but by hand: `pfp ingest` then
`dbt build`, run one at a time, with silver rebuilt in full every time and no visibility into
where a column came from or whether a number looks wrong before someone asks why. Phase 2
closes the gaps PROJECT.md calls "the most important gap for data-leadership roles":

- **Orchestration** (Dagster): the ingest → dbt → test sequence becomes a real DAG, not a
  README instruction.
- **Incremental modeling**: silver stops rebuilding from scratch every run — a transaction's
  own business key (already designed in T3a, [`brain/concepts/business-key.md`](../brain/concepts/business-key.md))
  drives a dbt `MERGE`, and this phase resolves that note's own open question (two legitimate
  same-day, same-amount, same-merchant purchases colliding on one key).
- **Gold**: a star schema (`fact_transactions` + dimensions) — the shape a BI tool or a
  Phase 3 ML feature pipeline actually wants, not silver's flat table. Every currency stays
  separate (no FX conversion, ever — Piero's explicit call), and direction is standardized to
  `ingreso`/`egreso`/`pago` per account kind, not each bank's own raw sign convention.
- **Ingestion correctness as a model-layer test, not just a Python-level check**: each
  statement's own declared balance delta re-verifies T20's incremental MERGE output, catching
  anything the MERGE gets wrong that T8's existing per-parse reconciliation never would.
- **Quality and observability**: Elementary, as a dbt package — anomaly detection and
  column-level lineage with no infrastructure of its own.
- **Catalog and lineage**: OpenMetadata, ingesting from dbt's own manifest and DuckDB's
  catalog — where a column came from and who last changed its model, without opening the code.

**Explicitly out of scope for this phase** (Piero's own framing, 2026-09-14): automatic
transaction categorization and any other ML/LLM work. That's Phase 3, deliberately kept
separate — the goal here is a platform where collecting and modeling the data works end to
end and is observable, *before* anything gets built on top of it that depends on a model.

**Verifiable result once the phase closes:**

```bash
docker compose up -d                        # local S3 (unchanged from Phase 1)
uv run dagster asset materialize --select '*'  # ingest -> silver (incremental) -> gold, one DAG
uv run elementary monitor report              # anomaly/observability report, dbt-native
# OpenMetadata UI (localhost): fact_transactions' lineage traces back to the exact
# bronze.transactions rows and the PDF's sha256 that produced them
```

## Architecture decisions

Every decision gets recorded as an ADR in `brain/decisions/` in the task where it's made —
numbered from whatever's free once Phase 1 actually closes (checked at write time, not
reserved in advance, the same discipline Phase 1 ended up needing when parallel tasks
collided on a number more than once).

| Decision | Choice | Why |
|---|---|---|
| Orchestrator | **Dagster**, wrapping the existing `pfp` CLI and dbt project as assets — not a rewrite of either | PROJECT.md's own choice; Dagster's asset model maps directly onto "bronze asset -> silver asset -> gold asset" without inventing a new execution layer |
| Business-key collision (T3a's open question) | An occurrence number, scoped to *one source file*: `row_number() over (partition by business_key order by <the row's position in that PDF>)` appended to the key | The concept note itself already named this as "one option"; two identical-looking purchases in the *same* statement are legitimately different rows, but the same purchase appearing in two different (possibly regenerated) PDFs of the *same* period should still collide — scoping the tiebreak to one file, not globally, is what keeps both true |
| Incremental strategy | dbt `materialized='incremental'`, `incremental_strategy='merge'`, `unique_key` = the business key above | DuckDB supports `merge` natively (unlike some warehouses needing `delete+insert`); avoids a full silver rebuild every run, the actual Phase 2 ask |
| Gold shape | Star schema: `fact_transactions` (one row per business key) + `dim_date`, `dim_account`, `dim_user`, `dim_bank` | PROJECT.md's own "fact_transactions + dimensions"; no `dim_category` yet — that dimension is Phase 3's, and shipping an empty/placeholder one now would just be schema speculation ahead of the model that fills it |
| Currency | **No FX conversion, ever.** Every currency-aware view (gold included) stays partitioned by `currency`; PEN and USD are never summed into one number | Piero's explicit call (2026-09-14): an FX rate is one more moving, external input this project would have to source and keep current, for a number (a blended "net worth") nobody asked for. Accounts, and a credit card's debt specifically, already read cleanest kept separate by currency — that separation is a feature, not a gap to paper over |
| Flow direction (`flow_type`) | A derived column on `fact_transactions`: `ingreso` / `egreso` / `pago`, computed from `account_kind` (T18a) + sign — never the bank's own raw sign convention directly. `asset` + positive -> `ingreso`; `asset` + negative -> `egreso`; `liability` + positive (a charge) -> `egreso`; `liability` + negative (a payment/credit) -> `pago`, kept distinct from `ingreso` | Piero's own framing (2026-09-14): BCP and Scotiabank's opposite sign conventions (T18a) mean summing raw `amount` across a checking account and a credit card gives a number with no coherent meaning. A `pago` on a liability account is usually a transfer from the user's own other account (already flagged separately by `is_internal_transfer`, T18b) or a refund — genuinely ambiguous which, so it gets its own bucket rather than being forced into `ingreso` and inflating "income." `flow_type` is direction, not merchant category — doesn't touch or anticipate Phase 3's `dim_category` |
| Ingestion correctness, at the model layer | A dbt test compares each account's summed `silver.transactions` amounts per statement period against that same statement's own declared opening/closing balance delta (`bronze.statements`) | Piero's own framing (2026-09-14): `ingestion/reconciliation.py` already checks this once, in Python, at parse time (T8) — but T20's MERGE is new code with its own chance to silently drop or duplicate a row. Re-checking the same arithmetic at the model layer, from the data that's actually in the lake, catches what the MERGE gets wrong that a Python-level check upstream of it never would |
| Quality/observability | **Elementary** (chosen 2026-09-14, over Great Expectations) | Runs as a dbt package, no separate service — fits a local, zero-cost install the way GX's own separate validation layer wouldn't; dbt-native anomaly detection and column-level lineage |
| Catalog/lineage | **OpenMetadata** (chosen 2026-09-14, over DataHub) | Lighter of the two, still real column-level lineage; DataHub is more extensible but needs platform-engineering time this is a one-person install. Even so: needs 6 GiB+ RAM, Postgres/MySQL and Elasticsearch — see Risks, this is the phase's one real resource risk and gets its own checkpoint before the rest of the phase depends on it |

## Structure once Phase 2 closes

```
.
├── dagster/                  # Dagster definitions: assets wrapping pfp ingest + dbt
│   └── definitions.py  assets/{bronze,silver,gold}.py
├── dbt/
│   ├── models/silver/         # now incremental, MERGE by business key
│   ├── models/gold/           # fact_transactions + dim_*
│   └── (elementary package, dbt_packages/)
├── openmetadata/              # docker-compose fragment + ingestion workflow config
├── ...                        # everything Phase 1 already has, unchanged in shape
```

## Ways of working

Unchanged from Phase 1 ([`tasks/plan.md`](plan.md)'s own "Ways of working" and "Definition of
Done" sections apply verbatim): 1 task = 1 branch = 1 PR into `develop`, TDD for all logic,
every PR updates the brain, only Piero merges, `ponytail-review` actually run (not just
checked) before every PR.

One addition specific to this phase: a task that adds a new long-running service
(OpenMetadata) states its own measured RAM/CPU footprint in its PR, the same way Phase 1's
benchmarks task measured parsing/write performance — a resource claim gets verified, not
assumed.

## Tasks

See [`tasks/todo-phase2.md`](todo-phase2.md) for full acceptance criteria per task. Summary:

| Task | What | Depends on |
|---|---|---|
| T20 | Business-key MERGE in silver | Phase 1 closed (T19) |
| T21 | Dagster orchestration (bronze -> silver -> gold as one DAG) | T20 |
| T22 | Elementary (dbt-native quality/observability) | T20 |
| T23 | Gold star schema (`fact_transactions` + dimensions) | T20 |
| T24 | OpenMetadata catalog/lineage | T21, T23 (needs the DAG and the gold layer to have something real to catalog) |
| T25 | Phase 2 close | T20-T24 |

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| OpenMetadata's 6 GiB+ RAM (Postgres/MySQL + Elasticsearch) on top of everything Phase 1 already runs (SeaweedFS, DuckDB, Docker Desktop itself) exceeds what WSL2 can spare | High | T24 starts with a standalone RAM/CPU measurement against `.wslconfig`'s actual limit *before* building the ingestion workflow — if it doesn't fit, the fallback (lighter catalog, or deferring T24 alone past phase close) is decided then, not assumed now |
| The business-key occurrence-number tiebreak (above) still isn't right for some real statement shape not yet seen | Medium | Reconciliation is the backstop, same as every parser: a MERGE that silently drops or duplicates a real row breaks `silver.transactions`' own row-count expectations, which T20's tests check directly, not just the MERGE's mechanics |
| Dagster becomes a second orchestration layer that duplicates what `pfp`'s CLI and `Makefile` targets already do, rather than replacing the manual sequence | Medium | T21's assets call the *same* functions `ingestion/cli.py` and `dbt` already expose — Dagster wraps, it doesn't reimplement; `make poc` and the CLI stay for local single-shot use, Dagster owns the scheduled/DAG'd path |
| Incremental `MERGE` semantics differ subtly from Phase 1's append-only bronze -> full-refresh silver (e.g. a late-arriving backfilled row via `pfp backfill`, ADR 0010, needs to actually update its silver row, not get skipped as "already merged") | Medium | T20's own tests cover a backfill-then-rebuild scenario explicitly, not just a fresh MERGE |
| CI's ephemeral environment (T17) now needs to run a Dagster job, not just `pfp ingest` + `dbt build` directly, and getting that wrong silently makes CI test something looser than what actually runs on a real install | Medium | T21 or T25 (whichever ends up right) updates `ephemeral-integration` to invoke the Dagster job itself, not the bypassed CLI calls, so CI proves the real path |

## Confirmed decisions (2026-09-14)

1. **Scope boundary:** everything through gold + governance, nothing from Phase 3 (ML
   classification, forecasting, anomaly-charge detection via a model) — Piero's explicit
   framing: get data collection working end to end first, add AI after.
2. **Catalog:** OpenMetadata over DataHub.
3. **Quality:** Elementary over Great Expectations.
4. **Business-key collision:** resolved via a per-file occurrence number (see Architecture
   decisions above) — carries forward T3a's own tracked open question rather than leaving it
   open into Phase 2.
5. **No FX conversion, anywhere:** currencies (and a credit card's debt) stay separated, never
   blended into one number. Considered and explicitly rejected — see Architecture decisions.
6. **`flow_type`, not raw sign:** `fact_transactions` gets an `account_kind`-aware `ingreso` /
   `egreso` / `pago` column, so spend/income analysis doesn't depend on knowing each bank's own
   sign convention. See Architecture decisions for the exact mapping and why `pago` is its own
   bucket rather than folded into `ingreso`.
7. **Balance totals double as an ingestion-correctness test**, not just a display number — a
   dbt test re-checks T20's MERGE output against each statement's own declared balance delta,
   promoting T8's existing Python-level reconciliation check into a model-layer one too.

## Open questions

1. **Exact OpenMetadata footprint on this machine** — T24's own first acceptance criterion,
   not assumed here.
2. **Whether Dagster schedules/sensors run at all locally**, or whether this phase only needs
   on-demand `asset materialize` (a schedule needs something always running, which cuts
   against "zero cost, nothing always-on" unless it's cheap enough to leave up) — resolved
   when T21 is scoped in detail.
3. **`dim_account`'s grain**: one row per `account_id` ever seen, or a slowly-changing
   dimension if an account's own metadata (e.g. `account_kind`, T18a) could ever change after
   the fact — likely unnecessary (a bank's product type doesn't change), but worth a one-line
   confirmation in T23 rather than assuming.
