---
type: decision
phase: 5
status: accepted
date: 2026-09-27
---

# ADR 0041: an upload is a request, accepted or rejected whole, and the sender is told

## Context

[ADR 0040](0040-upload-portal-unlocks-at-upload-and-owner-processes.md) let people send PDFs and
the owner process them. Three things were missing, asked by the owner: sending several months in
one go (up to 10 files), rejecting the whole request when one file is wrong rather than loading
part of it, and telling the sender what happened to their files.

## Decision

- **A request holds up to 10 PDFs**, all of one kind, bank and currency, with one password.
- **All or nothing, twice.** When it arrives, every file is unlocked and checked (password, a
  real PDF, at most 60 pages, cleaned of scripts); if any fails, **nothing is stored** and the
  person is told which file numbers failed and why. Later, when the owner processes it, every
  file is read by its parser and must **reconcile and match** the kind (account is an asset,
  card a liability) and the currency the person said (soles, dollars, both); if any fails, the
  **whole request is rejected** and nothing loads.
- **A request is a folder** (`inbox/<user_id>/_submissions/<id>/`: the unlocked files and a
  `submission.json`, `ingestion/submissions.py`), never seen by the pipeline until accepted.
  Statuses: `received` (waiting for `make ingest-uploads`), `review` (a bank, kind or currency no
  parser reads; waits for the owner), `accepted`, `rejected`. `make decide-submission` lets the
  owner `reject` a `review` one or `release` it once support exists.
- **The sender gets an email at each step**: received (portal), then accepted (how many statements
  loaded, how many duplicates ignored) or rejected (which file numbers and how), sent by
  `scripts/process_submissions.py` over the alerting's SMTP. Counts and file numbers only, never
  a file name, an amount or a page (ADR 0004). Nothing is sent without SMTP; it says so.
- **Duplicates are not failures**: the pipeline already ignores a file it has (ADR 0024) and the
  email says how many. Files that do not parse, do not reconcile or are not what was said go to
  rejection; the organizer's `_needs_review` and `_duplicates` folders remain for the pipeline.
- **A hostile PDF is defused, not trusted**: scripts, launch actions, embedded files and XFA are
  removed at upload; a fillable form dressed as a statement has no page text to read and is
  rejected. A forged statement whose numbers reconcile cannot be told from a real one by any
  parser: that limit is the reason the owner still sees what is loaded.

## Amendment: the savings and investments workbook (T49)

The portal has a second section, **savings and investments (Excel)**, on the same request model:
the person downloads a **generic template** (`ingestion/manual_layout.py`: the owner's template
with funds and accounts in free text instead of a Tyba/Flip drop-down), fills at least one sheet
(the other may keep only its headers) and sends **one workbook**. On arrival only its *structure*
is checked, with no secret: at most 5 MB, a real `.xlsx` that does not unpack to more than 50 MB
(a zip bomb), no macros, the right sheets and columns, no leftover `EJEMPLO` rows, at most 20,000
rows, not both sheets empty. Any problem keeps nothing. The *content* (each row, balances that
follow from the previous one) is read later by `make ingest-uploads` with the owner's account key,
which the portal container must not hold: if any problem is found the **whole workbook is
rejected** and the sender is told the row numbers and column names (never a value); otherwise
`pfp import-manual` loads it and they get an accepted email. A new workbook replaces the months
it contains. To let an investments-only person leave the savings sheet with headers, the importer
now accepts an empty savings sheet when the investments sheet has data.

## Consequences

- `make ingest-uploads` now decides requests (and emails) instead of looping over folders; the
  `_new_bank/` folder of ADR 0040's first version is replaced by `review` requests.
- The person learns the result of a file's content only after the owner runs the command (the
  portal container has no account key and never parses).
- One more thing the owner runs by hand; a schedule (cron) is possible later.

## Related

[ADR 0040](0040-upload-portal-unlocks-at-upload-and-owner-processes.md),
[ADR 0024](0024-regenerated-pdfs-with-identical-content-are-duplicates.md),
[ADR 0026](0026-alerts-errors-now-warnings-weekly-names-and-counts-only.md),
[ADR 0004](0004-real-pdfs-never-leave-your-machine.md).
