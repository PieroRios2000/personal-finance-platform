---
type: decision
phase: 3
status: accepted
date: 2026-09-28
---

# ADR 0045: batch-categorize new movements at ingest, not as a live request

## Context

T51-T53 gave the owner a trained classifier and a manual labeling round trip
(`make export-category-labels` → edit → `make import-category-labels`), but a brand-new
description only gets a category once the owner remembers to run that round trip. Reviewer
feedback (2026-09-27) already steered this away from a live HTTP endpoint: "tu categorización
ocurre cuando entra un estado de cuenta, no en tiempo real, así que el patrón natural es
inferencia batch como un paso más de Dagster que escribe en gold." T54 is that step.

## Decision

- **A new bronze table, `category_predictions`** (`lakehouse.bronze._CATEGORY_PREDICTIONS_SCHEMA`):
  `(user_id, bank, description, category, predicted_at)`, whole-set replaced on every run
  (`replace_category_predictions`, same shape as `replace_category_labels`) -- always reflects
  the latest trained model, cheap to recompute at this project's scale (tens to low hundreds of
  distinct descriptions).
- **`category` is already `categorization.model.suggest`'s own output**: the trained model's
  prediction above its calibrated confidence threshold, the rules-based guesser's below it --
  the exact same choice `export_category_labels.py` already makes for the manual suggestion, now
  automatic. No separate confidence column: the threshold decision is baked into which answer
  got written.
- **`scripts/categorize_new_movements.py`, `run(user_id, model_path=None)`**: reads every
  distinct `(bank, description)` the user has in `bronze.transactions`
  (`bronze.distinct_bank_descriptions`), skips whatever is already in `bronze.category_labels`
  (`bronze.labeled_bank_descriptions`, the owner's own confirmed answer always wins), predicts
  the rest, writes the whole batch. No trained model yet: reports it and clears any stale
  predictions rather than leaving outdated ones in place. Reads and writes bronze only -- no
  `PFP_PG_*` needed, so this never blocks on Postgres being reachable at ingest time.
- **Bronze has no `is_internal_transfer` flag** (that's computed later, in silver), so a
  description belonging to an internal transfer gets predicted too here. Accepted as harmless
  waste at this project's scale: `gold.rpt_movements`'s own join only ever surfaces a prediction
  for a real spending/income row, never an internal transfer, regardless of whether one was
  computed for it. The alternative -- running this step after `dbt build` instead, so it could
  read `gold.fact_transactions.is_internal_transfer` and skip those rows -- would decouple it
  from ingest entirely and add a `PFP_PG_*` dependency this step doesn't otherwise need, for a
  saving that doesn't change any result the owner ever sees.
- **Runs automatically from both real entry points, sharing one primitive.** `ingestion.cli
  ._run_ingest()` (`pfp ingest`/`make ingest`) and `orchestration.assets.bronze.bronze()` (the
  Dagster asset, CI's `ephemeral-integration`) both call `scripts.categorize_new_movements.run()`
  directly, at the end of their own existing bronze-writing steps -- the same "shared primitive,
  no cross-import between the two entry points" shape `orchestration.assets.bronze` already uses
  for `ingestion.organizer.organize`/`lakehouse.bronze.write_statement`, one level up. Neither
  entry point depends on the other.
- **`gold.rpt_movements.category` now coalesces three ways**: the owner's own label, then the
  model's batch prediction, then `'Sin categorizar'`. A new `category_confirmed` boolean is true
  only for the owner's own label, never for a prediction -- so nothing built on this table can
  mistake a proposal for a confirmed answer, the same "propose, never assign silently" ADR 0043
  already established for the manual flow, carried one layer further.
- **`make categorize-new-movements`**: a manual escape hatch to re-run just this step (e.g. right
  after `make train-category-model`, without a full re-ingest) -- not the primary path, which is
  automatic, but useful for catching up bronze with a freshly trained model on demand.

## Alternatives considered

- **A FastAPI endpoint that predicts on request.** Rejected per the reviewer's own point: nothing
  in this project categorizes in real time, so a standing HTTP service would have no caller.
  Still left optional in the backlog (T54's original text) if a real one ever shows up (e.g. the
  upload portal previewing a category before the owner processes a request).
- **Run categorization after `dbt build`, reading `gold.fact_transactions`.** Considered so it
  could exclude internal transfers up front. Rejected: ties this step to Postgres being reachable
  and to dbt having already run, when the whole point is a batch step *at ingest* -- and the
  excluded rows never surface anywhere anyway (see Decision above), so the exclusion buys nothing
  a reader would ever notice.
- **Store a numeric confidence alongside the prediction.** Considered, then dropped once the
  prediction itself switched to `categorization.model.suggest()` (threshold-aware) instead of a
  raw `predict()` call: the threshold decision already happened before the row was written, so a
  separate confidence column would be redundant with no consumer.
- **One shared function living in `ingestion` or `lakehouse` instead of `scripts`.**
  `categorization` cannot be imported from either (import-linter: "categorization is standalone:
  no parsers, no lake, no orchestration"), and `scripts/` is already the established home for
  code that bridges `categorization` and `lakehouse` together
  (`import_category_labels.py`/`train_category_model.py` already do exactly this) -- consistent
  with precedent, no contract to work around.

## Consequences

- Every `pfp ingest`/Dagster `bronze` materialization now also does a bounded amount of
  extra work (predicting for whatever's new and unlabeled) -- negligible at this project's
  scale, and skipped entirely (falls through immediately) when no model has been trained yet.
- `gold.rpt_movements` gained one column (`category_confirmed`); nothing that already reads
  `category` needed to change, since the coalesce still ends in the same `'Sin categorizar'`
  fallback as before.
- The owner's manual labeling round trip (T51) is unchanged and still the only way a prediction
  ever becomes a *confirmed* label -- this ADR only changes how fast an unconfirmed proposal
  reaches the dashboard, not who gets to confirm it.

## Related

[ADR 0043](0043-transaction-categorization-human-in-the-loop-labeling.md) (propose, never assign
silently -- the principle this carries one layer further),
[ADR 0044](0044-category-classifier-char-ngrams-vs-rules-baseline.md) (the model and
`categorization.model.suggest`'s threshold),
[ADR 0021](0021-ci-invokes-the-dagster-pipeline.md) (why the Dagster asset graph -- and by
extension `orchestration.assets.bronze` -- exists as its own entry point at all).
