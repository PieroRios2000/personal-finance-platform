---
type: decision
phase: 3
status: proposed
date: 2026-10-05
---

# ADR 0049: recurrence features and the owner's fixed/variable mark do not help the category classifier

## Context

The spend forecast (ADR 0048) detects recurring charges and the owner confirms which are fixed
or variable. The owner's idea (2026-10-04) was that the same signals might help the category
classifier: a monthly charge of a steady amount is probably "Servicios". Spec section 4.8
promised an experiment with the protocol of [ADR 0044](0044-category-classifier-char-ngrams-vs-rules-baseline.md)
and a pre-stated acceptance rule, and said a null result is a valid outcome.

## Decision

The classifier stays **text-only** (TF-IDF over character n-grams plus logistic regression). No
variant met the acceptance rule, so nothing in the saved model, `make train-category-model` or
`make categorize-new-movements` changes.

The experiment is kept as an offline script, `scripts/experiment_recurrence_features.py`
(`categorization/recurrence.py` and `categorization/feature_experiment.py` hold the testable
parts), so it can be re-run when there are more labels or more months.

**What was compared.** Four feature sets on the same merchant-grouped folds (a merchant is
`(bank, description with digit runs collapsed)`), each over 5 folds x 5 shuffles:

- `text`: the baseline.
- `recurrence`: months seen in the previous 12 (scaled), share of available months, amount
  spread (median absolute deviation over the median of the prior monthly totals), each with a
  "missing" flag.
- `plan_kind`: the owner's mark for the merchant, one-hot (fixed / variable / ignore / none).
- `all`: both.

Recurrence is **point in time**: a row only sees months strictly before its own, so a later
statement never changes an earlier row (tested). It uses no labels, which is why it is computed
once over the user's movements and not inside each training fold.

**Acceptance rule (spec 4.8, unchanged):** a variant replaces text-only only if its mean
macro-F1 exceeds the baseline's by more than one standard deviation of the fold-to-fold spread
and no weak category's precision drops (Alimentacion, Restaurantes, Servicios, Transporte).

## Result

On the owner's real reviewed labels: 1,345 labeled movements (of 1,529), 402 merchants, 10
categories, 5 folds x 5 shuffles. Baseline fold-to-fold SD 0.107; run-to-run range of the
baseline's pooled macro-F1 0.073.

| Feature set | Macro-F1 | Margin over text | Weak-category precision drops |
|---|---|---|---|
| text (baseline) | 0.468 | | |
| text + recurrence | 0.455 | -0.013 | Alimentacion 0.168 to 0.159, Transporte 0.934 to 0.898 |
| text + plan mark | 0.468 | +0.001 | Transporte 0.934 to 0.480 |
| text + both | 0.428 | -0.040 | Transporte 0.934 to 0.482 |

No margin approaches 0.107 (nor the smaller 0.01 to 0.04 spread seen in the 2026-10-03 run), so
the verdict does not depend on which spread is used. Servicios, the category the idea was aimed
at, has precision 0.000 under every feature set.

Coverage explains part of it: 588 of the 1,345 rows have two or more prior months of history and
only 191 rows (18 merchants) carry a plan mark. Accuracy on the rows with history rises a little
with recurrence (text 0.834, recurrence 0.864, n = 588) and falls on the rows without it (0.689
to 0.658, n = 757), a wash overall. That split was looked at after the fact; a rule such as "use
recurrence only when the merchant has history" would be a new hypothesis, not a result of this
experiment, and would need its own pre-stated run.

## Alternatives considered

- **Adopt recurrence for rows with history.** Post hoc and untested on fresh data; rejected.
- **Hide the owner's mark from evaluation rows** (spec risk list). The mark is a property of the
  merchant, so a held-out merchant that the owner has marked keeps its mark, as it would in use.
  That makes the `plan_kind` result an optimistic upper bound, and even that bound shows no gain.
  The mark is not derived from the category label, but the plan's `ignore` and `fixed` choices
  can correlate with categories; a future positive result would need that checked.
- **Other models** (gradient boosting on the numeric features). Out of scope: ADR 0044 chose a
  linear model for this data size, and a null result on the features does not call for a new
  model class.

## Consequences

- The model, the saved bundle and the threshold are untouched.
- The result is a negative one, recorded so the idea is not re-proposed without new evidence:
  more months of history or more reviewed labels are the conditions for re-running it.
- Everything printed is counts, scores and category names, never a description or an amount.

## Related

[ADR 0044](0044-category-classifier-char-ngrams-vs-rules-baseline.md),
[ADR 0048](0048-spend-forecast-baselines-and-savings-goal-scenarios.md),
[spec 4.8](../../docs/specs/category-forecast-and-savings-goal.md).
