# Spec: monthly spend forecast per category and savings-goal projection

Status: **proposed** (2026-10-04). Nothing here is built. Decision record:
[ADR 0048](../../brain/decisions/0048-spend-forecast-baselines-and-savings-goal-scenarios.md).
Component note (planned): [Spend forecast](../../brain/components/spend-forecast.md).
Tasks T56-T63 are listed in [`tasks/backlog.md`](../../tasks/backlog.md) and detailed below.

It closes two plan items at once: Phase 3's "monthly spend forecasting (time series)" and the
cash-flow part of [Phase 6](../../brain/phases/phase-6.md) ("how long until I reach my savings
goal"). One feature, because the second needs the first.

## 1. Objective

Answer three questions from the owner's own closed months, with numbers and honest uncertainty:

1. **What will I spend next month, per category?** And which categories were above what was
   expected last month.
2. **How long until I reach a savings goal I set**, from what is already saved plus what is
   projected to be saved each month?
3. **What would have to change** (monthly saving needed, by when) and where is the room: which
   categories are above their usual level.

Owner decisions (2026-10-04), taken as given:

- The system **proposes** which recurring expenses look fixed; the owner **confirms** later which
  are fixed or variable.
- The owner **enters a savings goal**; the output is the **time to reach it**, from the
  liquid savings already held plus the projected monthly saving.
- The forecast is **per category**, to see where spending is above expected and adjust total
  spending.

## 2. Scope and non-scope

In scope (v1):

- Detecting fixed-expense candidates from history; an export, edit and import file for the owner.
- A per-category, per-currency forecast of variable spending for the next 3 closed-month steps,
  chosen by a rolling-origin backtest against a baseline, with prediction intervals.
- A savings projection with three scenarios, the time to the goal as a range, and an "adjust" view.
- Gold tables, a Superset section, MLflow tracking of the backtests, a monthly routine step.

Out of scope (each with the reason):

- **Planned extras and expected-income calendars** (a known bonus in March, a trip in July).
  Irregular months are covered by the scenarios; revisit after the first real run shows how much
  the owner misses them (open question 4).
- **Non-monthly fixed expenses** (annual insurance, quarterly fees). They stay inside the
  variable series, where the seasonal candidate can pick up a yearly spike. A `frequency` column
  is added to the file when a first real non-monthly item exists; today it would be a one-value
  column.
- **An exchange-rate path and an external rate API.** v1 uses one owner-entered rate, constant
  over the projection,. The Phase 6 "sol/dólar projection section"
  stays planned; this spec does not block it (ADR 0025 keeps conversion out of bronze, silver
  and gold).
- **Investments** (ADR 0025): never part of the goal.
- **Per-category budgets typed by the owner, advice text, a live endpoint, Dagster scheduling,
  deep-learning or Prophet-class models.** See section 5.
- **Other users' forecasts on the public demo beyond the synthetic demo user.** Same rule as
  ADR 0042.

## 3. Inputs and outputs

### 3.1 Inputs

| Input | Source | Notes |
|---|---|---|
| Spending movements | `gold.rpt_movements` | Same definition as the dashboard: `flow_type = 'egreso' AND NOT is_internal_transfer`, the category shown (owner label, else the model's, else `Sin categorizar`; outflows labelled `Ingresos` shown as `Sin categorizar`, [ADR 0043](../../brain/decisions/0043-transaction-categorization-human-in-the-loop-labeling.md)). |
| Income movements | `gold.fact_transactions` | `flow_type = 'ingreso' AND NOT is_internal_transfer`. |
| Starting savings | `gold.rpt_capital.savings_balance` of the last closed month, per currency | Liquid bank accounts only; the `investments_balance` column is ignored (ADR 0025). Debt (`debt_balance`) is not netted: card spending is already counted as spending when charged. |
| Plan workbook | `~/finance-data/manual/plan-de-ahorro.xlsx`, owner-edited | Section 4.1. Never in Git. |

Only **closed months** enter, exactly as `rpt_movements` and `rpt_balances` (they leave out
`first_day_of_current_month`). The latest data point is therefore the last closed month; the
current month is neither training data nor compared against its forecast until it closes.

### 3.2 Outputs

All outputs carry `user_id` and get the same row-level-security rule as the existing datasets.

| Gold table | Grain | Purpose |
|---|---|---|
| `fct_spend_forecast` | `user_id, run_month, kind, category, currency, target_month` | `kind` is `backtest` (a past one-step forecast, with its actual) or `forecast` (future). Columns: `horizon`, `model`, `p10`, `p50`, `p90`, `actual` (null while the month is open). |
| `rpt_category_variance` | `user_id, category, currency` | Latest closed month: actual, the forecast made without it, its 80 % interval, `status` (`above` / `within` / `below`), months `above` in the last 6. |
| `rpt_forecast_series_quality` | `user_id, run_month, category, currency` | Selected model, months of history, backtest origins, MAE relative to the baseline, 80 % interval coverage, flags `low_history` and `baseline_used`. The "how much to trust it" table. |
| `rpt_fixed_expenses` | `user_id, bank, description` | Confirmed fixed items: expected amount, last observed month, `deviation_pct`, months seen in the last 6. |
| `rpt_goal_projection` | `user_id, scenario, month_index` | Month path per scenario: projected savings in the goal currency. |
| `rpt_goal_summary` | `user_id, scenario` | `months_to_goal` (or null, "not reached in 120 months"), `reached_month`, required monthly saving, projected monthly saving, gap; and the headroom rows for the adjust view (section 4.5). |

Bronze (written by Python, replace-by-partition, so a rebuild from the archive plus a re-run
reproduces them): `plan_fixed_items`, `plan_goal`, `spend_forecasts`, `spend_forecast_series`,
`goal_projection`. Silver stages them (typing and a uniqueness test); gold reads silver
([ADR 0029](../../brain/decisions/0029-dbt-stores-silver-and-gold-in-postgres.md)'s flow).

## 4. Design

### 4.1 Fixed expenses: the system proposes, the owner decides (decision 1)

**Detection** (pure function over closed months, per `(bank, normalized description)`,
the same key the category labels use; the currency is read from the movements, and a description
seen in two currencies is listed once per currency with a note, which the owner resolves):

- *Candidate fixed:* charged in at least 4 of the last 6 closed months, and the monthly total's
  spread is small (median absolute deviation ≤ 10 % of the median).
- *Recurring but not fixed:* charged in at least 4 of the last 6 months with a larger spread
  (a supermarket, fuel). Listed with `proposed_kind = variable`; it is never proposed as fixed.
- Everything else is not listed. The thresholds are named constants, tested on synthetic series,
  and are a starting point to calibrate on the owner's first real file (the file only counts and
  amounts it shows, it prints nothing to the console).

**The file** (`make export-plan`) follows the labeling file's pattern
([ADR 0043](../../brain/decisions/0043-transaction-categorization-human-in-the-loop-labeling.md)):
one Excel in `~/finance-data/manual/`, sheets in Spanish like the owner's other workbooks.

| Sheet | Columns | Who fills it |
|---|---|---|
| `Gastos fijos` | `bank`, `description`, `currency`, `category`, `months_seen`, `typical_amount`, `proposed_kind`, **`kind`** (`fixed` / `variable` / `ignore`), **`expected_amount`** | System prefills `kind = proposed_kind` and `expected_amount = typical_amount`; the owner edits the two bold columns. |
| `Meta` | `goal_amount`, `goal_currency`, `target_date` (optional), `usd_to_pen`, `income_pen_override`, `income_usd_override` (optional) | Owner only. Exported empty on first run. |

Re-exporting **keeps the owner's choices**: rows already classified keep `kind` and
`expected_amount`; new candidates are appended as proposals; a row no longer detected stays and
says so. `make import-plan WORKBOOK=...` validates (known currency, positive amounts, a
`target_date` in the future, a rate when any dollar amount is involved) and replaces the owner's
plan whole, like the labels. Rejecting a bad file changes nothing.

**How the kinds are used:**

- `fixed`: contributes its `expected_amount` every month, deterministic (no interval), and its
  movements are removed from the variable series. `rpt_fixed_expenses` shows when the real amount
  drifts from the expected one (> 10 %), so a price rise is noticed; the monthly routine
  re-proposes the observed typical amount without overwriting the owner's.
- `variable`: stays in its category's series (default for anything unclassified).
- `ignore`: a known one-off excluded from the variable series. Its excluded total is shown, so the
  choice is visible rather than silently lowering the forecast.

**Reusable data model.** `plan_fixed_items` is keyed by `(user_id, bank, normalized description)`
(currency is an attribute; the rare description in two currencies is two rows distinguished by currency in the file and resolved by the owner), the same join key as the category labels, and
keeps the owner's `kind` and the detection features (`months_seen`, amount spread, day-of-month
regularity) as columns. That makes the file usable as classifier input later (section 4.8) without
a second table or a different key.

Rejected: *the owner classifies everything up front* (hundreds of descriptions; the owner asked
to confirm proposals later) and *fully automatic classification with no confirmation* (a wrong
"fixed" would hide a real spending change; same human-in-the-loop principle as categories).

### 4.2 Variable forecast, per category and currency (decision 3, owner point 3)

**Series.** For each `(user, category, currency)`: monthly variable spending over closed months,
zero-filled between the first month the user has any data in that currency and the last closed
month (a category absent in a month is a real zero, but months before the user's history are not).
Currencies are never added together (as everywhere). A second, total series per currency (all
spending, fixed included) is forecast separately: the sum of per-category intervals would assume
every category errs the same way in the same month, so the total gets its own backtest and
interval, and the scenarios use that.

**Candidates** (five, all a few lines of numpy/pandas, none fitted by an optimizer):
`naive_last` (last month), `mean_3`, `median_6` (the **baseline**: robust to a single large
month), `ses` (simple exponential smoothing, fixed `alpha = 0.3`) and `seasonal_naive_12` (same
month last year; considered only with at least 12 months of training).

**Backtest** (rolling origin, expanding window, no look-ahead): origins from 9 months of training
to the last closed month; at each origin forecast `h = 1..3` and score `h = 1` (selection) and
`h = 3` (reported). Selection per series: the candidate with the lowest `h = 1` MAE, accepted only
if it beats the baseline by at least 5 % **and** wins on at least 60 % of the origins; otherwise
the baseline is used and `baseline_used = true` says so. A series with fewer than 9 months, or
nearly all zeros, uses the baseline and is flagged `low_history`.

**Intervals.** Empirical, from the selected model's own backtest errors: `p10` and `p90` are the
point forecast plus the 10th and 90th percentile of its signed errors, lower bound floored at 0.
Fewer than 12 errors: the errors of all series in the same currency, scaled by this series' level,
are pooled. The
reported coverage is measured on the same errors the interval came from, so it is **optimistic**,
and the table says so.

**Metrics** logged per run: MAE relative to the baseline (`1.0` = no better) and 80 % interval
coverage; aggregated across series as a plain mean and as a spend-weighted mean.
State plainly in the dashboard when the baseline is the model for most series. With about two
years of monthly history a model that does not beat a trailing median is the expected outcome for
many categories, and reporting that is a result, not a failure.

**Library: hand-rolled numpy/pandas, no `statsmodels`.** pandas, scikit-learn and mlflow already
bring numpy and scipy; `numpy` is declared explicitly (`uv add numpy`, already in `uv.lock`, so no
new package and no new pip-audit surface). `statsmodels` would add a dependency and its
exponential-smoothing/ARIMA fits are unstable on 24 monthly points (a seasonal model needs
several seasons to estimate its state). Prophet, sktime, ARIMA families: rejected for the same
reason plus size. Revisit only if a series with 5+ years of history appears.

### 4.3 Category variance (owner point 3: where am I above expected)

`rpt_category_variance` compares the last closed month's actual with the forecast made **without
that month** (a backtest row, so it works from the first run): `above` when actual > `p90`,
`below` when < `p10`, otherwise `within`. "Above expected" therefore means "above what the
category's own history predicted, with its own noise", not above an arbitrary budget. Fixed items
show on their own table.

### 4.4 Savings projection and scenarios (decision 4, owner point 2)

Per month `t` after the last closed month, in the **goal currency**:

`savings_t = savings_(t-1) + income_t - spending_t`

- **Start:** liquid savings of the last closed month per currency (section 3.1), dollars converted
  at the owner's `usd_to_pen` (or its inverse when the goal is in dollars).
- **Spending:** fixed items at their expected amount + the variable forecasts for `t = 1..3`;
  beyond that the last point forecast is held flat (or the last 12 months repeated when
  `seasonal_naive_12` was selected). The total-series interval gives the scenario spread.
- **Income:** the median of the last 12 closed months of non-internal income (6 if fewer; below 6,
  no scenarios, only a message), or the owner's override.
- **Scenarios:** *base* = point forecasts and median income. *cautious* = spending at the
  total-series `p90` and income at the 25th percentile of the last 12 months. *optimistic* =
  spending at `p10` and income at the 75th percentile. They are **scenarios, not a confidence
  interval**: each month takes the same percentile, which is neither independent nor a joint
  probability, and the summary and the dashboard say so.
- **Output:** `months_to_goal` per scenario, the first month where savings reach `goal_amount`;
  shown as `optimistic ≤ base ≤ cautious`. If monthly saving is not positive, or the goal is not
  reached within 120 months, the answer is "not reached", never a number. The base scenario is
  (to see the effect of the rate, change it in `Meta` and re-run).
- **Cross-check:** for each of the last 6 closed months, the net flow (income − spending) is
  compared with the change in `savings_balance`. If they disagree by more than 25 % of spending
  in most months (untracked accounts, card debt carried, unrecorded cash), the dashboard shows a
  warning that the projection does not explain the balance, and the balance change is displayed
  next to it. Rejected as the primary method: projecting from balance changes alone (it cannot be
  split by category, which is what the owner asked for).

### 4.5 The "adjust" view (owner point 3)

Numbers only, no advice text:

- `required_monthly_saving` to reach the goal by `target_date` (if given) and the base scenario's
  `projected_monthly_saving` (mean of months 1-3) → `gap`.
- Per variable category: the base forecast, a reference level the owner has actually achieved (the
  25th percentile of that category's last 12 months), `headroom = max(0, forecast - reference)`
  and its share of the total headroom. The sum of headrooms is compared with the gap
  ("returning every category to its own better quartile would cover X % of the gap").
- Categories with `status = above` (section 4.3) are marked.

Rejected: *owner-typed budgets per category* (more input than the owner asked for; the reference
level comes from their own history, and budgets can be added later without changing the tables).

### 4.6 Process and tools

- **Where code lives:** a new `forecasting/` package (series, candidates, backtest, intervals,
  fixed-expense detection, projection: pure functions, no I/O) and thin `scripts/` for the file
  and the runner, like `categorization/`. It is added to `[tool.hatch.build.targets.wheel]` and to
  the import-linter `root_packages`, with a contract: `forecasting` imports neither `ingestion`
  nor `lakehouse` (the runner script, like `categorize_new_movements`, does the I/O).
- **Reads/writes:** reads gold through the same `PFP_PG_*` psycopg connection the export scripts
  use; writes bronze Delta tables; dbt then builds silver and gold. The runner is
  `make forecast` = read gold → forecast and project → write bronze → `dbt build --select` the
  new models. (A build before and after: the forecast depends on the latest gold, and the new gold
  tables depend on the forecast.) Writing bronze rather than Postgres directly keeps the rule that
  Python only writes the lake and dbt owns silver and gold.
- **MLflow:** one experiment `spend-forecast`; each run logs parameters (min training months,
  horizons, candidate list, thresholds) and the aggregate metrics above. **No amounts, no
  descriptions**: only ratios and counts (ADR 0004). Same local `mlruns/` caveat as the classifier.
- **Monitoring:** every run stores `forecast` rows with their `run_month`; once the month closes,
  the realized error of last month's forecast is in gold (`actual` joined by `target_month`). A
  chart of realized relative error against the backtest's is the monitoring; the owner judges it. Evidently (ADR 0046) is not
  used: about two dozen points per series is too few for a distribution-drift test.
- **Dagster:** none in v1. Training the classifier is manual in the monthly routine; the forecast
  joins it as a step. A downstream asset is a later option, not a goal.
- **Retraining:** there is no model artifact to retrain: every `make forecast` re-fits from the
  closed months (cheap, stateless). Monthly cadence is therefore the routine itself.

### 4.7 Privacy

- No description text, amount or total from real data in the repo, docs, CI logs, MLflow or
  alerts. Fixtures are synthetic series generated in the tests.
- The plan workbook (descriptions, amounts, the goal) lives in `~/finance-data/manual/`, outside
  Git, like the labeling workbook.
- Console output of every script: counts and scores only.
- The public demo (`pfp-prod`) shows the section for the synthetic `demo` user only; the seed gets
  a small plan so the section is not empty.

### 4.8 Planned follow-up: recurrence as classifier features (after T62)

The recurrence signals computed for fixed-expense detection (months seen out of the last N,
amount spread, same-day-of-month regularity) and the owner's confirmed fixed/variable mark may help
the category classifier ("a monthly, same-amount charge is probably Servicios"). Not part of v1;
a separate experiment task (T63) once the forecast has shipped, because it needs the detection
features and real confirmed marks to exist.

**Experiment design.** Same protocol as [ADR 0044](../../brain/decisions/0044-category-classifier-char-ngrams-vs-rules-baseline.md):
merchant-grouped repeated cross-validation, macro-F1 on the trusted (reviewed) labels only,
compared with the text-only model run through the same folds in the same experiment (reference:
macro-F1 0.49 on 543 reviewed labels, 3 folds, at the 2026-10-04 amendment). Variants: text +
derived recurrence features; text + derived features + the owner's mark. **Acceptance:** a variant
replaces text-only only if its mean macro-F1 exceeds text-only's by more than one standard
deviation of the fold-to-fold spread (reported with N and folds, as ADR 0044 does), and no
weak-category precision drops. Otherwise the result is recorded as an amendment and the model
stays text-only. A null result is a valid outcome.

**Risks, stated up front.**

- ADR 0044 already tested extra non-text features (bank, currency, flow type, log amount, month)
  and none beat text-only outside the noise (spread 0.01 to 0.04); several were worse. Recurrence
  is a different kind of signal, but the prior is a null result.
- A recurrence flag is derived from the same description, so it can duplicate what the character
  n-grams already know, or leak: a label the owner gave to a description also shaped which rows are
  "recurring". The cross-validation must compute recurrence features inside each training fold
  from past months only.
- The owner's confirmed fixed/variable mark is label-like input. It must be **point-in-time**: it
  may be used only for movements that were classified after the mark existed, never for earlier
  rows or for the evaluation fold's own rows, and a new description (no mark yet) must predict
  from the derived features alone.
- The model still only **proposes**: `category_confirmed` stays true only for the owner's own
  label ([ADR 0043](../../brain/decisions/0043-transaction-categorization-human-in-the-loop-labeling.md),
  [ADR 0047](../../brain/decisions/0047-category-model-is-pinned-to-its-user.md)).
- The prediction grain is per description ([ADR 0045](../../brain/decisions/0045-batch-categorization-at-ingest.md));
  features must be per `(bank, description)` too, or that grain changes.

## 5. Alternatives considered

| Decision | Chosen | Rejected, and why |
|---|---|---|
| Fixed expenses | Proposed by rule, confirmed by the owner | Fully manual (too much typing); fully automatic (a wrong "fixed" hides a real change) |
| Forecast models | Five simple candidates + baseline, backtested | One fixed model for all (no evidence it works per series); ARIMA/ETS via statsmodels, Prophet (unstable or heavy on ~24 points, new dependency) |
| Evaluation | Rolling-origin backtest vs a trailing-median baseline | Single train/test split (12 test months at most, one lucky window decides); no baseline (nothing says whether it is worth anything) |
| Uncertainty | Empirical error quantiles, pooled when short | Normal-theory intervals (monthly spend is skewed with a floor at 0); no interval (the owner needs to see "above expected" relative to noise) |
| Total spending | Its own series and interval | Sum of category quantiles (assumes perfectly correlated errors) |
| Projection | Three scenarios, time as a range, "not reached" allowed | One point estimate (false precision); Monte Carlo paths (assumes an error model nobody has validated on this data) |
| FX | Owner-entered constant rate | Public rate API (new network dependency; the platform is local); a rate-path model (Phase 6, not needed to answer the goal question) |
| Where outputs live | Bronze → silver → gold | Python writing Postgres (breaks "rebuild from the lake"); computing it all in SQL (the backtest and the projection are logic that needs unit tests) |

## 6. Acceptance criteria (feature level)

- [ ] From a synthetic history, `make export-plan` proposes the planted fixed items and not the
      planted variable ones; re-export keeps the owner's edits; `make import-plan` rejects a bad file
      whole.
- [ ] `make forecast` is deterministic and idempotent: running it twice leaves gold identical.
- [ ] Property tests: forecasts at an origin do not change when later months change (no
      look-ahead); a flat noisy series selects the baseline; a planted seasonal series selects
      `seasonal_naive_12`; a series with fewer than 9 months is `low_history`.
- [ ] The projection returns "not reached" for a non-positive saving, a monotone
      `optimistic ≤ base ≤ cautious`, and the goal in either currency gives the same answer at the
      same rate.
- [ ] Only closed months enter; the current month is never in a series (test with a frozen date).
- [ ] The dashboard section appears for the demo user with row-level security (a user sees
      only their own rows) and shows the scenarios-not-confidence note.
- [ ] MLflow logs ratios and counts only; a test fails if a logged value or tag contains a
      description from the fixture.
- [ ] Docs: ADR, brain notes, `docs/monthly-routine.md` updated; `make ci-local` (and
      `ci-local-full`, since `dbt/` changes) green.

## 7. Risks

| Risk | Mitigation |
|---|---|
| About two years of history: seasonal terms and intervals rest on few points | The 5 % / 60 % acceptance rule for a non-baseline winner; `low_history` and `baseline_used` flags shown; coverage labelled optimistic |
| Selecting among 5 candidates on 12-15 origins is optimistic (winner's curse) | Few candidates, fixed `alpha`, a margin plus a win-rate rule, and the realized-error monitor as the honest check after the fact |
| Category labels move (the model's proposals are not owner labels) | The forecast reads the category shown today; a relabel rewrites history, so each run stores its own rows under its `run_month` and the variance view reads the latest run |
| A one-off month (trip, repair) distorts a category | The median baseline is robust to it; `ignore` kind for known ones; the variance view marks `above` rather than hiding it |
| Net flow does not explain the balance (accounts or cash not tracked) | The cross-check and its warning; the projection never claims more than the data supports |
| Savings in dollars and goals in soles move with the rate | Constant owner rate, changed in `Meta` and re-run to see its effect; the FX path stays a separate Phase 6 item |
| Fixed-expense thresholds fit the owner's file badly | Constants tested on synthetic data and calibrated once on the first real export; the owner's confirmation is the final word |
| Real data leaking through logs, MLflow or fixtures | Counts and ratios only, a leak test, synthetic fixtures, gitleaks and the diff review (CLAUDE.md) |

## 8. Task breakdown

Order is the dependency order. Each task = one branch from `develop` = one PR, TDD (failing test
first), `make ci-local` before the PR, brain updated, and the skills named in `tasks/plan.md`.

| Task | What | Depends on | Verification |
|---|---|---|---|
| **T56** | `forecasting/` package skeleton + fixed-expense detection (pure) + `make export-plan` (candidates, empty `Meta`, keeps prior choices). Adds `numpy` explicitly, wheel and import-linter entries. | none | Tests on synthetic series (planted fixed/variable/recurring); re-export preserves edits; `uv run pip-audit` unchanged apart from the explicit numpy; `make ci-local` |
| **T57** | `make import-plan`: validation, `bronze.plan_fixed_items`, `bronze.plan_goal`; silver staging; gold `rpt_fixed_expenses`. | T56 | Bad file rejected whole; good file replaces the plan; dbt tests (`unique`, `accepted_values` for `kind`); `ci-local-full` |
| **T58** | Forecast core (pure): series builder (closed months, zero-fill, fixed removed), five candidates, rolling-origin backtest, selection rule, empirical intervals, pooled fallback, metrics. | T56 | Property tests (no look-ahead, determinism, seasonal vs flat, short history, intermittent zeros); coverage ≥ floor |
| **T59** | `make forecast` runner: read gold, write `bronze.spend_forecasts` and `spend_forecast_series`, MLflow experiment, silver/gold `fct_spend_forecast`, `rpt_category_variance`, `rpt_forecast_series_quality`. | T57, T58 | Idempotent twice-run test; leak test on MLflow; `ci-local-full`; run on the demo user in a throwaway project |
| **T60** | Projection (pure) + persistence: start balance, income, three scenarios, time-to-goal, cross-check, adjust view; gold `rpt_goal_projection`, `rpt_goal_summary`. | T59 | Property tests (monotone scenarios, "not reached", currency symmetry); dbt tests; `ci-local-full` |
| **T61** | Superset section "Forecast & goal" (dashboards as code, row-level security on the new datasets) + demo seed plan. | T60 | `tests/test_bi_config.py` additions; throwaway project (`make bi-up`) check with the demo user; screenshot reviewed by the owner |
| **T62** | Monitoring chart (realized vs backtest error), `docs/monthly-routine.md` step (`export-plan` → edit → `import-plan` → `forecast`), `docs/where-to-look.md` rows, brain and backlog closed out. | T61 | `tests/test_monthly_routine.py` still passes with the new targets in order; docs-links check |
| **T63** (follow-up) | Experiment: recurrence and the fixed/variable mark as classifier features (section 4.8). Offline script; an amendment to ADR 0044 with the result either way; the model changes only if the acceptance margin is met. | T62, and real confirmed marks | Same folds as the text-only baseline; features computed inside each training fold; a test that the owner's mark is never read for an evaluation row |

The cost study and the anomaly detector remain separate Phase 3 items and do not depend on this.

## 9. Open questions for the owner

Each has a recommendation; the spec proceeds on it unless told otherwise.

1. **Goal currency and date.** Recommend the goal in soles, `target_date` optional (without it
   the output is only "how long", without the gap and required saving).
2. **What counts as "already saved".** Recommend every liquid bank account including the Ripley
   savings sheet, as ADR 0025 says. Should some amount be reserved (an emergency fund the goal
   must not touch)? Recommend no reserve in v1; a `reserved_amount` cell in `Meta` is trivial to
   add if you want one.
3. **Yearly expenses** (insurance, taxes, annual fees). Recommend leaving them inside the variable
   series for v1 and adding a `frequency` column when you have a real one.
4. **Planned extras and known income changes.** Recommend deferring until the first real run shows
   whether the three scenarios already cover your irregular months.
5. **Fixed vs variable.** This is yours, after the first `make export-plan`: the system proposes,
   you confirm. Recommend doing it once before the first forecast, then reviewing only changes
   in the monthly routine.
