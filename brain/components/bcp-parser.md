---
type: component
phase: 1
status: built
task: T11, fix/bcp-parser-real-layout
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

Column positions (FECHA/DESCRIPCION/CARGO(S)/ABONO(S), and SALDO when present) aren't
hardcoded to one fixed set of pixel coordinates. `parse()` finds the row containing the
header words in *this* PDF, records each one's x-position, then assigns every other row's
words to the nearest header to its left.

**Calibrated against a real masked layout dump** (T9's inspector, 2026-09 — Piero's own real
BCP statement was landing in `_needs_review/` until this). The real layout turned out to
differ from T10's original synthetic fixture in several ways, all handled by one
implementation rather than a special case per format:

- No "CUENTA NRO." or "PERIODO" labels at all. The account number is found by its own shape
  (dash-grouped digits with a long middle group) wherever it appears on the page; the period
  is a line with "DEL \<date\> AL \<date\>", no leading label required.
- A 2-digit year in the period (`_parse_date` accepts both 2 and 4).
- The header row has FECHA *twice* (processing date, then value date, ~46pt apart) and
  CARGOS/ABONOS (plural) with no SALDO column in the table at all. Only the later FECHA
  occurrence becomes the "FECHA" column `parse()` reads; earlier ones are given a throwaway
  column so their words don't bleed into it.
- Each row's own date is "DDMMM" (day + 3-letter Spanish month abbreviation, e.g. "05ENE"),
  alongside the original "DD/MM".
- The closing balance is a bare "SALDO" (no "ACTUAL"/"FINAL" qualifier), and its amount sits
  on a *neighboring* line rather than beside it — found by scanning bottom-up for the last
  "SALDO" mention on the page (protecting against a transaction description that happens to
  contain the word "SALDO"), checking the closest lines above and below for an amount.

`tests/fixtures/synthetic_pdfs.py`'s `bcp_real_layout_statement_pdf()` renders every one of
these traits (additive next to the original fixture, which dozens of other tests still use
unchanged). The closing-balance search is the one piece built on a best-evidenced heuristic
rather than a certainty — see the module docstring in `ingestion/parsers/bcp.py`;
`reconcile()` is the actual backstop if it ever picks the wrong amount, failing loudly as a
`ReconciliationError` instead of silently accepting a wrong balance.

**Not yet verified end-to-end against Piero's own real PDF** (ADR 0004 — nobody, including
Claude, opens it directly): the fix was built and tested entirely against the masked dump and
the new synthetic fixture. The next step is running `pfp ingest` against the real file again.

## OCR fallback for scanned pages (T11b)

Some BCP statement pages are scanned images with no text layer (T9 found at least one in the
owner's real PDFs). `parse()` reads each page's words with `page.extract_words() or
ocr.extract_words(page)`: if pdfplumber's own extraction comes back empty, [`ingestion/ocr.py`](../../ingestion/ocr.py)
renders that one page at 300 dpi (`page.to_image()`, a pdfplumber built-in) and reads it with
Tesseract in Spanish (`pytesseract.image_to_data`), returning words shaped exactly like
`extract_words()`'s own output (`text`, `x0`, `x1`, `top`, `bottom`). Line-grouping and
column-assignment downstream don't know or care where a word came from.

The one design point worth remembering: Tesseract's positions are in pixels, but
`extract_words()`'s (and this parser's column logic's) are in PDF points. `ocr.py` divides
every pixel position by `page.to_image()`'s own `.scale` (pixels-per-point, close to but not
exactly 300/72 — the render rounds to a whole pixel count) rather than assuming the nominal
ratio, so OCR'd words land in the exact same point-space the vector-text path already uses.
Getting this wrong would silently misplace every OCR'd word into the wrong column.

Reconciliation is OCR's safety net for free: `parse()` already calls `reconcile()` before
returning, so a misread digit from OCR makes the statement fail to balance, raising
`ReconciliationError`, with no extra code needed.
`tests/test_ocr.py` covers the position math (a known-drawn word ends up within a few points of
where it was drawn) and both ends of the fallback through `bcp.parse()`: a statement whose
transaction table lives only on a scanned page reconciles correctly, and one with a garbled
amount on that scanned page raises `ReconciliationError` instead of being silently accepted.

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
