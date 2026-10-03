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

## Amendment: three of those four gaps get their own category after all (2026-09-27)

Once he saw the gap spelled out, the owner asked for three of the four back: `Alimentacion`
(groceries), `Ingresos` (income) and `Transferencias` (transfers). `categorization/rules.py`
gained a keyword rule for each.

**Card payments stay without one, and correctly so, not as a remaining gap**: paying off the
owner's own credit card is a transfer to his *own* other account, which `export_category_labels.py`
already excludes before this list is ever consulted (`where ... and not is_internal_transfer`,
ADR 0017's matching). It never reaches `categorization/rules.py` in the first place, so it needs
no rule and no category -- the earlier framing of it as a fourth gap next to the other three was
imprecise; corrected here.

`Transferencias` here specifically means a transfer to *someone else's* account: the only kind
of transfer that ever reaches this guesser, since `is_internal_transfer` (the owner's own accounts)
is filtered out upstream.

## Amendment: six more categories, added by the owner while labeling (2026-10-03)

Labeling his real descriptions, the owner added `Entretenimiento`, `Salud`, `Ahorros`,
`Cuidado Personal`, `Ropa` and `Educacion` (32 of 589 descriptions), because he judged they
deserved their own line. `import_category_labels.py` correctly rejected the workbook until the
list was extended, so the list stays closed and the owner's call is applied in code
(`CATEGORIES`, the `category.csv` seed, the dbt `accepted_values`). The cold-start rules no
longer file pharmacies, clinics and schools/courses under `Servicios`; streaming stays there
because it is not known whether his `Entretenimiento` is streaming. The list is now 15.

Consequence: four of the new categories have 1-4 labeled descriptions, so the trainer's
"at least 2 per category" guard refuses to train (`Educacion` has 1) and the fold count would be
capped at 2 by `Ropa`. More labels, or merging the rarest into a neighbour, is needed before any
metric is worth publishing (ADR 0044).

## Amendment: the dashboard shows the classification as its own section (2026-10-03)

`bi/build_dashboards.py` adds a "Categories" section between the cash flow and the
investments, over `gold.rpt_movements` only (no new table): what you spent on, by category;
where each category came from (`category_confirmed` = you labelled it, a model guess, or
none yet, counted in movements); spending per month by category; and a table of the
movements nobody has confirmed. Movements between the owner's own accounts are left out of
the whole section (ADR 0017). The section keeps this ADR's rule visible: a guess is shown as
a guess, in its own colour and its own table, and the fix is made in the labelling workbook,
not in the dashboard. The demo environment has no labels, so there the section shows
everything as "no category yet".

## Related

[ADR 0004](0004-real-pdfs-never-leave-your-machine.md),
[ADR 0009](0009-multi-user-multi-account-content-over-filename.md) (`normalize_description`),
[ADR 0020](0020-gold-star-schema-flow-type-and-dim-account-grain.md) (why `fact_transactions`
left category out on purpose),
[ADR 0027](0027-manual-excel-for-ripley-savings-and-investment-tracking.md) (the same
shape-vs-content split this reuses).
