---
type: decision
phase: 5
status: accepted
date: 2026-09-26
---

# ADR 0040: an upload portal that unlocks at upload; the owner processes

## Context

Once other people can sign in (ADR 0034-0039) they see an empty dashboard: their
statements can only be loaded by the owner, from the owner's machine. Phase 5 planned an
uploader. Four things were open (backlog, 2026-09-26) and the owner decided them.

## Decision

- **A signed-in portal** (`upload/`, its own Dex client `portal`, its own hostname) where a
  person sends bank statements (PDF). It runs in the stack behind the `bi` profile.
- **The destination is the account's `user_id`, never a form field**: looked up in Dex on
  every request. An account nobody scoped yet (username = its email, ADR 0036) is given
  `<name>-<4 hex>` the first time it uploads, set as its Dex username over the gRPC API
  (Superset renames the user at next login, ADR 0036 fix): no operator step. The owner's
  own account keeps `piero` with `make dex-scope` (ADR 0039).
- **The PDF password is typed per upload, used once, never stored**: the portal opens the
  file with it and saves an *unlocked* copy in `inbox/<user_id>/` (`ingestion.unlock`).
  The pipeline, run later by the owner, then needs no password of that person.
- **The chosen bank is a hint written into the file's metadata.** Unlocking drops BCP's
  `$BOP$` prefix, and the Scotiabank password fallback would claim any unlocked PDF, so
  the dispatcher reads the hint between its two passes. The parser it names must still
  parse and reconcile the file, or it goes to `_needs_review` (ADR 0009: content decides).
- **Any registered account may upload**, under a notice that the files stay on the
  owner's machine and the owner can open them. Limits: 15 MB a file, 12 files a time, 40 a
  hour per person, only banks the parsers know, a CSRF token on the form.
- **The owner triggers processing**: `make ingest-uploads` (one `pfp ingest` per inbox
  folder) then `make build`. Nothing public runs the pipeline.
- **v1 is the bank-statement section.** Sections by file type (card balance, the manual
  Excel for savings and investments) follow; the Excel needs its per-user layout decided.

## Amendment (2026-09-27): what kind of file, and other banks

The form asks two more things, at the owner's request: **what the file is** (a bank account
statement or a credit card statement) and **the bank**, with an "Other bank" option and a name
field. Only the pairs a parser reads today go to the pipeline: BCP account statements, and
Scotiabank's card and account statements (one parser). **Anything else, another bank or BCP's
credit card, is not fed to the pipeline**: it is unlocked like the rest and kept in
`inbox/<user_id>/_new_bank/`, which `pfp organize` never looks in, tagged with the bank and kind
the person said (`/PFPBank`, `/PFPKind`). The person is told plainly that it is not read yet.
`make review-uploads` lists what waits, by bank and kind with counts of files and people, never
a file name or a page. Each new bank or kind is then **its own isolated request**: the owner
looks at a masked sample of the layout (ADR 0004, the layout inspector) and decides how to write
the extraction, as was done for BCP and Scotiabank.

The form also asks **the currency**: soles, dollars, **both** (a card statement usually carries both
at once, as Scotiabank's does) or **another currency**, named. Soles, dollars and both are what the
pipeline reads; another currency is its own request, so a file in one goes to `_new_bank/` even for
a supported bank and kind. It is written into the file as `/PFPCurrency`, and `make review-uploads`
groups by bank, kind and currency. As with the bank, it is a hint: the parsers read the currency
from the content.

**The owner is told when a file is kept for review**: an email over the alerting's channel (Phase 7,
the same `ALERT_SMTP_*` and `ALERT_EMAIL_TO`; nothing is sent while `ALERT_EMAIL_TO` is unset). It is
immediate, not the weekly digest of ADR 0026, because a person is waiting on an answer, and it says
only bank, kind, currency and how many (never a file name, a person or a page, ADR 0004). It is sent
from a thread, at most 6 an hour whatever people upload; the rest stay listed by `make review-uploads`.

**Amended by [ADR 0041](0041-uploads-are-requests-accepted-or-rejected-whole.md)**: an upload is a request of up to
10 files, accepted or rejected whole, kept in `_submissions/`, and the sender is emailed at each step.

## Alternatives considered

- **Store passwords (encrypted)**: convenient, but holds other people's bank secrets.
- **Process at upload**: puts the whole pipeline behind a public endpoint.
- **A path/`user_id` chosen by the person**: would let anyone write into another's folder.
- **Reject protected PDFs**: most real statements are protected.

## Consequences

- ADR 0004 said real PDFs never leave the owner's machine; here other people's do arrive
  on it. That is the point, and why the notice exists and the owner is the only reader.
- A file someone uploaded is readable by the owner's own user (mode 600) only.
- Unlocked PDFs sit unprotected in the inbox: as safe as the owner's disk already is.
- Verified with synthetic PDFs (an encrypted BCP one, uploaded and processed with none of
  the owner's passwords); real statements need the owner's own check.

- **CI keeps it from breaking**: a `portal-e2e` job (and its gate, ADR 0019) brings the
  real services up and runs the whole path (sign up, sign in, upload, pipeline) on every
  change to the portal's paths. The `portal-e2e-gate` check has to be added to the
  ruleset's required checks by the owner (GitHub setting, not code).

## Related

[ADR 0004](0004-real-pdfs-never-leave-your-machine.md),
[ADR 0009](0009-multi-user-multi-account-content-over-filename.md),
[ADR 0036](0036-row-level-security-by-ingesting-user.md),
[ADR 0039](0039-all-dex-accounts-are-dynamic.md).
