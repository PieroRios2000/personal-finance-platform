# Spec: anomalous-charge detection

Status: **proposed** (2026-10-24, the owner's answers on signals, grain, surfacing and approach
taken as given below). Nothing here is built. Decision record:
[ADR 0053](../../brain/decisions/0053-anomalous-charge-detection-rules-not-ml.md).
Component note (planned): `brain/components/anomaly-detection.md`.
Tasks T74+ are listed in [`tasks/backlog.md`](../../tasks/backlog.md) once this spec is approved.

Closes Phase 3's last open bullet ("Anomalous-charge detection"), after transaction
categorization (ADR 0043-0046) and the forecast/savings-goal projection
([spec](category-forecast-and-savings-goal.md), T56-T66).

## 1. Objective

Answer, for each movement the owner reviews:

1. **Is this one charge unusually large for its category**, compared with my own history in that
   category?
2. **Is this a merchant/description I've never paid before?**
3. **Does this look like the same charge billed twice** (same amount, same merchant, a few days
   apart)?
4. **Did a whole category run above what its own history predicted this month?** -- already
   answered by `gold.rpt_category_variance` (T59, built); this spec adds no new logic for it, only
   a place on the dashboard where it sits next to 1-3.

Questions 1-3 are about one movement; question 4 is about a category's month total. Different
grain, same dashboard section, because the owner reviewing "what looks off" wants both at once.

## 2. Scope and non-scope

Owner decisions (2026-10-24), taken as given:

- **Signals in v1**: unusual amount for the category, a never-seen-before merchant, a
  duplicate-looking charge, and reusing the existing forecast-interval variance (question 4
  above) -- all four.
- **Grain: per transaction** for signals 1-3 (evaluated on each movement, not only on a month
  total), so the dashboard can point at the specific charge, not just "this category ran high."
- **Surfacing: a new dashboard section in v1.** No email alert yet (Phase 7's alerting system
  stays wired for the upload-portal review flow only; nothing here pages the owner).
- **Approach: simple statistical rules first**, the same discipline the classifier (ADR 0044)
  and the forecast (ADR 0048) both followed -- a baseline before any ML model, because a flag the
  owner can't trust is worse than no flag.

In scope (v1):

- Three new per-transaction rules (amount outlier, new merchant, duplicate) computed in gold from
  `gold.rpt_movements`, read-only -- nothing here hides, blocks, or auto-corrects a transaction.
- A new `gold.rpt_anomalies` table (one row per flagged movement, which rule(s) fired).
- A new "Anomalies" Superset section/tab: the flagged-movements table plus the existing
  `rpt_category_variance` rows where `status = 'above'` for the latest closed month.
- Only closed months, the same convention `rpt_movements` and the forecast already use.

Out of scope (each with the reason, revisit later):

- **Email alerts.** The owner chose dashboard-only for v1; Phase 7's alert pipe already exists
  (`ALERT_EMAIL_TO`), so wiring a flagged movement into it later is small, not a reason to build
  it now.
- **An ML anomaly model** (isolation forest, autoencoder, etc.). Same reasoning ADR 0044/0048
  used: a model needs a baseline to beat, and there is no labeled "this was/wasn't actually
  anomalous" ground truth to train or score one against yet.
- **Cross-user novelty** ("no other user has ever seen this merchant either"). Every signal stays
  scoped to one user, matching the row-level-security model everywhere else in this project
  (ADR 0036) -- there is no cross-user comparison anywhere else either.
- **A dismiss/confirm workflow** (the owner marking a flag as "not actually anomalous," the way
  category labels work). v1 is a read-only signal, not a second labeling loop; revisit if the
  false-positive rate in practice makes that worth building (open question 3 below).
- **Non-spending movements.** Income, transfers (`is_internal_transfer`) and `pago` rows are
  excluded from all three new rules the same way `rpt_movements`'s own dashboard already excludes
  them from spending views; a duplicate check on an internal transfer between the owner's own
  accounts would just flag a normal monthly pattern.

## 3. Inputs and outputs

### 3.1 Inputs

| Input | Source | Notes |
|---|---|---|
| Spending movements | `gold.rpt_movements` | Same filter as the dashboard's spending views: `flow_type = 'egreso' AND NOT is_internal_transfer`. Only closed months (already enforced upstream). |
| Category history | Same table, grouped by `(user_id, category, currency)` | For the amount-outlier rule's per-category median/MAD. |
| Merchant history | Same table, grouped by `(user_id, description)` | For the new-merchant rule. `description` is already `normalize_description()`-d (same join key the category labels use). |
| Category variance | `gold.rpt_category_variance` (T59, built) | Reused as-is for question 4; no new column or logic. |

### 3.2 Outputs

| Gold table | Grain | Purpose |
|---|---|---|
| `rpt_anomalies` | `user_id, account_id, date, amount, description, occurrence_number` (the same composite business key `fact_transactions` uses) | One row per movement that trips at least one rule: boolean columns `is_amount_outlier`, `is_new_merchant`, `is_duplicate`, plus the numbers behind each (`category_median`, `category_mad`, `deviation_score`, `duplicate_of_date` when `is_duplicate`). Carries `user_id` for row-level security (ADR 0036). |

No new bronze/silver tables: every input already exists in gold, so this is a pure gold-layer
dbt model, unlike the forecast (which needed new bronze tables for the plan workbook and the
Python-computed forecast itself). No Python/MLflow involved -- these are dbt SQL rules, not a
trained model.

## 4. Design

### 4.1 Amount outlier (signal 1)

For each `(user_id, category, currency)` with at least **5** closed-month spending movements:

