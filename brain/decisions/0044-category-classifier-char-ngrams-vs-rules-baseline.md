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

## Amendment: the threshold-selection macro-F1 is not a reportable metric (2026-09-28)

A follow-up review flagged that `choose_confidence_threshold` picks the threshold by maximizing
macro-F1 over the exact same held-out cross-validated predictions that score is computed from --
the same look-ahead any hyperparameter search has when the search and the report share one split.
That number is real for *choosing* a threshold (there is no spare data at this project's scale to
hold out a third split just for that), but it is optimistic by construction and must never be
presented as a clean metric. `choose_confidence_threshold` already never returned it and never
logged it; its docstring now says so explicitly, so it can't quietly get added back in without a
second thought. The two numbers this project actually reports and that are honest -- `train()`'s
and `score_rules()`'s own macro-F1s, neither one involving the threshold at all -- are unaffected
and remain what `scripts/train_category_model.py` prints and logs to MLflow.

## Amendment: first real-label results, and why the model stays text-only (2026-10-03)

First training on the owner's real labels: 589 descriptions, 10 categories in use. Reviewed
labels only (543, 3 folds): model macro-F1 0.49. Rules baseline on all labels: 0.23. Always
guessing the biggest category: 0.07. These, with their N and fold count, are the only numbers
quoted in the README.

An offline experiment (one row per movement, 1,529 rows, merchant-grouped 5-fold cross-validation
repeated over 5 shuffles) tested adding bank, currency, flow type, log amount and month to the
description text. Macro-F1 on reviewed labels: text only 0.465, plus amount 0.480, plus bank,
currency and flow 0.468, all of those 0.442, plus month 0.453, with run-to-run spread of 0.01 to
0.04. No variant beat text-only outside the noise, and several were worse, so the model stays
text-only and `bronze.category_predictions` keeps its per-description grain (ADR 0045). Only
logistic regression was tried; a tree-based model could use the amount better and is untested.
The binding constraint is the number of labeled merchants in the weak categories (services,
restaurants, transport), not the feature set.

## Amendment: results re-run on the current labels (2026-10-04)

`make train-category-model` was re-run before October's statements are labeled. The label set is
the same as on 2026-10-03 (589 descriptions, 10 categories, 543 of them reviewed, 46 accepted as
the rules' own suggestion), so the figures did not move; this records them in full, with the
caveats, as the reference to beat once October's labels exist.

One label per distinct description, merchant-grouped cross-validation (the script's own, one pass):

| | Macro-F1 | Labels | Folds |
|---|---|---|---|
| Model, reviewed labels only | 0.492 | 543 | 3 |
| Model, all labels | 0.615 | 589 | 5 |
| Rules, all labels | 0.229 | 589 | n/a |
| Rules, reviewed labels only | 0.049 | 543 | n/a |

One row per movement (1,529 rows, 441 distinct description groups, merchant-grouped 5-fold,
repeated over 5 shuffles, text only, offline script outside the repo): 0.593 on all labels
(spread 0.036) and 0.465 on the 1,345 reviewed rows (spread 0.009).

Precision per category on reviewed labels (the script prints precision, not recall): catch-all
0.91, travel 0.79, entertainment 0.78, sports 0.60, income 0.50, health 0.50, transport 0.36,
food 0.33, restaurants 0.27, services 0.00. On all labels transport rises to 0.71 and services to
1.00, which shows how much of the all-labels score comes from rows the rules had already solved.

Caveats that apply to every figure above:
- **Few labels, very uneven.** The catch-all is 52% of the labels; several categories have a
  few dozen examples or fewer, so one merchant moving between folds shifts that category's
  precision by tens of points. Differences of 0.02 to 0.04 are noise.
- **Two label qualities.** The 46 accepted-as-is labels make the all-labels score (0.615)
  optimistic and the rules baseline on all labels (0.229) generous. The reviewed-only rules score
  (0.049) is not a fair head-to-head either: a reviewed row is, by construction, one the owner
  corrected or the rules had no opinion on. The model's reviewed-only 0.492 is the figure to quote.
- **Label noise.** Labels attach to `(bank, description)`, not to the direction of the money, so
  a description used for both an inflow and an outflow carries one category (five outflows labeled
  as income were found this way, and the dashboard now shows them as not categorized, ADR 0043).
- **Grain.** Per-description scores treat a once-seen merchant like a daily one; per-movement
  scores weight by frequency. Both are kept because they answer different questions, and the
  README labels each.

CV wording that matches these numbers exactly: "Category classifier (TF-IDF character n-grams +
logistic regression) on 589 self-labeled merchant descriptions in 10 categories: macro-F1 0.49
on the 543 reviewed labels (merchant-grouped 3-fold CV), against 0.23 for a keyword-rules
baseline on all labels."

## Amendment: recurrence features and the owner's mark were tested and rejected (2026-10-05)

T63 tested recurrence features and the owner's fixed/variable mark as extra inputs, with this
ADR's protocol (merchant-grouped folds, trusted labels, macro-F1). Text-only 0.468; with
recurrence 0.455; with the mark 0.468; with both 0.428; baseline fold SD 0.107. No variant met
the acceptance margin and two lowered Transporte's precision, so the classifier stays text-only.
Detail in [ADR 0049](0049-recurrence-and-plan-marks-do-not-help-the-category-classifier.md).

## Related

[ADR 0043](0043-transaction-categorization-human-in-the-loop-labeling.md),
[ADR 0004](0004-real-pdfs-never-leave-your-machine.md).
