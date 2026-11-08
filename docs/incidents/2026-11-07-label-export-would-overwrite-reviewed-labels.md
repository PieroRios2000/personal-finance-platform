# 2026-11-07: the monthly label round trip would have overwritten the owner's reviewed labels

**Status:** resolved · **Severity:** near miss

## Summary

Preparing the second month of category labels on the real `pfp-poc` data, the export was found to
prefill every row with the model's current guess instead of the owner's label, while the import
replaces the whole label set. Following `docs/monthly-routine.md` step 2 as written would have
replaced the owner's labels with the model's guesses. It was caught before any import; the owner got
a safe one-off file that day, and this PR fixes the export and the import.

## Impact

None on data: no import ran with the faulty file. What *would* have happened, measured on the real
labels: 589 labels (543 reviewed) replaced by the guesses of a model with a macro-F1 of about 0.49 on
reviewed labels, and every reviewed label the model now agrees with flipped to "accepted the guess",
shrinking the trusted set `make train-category-model` reports on (ADR 0044).

## Timeline

| When | What happened |
|---|---|
| 2026-10-03 | First real labelling: an export with no labels yet, so prefilling guesses was right |
| 2026-11-07 | September's BCP statements loaded, 8 new descriptions; before running `make export-category-labels`, reading the export and import code showed the round trip would overwrite the existing labels |
| 2026-11-07 | One-off safe export written outside the repo (labels prefilled, trust preserved, new rows first); read back with `read_completed`: 597 rows, 8 new, 589 labels unchanged, 0 changed |
| 2026-11-07 | Reproduced in a test (`tests/test_category_labels_round_trip.py` failed on the old code: 3 of 4 labels changed category or trust), then fixed |

## Root cause

- The export (T51) was written for the first labelling, when no label existed: `write_template`
  always set `category` to the guess.
- The import replaces the whole set (a deliberate snapshot, ADR 0043) and derives `is_trusted` from
  whether `category` still equals `suggested_category`. Once labels exist and a model trained on them
  makes the suggestion, that comparison no longer says whether the owner reviewed the row.
- ADR 0043 and SETUP.md both stated that an already-labelled description keeps its category, and no
  test covered a second export: the documented behaviour was never checked against the code.

## Recovery

Nothing to recover. The owner's file that day came from a one-off script (labels prefilled from
`silver.category_labels`, `suggested_category` chosen so `read_completed` returned the same trust),
verified by reading it back before handing it over. The previous file was backed up first.

## What went well / what went wrong

- Went well: the code was read before running a step that replaces data, and the risk was measured
  on the real labels with counts only.
- Went wrong: a round trip that replaces data had no round-trip test, and two documents described
  behaviour the code did not have.

## Prevention

| Action | Where | Status |
|---|---|---|
| Export prefills the owner's labels from bronze, unlabelled pairs first and highlighted | `scripts/export_category_labels.py`, `categorization/labels.py` | done (this PR) |
| Import keeps the trust of an unchanged label | `categorization.labels.keep_existing_trust`, `scripts/import_category_labels.py` | done (this PR) |
| Round-trip test: an unedited export -> import changes no label | `tests/test_category_labels_round_trip.py` | done (this PR) |

## Lessons

- A file that is exported, edited and re-imported to *replace* a set needs a test that an unedited
  round trip is a no-op.
- A flag derived from another column (`is_trusted` from `suggested_category`) breaks when what fills
  that column changes; keep the state it stands for where it already lives (bronze).
