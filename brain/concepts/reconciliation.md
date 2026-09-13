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
| Continuity | A period's closing balance is the next period's opening balance, for the same account; catches missing statements | T16 |
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

## Related

- [Medallion architecture](medallion.md) — bronze only accepts reconciled statements.
- [Users and accounts](users-and-accounts.md) — continuity and inter-account reconciliation need to know which account each movement belongs to.
- [ADR 0004: Real PDFs](../decisions/0004-real-pdfs-never-leave-your-machine.md) — what gets shown when testing against real PDFs.
- [Phase 1](../phases/phase-1.md)
