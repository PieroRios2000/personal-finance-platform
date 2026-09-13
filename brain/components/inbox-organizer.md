---
type: component
phase: 1
status: built
task: T12b
---

# Inbox organizer

Files a folder of PDFs dropped under any name into the standardized per-user archive
(ADR 0009), so `~/finance-data/inbox/<user>/` can be a messy drop zone (browser downloads,
email attachments, manual saves) while `~/finance-data/raw/<user>/` stays predictable.

## Pieces

| Piece | What it does |
|---|---|
| [`ingestion/organizer.py`](../../ingestion/organizer.py) | `organize(user_id, *, inbox_root, archive_root) -> OrganizeReport`: walks the inbox, hashes and dispatches each PDF, and moves it to its standard place |
| [`ingestion/cli.py`](../../ingestion/cli.py) | `pfp organize --user <u> [--inbox-root DIR] [--archive-root DIR]` prints `OrganizeReport.render()` |

## What happens to each PDF

1. Hash it (T7's `file_sha256`).
2. **A repeat within this run** (same hash seen earlier in this pass) → `_duplicates/`.
3. Detect the bank ([dispatcher](cli.md), T12) and parse it, reusing the matching parser's
   `password_env` the same way `pfp parse` already does.
4. On success: move to `<bank>/<last4>-<id6>/<start>_<end>.pdf`.
   - If that path is already taken by a file with a **different** hash, it's a regenerated
     statement: filed as `..._v2.pdf` (climbing to `_v3`, etc. if those exist too).
   - If it's already taken by a file with the **same** hash, it's a duplicate that showed up
     in a later run (see below) → `_duplicates/`.
5. Anything that fails to parse — `UnrecognizedBankError`, a wrong/missing password
   (`pikepdf.PasswordError`), a reconciliation failure, or a malformed statement (`ValueError`)
   — goes to `_needs_review/` with a plain-language reason, never a raw traceback.
6. Nothing is ever deleted; a file that can't be filed is moved aside, never left in the inbox
   *and* copied elsewhere.

## Duplicate detection is intentionally partial

There's no persistent "already ingested" registry yet — that's T14's bronze writer, which will
track every file's hash against what's already in the lake. Until then `organize()` only
catches two kinds of duplicate, both without a database:

1. Two files in the **same inbox pass** with identical bytes (an in-memory set of hashes seen
   so far in this run).
2. A file whose content exactly matches what's **already sitting in the archive** at its own
   account/period destination — found by hashing the one file already there, not by a general
   index. This is the flip side of the "regenerated statement" check: same destination, same
   hash means duplicate; same destination, different hash means a new version.

A duplicate that shows up in a **later, separate** run with no earlier match in that run's
inbox and nothing yet archived at that destination (e.g. both copies land in separate inbox
passes before either is processed) is **not** caught — T14 closes that gap with a real registry.

## Multi-account PDFs aren't wired up

ADR 0009 calls out a statement PDF that covers more than one account, filed under
`<bank>/_multi-account/`. That path doesn't exist in this code: today's
[`ingestion.parsers.bcp.parse()`](bcp-parser.md) (T11) returns exactly one `Statement` per
call — its account regex `.search()`es for the *first* "CUENTA NRO." match and has no way to
report "there was a second one". Adding a `_multi-account/` branch now would be a dead branch
this parser can never exercise, not a real placeholder. It becomes reachable once a parser can
either return several statements for one PDF or at least flag "more than one account found".

## The report never prints a raw inbox filename

A file's original name can itself carry the real account number (ADR 0009's whole reason for
reading content, never file names). `OrganizeReport.render()` follows the same rule for its own
output: archived items are shown by their *new* name (derived from the period, never sensitive),
but duplicates and needs-review items are referenced only by a short sha256 prefix plus a
plain-language reason — never the name they arrived under. The files themselves keep their
original name on disk under `_duplicates/`/`_needs_review/` (useful for Piero browsing his own
machine), with a numeric suffix added only if that name is already taken there.

## Per-account coverage and gaps

The report's last section lists, per (bank, last 4), how many periods are archived, the earliest
to latest span, and which calendar months look missing in between — read back from the filenames
already in that account's folder (there's no separate index), assuming one statement covers one
calendar month.

## How to use it and how to verify it

```bash
uv run pfp organize --user piero
# or, to point at a non-default location:
uv run pfp organize --user piero --inbox-root /some/inbox --archive-root /some/raw
```

`--inbox-root`/`--archive-root` default to `~/finance-data/inbox`/`~/finance-data/raw`
(`organizer.DEFAULT_INBOX_ROOT`/`DEFAULT_ARCHIVE_ROOT`) but are always overridable, which is
also what makes `organize()` testable against `tmp_path` with no real files involved.

Verified with synthetic BCP PDFs (`tests/fixtures/synthetic_pdfs.py`, extended with an
`account_number` parameter for this task): three statements from three different accounts land
in three different folders, an identical-bytes repeat lands in `_duplicates/`, and an unreadable
one lands in `_needs_review/`. `ingestion/organizer.py` is at 100% line coverage
(`uv run pytest --cov`); see `tests/test_organizer.py`.

## Related

- [Dispatcher and CLI](cli.md) — `organize` reuses `dispatcher.detect()` exactly like `parse` does.
- [BCP parser](bcp-parser.md) — why multi-account detection isn't reachable yet.
- [Users and accounts](../concepts/users-and-accounts.md) — the archive layout this component builds.
- [ADR 0009](../decisions/0009-multi-user-multi-account-content-over-filename.md) — the decision this component implements.
- [Phase 1](../phases/phase-1.md)
