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
- A row's description *data* can start to the left of where the "DESCRIPCION" *header* word
  itself is drawn (58pt left of it, in a second real dump) — closer to the FECHA (value date)
  header than its own. Words landing in the FECHA cell that aren't the date itself (the date
  is always the leftmost one) get moved to the front of the real description instead of
  wrecking that row's date.
- A cell can print a literal "0.00" — alone (an informational row) or beside the real amount
  in the other column (which used to look like "both a charge and a credit" even though only
  one side is a real movement). Treated as absent, same as an empty cell, since it has no
  monetary effect either way.
- Whatever lands in CARGO/ABONO isn't guaranteed to be a clean amount at all; a fourth real
  statement had non-numeric text bleed in there and crashed the whole process with a raw
  `decimal.InvalidOperation`. Validated against the amount shape before `_money()` ever sees
  it; a mismatch is now a normal, row-scoped `ValueError` (never the raw cell text itself,
  which could hold leaked real content) instead of an unhandled crash.
- **Multi-page statements**: a real BCP page repeats the same header row and account/period
  boilerplate at the *same* y-position on every page. Lines are grouped *within each page*
  separately, not across the whole flattened document — otherwise an unrelated row on a later
  page at that same y silently merges into the current one, corrupting both. This was the
  final piece: it's the normal case for any multi-page statement, not a rare edge case.

`tests/fixtures/synthetic_pdfs.py`'s `bcp_real_layout_statement_pdf()` renders every one of
these traits (additive next to the original fixture, which dozens of other tests still use
unchanged), plus a dedicated hand-built multi-page test for the last one. The closing-balance
search is the one piece still built on a best-evidenced heuristic rather than a certainty —
see the module docstring in `ingestion/parsers/bcp.py`; `reconcile()` is the backstop if it
ever picks the wrong amount, failing loudly as a `ReconciliationError` instead of silently
accepting a wrong balance.

**Verified end to end against all four of Piero's real BCP statements** (2026-09): every one
now archives and reconciles, three months (2025-09 to 2025-11) with no gaps. Each of the five
fixes above was found by iterating — Piero ran `pfp ingest`, hit a real error, ran T9's masked
inspector on the specific failing file when a new masked dump was needed, and I calibrated the
next fix against it — never by guessing ahead of what the data actually showed.

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

## Account kind (T18a)

Every `Statement` this parser builds gets `account_kind="asset"`: a BCP checking account's
balance is money on hand, never debt owed. Hardcoded here, not read from the PDF — see
[ADR 0015](../decisions/0015-account-kind-asset-or-liability.md) for why, and for how it
reaches `silver.transactions` for T18b's transfer matching.

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

- [ADR 0015: Account kind (asset/liability)](../decisions/0015-account-kind-asset-or-liability.md) — why this parser hardcodes `account_kind="asset"`.
- [ADR 0004: Real PDFs](../decisions/0004-real-pdfs-never-leave-your-machine.md) — why the real-PDF test only checks pass/fail.
- [Quality bar](quality-bar.md) — the exceptions process this component uses.
- [Reconciliation](../concepts/reconciliation.md) — `parse()` calls `reconcile()` before returning.
- [Users and accounts](../concepts/users-and-accounts.md) — content over file name.
- [Phase 1](../phases/phase-1.md)
