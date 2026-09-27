---
type: decision
phase: 3
status: accepted
date: 2026-09-27
---

# ADR 0043: transaction categorization starts with owner-confirmed labels, never a guess alone

## Context

Phase 3 (ML in production) starts with automatic transaction categorization. `gold.fact_transactions`
was built with no `dim_category` on purpose (its own comment, T23): the category is a Phase 3
decision, not a fact the parsers can read off a PDF. Training a classifier needs labeled data, which
does not exist yet, and the owner asked for a human-in-the-loop flow: **the model proposes, the
person confirms or overrides** -- never a category assigned silently, and never a real description
sent anywhere (ADR 0004 applies to this exactly as it does to a real PDF).

## Decision

- **A cold-start guesser** (`categorization/rules.py`): a short, ordered list of keyword patterns
  common to Peruvian bank statements (a known merchant, "COMISION", "SUELDO", ...), verified only
  against synthetic descriptions, never the owner's real ones. It exists to give every row a
  starting point before any label -- and later, any model -- exists.
- **A labeling file** (`categorization/labels.py`, mirroring `ingestion/manual_layout.py`'s split of
  shape from content): `scripts/export_category_labels.py` runs on the owner's own machine, groups
  every non-internal-transfer movement in gold by `(bank, description)` (already
  `normalize_description()`-d), and writes one row per group with the guess already filled into an
  editable `category` column. The owner opens it, fixes what's wrong, saves;
  `scripts/import_category_labels.py` reads it back, checks every category against a **fixed,
  short list** (`categorization/labels.CATEGORIES`, seeded in `dbt/seeds/category.csv` as
  `gold.dim_category`), and replaces the owner's whole label set in bronze
  (`lakehouse.bronze.replace_category_labels`, a lookup table, not append-only: there is no history
  to keep, only the current, corrected mapping).
- **`gold.rpt_movements` carries `category`** via a left join on `(user_id, bank, description)| to
  `silver.category_labels`, coalesced to `'Sin categorizar'` -- not on `fact_transactions` itself,
  which stays exactly what the parsers and reconciliation produced. A movement whose description was
  never labeled, or before any labeling file has ever been imported, reads as `'Sin categorizar'`
  rather than null.
- **The trained classifier (next task) replaces the guesser as the proposal, not the confirmation
  step**: whatever model gets built, its output still lands in the same editable `category` column
  for the owner to accept or override, never written straight to gold unconfirmed.

## Alternatives considered

- **Type a category from scratch, no suggestion**: more owner effort for no reason once any guess,
  rules or model, exists.
- **The model decides outright, no review**: the owner explicitly did not want this.
- **A free-text category**: harder to chart, easy to end up with near-duplicates ("Comida" vs
  "Alimentacion"); a fixed list closes that off, with "Otros" as the catch-all.
- **Send descriptions to an LLM for a first-pass label**: sends real financial text off the
  machine before any label exists to judge accuracy against locally -- the same reasoning
  ADR 0004 already applies to a real PDF.

## Consequences

- One more owner-run step per new merchant that shows up: `make export-category-labels`, edit,
  `make import-category-labels`, `make build`. A description already labeled needs no repeat work.
- The label set is a snapshot, not versioned: re-importing a corrected file replaces the whole set,
  same as the manual Excel's own investment months.
- `categorization/` is a new root package (import-linter), standalone like `alerting`: it knows the
  label file's shape and the cold-start rules, nothing about how a statement is parsed or stored.

## Amendment: the final six categories (2026-09-27)

The category list this ADR launched with (14 items, an English-descriptions placeholder) is
replaced by the owner's own short list: `Servicios`, `Restaurantes`, `Viajes`, `Transporte`,
`Deporte`, `Gastos varios` (`categorization/labels.py`'s `CATEGORIES`, `dbt/seeds/category.csv`).
His own reasoning: each category earns its own line in a dashboard chart, and narrowing further
only makes sense once these stop being enough ("por el momento con estas categorias podemos
empezar, despues podemos desglosarlo").

This list is spending-only. `Servicios` absorbs what were separate categories for utilities,
streaming, health, education and bank fees -- all recurring, non-discretionary charges the owner
is fine seeing as one line. `Viajes` (airfare, lodging, travel agencies) and `Deporte` (gyms,
sports clubs) are new. **Groceries, income, transfers between the owner's own accounts and card
payments have no dedicated category under this list** -- `categorization/rules.py` leaves them
unmatched on purpose, and they land in `Gastos varios` like anything else the guesser doesn't
recognize. Flagged to the owner when this landed; his call to accept the gap for now rather than
grow the list back.

## Related

[ADR 0004](0004-real-pdfs-never-leave-your-machine.md),
[ADR 0009](0009-multi-user-multi-account-content-over-filename.md) (`normalize_description`),
[ADR 0020](0020-gold-star-schema-flow-type-and-dim-account-grain.md) (why `fact_transactions`
left category out on purpose),
[ADR 0027](0027-manual-excel-for-ripley-savings-and-investment-tracking.md) (the same
shape-vs-content split this reuses).
