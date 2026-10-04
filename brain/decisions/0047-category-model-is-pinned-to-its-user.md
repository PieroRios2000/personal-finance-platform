---
type: decision
phase: 3
status: accepted
date: 2026-10-04
---

# ADR 0047: the saved category model proposes only for the user it was trained for

## Context

ADR 0045 wired the batch prediction into `pfp ingest` and the Dagster `bronze` asset. A review of
every path that lands movements in bronze (2026-10-04) found two things:

- `make ingest-uploads` was documented as not calling the step. It does: `process_submissions`
  runs `pfp ingest --user <uploader>` for each accepted request, so the batch step already ran
  there. The backlog note was wrong, and a test now pins it.
- That same path exposed a real gap. The model is one file per install
  (`~/finance-data/models/category_classifier.joblib`), trained on one person's labels, but
  `categorize_new_movements.run(user_id)` applied it to whichever user was ingesting. An
  uploader's descriptions were being predicted by the owner's model, with its fitted vocabulary
  (the owner's own transaction text, ADR 0044) and its label set.
- `pfp backfill` rewrites bronze rows from the archive and did not run the step at all.

## Decision

- `Bundle` gains `trained_for: str | None` (the user whose labels fitted it), set by
  `scripts/train_category_model.py` from `--user`.
- `categorize_new_movements.run(user_id)` applies the bundle only when `bundle.trained_for ==
  user_id`. Otherwise it behaves as "no model": reports `has_model=False` and clears that user's
  stale predictions (a user never keeps another person's proposals).
- A bundle saved before this field (`trained_for is None`) is treated as not belonging to anyone:
  the owner retrains once (`make train-category-model`), which he does monthly anyway.
- `pfp backfill` (not `--dry-run`) ends with the same step as `pfp ingest`, through one shared
  `ingestion.cli._categorize`.
- Proposals stay proposals: `category_confirmed` is true only for the owner's own label (ADR 0043).
- Not wired, on purpose: `pfp import-manual` (savings and investment months, not categorized
  movements) and `scripts/seed_demo.py` (the `demo` user has no labels, hence no model).
- The monthly routine is written down and tested: `docs/monthly-routine.md`;
  `tests/test_monthly_routine.py` checks every `make` target it names exists, in the order the
  data flows.

## Alternatives considered

- **One model file per user.** Cleaner in the long run, but it moves the owner's file and every
  path variable (`PFP_CATEGORY_MODEL_PATH`) for a case that has one trained user today. Revisit
  when a second person has labels.
- **Applying the owner's model to everyone as a cold start.** Rejected: the categories and
  vocabulary are the owner's, the quality on other people's merchants is unmeasured, and it would
  silently reuse the owner's text.

## Consequences

- Until the owner retrains once after this lands, his predictions are cleared on the next
  ingest or `make categorize-new-movements` (his bundle has no `trained_for`).
- Other users get no proposals, only `Sin categorizar`, until they have their own model.

## Related

[ADR 0045](0045-batch-categorization-at-ingest.md),
[ADR 0044](0044-category-classifier-char-ngrams-vs-rules-baseline.md),
[ADR 0043](0043-transaction-categorization-human-in-the-loop-labeling.md),
[ADR 0036](0036-row-level-security-by-ingesting-user.md).
