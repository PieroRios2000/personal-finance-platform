---
type: component
phase: 1
status: built
task: T12
---

# Dispatcher and CLI

Picks the right bank parser for a PDF by its content, and exposes `pfp parse` so you can run
one from the terminal without writing Python.

## Pieces

| Piece | What it does |
|---|---|
| [`ingestion/dispatcher.py`](../../ingestion/dispatcher.py) | `detect(path)` tries every registered parser's own `detect()` and returns the first match (a `_Parser` entry: bank name, its PDF-password env var, and its `detect`/`parse` functions), or raises `UnrecognizedBankError`. Adding a bank (T18: Scotiabank) is one more entry in `_PARSERS` |
| [`ingestion/cli.py`](../../ingestion/cli.py) | `pfp parse <pdf> [--user]`: detects the bank, reads its password from the matching env var, parses, and prints a short summary (bank, account, period, transaction count, reconciliation result) |
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
```

`PFP_USER` is used when `--user` is omitted. Exits non-zero with a message on stderr if the
bank isn't recognized, the password is wrong, or the statement doesn't reconcile
(`ingestion.reconciliation.ReconciliationError`). Verified against a synthetic BCP PDF (with
the `$BOP$` prefix, so `detect()` recognizes it) under two different file names: identical
output both times.

## Related

- [BCP parser](bcp-parser.md) — the first entry in the dispatcher's registry.
- [Users and accounts](../concepts/users-and-accounts.md) — content decides the bank, never the file name.
- [Reconciliation](../concepts/reconciliation.md) — what "Reconciliation: OK" actually checked.
- [Phase 1](../phases/phase-1.md)
