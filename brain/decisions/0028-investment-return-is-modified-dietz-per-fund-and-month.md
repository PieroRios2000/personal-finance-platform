---
type: decision
phase: 6
status: accepted
date: 2026-09-19
---

# ADR 0028: An investment's return is its Modified Dietz return, per fund, currency and month

## Context

The owner wants to see how the investments held elsewhere (three Tyba funds and Flip) grow or
shrink month by month, to judge their returns ([ADR 0027](0027-manual-excel-for-ripley-savings-and-investment-tracking.md)).
The only data is what the owner types: contributions, withdrawals, and a balance after each row,
with a month-end valuation. A balance going up does not mean the fund did well: the owner may
have put money in. The measure has to separate the fund's own result from the owner's flows.

## Decision

- **Where it lives:** the `Inversiones` sheet is loaded into its own bronze table
  (`investment_entries`), then `silver.investment_entries` (typed) and
  `gold.fct_investment_monthly`. Investments are **not** statements or transactions and never
  enter `silver.transactions`, the internal-transfer matching, or the savings goal
  ([ADR 0025](0025-savings-goal-projection-counts-liquid-savings-only.md)). Currencies and funds are
  never mixed or converted.
- **Gain of a month** = closing balance - opening balance - contributions + withdrawals: the change
  the owner's own money does not explain. **Return of a month** = the gain divided by the
  time-weighted capital (opening balance plus each flow weighted by the share of the month it was
  invested), the *Modified Dietz* return: the standard approximation when money moves during the
  period and only balances at the period's edges are known.
- **Opening balance** is the previous month's closing balance; for a fund's first month it is the
  balance before its first row, so a fund already worth something when the records begin does not
  read as a huge first-month gain.
- **A month is "reliable"** only if it has a month-end `valorizacion` row and follows the previous
  month directly. Without a valuation the closing balance is just "the balance at the last
  movement": the return is left null. After a missing month the figure would span several months:
  it is computed but flagged.
- **Cumulative figures** (net contributed and total gain since the records begin) are kept beside
  the monthly ones, since with a few months of history they are what says most.
- **Loading is idempotent and replaces:** each fund-currency-month has an identity independent of
  its content, so a corrected workbook replaces those months (the same rule as the savings sheet).
  A lake that never loaded the sheet still builds: the silver model falls back to an empty table
  (`bronze_table_exists`).

## Alternatives considered

- **Time-weighted return (chaining sub-period returns at every flow)**: needs a valuation at every
  flow date, which the owner does not have; Modified Dietz needs only month-end balances.
- **Money-weighted return / IRR**: sensitive to timing on a few months of data and harder to
  explain; can be added on top of the same table later.
- **Simple balance growth**: mixes the owner's contributions with the fund's result; it would make a
  large contribution look like a great month.
- **Put investments in `silver.transactions` as `aporte`/`retiro` movements**: they would be read as
  spending or income and would distort the liquid cash flow the savings goal is built on.

## Consequences

- With about three months of history, the first returns are short series and say little; the
  cumulative gain is the most useful figure until more months accumulate.
- Modified Dietz is an approximation; large flows late in a volatile month make it less exact.
- Fees and taxes are not modelled (a `comision` column would be added if a fund charges them), so
  returns are as the owner's balances show them.
- The manual `saldo_final` is not checked against anything the fund itself declares (unlike a bank
  statement), so a mistyped balance shows up only as a strange return.

## Related

- [Investment tracking](../components/investment-tracking.md)
- [dbt gold](../components/dbt-gold.md)
- [ADR 0027](0027-manual-excel-for-ripley-savings-and-investment-tracking.md)
