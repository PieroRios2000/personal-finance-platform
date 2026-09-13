---
type: decision
phase: 1
status: accepted
date: 2026-09-13
---

# ADR 0010: A bronze backfill replaces a file's rows, it doesn't version them

## Context

The BCP parser (T11) needed five separate fixes against Piero's own real statements before
all four of them parsed correctly — a real layout that didn't match the original synthetic
fixture, a description column starting left of its own header, a literal `0.00` beside a real
amount, non-numeric text in an amount cell, and lines grouped across pages instead of within
one ([BCP parser](../components/bcp-parser.md)). Every one was found the same way: run
`pfp ingest`, hit a wrong or crashing result, fix, repeat.

The dangerous half of that loop is the part that *doesn't* crash. A parser bug can produce a
statement that reconciles — the balances add up — while a date, a description or an amount is
quietly wrong. Those rows then sit in bronze forever: `pfp ingest` (T14) only ever looks at
the inbox, and it skips any file whose sha256 is already in `bronze/ingested_files`, so a
fixed parser only ever helps the *next* statement. Nothing re-reads what's already archived.

The archived PDFs themselves are the durable source of truth: `organize()` files every one of
them under `raw/<user>/<bank>/<last4>-<id6>/<start>_<end>.pdf` and never deletes anything
(ADR 0009). So re-deriving bronze from them is always possible. The open question was what to
do with a file's *existing* bronze rows when it gets re-parsed.

## Decision

- **`pfp backfill --user <u> [--archive-root DIR] [--bank B] [--account LAST4] [--dry-run]`**
  (T14c) walks the already-organized archive — never the inbox — re-parses each statement with
  today's parser, and **replaces** that file's rows in bronze: delete, then write. Asked
  directly, Piero chose replace over versioning.
- **Replace means delete + append, scoped to `(user_id, file_sha256)`**:
  `lakehouse.bronze.replace_statement()` deletes from `bronze/transactions`
  (`source_file_sha256`) and `bronze/statements` (`file_sha256`), always narrowed by `user_id`
  as well, then calls the existing `write_statement()`. The same PDF can legitimately belong
  to two users (ADR 0009 files a joint account as one copy per user) and both copies share one
  sha256, so an unscoped delete would take the other user's rows with it.
- **`bronze/ingested_files` is left alone, `ingested_at` included.** The file's bytes haven't
  changed — only this parser's reading of them has — so "this file was first ingested at T"
  stays true, and it's what keeps that registry one row per file. `write_statement()` was
  narrowed to record a file there only when it isn't registered yet, which is exactly what
  every caller already wanted. The replacement `transactions`/`statements` rows *do* carry a
  fresh `ingested_at`: they really were written now, and that's what tells a backfilled row
  from an originally ingested one.
- **A backfill always rewrites, even when nothing changed.** The report says whether the fresh
  parse's dates, descriptions and amounts match what bronze holds (and `--dry-run` stops
  there), but a real run doesn't use that to skip the write. Deciding "identical" would mean
  comparing every column of both tables, and getting that subtly wrong would silently skip the
  very correction the run exists to make — the exact failure mode this feature was built for.
- **`_duplicates/` and `_needs_review/` are excluded**, and the `--bank`/`--account` filters
  match the directory layout `organize()` produced rather than the file's content, so
  narrowing a run never costs a parse. A `_needs_review/` file was never ingested in the first
  place; moving it back to the inbox and re-running `pfp ingest` is what reprocesses it.

## Alternatives considered

- **Version the rows instead of replacing them** — add an `ingestion_run_id` (or a
  `parsed_at`/`valid_from` column) to `transactions`/`statements`, append the new parse
  alongside the old one, and have every reader keep only the latest row per file. Rejected for
  Phase 1: it moves the cost from one CLI command to *every* downstream consumer — the silver
  models (T16), every ad-hoc DuckDB query, every reconciliation — each of which would have to
  remember to deduplicate by latest, and would be silently wrong if it forgot. That's a heavy,
  permanent tax on a single-user tool to preserve a record of a parse we already know to be
  wrong. Worth revisiting if bronze ever gets several writers, or if "what did we think this
  statement said last month" becomes a real question.
- **Delete the file's `ingested_files` row and re-run `pfp ingest`.** Rejected: `ingest` walks
  the inbox, not the archive, so the file would have to be copied back out of `raw/` first,
  re-organized (and re-deduplicated) on the way in, with no `--bank`/`--account` narrowing and
  no dry run — a lot of moving parts around files that are already exactly where they belong.
- **Wipe the user's partition and re-ingest everything.** Simple, but it turns a targeted fix
  into an all-or-nothing operation: one PDF that no longer parses would leave a hole in months
  of otherwise-correct data, and nothing would report it per file.
- **A `replace=True` flag inside `write_statement()`** rather than a separate
  `replace_statement()`. Rejected as the less clear of the two: the only difference between
  ingesting and backfilling is the two deletes in front, and a flag would put a branch in the
  middle of the shared write path that every caller then has to reason about.

## Consequences

- **What a wrong parse used to say is no longer queryable in the current table.** That's the
  trade being made, and it's smaller than it sounds in practice: the archived PDF is untouched
  and is what the rows were derived from, so the current parser's reading can always be
  rebuilt. Delta's own log also softens it — `delete` and `append` create new table versions
  rather than editing files in place, so the previous rows stay readable by time travel
  (`DeltaTable(uri, version=n)`) until a `VACUUM` removes the old files. Verified on a
  synthetic lake while building T14c: after two backfills, versions 0–9 each still read back
  their own row counts.
- **The delete and the write are not atomic, across tables or within one.** delta-rs has no
  cross-table transaction (the same caveat `write_statement()` already documents), so a crash
  between `transactions`'s delete and `statements`'s write — or between a delete and its own
  write — leaves that file with rows missing in bronze. It's recoverable by re-running
  `pfp backfill`: the archived PDF hasn't changed and the command is idempotent by
  construction. It also means the archive, not bronze, is what must never be lost.
- **Bronze is no longer strictly append-only.** `replace_statement()` is the only writer that
  deletes, and it deletes exactly one file's rows for one user; `pfp ingest`'s path is
  unchanged. Anything downstream that assumed rows never disappear (nothing does today) would
  need to know.
- **A file that isn't in the archive any more can't be backfilled.** Deleting a PDF out of
  `raw/` after ingesting it leaves its bronze rows with nothing left to re-derive them from.
- **One file that fails to re-parse never stops the run.** Each failure is reported by sha256
  prefix with a plain-language reason and its bronze rows are left untouched, so a partially
  fixed parser still corrects everything it can read today.

## Related

- [ADR 0009: Several users, several accounts, content over filename](0009-multi-user-multi-account-content-over-filename.md) —
  the archive layout the walk and the `--bank`/`--account` filters rely on, and the
  one-copy-per-user rule that forces the delete to be scoped by `user_id`.
- [ADR 0006: Lake location by URI](0006-lake-location-by-uri.md) — the bronze tables being
  replaced here.
- [Lakehouse](../components/lakehouse.md) — `replace_statement()`/`transactions_for_file()`.
- [Dispatcher and CLI](../components/cli.md) — `pfp backfill` itself.
- [BCP parser](../components/bcp-parser.md) — the five real fixes that made this necessary.
- [Idempotency](../concepts/idempotency.md)
- [Phase 1](../phases/phase-1.md)
