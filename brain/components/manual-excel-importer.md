---
type: component
phase: 6
status: built
task: Phase 6, feat/manual-excel-importer
---

# Manual Excel importer

Reads the `Ahorros` sheet of the manual Excel (Banco Ripley's savings, typed by the owner because
the bank gives no statements) into the same `Statement`s the PDF parsers produce, so they flow
through bronze, silver and gold. Decision and reasons:
[ADR 0027](../decisions/0027-manual-excel-for-ripley-savings-and-investment-tracking.md); the
sheet's columns and rules: [`docs/manual-data.md`](../../docs/manual-data.md). The `Inversiones`
sheet is **not** imported yet (investment tracking is the next piece).

## Pieces

| Piece | What it does |
|---|---|
| [`ingestion/manual_excel.py`](../../ingestion/manual_excel.py) | `read_savings(path, user_id=...)` → one reconciled `Statement` per account, currency and calendar month, plus a list of problems (row numbers and column names, never values) and a count of missing months |
| `pfp import-manual <workbook>` in [`ingestion/cli.py`](../../ingestion/cli.py) | Writes those statements with `bronze.replace_statement`; writes nothing at all if there is any problem; prints counts only |
| [`scripts/make_manual_templates.py`](../../scripts/make_manual_templates.py) | The template (`plantilla-finanzas-manual.xlsx`) with the agreed columns |
| [`scripts/inspect_manual_excel.py`](../../scripts/inspect_manual_excel.py) | A masked description of a real workbook (shapes and counts only) for the owner to review |

## Rules worth knowing

- **Reconciliation is the balance chain.** Each row's `saldo_final` must be the previous row's plus
  or minus its `monto`. A positive amount whose balance went down is a withdrawal (found on the
  owner's real file: withdrawals were typed unsigned); a negative one is taken as typed; the first
  row of an account is taken as typed. Anything else is reported by row number and nothing is
  loaded.
- **A month's identity does not depend on its content** (a hash of user, account, currency and
  month), so loading a corrected or extended workbook **replaces** the months it contains and
  adds the new ones; loading the same workbook again changes nothing. Checked end to end on the
  owner's real workbook: importing twice and running `dbt build` twice leaves the same gold rows
  and every dbt node passing (continuity by month, reconciliation by file, the silver merge).
- **A month replaced by one with no transactions** (only a balance marker) leaves no stale rows
  in silver: `purge_reprocessed_files` also deletes silver rows whose `source_file_sha256` bronze no
  longer holds any transaction for (found in review; covered by an integration test). A month
  **absent** from the workbook is deliberately not deleted, so a partial workbook is safe.
- Cell values are never in a message: pydantic and reconciliation errors (which quote values) are
  caught and reported as "the month could not be built (invalid values)" with the row.
- **`cierre de mes`** (amount 0) marks a month without movements: a balance marker, not a
  transaction.
- The account is identified by the name typed in the sheet (no account number exists), with
  `account_last4` = `0000`; `bank` is that same name.
- Example rows left in the sheet (`EJEMPLO`) stop the import.

## Not built

- The `Inversiones` sheet (contributions, withdrawals, month-end valuations, monthly return).
- A form to type movements without opening Excel (Phase 5).
- Fees and taxes.

## Related

- [ADR 0027](../decisions/0027-manual-excel-for-ripley-savings-and-investment-tracking.md)
- [Phase 6](../phases/phase-6.md)
- [Lakehouse](lakehouse.md) — `replace_statement`
- [Reconciliation](../concepts/reconciliation.md)
