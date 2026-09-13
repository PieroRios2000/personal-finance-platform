---
type: component
phase: 1
status: built
task: T12, T12b, T14, T14c
---

# Dispatcher and CLI

Picks the right bank parser for a PDF by its content, and exposes `pfp parse`, `pfp organize`,
`pfp ingest` and `pfp backfill` so you can run the whole ingestion path from the terminal
without writing Python.

## Pieces

| Piece | What it does |
|---|---|
| [`ingestion/dispatcher.py`](../../ingestion/dispatcher.py) | `detect(path)` tries every registered parser's own `detect()` and returns the first match (a `_Parser` entry: bank name, its PDF-password env var, and its `detect`/`parse` functions), or raises `UnrecognizedBankError`. Adding a bank (T18: Scotiabank) is one more entry in `_PARSERS` |
| [`ingestion/cli.py`](../../ingestion/cli.py) | `pfp parse <pdf> [--user]`: detects the bank, reads its password from the matching env var, parses, and prints a short summary (bank, account, period, transaction count, reconciliation result). `pfp organize [--user] [--inbox-root] [--archive-root]`: files every PDF in the inbox into the standard archive (T12b, see [Inbox organizer](inbox-organizer.md)) and prints its report. `pfp ingest [--user] [--inbox-root] [--archive-root]` (T14): does what `organize` does, then writes every newly archived statement to bronze (see [Lakehouse](lakehouse.md)), skipping any file whose sha256 `lakehouse.bronze.is_ingested()` already knows about, and prints a `Bronze: N written, M already ingested` summary line. `pfp backfill [--user] [--archive-root] [--bank B] [--account LAST4] [--dry-run]` (T14c): re-parses statements already in the archive and replaces their bronze rows (see below) |
| `[project.scripts]` in `pyproject.toml` | Installs `pfp` as a console command (this is also what made the project a real installable package — see [Python project](python-project.md)) |

## `pfp backfill`: making a parser fix reach data already in bronze (T14c)

`pfp ingest` only ever looks at the inbox, and skips any file whose sha256 is already in
`bronze/ingested_files` — so fixing a parser bug helps the *next* statement and does nothing
for the ones already ingested, including the ones a buggy parse got subtly wrong while still
reconciling. `backfill` closes that: it walks
`<archive-root>/<user>/**/*.pdf` — what [`organize()`](inbox-organizer.md) already filed, never
the inbox — re-parses each statement with today's parser, and replaces that file's rows in
bronze ([`replace_statement()`](lakehouse.md), [ADR 0010](../decisions/0010-bronze-backfill-replaces-not-versions.md)).

- **`_duplicates/` and `_needs_review/` are skipped.** Neither holds an archived statement; a
  `_needs_review/` file was never ingested in the first place, and the way to retry one is to
  move it back to the inbox and re-run `pfp ingest`.
- **`--bank`/`--account` match the directory layout** `<bank>/<last4>-<id6>/` that `organize()`
  produced (`--bank` case-insensitively), so narrowing a run never costs a parse.
- **`--dry-run` writes nothing** and reports, per file, how many transactions bronze holds
  versus how many the fresh parse produces, plus whether their dates, descriptions and amounts
  match. A real run always rewrites — see ADR 0010 for why it doesn't try to skip "unchanged"
  files.
- **One bad file never aborts the run.** An unrecognized bank, a wrong/missing password, a
  reconciliation failure or a malformed statement is reported by sha256 prefix with a
  plain-language reason, and that file's bronze rows are left untouched — the same error
  handling shape `organize()` uses, and the same standard as the BCP parser's crash-safety fix.
  A missing `PFP_ACCOUNT_KEY` is the one thing that stops the run: every file would fail the
  same way.
- **The report follows `OrganizeReport.render()`'s privacy rule**: counts, dates, sha256
  prefixes and a bank plus last 4 digits, never a description, an amount or a full account
  number (ADR 0004), and never a file's name on disk.

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
uv run pfp backfill --user piero --dry-run        # what would change, writes nothing
uv run pfp backfill --user piero --bank BCP       # re-parse and replace, one bank
```

`PFP_USER` is used when `--user` is omitted. `parse` exits non-zero with a message on stderr
if the bank isn't recognized, the password is wrong, or the statement doesn't reconcile
(`ingestion.reconciliation.ReconciliationError`); `organize`/`ingest` exit non-zero the same
way for `MissingAccountKeyError` (ADR 0005's `PFP_ACCOUNT_KEY` unset), as does `backfill`
(which also exits non-zero on a missing `LAKEHOUSE_URI`, before it reads a single PDF).
Verified against a
synthetic BCP PDF (with the `$BOP$` prefix, so `detect()` recognizes it) under two different
file names: identical output both times. `ingest`'s bronze write was verified directly too:
running it twice against the same PDF content (re-dropped into the inbox after the first
archived copy was removed, so `organize` re-archives it) writes 0 new rows the second time.

`backfill` was verified the same way, on a throwaway lake and archive built from two synthetic
statements for two different accounts: `pfp ingest` first (2 statements written, 8 transaction
rows), then `pfp backfill --dry-run` (`Scanned: 2  Would replace: 2`, nothing written), then a
real run and a `--account`-filtered run — after all of them, still 8 transaction rows, 2
statement rows and 2 `ingested_files` rows, i.e. replaced rather than appended.

**Known, pre-existing:** on this machine a `pfp` run that reads a bronze table can print
`terminate called without an active exception` and exit 134 *after* its report — a
`deltalake==1.6.3` abort during interpreter shutdown, reproducible with the library alone and
unrelated to the CLI (`pfp ingest` does it too, and `pytest` doesn't). See SETUP.md's known
issues.

## Related

- [BCP parser](bcp-parser.md) — the first entry in the dispatcher's registry.
- [Inbox organizer](inbox-organizer.md) — what `organize`/`ingest` file PDFs into, and its own
  duplicate-detection scope (narrower than bronze's `ingested_files` registry).
- [Lakehouse](lakehouse.md) — what `ingest` writes to and what `backfill` replaces in.
- [ADR 0010: A backfill replaces a file's rows](../decisions/0010-bronze-backfill-replaces-not-versions.md) —
  the decision `pfp backfill` implements.
- [Users and accounts](../concepts/users-and-accounts.md) — content decides the bank, never the file name.
- [Reconciliation](../concepts/reconciliation.md) — what "Reconciliation: OK" actually checked.
- [Phase 1](../phases/phase-1.md)
