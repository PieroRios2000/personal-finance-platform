---
type: component
phase: 3
status: in-progress
task: T51, T52
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
| [`categorization/labels.py`](../../categorization/labels.py) | The labeling file's shape (columns, the fixed category list) and its read/write, with no secret needed |
| [`scripts/export_category_labels.py`](../../scripts/export_category_labels.py) | `make export-category-labels`: groups gold movements by `(bank, description)`, writes the file with a guess prefilled |
| [`scripts/import_category_labels.py`](../../scripts/import_category_labels.py) | `make import-category-labels WORKBOOK=...`: validates the completed file, replaces the owner's labels in bronze |
| [`lakehouse/bronze.py`](../../lakehouse/bronze.py)`.replace_category_labels` | The lookup table (not append-only): whole-set replace per import |
| [`dbt/seeds/category.csv`](../../dbt/seeds/category.csv) → `gold.dim_category` | The fixed, short category list |
| [`dbt/models/silver/category_labels.sql`](../../dbt/models/silver/category_labels.sql), [`gold/rpt_movements.sql`](../../dbt/models/gold/rpt_movements.sql) | The bronze source modeled to silver, left-joined into the reporting layer, coalesced to `'Sin categorizar'` |

| [`categorization/model.py`](../../categorization/model.py) | The classifier (TF-IDF char n-grams + logistic regression): `train()`, `predict()`, `score_rules()` for the same metrics on the baseline |
| [`scripts/train_category_model.py`](../../scripts/train_category_model.py) | `make train-category-model`: trains on every label imported so far, reports macro-F1 and precision per category next to the rules baseline, logs to a local MLflow, saves the model under `~/finance-data/models/` |

## What's next

Once there are enough real, confirmed labels: wire the trained model into `export_category_labels.py` as the suggestion (replacing the rules-based guess, still reviewed, never assigned outright), integrate categorization as a batch step of ingest/Dagster rather than a live service, and drift monitoring (Evidently). FastAPI serving stays optional, only if a real caller shows up.

## Related

[dbt gold](dbt-gold.md), [Manual Excel importer](manual-excel-importer.md) (the same
shape/content split), [ADR 0004](../decisions/0004-real-pdfs-never-leave-your-machine.md).
