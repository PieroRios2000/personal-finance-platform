---
type: decision
phase: 1
status: accepted
date: 2026-09-13
---

# ADR 0012: A second bank without a byte signature, and one PDF producing several statements

## Context

T18 adds a second bank parser, Scotiabank, and two of its real properties don't fit the shape
T11/T12 built for BCP alone:

- BCP's real export carries a cheap, password-free signature to check before ever touching a
  password — a `$BOP$` byte prefix (T9's masked dump confirmed it). A real Scotiabank PDF's raw
  bytes start with a plain `%PDF-`, the same as any other PDF; there is nothing to check without
  opening the file.
- Scotiabank's statement is a credit card, not an account: it carries Soles and Dólares activity
  side by side on the same pages, each with its own opening balance ("Saldo Anterior") and its
  own running total. `Statement` (ADR 0005) holds one `opening_balance`/`closing_balance`, not one
  per currency — a single `Statement` can't represent both currencies at once without either
  merging two independent balances into one meaningless number or silently dropping one currency.

## Decision

- **`ingestion/parsers/base.py`'s `detect` is now optional** (`Callable[[Path], bool] | None`). A
  parser with no cheap signature (Scotiabank) registers with `detect=None` instead of implementing
  a `detect()` that would have to open and decrypt the file just to answer yes/no — no cheaper
  than parsing it outright.
- **`ingestion/dispatcher.py`'s `detect()` runs two passes.** Every parser with a real `detect()`
  is tried first, in registration order, touching neither the file's content nor any password —
  BCP's detection stays exactly as fast and as independent of configuration as before. Only if
  none of them match does a second pass run: each `detect=None` parser is tried by decrypting the
  file with its own `password_env` (`SCOTIABANK_PDF_PASSWORD`), and the first one that opens is
  the match. Detecting **is** decrypting for a bank with no signature — there's no cheaper
  question to ask first.
- **`BankParser.parse()` returns `list[Statement]`, project-wide** — not just for Scotiabank. BCP
  always returns exactly one; Scotiabank returns one per currency that has an opening balance or
  transactions in it (never zero, never both currencies unconditionally). Every caller
  (`ingestion/cli.py`, `ingestion/organizer.py`) loops over the list instead of holding a single
  `Statement`.

## Alternatives considered

- **Add a `Currency` field to `Statement` and let one `Statement` cover both**: rejected. A
  `Statement`'s `opening_balance`/`closing_balance`/reconciliation all assume one ledger; forcing
  two currencies through one would mean either picking a currency to report (silently dropping the
  other) or inventing a combined balance no real statement ever prints — nothing to reconcile
  against.
- **Two separate `Transaction` currencies within one `Statement`, no balance change**: rejected for
  the same reason — `reconcile()` (ADR checked against `opening_balance + sum(transactions) ==
  closing_balance`) becomes meaningless the moment `transactions` mixes two currencies with two
  independent running totals.
- **A slower, content-sniffing `detect()` for Scotiabank that looks for a telltale unencrypted
  string before attempting decryption**: rejected — nothing in the confirmed masked dump is both
  unencrypted and unique to Scotiabank; the file opens encrypted end to end, so the only real
  signature is "opens with this bank's password."
- **Try every registered parser's password against every file, always, and skip BCP's fast
  path entirely**: rejected — would make BCP's detection depend on `BCP_PDF_PASSWORD` being set at
  all, breaking the byte-prefix check's whole point (instant, password-free) and slowing down the
  common case for no benefit.

## Consequences

- A bank in the password-fallback pass is unreachable for detection if its password env var isn't
  set to the right value — the same failure BCP already has one step later, at `parse()` time
  (a wrong `BCP_PDF_PASSWORD` raises there instead); this just moves the same class of failure one
  step earlier for banks with no signature.
- `pikepdf.PasswordError` alone isn't enough to catch in the fallback's decrypt attempt: a
  malformed or non-PDF file raises a sibling `pikepdf.PdfError` instead (checked directly against
  the installed pikepdf — neither is a subclass of the other). `_decrypts()` catches the shared
  `pikepdf.PikepdfError` base so a garbage file falls through to `UnrecognizedBankError` instead of
  crashing detection outright.
- `pfp backfill` (T14c) must replace a multi-statement file's rows without wiping its own earlier
  statement: `bronze.replace_statement()` deletes every row for a `file_sha256` before writing, so
  it's called once for the first statement and the rest are plain `write_statement()` appends onto
  the now-empty slate. `pfp ingest` has no equivalent problem — `write_statement()` only appends
  and registers `ingested_files` once regardless of how many times it's called for the same file
  (T14c).
- `organizer.py`'s archive destination (bank/account/period) is derived from the first statement a
  file produces; every parser reads those three facts once per file and stamps them on every
  `Statement` it emits, so they can never disagree between two statements from the same file. A
  PDF spanning several *accounts* (not just currencies) remains out of `organizer.py`'s reach even
  now — Scotiabank splits by currency, not by account — and is still routed to
  `_needs_review/`, unchanged from ADR 0009.

## Related

- [ADR 0009: Several users and several accounts, read from content, never from the file name](0009-multi-user-multi-account-content-over-filename.md)
- [ADR 0005: `Transaction`/`Statement` schema scoped to a user and an account](0005-transaction-schema-with-user-and-account.md)
- [ADR 0010: Bronze backfill replaces, not versions](0010-bronze-backfill-replaces-not-versions.md) — the
  ordering fix this ADR's `replace_statement`-then-`write_statement` split depends on.
- [BCP parser](../components/bcp-parser.md) — the position/shape-based parsing lesson this ADR's
  parser applies from the start.
- [Scotiabank parser](../components/scotiabank-parser.md)
- [Phase 1](../phases/phase-1.md)
