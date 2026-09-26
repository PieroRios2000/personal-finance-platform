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

## Related

[ADR 0004](0004-real-pdfs-never-leave-your-machine.md),
[ADR 0009](0009-multi-user-multi-account-content-over-filename.md),
[ADR 0036](0036-row-level-security-by-ingesting-user.md),
[ADR 0039](0039-all-dex-accounts-are-dynamic.md).