```
median := median(amount) over that category's history
mad := median(abs(amount - median)) over the same history
deviation_score := abs(amount - median) / (1.4826 * mad)   -- 1.4826 scales MAD to match
                                                              -- a normal distribution's std dev
is_amount_outlier := deviation_score > 3.5 AND mad > 0
```

Median/MAD instead of mean/standard deviation because a single large charge otherwise drags its
own threshold upward -- exactly the robustness concern ADR 0044 raised about outliers shaping a
baseline. Categories with fewer than 5 movements, or where every movement is the same amount
(`mad = 0`, mostly subscriptions), never flag -- too little history to say what "unusual" means
(the same "too few examples" guard the classifier already applies, ADR 0044).

### 4.2 Never-seen-before merchant (signal 2)

```
is_new_merchant := this description never appeared for this user_id before this movement's date
```

A straight self-anti-join on `(user_id, description)` by date. No minimum-history guard: unlike
the amount rule, a genuinely first-ever charge from a merchant is exactly what this signal means,
even in month one. (Open question 1 below: whether the owner wants a grace period instead.)

### 4.3 Duplicate-looking charge (signal 3)

```
is_duplicate := another movement exists for the same user_id, account_id, amount and description,
                within 3 days (either direction)
```

Account-scoped (not just user-scoped): the same charge appearing on two different cards would be
a real duplicate billing concern; the same amount/merchant on two different accounts by the owner
is more likely two unrelated purchases. 3 days, not 30, to avoid flagging a genuinely recurring
monthly charge (two different months' Netflix charges are never within 3 days of each other).

### 4.4 Category variance (signal 4, no new logic)

The "Anomalies" section's second block is `select * from rpt_category_variance where status =
'above'` for the latest `run_month` -- already built, already row-level-secured. This spec adds
no column, no model, no task beyond the dashboard chart itself.

### 4.5 Dashboard

One new Superset tab, "Anomalies," two charts:

- A table of `rpt_anomalies` rows for the latest closed month: date, description, amount,
  category, which rule(s) fired.
- A table of `rpt_category_variance` rows where `status = 'above'` for the latest closed month:
  category, actual, the interval's upper bound (`p90`), how many of the last 6 months were also
  above.

Same row-level security as every other tab (ADR 0036): each account sees only its own `user_id`.

## 5. Alternatives considered

- **A single anomaly "score" column on `rpt_movements`** instead of a separate `rpt_anomalies`
  table. Rejected: it would touch a table every other dashboard chart and test already depends
  on, for a feature most movements will never trigger (the forecast/fixed-expenses spec made the
  same call keeping `rpt_fixed_expenses`/`rpt_category_variance` as their own tables).
- **A z-score (mean/std dev) instead of median/MAD.** Rejected for the reason in 4.1: a single
  large outlier would raise its own detection threshold.
- **An isolation-forest or autoencoder model.** Rejected for v1 per the owner's own choice and
  the same "no ground truth to score against yet" reasoning ADR 0044/0048 already used for the
  classifier and the forecast.

## 6. Acceptance criteria (feature level)

- `gold.rpt_anomalies` exists, carries `user_id`, and flags at least one of the three signals on
  a synthetic fixture built specifically to trigger each rule (one planted outlier, one planted
  brand-new merchant, one planted same-amount-same-merchant pair 1 day apart) -- and flags
  **nothing** on a fixture with no planted anomalies, including categories with fewer than 5
  movements.
- The "Anomalies" Superset tab renders both charts, row-level-secured, against the demo seed.
- `rpt_category_variance` is read, not modified.
- `make ci-local` green; no new bronze/silver tables, no new Python/MLflow dependency.

## 7. Risks

- **False positives are the main risk, not false negatives.** A legitimate large one-time
  purchase (new appliance, a trip) will trip the amount-outlier rule every time -- this is by
  design (it *is* unusual for that category), but the dashboard copy needs to say "unusual," not
  "wrong," so the owner reads it as a prompt to glance at, not an error.
- **Cold start.** A user's first few months will have almost every category under the 5-movement
  floor (no amount-outlier flags at all) and almost every merchant flagged as "new" (signal 2 has
  no floor by design, open question 1). Expected and acceptable: the demo seed and the owner's
  own ~19 months of real history are both well past cold start already.
- **The 3.5 MAD threshold and the 3-day duplicate window are both guesses, not backtested** (there
  is no "actually anomalous" label to backtest against, unlike the forecast's intervals). Expect
  to tune both after the owner sees the first real run's flag count (open question 2).

## 8. Task breakdown

- **T74** `gold.rpt_anomalies`: the three rules (4.1-4.3), tests on the synthetic fixture from
  section 6.
- **T75** "Anomalies" Superset tab: both charts, row-level security, demo seed data.
- **T76** Run against the owner's real data once; report the real flag counts (never the
  descriptions) so the thresholds in 4.1/4.3 can be tuned if needed (open question 2).

## 9. Open questions for the owner

1. **Signal 2's cold-start noise**: no floor at all (first-ever charge from any merchant always
   flags, even in month one), or a grace period (e.g., no new-merchant flags in a user's first 3
   closed months)? This spec assumes **no floor** (section 4.2) -- correct this now if a grace
   period is preferred.
2. **The two guessed constants** (3.5 MAD for the amount rule, 3 days for the duplicate window):
   fine to start with and tune after seeing T76's real flag count, or do you want different
   starting values?
3. **If T76's real run produces too many flags to be useful**, is a per-movement dismiss/confirm
   workflow (out of scope above) something you'd want built next, or would tightening the
   constants in open question 2 be enough first?
