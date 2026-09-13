---
type: component
phase: 1
status: built
task: T11
---

# BCP parser

Turns a BCP statement PDF into a reconciled `Statement` (T6's schema), reading the bank,
account number and period from the PDF's own content — never from the file name (ADR 0009).

## Pieces

| Piece | What it does |
|---|---|
| [`ingestion/parsers/base.py`](../../ingestion/parsers/base.py) | The `BankParser` shape every bank module exposes: `detect(path) -> bool` and `parse(path, *, user_id, file_sha256, password="") -> Statement` |
| [`ingestion/parsers/bcp.py`](../../ingestion/parsers/bcp.py) | `detect()` checks for BCP's confirmed `$BOP$` byte prefix (T9); `parse()` unlocks with pikepdf, reads words with pdfplumber, and builds a `Statement` |
| [`tests/parsers/test_bcp.py`](../../tests/parsers/test_bcp.py) | Detection, parsing, encrypted PDFs, a broken statement raising `ReconciliationError`, year inference across a new year, and one `real_pdf`-marked test (see below) |

## How the layout is read

Column positions (FECHA/DESCRIPCION/CARGO/ABONO/SALDO) aren't hardcoded to one fixed set of
pixel coordinates. `parse()` finds the row containing all five header words in *this* PDF,
records each one's x-position, then assigns every other row's words to the nearest header to
its left. T10's synthetic fixture and a real BCP statement won't necessarily share exact
positions, but they do share this column order, so deriving the boundaries from the header row
itself should generalize better than one fixture's coordinates would.

**This is still provisional.** It has only been checked against T10's synthetic PDF — not a
real masked layout dump, which the owner hasn't shared yet (see [T10](layout-inspector.md) and
the matching risk in `tasks/plan.md`). The real-PDF test below is designed to catch a mismatch
once that dump exists, without needing this component itself to change first.

## How to use it and how to verify it

```python
from ingestion.parsers import bcp

if bcp.detect(path):
    statement = bcp.parse(
        path, user_id="piero", file_sha256=file_sha256, password=password
    )
```

`uv run pytest` runs the synthetic tests. `uv run pytest -m real_pdf` additionally runs
`test_parses_and_reconciles_a_real_bcp_statement`, which searches
`~/finance-data/{inbox,raw}` for a PDF `detect()` recognizes and skips itself if none is found
or `BCP_PDF_PASSWORD` isn't set — an approved floor-guard exception covers its `pytest.skip()`
calls (see CONSTRAINTS.md), since that heuristic can't tell a legitimate environment-gated skip
from a harmful one. It never asserts or prints an extracted value (ADR 0004).

## Related

- [ADR 0004: Real PDFs](../decisions/0004-real-pdfs-never-leave-your-machine.md) — why the real-PDF test only checks pass/fail.
- [Quality bar](quality-bar.md) — the exceptions process this component uses.
- [Reconciliation](../concepts/reconciliation.md) — `parse()` calls `reconcile()` before returning.
- [Users and accounts](../concepts/users-and-accounts.md) — content over file name.
- [Phase 1](../phases/phase-1.md)
