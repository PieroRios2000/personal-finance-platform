---
type: decision
phase: 3
status: proposed
date: 2026-10-04
---

# ADR 0048: spend forecast with backtested baselines, owner-confirmed fixed expenses, and a savings goal answered with scenarios

## Context

Two plan items need the same machinery: Phase 3's monthly spend forecasting and Phase 6's
"how long until I reach my savings goal". On 2026-10-04 the owner decided three things: the system
proposes which expenses look fixed and the owner confirms later; the owner enters a savings goal
and the answer is the time to reach it from what is saved plus what is projected to be saved; and
the forecast is per category so spending that is above expected can be adjusted. Later the same
day he added: the goal is in **dollars** (so soles and dollars saved need an exchange rate), Ripley
savings are the **emergency fund** and all investments are **risk savings**, and the goal must carry
an **emergency amount calculated from his spending and income**.

The data is small: roughly two years of closed months, two currencies, a dozen-odd categories,
several of them sparse. Choices that suit thousands of points (ARIMA families, Prophet, neural
nets) would overfit or fail to converge, and a single train/test split could not tell whether any
model is worth having. The full design is in
[the spec](../../docs/specs/category-forecast-and-savings-goal.md).

## Decision

- **Fixed expenses are proposed by a rule and confirmed by the owner** in an edited workbook
  (`kind` fixed / variable / ignore, `expected_amount`), imported whole like the category labels.
  Fixed items are deterministic; their movements leave the variable series.
- **The variable forecast is five simple candidates against a trailing-median baseline**,
  per category and currency, chosen by a rolling-origin backtest. A non-baseline winner must beat
  the baseline by 5 % and win on 60 % of origins, otherwise the baseline is used and says so.
  Intervals are empirical error quantiles. Total spending has its own series and interval.
- **Hand-rolled numpy/pandas, no `statsmodels`.** `numpy` is declared explicitly (already
  locked through pandas and scikit-learn, so no new package).
- **The goal is in US dollars.** The owner enters `usd_to_pen` (soles per 1 dollar); soles become
  dollars by dividing by it. With no rate the projection refuses to run and says why.
- **Two buckets, shown as two lines.** Ripley savings are the emergency fund; investments are risk
  savings at their last closed month-end valuation, held flat. The goal is shown as `liquid` (emergency
  excess, other bank accounts, new savings) and `with_risk` (plus investments), until the owner says
  which one his goal means. This amends ADR 0025.
- **The emergency amount is calculated:** `emergency_months` (default 6) x monthly essential outflow
  (fixed items + the 6-month median of variable spending, `emergency_basis = all`; `fixed_only` is
  the switch for the floor), cross-checked against income. New savings fill the emergency gap first,
  then the goal.
- **The goal is answered with three scenarios** (base, cautious, optimistic) as a range of months,
  "not reached" when it is not. They are explicitly not a confidence
  interval.
- **Only closed months, the dashboard's spending definition** (`egreso`, not an internal
  transfer).
  [ADR 0025](0025-savings-goal-projection-counts-liquid-savings-only.md) is amended: investments
  are no longer excluded outright, they are the second line.
- **Conversion stays confined to the projection**, with one owner-entered rate and no external
  API; bronze, silver and gold remain unconverted.
- **Python writes bronze, dbt builds silver and gold**, the shape of
  [ADR 0045](0045-batch-categorization-at-ingest.md). Gold gets the forecast, variance, series
  quality, fixed-expense and goal tables; Superset gets a "Forecast & goal" section.
- **MLflow logs ratios and counts only**, never an amount or a description.
- **Realized-vs-backtest error is the monitor**; Evidently is not used at this volume.

## Alternatives considered

- **`statsmodels` / ARIMA / ETS / Prophet:** an extra dependency and pip-audit surface for models
  that are unstable on about two dozen points; a seasonal model needs several seasons. Revisit with
  5+ years of history.
- **One model for every series, no baseline:** gives no evidence the forecast is worth anything;
  the baseline comparison is the point of the backtest.
- **Normal-theory or no intervals:** monthly spend is skewed with a floor at zero, and "above
  expected" only means something relative to the category's own noise.
- **A single projection number or Monte Carlo paths:** the first claims precision the data
  cannot give; the second assumes an error model nobody has validated on this data.
- **Summing category quantiles for the total:** assumes every category errs the same way in the
  same month.
- **A typed emergency amount, or a fixed share of income:** a typed number goes stale as spending
  changes, and a share of income ignores what the owner actually spends.
- **One merged balance, or counting the investments with no alternative line:** the first hides that
  investments move with the market; the second picks an answer the owner has not given.
- **A public exchange-rate API, or an FX path model now:** a network dependency in a local-only
  platform; neither is needed to answer the goal question. The Phase 6 FX section stays a
  separate item.
- **Python writing Postgres directly, or all logic in SQL:** the first breaks "rebuild from the
  lake"; the second makes the backtest and the projection hard to unit-test.
- **Owner-typed per-category budgets:** more input than asked for; a reference level from the
  owner's own history gives the "where is the room" view, and budgets can be added later.

## Consequences

- Seven tasks (T56-T62) plus the follow-up T63, each its own PR; nothing changes until the first lands.
- A new `forecasting/` package, a new import-linter contract and a new `numpy` line in
  `pyproject.toml`; `docs/monthly-routine.md` gains `export-plan`, `import-plan` and `forecast`.
- Honest outcomes are possible and acceptable: for many categories the baseline will be the
  model, and the dashboard says so.
- The scenarios treat every month at the same percentile, so the range is wider than a joint
  probability would be; the dashboard states it.
- A follow-up experiment (T63) will test recurrence and the fixed/variable mark as classifier
  features, with ADR 0044's protocol and an acceptance margin over the fold spread. ADR 0044 found
  extra non-text features did not help, the flag can leak or duplicate the text signal, and the
  owner's mark must be point-in-time; the model keeps only proposing. The plan file is keyed by
  `(user_id, bank, normalized description)`, the category labels' key, so it can be reused.
- Gold gains `rpt_emergency_fund`; the goal tables carry a `line` column.
- The answer moves with the owner's rate; he changes it in the workbook and re-runs.
- Open for the owner: whether the goal counts the investments (spec, section 9, point 1).
- Annual expenses, planned extras and an exchange-rate path are left open (spec, section 9).

## Amendments (T58)

- `Total` is the sum of the *variable* categories per currency, forecast as its own series;
  fixed items enter the projection as their expected amount.
- A run is identified by `run_month`, the first day of the last closed month: deterministic,
  so running twice in a month is idempotent.
- The backtest interval uses the series' final error quantiles for every origin, so its
  reported coverage is optimistic; the dashboard says so.
- On pure noise the rule false-switches to a candidate in roughly 12-27 % of series
  (measured on synthetic iid noise, 24-36 months); the margin and win-rate conditions bound it,
  they do not remove it.

## Related

- [Spec](../../docs/specs/category-forecast-and-savings-goal.md)
- [Spend forecast](../components/spend-forecast.md)
- [Savings-goal projection](../concepts/savings-goal-projection.md)
- [ADR 0025](0025-savings-goal-projection-counts-liquid-savings-only.md)
- [ADR 0043](0043-transaction-categorization-human-in-the-loop-labeling.md)
- [ADR 0045](0045-batch-categorization-at-ingest.md)
- [Phase 6](../phases/phase-6.md)
