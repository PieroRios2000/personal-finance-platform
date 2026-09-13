---
type: component
phase: 1
status: built
task: T12, T12b, T14
---

# Dispatcher and CLI

Picks the right bank parser for a PDF by its content, and exposes `pfp parse`, `pfp organize`
and `pfp ingest` so you can run the whole ingestion path from the terminal without writing
Python.

## Pieces

| Piece | What it does |
|---|---|
| [`ingestion/dispatcher.py`](../../ingestion/dispatcher.py) | `detect(path)` tries every registered parser's own `detect()` and returns the first match (a `_Parser` entry: bank name, its PDF-password env var, and its `detect`/`parse` functions), or raises `UnrecognizedBankError`. Adding a bank (T18: Scotiabank) is one more entry in `_PARSERS` |
| [`ingestion/cli.py`](../../ingestion/cli.py) | `pfp parse <pdf> [--user]`: detects the bank, reads its password from the matching env var, parses, and prints a short summary (bank, account, period, transaction count, reconciliation result). `pfp organize [--user] [--inbox-root] [--archive-root]`: files every PDF in the inbox into the standard archive (T12b, see [Inbox organizer](inbox-organizer.md)) and prints its report. `pfp ingest [--user] [--inbox-root] [--archive-root]` (T14): does what `organize` does, then writes every newly archived statement to bronze (see [Lakehouse](lakehouse.md)), skipping any file whose sha256 `lakehouse.bronze.is_ingested()` already knows about, and prints a `Bronze: N written, M already ingested` summary line |
| `[project.scripts]` in `pyproject.toml` | Installs `pfp` as a console command (this is also what made the project a real installable package — see [Python project](python-project.md)) |

## A design note: modules aren't Protocols

`ingestion/parsers/base.py`'s `BankParser` Protocol documents what a parser module must
expose, but mypy doesn't structurally match a plain module against an attribute-based
Protocol (verified directly: assigning an imported module to a `Protocol`-typed variable
fails strict mypy). `dispatcher.py` doesn't fight this — each parser module's `detect`/`parse`
functions get pulled out into a small `_Parser(NamedTuple)` instead, which mypy checks
normally. `base.py`'s Protocol stays as documentation for whoever writes the next parser.

## How to use it and how to verify it

```bash
uv run pfp parse ~/finance-data/inbox/piero/some-statement.pdf --user piero
uv run pfp organize --user piero
uv run pfp ingest --user piero
```

`PFP_USER` is used when `--user` is omitted. `parse` exits non-zero with a message on stderr
if the bank isn't recognized, the password is wrong, or the statement doesn't reconcile
(`ingestion.reconciliation.ReconciliationError`); `organize`/`ingest` exit non-zero the same
way for `MissingAccountKeyError` (ADR 0005's `PFP_ACCOUNT_KEY` unset). Verified against a
synthetic BCP PDF (with the `$BOP$` prefix, so `detect()` recognizes it) under two different
file names: identical output both times. `ingest`'s bronze write was verified directly too:
running it twice against the same PDF content (re-dropped into the inbox after the first
archived copy was removed, so `organize` re-archives it) writes 0 new rows the second time.

## Related

- [BCP parser](bcp-parser.md) — the first entry in the dispatcher's registry.
- [Inbox organizer](inbox-organizer.md) — what `organize`/`ingest` file PDFs into, and its own
  duplicate-detection scope (narrower than bronze's `ingested_files` registry).
- [Lakehouse](lakehouse.md) — what `ingest` writes to.
- [Users and accounts](../concepts/users-and-accounts.md) — content decides the bank, never the file name.
- [Reconciliation](../concepts/reconciliation.md) — what "Reconciliation: OK" actually checked.
- [Phase 1](../phases/phase-1.md)
