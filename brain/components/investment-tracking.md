---
type: component
phase: 6
status: built
task: Phase 6, feat/investment-tracking
---

# Investment tracking

Follows the funds and platforms the owner invests in (Tyba funds, Flip) from the manual Excel's
`Inversiones` sheet, and computes each one's return per month. Decisions and reasons:
[ADR 0027](../decisions/0027-manual-excel-for-ripley-savings-and-investment-tracking.md) and
[ADR 0028](../decisions/0028-investment-return-is-modified-dietz-per-fund-and-month.md); the sheet's
columns and rules: [`docs/manual-data.md`](../../docs/manual-data.md).

## Pieces

| Piece | What it does |
|---|---|
| [`ingestion/manual_excel.py`](../../ingestion/manual_excel.py) `read_investments` | The sheet into one `InvestmentMonth` per fund, currency and month (rows, kinds and balances validated; problems by row and column, never values). The sheet is optional |
| `InvestmentEntry` / `InvestmentMonth` in [`ingestion/schema.py`](../../ingestion/schema.py) | The typed rows: `aporte` and `retiro` have an amount greater than 0, `valorizacion` has amount 0 |
| `bronze.replace_investment_month` in [`lakehouse/bronze.py`](../../lakehouse/bronze.py) | Deletes the month's earlier rows (by `user_id` and `month_key`) and appends the new ones: loading again changes nothing, a corrected month is replaced |
| `pfp import-manual` in [`ingestion/cli.py`](../../ingestion/cli.py) | Loads both sheets; nothing is written if either has a problem |
| [`dbt/models/silver/investment_entries.sql`](../../dbt/models/silver/investment_entries.sql) | Typed rows with their month; an empty table when the lake has no investments (`bronze_table_exists`) |
| [`dbt/models/gold/fct_investment_monthly.sql`](../../dbt/models/gold/fct_investment_monthly.sql) | Per fund, currency and month: opening and closing balance, contributions, withdrawals, gain, Modified Dietz `return_pct`, `is_return_reliable`, cumulative net contributed and cumulative gain |

## How to read `fct_investment_monthly`

- `gain` = closing - opening - contributions + withdrawals. `return_pct` = gain / (opening + each flow
  weighted by the share of the month it was invested).
- `return_pct` is null and `is_return_reliable` is false for a month **without a `valorizacion`**
  row; a month after a **missing month** has `months_since_previous` > 1 and is flagged too.
- Never mixed: each `place` and `currency` is its own series. Not part of `silver.transactions`,
  the transfer matching or the savings goal.

## Verified

Integration tests against a real local S3 seed bronze and check the figures (the month's gain and
return, the first month's opening, cumulative figures, unreliable months, separate currencies and
funds).

## Not built

- Fees and taxes; an IRR; a dashboard (Phase 5 territory).

## Related

- [ADR 0028](../decisions/0028-investment-return-is-modified-dietz-per-fund-and-month.md)
- [Manual Excel importer](manual-excel-importer.md)
- [dbt gold](dbt-gold.md)
- [Phase 6](../phases/phase-6.md)
