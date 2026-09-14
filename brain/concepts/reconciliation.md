---
type: concept
phase: 1
---

# Reconciliation

Check that the data adds up: each PDF against itself, each account over time, and accounts
against each other. If something doesn't add up, the difference is reported instead of
storing incorrect data.

## How it applies here

Reconciliation is integral, at three levels:

| Level | What it checks | Where |
|---|---|---|
| Statement | `opening balance + Σ amounts = closing balance`, and the charge/credit totals when the bank declares them | T8 |
| Continuity | A period's closing balance is the next period's opening balance, **and the next period starts the day after the previous one ended**, for the same user and account; catches missing statements | T16 |
| Between accounts | Every transfer between accounts of the same user has its counterpart, and never counts as an expense or income | T18b |

- `ReconciliationError` reports the expected value, the actual one, and the difference.
- It's OCR's safety net (T11b): one misread digit on a scanned page breaks the balance.
- With real PDFs, local tests (`pytest -m real_pdf`) show only pass/fail and the differences,
  never the extracted values.
- The statement-level check is exercised against a fictional PDF, never a real one:
  `tests/fixtures/synthetic_pdfs.py` (T10) builds one with a coherent opening balance +
  Σ movements = closing balance by default, and a `reconciles=False` (or an explicit
  `closing_balance`) variant to test the failure path.

This is the personal version of the reconciliation and validation methodologies used in data
migrations.

## Where each level lives, and why they are different kinds of check

The statement level is a **Python function that runs before anything is written**
([`ingestion/reconciliation.py`](../../ingestion/reconciliation.py)): a statement whose own
numbers don't add up never reaches bronze. The continuity level is a **dbt test that runs over
what is already stored** ([dbt silver](../components/dbt-silver.md)'s
`dbt/tests/assert_statement_continuity.sql`, T16), and it has to be: nothing about a single
file can tell you a *different* file is missing. Only the set of archived periods can.

That is also why continuity needs two halves rather than one. A missing month normally shows up
as a balance drift between the periods on either side of it, but not if that month's movements
happen to net to zero — the balances line up perfectly and only the date check notices the hole.
Both are checked, and both fail the build (dbt severity `error`), rather than warning.

The consequence worth knowing: a lake with real, partially archived history will fail this test
until the missing statements are ingested, and that is the intended behaviour — it is the
project telling you which periods you never archived. The tests seed their own synthetic
statements into a dedicated prefix so the check is asserted against known data.

## Related

- [Medallion architecture](medallion.md) — bronze only accepts reconciled statements.
- [dbt silver](../components/dbt-silver.md) — where the continuity level runs.
- [Users and accounts](users-and-accounts.md) — continuity and inter-account reconciliation need to know which account each movement belongs to.
- [ADR 0004: Real PDFs](../decisions/0004-real-pdfs-never-leave-your-machine.md) — what gets shown when testing against real PDFs.
- [Phase 1](../phases/phase-1.md)
