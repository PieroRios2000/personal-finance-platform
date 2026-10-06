---
type: component
phase: 3
status: in-progress
task: T51, T52, T53, T54
---

# Categorization

Automatic transaction categorization (Phase 3's first piece): a proposed category the owner
confirms or overrides, never assigned silently. Design in
[ADR 0043](../decisions/0043-transaction-categorization-human-in-the-loop-labeling.md) (the labeling flow),
[ADR 0044](../decisions/0044-category-classifier-char-ngrams-vs-rules-baseline.md) (the model) and
[ADR 0045](../decisions/0045-batch-categorization-at-ingest.md) (the automatic batch step) and
[ADR 0046](../decisions/0046-classifier-drift-monitoring-with-evidently.md) (drift monitoring).

## Pieces

| Piece | What it does |
|---|---|
| [`categorization/rules.py`](../../categorization/rules.py) | The cold-start guesser: keyword patterns common to Peruvian bank statements, tried in order |
| [`categorization/labels.py`](../../categorization/labels.py) | The labeling file's shape (columns, the fixed category list) and its read/write; `read_completed` also derives `trusted` per row (false for an accepted, unreviewed rules suggestion) |
| [`scripts/export_category_labels.py`](../../scripts/export_category_labels.py) | `make export-category-labels`: groups gold movements by `(bank, description)`, writes the file with a guess prefilled |
| [`scripts/import_category_labels.py`](../../scripts/import_category_labels.py) | `make import-category-labels WORKBOOK=...`: validates the completed file, replaces the owner's labels in bronze, reports how many were reviewed vs. accepted as-is |
| [`lakehouse/bronze.py`](../../lakehouse/bronze.py)`.replace_category_labels` | The lookup table (not append-only): whole-set replace per import, now carrying `trusted` too |
| [`dbt/seeds/category.csv`](../../dbt/seeds/category.csv) → `gold.dim_category` | The fixed, short category list |
| [`dbt/models/silver/category_labels.sql`](../../dbt/models/silver/category_labels.sql), [`gold/rpt_movements.sql`](../../dbt/models/gold/rpt_movements.sql) | The bronze source modeled to silver, left-joined into the reporting layer, coalesced to `'Sin categorizar'` |

| [`categorization/model.py`](../../categorization/model.py) | The classifier (TF-IDF char n-grams + logistic regression): `train()`, `predict()`, `score_rules()` for the same metrics on the baseline, `choose_confidence_threshold()`, `suggest()`, `Bundle`, `load()` |
| [`scripts/train_category_model.py`](../../scripts/train_category_model.py) | `make train-category-model`: trains on every label imported so far, reports macro-F1 and precision per category next to the rules baseline (on all labels, and again trusted-only), logs to a local MLflow, saves a `Bundle` (pipeline + confidence threshold) under `~/finance-data/models/` |

Current result on the owner's labels (re-run 2026-10-04, 589 descriptions, 10 categories):
macro-F1 0.49 on the 543 reviewed labels (merchant-grouped 3-fold), 0.62 on all labels, 0.23 for
the rules; every caveat and the per-category precision are in
[ADR 0044](../decisions/0044-category-classifier-char-ngrams-vs-rules-baseline.md)'s last amendment.

`export_category_labels.py`'s suggestion is the trained model's prediction once one has been
saved there *and* its confidence clears the saved threshold, the rules-based guess otherwise
(cold start, or the model isn't confident enough, T53) -- the same "propose, never decide" shape
either way, never a silent switch the owner has to know about. `train()`'s own cross-validation
groups by merchant (digits stripped), not by row, so two near-duplicate descriptions of the same
merchant never land in different folds and let the model partly grade itself.

| [`scripts/categorize_new_movements.py`](../../scripts/categorize_new_movements.py) | `run()`: batch-predicts a category for every new, unconfirmed `(bank, description)` -- called automatically by `ingestion.cli._run_ingest()`, `pfp backfill` and `orchestration.assets.bronze.bronze()` (T54, ADR 0045, 0047; `make ingest-uploads` reaches it via `pfp ingest`), only for the user the saved model was trained for (`Bundle.trained_for`), also `make categorize-new-movements` by hand |
| [`lakehouse/bronze.py`](../../lakehouse/bronze.py)`.replace_category_predictions`, `distinct_bank_descriptions`, `labeled_bank_descriptions` | The predictions table (whole-set replace per run) and the two reads `categorize_new_movements.run()` needs |
| [`dbt/models/silver/category_predictions.sql`](../../dbt/models/silver/category_predictions.sql) | Same `bronze_table_exists` empty-until-populated pattern as `category_labels.sql` |

`gold.rpt_movements.category` now coalesces three ways: the owner's own label, then a batch
prediction, then `'Sin categorizar'`. `category_confirmed` is true only for the owner's own
label, so a prediction is never mistaken for a confirmed answer.

## Drift monitoring (T55, ADR 0046)

| [`scripts/monitor_category_drift.py`](../../scripts/monitor_category_drift.py) | `build_features()` (drops the description, keeps bank/currency/flow/length/digit share/amount/category/label source), `split_windows()` (reference vs the last N days, refuses a window under 30 rows), `write_report()` (Evidently `DataDriftPreset`, HTML 0600 under `~/finance-data/reports/`); `make monitor-category-drift` |

Read-only on `gold.rpt_movements`. Prints counts and a yes/no per column only. Drift is not error and
the windows are small: a flag means "look at the report" (ADR 0046).

## What's next

FastAPI serving stays optional, only if a real caller shows up for live (not batch) inference.
A scheduled run of the drift monitor (below) if a monthly manual check ever proves too easy to
forget.

## Related

[dbt gold](dbt-gold.md), [Manual Excel importer](manual-excel-importer.md) (the same
shape/content split), [ADR 0004](../decisions/0004-real-pdfs-never-leave-your-machine.md).

`categorization/recurrence.py` and `categorization/feature_experiment.py` (T63) are the offline experiment on recurrence features and the owner's fixed/variable mark: pure functions, run through `scripts/experiment_recurrence_features.py`. Result: no gain, the model stays text-only ([ADR 0049](../decisions/0049-recurrence-and-plan-marks-do-not-help-the-category-classifier.md)).

The month as a sequence (ingest, propose, label, retrain, re-propose, drift) is in
[docs/monthly-routine.md](../../docs/monthly-routine.md), with a test that its `make` targets exist.
