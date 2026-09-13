---
type: component
phase: 1
status: built
task: T9
---

# Masked layout inspector

Shows where each piece of text sits on a bank statement PDF, with digits shown as `9` and
text as `X`, so parsers and synthetic fixtures can be designed without any personal data
ever leaving your machine.

## Pieces

| Piece | What it does |
|---|---|
| [`scripts/inspect_pdf_layout.py`](../../scripts/inspect_pdf_layout.py) | Opens the PDF with pikepdf (tolerates bytes before `%PDF-`, like BCP's `$BOP$`, and decrypts it), reads words with positions via pdfplumber, groups them into lines and prints each one masked. Never prints the path or the file's metadata |
| `HEADERS` (in the same script) | Short list of generic headers (DATE, CHARGE, BALANCE…) shown as-is; everything else is masked. Never contains proper names |
| [`tests/test_inspect_pdf_layout.py`](../../tests/test_inspect_pdf_layout.py) | Synthetic PDFs built with fpdf2 in `tmp_path`: byte prefix, encryption, an image-only page, and a privacy test |

## How to use it and how to verify it

```bash
uv run --env-file .env scripts/inspect_pdf_layout.py ~/finance-data/raw/<user>/<file>.pdf \
    --password-env BCP_PDF_PASSWORD
```

Output on a synthetic PDF:

```text
Encrypted: yes
Pages: 2
Pages without a text layer (scanned): 2

== Page 1 · 595x842 pt ==
y=103 | x=40-71 DATE | x=150-213 DESCRIPTION | x=380-419 CHARGES | x=520-551 BALANCE
y=118 | x=40-63 99/99 | x=150-189 XXXXXX | x=191-221 XXXXX | x=385-420 9,999.99
```

- `y` is the top edge of the line and `x=start-end` the edges of each word, in points:
  right-aligned amounts share the same `end`.
- The password never goes on the command line: `--password-env` takes the variable's name and
  `uv run --env-file .env` loads it, with no extra dependencies.
- The shape still shows through (word length, punctuation, positions): review the output
  before sharing it.
- Verification: `uv run pytest tests/test_inspect_pdf_layout.py`. Only the owner runs it against
  real PDFs.

## Related

- [ADR 0004: Real PDFs](../decisions/0004-real-pdfs-never-leave-your-machine.md) — the decision this inspector makes possible.
- [Security guards](../components/security-guards.md) — keep a PDF from ever reaching Git.
- [Phase 1](../phases/phase-1.md)
