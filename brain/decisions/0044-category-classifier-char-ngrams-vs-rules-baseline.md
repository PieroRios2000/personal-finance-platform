---
type: decision
phase: 3
status: accepted
date: 2026-09-27
---

# ADR 0044: the category classifier is TF-IDF char n-grams + logistic regression, scored against the rules baseline

## Context

T51 (ADR 0043) gave the owner a labeling file with a rules-based guess to confirm or override.
T52 trains a real model on the labels that file collects. A reviewer's feedback (2026-09-27)
shaped the design directly:

- The owner's own labels will be **few** (85 real statements likely yield a few hundred distinct
  descriptions, some categories with very few examples) -- a simple, explainable model suits this
  better than a sophisticated one.
- **Accuracy is misleading** with uneven categories: a model that always guesses the biggest
  category scores high on accuracy and learns nothing.
- Categorization happens **when a statement is ingested, not in real time** -- there is no live
  request to serve yet.

## Decision

- **TF-IDF over character n-grams** (`analyzer="char_wb"`, `ngram_range=(2, 4)`), not word n-grams:
  short, noisy bank-statement text shares substrings (abbreviations, run-together words) even when
  it shares no whole word, and a small labeled set has too few repeats of any one word to learn
  much from words alone.
- **Logistic regression**, not a heavier model: interpretable (defensible in an interview: "why
  this model" has a one-sentence answer), fast to train and re-train on a laptop, and the standard,
  boring choice for TF-IDF features at this scale.
- **Reported metrics: macro-F1 and precision per category**, never plain accuracy
  (`categorization/model.Metrics`). Cross-validated (`cross_val_predict`), not the training set's
  own accuracy, so the number means something on data this small.
- **Scored against the rules-based guesser on the exact same labels**
  (`categorization.model.score_rules`), side by side, every training run
  (`scripts/train_category_model.py`) -- the question a reviewer will actually ask ("does the
  model beat the rules?") is what the script's own output answers, not something to compute later.
- **Guards, not silent bad results**: `NotEnoughDataError` when there are fewer than 10 labeled
  examples, fewer than 2 categories, or a category with fewer than 2 examples -- verified live
  against a throwaway project, both triggering the guard and training successfully once labels
  were rebalanced.
- **MLflow, sqlite backend**: MLflow 3.x deprecated the plain filesystem store; sqlite is the
  current, supported local option for a single-user project, so that is the default
  (`~/finance-data/mlflow.db`), never a bare `./mlruns` in the repo's own working directory (a
  `.gitignore` entry is the safety net in case that default is ever hit by mistake).
- **The trained model, and MLflow's run, never leave `~/finance-data/`**: a fitted TF-IDF
  vectorizer's vocabulary *is* the owner's real transaction text (ADR 0004 applies to it exactly
  as it does to a real PDF). `categorization/model.py` never prints, logs or returns a description
  or the vocabulary -- only counts and scores.
- **No FastAPI serving for now.** Categorization happens once, batch, right after a statement is
  ingested -- the natural integration point is a step in the existing Dagster pipeline (or the
  `pfp ingest`/`make ingest-uploads` flow itself) that writes the prediction into gold, not a
  standing HTTP service with no caller. Left in the backlog as optional, only if there is ever a
  real reason to call it live (e.g. the upload portal previewing a category before the owner
  processes a request).

## Alternatives considered

- **A pretrained/off-the-shelf classifier**: the owner explicitly wants one trained on this
  project's own data -- there is no public Peruvian-bank-statement dataset to pretrain on anyway.
- **Word n-grams**: tried first; the reviewer's point about short, noisy text held on the synthetic
  test data too -- character n-grams generalize better across "PLAZA VEA SAN MIGUEL" vs "PLAZA VEA
  JOCKEY PLAZA" than whole-word matching does on so few examples per category.
- **Weighting training examples by how many movements share a description**: would let one
  frequent merchant dominate a category; every confirmed label counts once, matching how the
  owner actually reviews the file (one decision per description, not per movement).

## Consequences

- Retraining is one command (`make train-category-model`) once new labels exist; it always
  reports both scores, so a regression (the model doing worse than the rules on a newly-labeled,
  messier batch) is visible immediately, not assumed away.
- A production FastAPI endpoint is deferred, not built speculatively before anything needs to
  call it.
- Verified end to end against synthetic, general categories on a throwaway project (per the
  owner's own instruction, before ever running this against his real labels): the not-enough-data
  guard triggered correctly, then training succeeded once every category had at least two
  examples, with metrics and a saved model, MLflow run included.

## Amendment: calibration and label bias (reviewer feedback, 2026-09-27)

A second review, after #158-#162 landed on `main`, raised four points against the design above.
All four are now implemented, not just noted:

- **The rules baseline can be measured against labels it proposed itself.** The labeling
  file prefills `category` with the rules-based guess; if the owner accepts it unreviewed, scoring
  the rules against that same label is circular and can make the baseline look better than it is.
  Fixed with `trusted` (`categorization.labels.read_completed`, `lakehouse.bronze`'s
  `category_labels` schema, `silver.category_labels`): false exactly when the owner left a real
  (non-`UNKNOWN`) suggestion untouched. `scripts/import_category_labels.py` reports how many
  labels were reviewed vs. accepted as-is; `scripts/train_category_model.py` reports the
  model-vs-rules comparison twice, on **all** labels and on **trusted-only** ones, and calls the
  second one the honest comparison out loud.
- **Cross-validation can leak through near-duplicate merchants.** "UBER TRIP 4821" and "UBER TRIP
  5530" are the same merchant with a different transaction id; splitting them into different folds
  lets a character n-gram model partly grade itself on a row it has already half-seen. Fixed with
  `GroupKFold` grouped by `_merchant_group` (digits collapsed to one placeholder), in both
  `train()`'s own cross-validated metrics and `choose_confidence_threshold` below.
- **An eyeballed confidence threshold, on this few examples, is not trustworthy** -- logistic
  regression's probabilities are not well calibrated with so little data. Fixed with
  `choose_confidence_threshold`: refits a pipeline per cross-validation fold, records each
  held-out row's own confidence and the rules-based guesser's answer for the same row, and picks
  the cutoff that maximizes macro-F1 on the combined (model above the cutoff, rules below it)
  predictions -- chosen from the data, never a hardcoded number. `Metrics.folds` and the threshold
  search's own fold count are both reported next to every macro-F1, since a 2-fold score (the
  realistic minimum at this data scale) deserves less confidence than a 5-fold one.
- **The saved artifact is now a `Bundle`** (`pipeline` + `confidence_threshold`), not a bare
  `Pipeline`: `scripts/export_category_labels.py`'s suggestion (`categorization.model.suggest`)
  uses the model's prediction only when its confidence clears the calibrated threshold, falling
  back to the rules-based guesser otherwise -- T53's original wiring always trusted the model's
  own top class regardless of confidence, which this replaces.

## Related

[ADR 0043](0043-transaction-categorization-human-in-the-loop-labeling.md),
[ADR 0004](0004-real-pdfs-never-leave-your-machine.md).
