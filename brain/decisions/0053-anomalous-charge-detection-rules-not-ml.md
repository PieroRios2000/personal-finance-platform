---
type: decision
phase: 3
status: proposed
date: 2026-10-24
---

# ADR 0053: anomalous-charge detection with simple per-category rules, not ML, surfaced on the dashboard only

## Context

Phase 3's plan ("ML in production") lists three items: transaction categorization (ADR
0043-0046, built), monthly spend forecasting (ADR 0048, built, T56-T66), and anomalous-charge
detection -- the last one still just a one-line mention in `PROJECT.md` and the architecture
diagram, with no spec or ADR. On 2026-10-24, with Phase 4 (cloud) just closed (T73), the owner
chose to start this to close Phase 3.

Interviewed on four axes:

1. **Which signals count as "anomalous" in v1?** Options offered: an unusual amount for the
   category, a never-seen-before merchant, a duplicate-looking charge, or reusing the forecast's
   own prediction interval (`gold.rpt_category_variance`, already built in T59). The owner chose
   **all four**.
2. **What grain?** Per transaction (so the dashboard can point at the specific charge) vs. per
   category/month (reusing the forecast's own monthly grain, simpler, but can't name the
   transaction). The owner chose **per transaction** for the new signals.
3. **How should it surface?** A dashboard section, an email alert (reusing Phase 7's existing
   `ALERT_EMAIL_TO` pipe), or both. The owner chose **dashboard only** for v1.
4. **Which technical approach?** Simple statistical rules first (same baseline-before-ML
   discipline as ADR 0044/0048) vs. an ML anomaly model (isolation forest, etc.) from the start.
   The owner chose **rules first**.

## Decision

Build three new per-transaction rules in `gold.rpt_anomalies` (median/MAD amount outlier per
`user_id, category, currency`; a first-ever-seen `description` per user; a same-amount,
same-merchant, same-account charge within 3 days) plus a new "Anomalies" Superset tab that shows
those rows alongside the already-built `rpt_category_variance` (`status = 'above'`) for the
latest closed month. No ML model, no email alert, no cross-user comparison, no dismiss/confirm
workflow in v1 -- see the [spec](../../docs/specs/anomalous-charge-detection.md) section 2 for
the full scope/non-scope list and section 4 for the exact rule definitions.

Median/MAD, not mean/standard deviation, for the same reason ADR 0044 already gave for keeping
the classifier simple: a single large charge would otherwise inflate its own detection threshold
upward via the mean, the same way one noisy label can bias a small training set.

## Consequences

- No new bronze or silver tables, no Python, no MLflow: this is a pure gold-layer dbt model
  reading tables that already exist, unlike the forecast (which needed new bronze tables and a
  Python/MLflow pipeline) or the classifier (a trained model).
- The 3.5 MAD threshold and the 3-day duplicate window are both starting guesses, not backtested
  -- there is no "actually anomalous" ground truth to backtest against the way the forecast's
  intervals could be. Expect to tune both after T76's real run reports the actual flag count
  (spec section 9, open question 2).
- Phase 3 closes once T74-T76 land -- the last of its three plan items.

## Related

[ADR 0043](0043-transaction-categorization-human-in-the-loop-labeling.md),
[ADR 0044](0044-category-classifier-char-ngrams-vs-rules-baseline.md) (the baseline-before-ML and
outlier-robustness reasoning this ADR reuses),
[ADR 0048](0048-spend-forecast-baselines-and-savings-goal-scenarios.md) (`rpt_category_variance`,
reused as-is for signal 4),
[ADR 0036](0036-row-level-security-by-ingesting-user.md) (the per-user scoping every signal
here stays inside),
[spec](../../docs/specs/anomalous-charge-detection.md).
