---
type: component
phase: 3
status: in-progress
task: T51
---

# Categorization

Automatic transaction categorization (Phase 3's first piece): a proposed category the owner
confirms or overrides, never assigned silently. Design in
[ADR 0043](../decisions/0043-transaction-categorization-human-in-the-loop-labeling.md).

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

## What's next

A classifier trained on the owner's own confirmed labels, replacing the rules-based guesser as
what proposes a category (still reviewed, never assigned outright) -- tracked with MLflow, served
for new movements, monitored for drift (Evidently). Left as its own task once enough labels exist.

## Related

[dbt gold](dbt-gold.md), [Manual Excel importer](manual-excel-importer.md) (the same
shape/content split), [ADR 0004](../decisions/0004-real-pdfs-never-leave-your-machine.md).
