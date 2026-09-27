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

## Related

[ADR 0043](0043-transaction-categorization-human-in-the-loop-labeling.md),
[ADR 0004](0004-real-pdfs-never-leave-your-machine.md).
