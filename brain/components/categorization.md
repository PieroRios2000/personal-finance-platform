---
type: component
phase: 3
status: in-progress
task: T51, T52, T53
---

# Categorization

Automatic transaction categorization (Phase 3's first piece): a proposed category the owner
confirms or overrides, never assigned silently. Design in
[ADR 0043](../decisions/0043-transaction-categorization-human-in-the-loop-labeling.md) (the labeling flow) and
[ADR 0044](../decisions/0044-category-classifier-char-ngrams-vs-rules-baseline.md) (the model).

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

`export_category_labels.py`'s suggestion is the trained model's prediction once one has been
saved there *and* its confidence clears the saved threshold, the rules-based guess otherwise
(cold start, or the model isn't confident enough, T53) -- the same "propose, never decide" shape
either way, never a silent switch the owner has to know about. `train()`'s own cross-validation
groups by merchant (digits stripped), not by row, so two near-duplicate descriptions of the same
merchant never land in different folds and let the model partly grade itself.

## What's next

Integrate categorization as a batch step of ingest/Dagster rather than a live service (T54), and
drift monitoring (Evidently, T55). FastAPI serving stays optional, only if a real caller shows up.

## Related

[dbt gold](dbt-gold.md), [Manual Excel importer](manual-excel-importer.md) (the same
shape/content split), [ADR 0004](../decisions/0004-real-pdfs-never-leave-your-machine.md).
