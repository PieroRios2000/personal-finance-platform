---
type: decision
phase: 1
status: accepted
date: 2026-09-12
---

# ADR 0009: Several users and several accounts, read from content, never from the file name

## Context

This install isn't just Piero's: more than one person can drop statements into it, and each
person can hold several accounts, even at the same bank. A PDF's own file name (however it
arrived — a browser download, an email attachment, a manual rename) can't be trusted to carry
that information: naming conventions vary by source, nothing enforces one, and — worse — a file
name can itself contain the real account number, which would leak exactly what ADR 0005's
`account_id` design exists to avoid.

## Decision

- **`user_id` comes only from the ingestion context** — `pfp ingest --user <id>`, defaulting to
  the `PFP_USER` environment variable (T6) when `--user` isn't passed — never parsed from the
  PDF or inferred from a file name.
- **Bank, account and period are always read from the PDF's content** by the parser (T11,
  T18), never from the file name. The file itself is recognized by its sha256 (T7); its name is
  never stored anywhere in the schema or the lake.
- **Per-user inbox and archive** (T12b): PDFs land in `~/finance-data/inbox/<user>/` under any
  name; once processed they're filed into
  `~/finance-data/raw/<user>/<bank>/<last4>-<id6>/<start>_<end>.pdf`, where `id6` is the first 6
  characters of `account_id` — two accounts sharing the same last 4 digits still land in
  different folders. A repeat is filed under `_duplicates/`; anything the dispatcher can't
  place goes to `_needs_review/` with a report of why. A file is never deleted.
- **The lake is partitioned by `user_id`** (T14): dropping someone's data is dropping their
  partition, nothing more surgical is needed.

## Alternatives considered

- **Read the account holder's name off the statement to identify the user**: fragile across
  banks and languages, and it's exactly the kind of personal data ADR 0004 keeps out of every
  log, fixture and generated artifact — using it for control flow would mean handling it more,
  not less.
- **Infer bank/account/period from the file name**: rejected. Besides being unreliable (three
  different naming conventions across browser, email and manual saves), `tasks/plan.md`'s risk
  log already flags that a file name can contain the real account number — using it as a signal
  would mean reading and likely logging that number.
- **One shared inbox for every user**: a dropped PDF would have no reliable owner besides
  content the code deliberately avoids parsing for identity; a per-user inbox makes ownership
  explicit at drop time instead.

## Consequences

- The dispatcher (T12) must fully parse a PDF — bank, account, period — before it knows where
  it belongs; an unrecognized or corrupted PDF has no account yet, so it's routed to
  `_needs_review/` instead of a partition.
- A joint account (the same real account held by two `user_id`s) is out of scope for Phase 1: it
  would land as two independent copies, one per user. Left as an open question in
  [Users and accounts](../concepts/users-and-accounts.md), revisited only if the case comes up.
- Losing `PFP_ACCOUNT_KEY` (ADR 0005) invalidates every `account_id` across every user at once,
  not just one — the backup requirement in `SETUP.md` matters more, not less, with several
  users on one install.
- A PDF that covers several accounts (seen on some real statements) still produces one
  `Statement` per account; the file itself is saved once, under `<bank>/_multi-account/` — noted
  here since it follows directly from "content, not the file name" driving the split.

## Related

- [ADR 0005: `Transaction`/`Statement` schema scoped to a user and an account](0005-transaction-schema-with-user-and-account.md)
- [ADR 0004: Real PDFs never leave your machine](0004-real-pdfs-never-leave-your-machine.md)
- [Users and accounts](../concepts/users-and-accounts.md)
- [Reconciliation](../concepts/reconciliation.md) — inter-account reconciliation depends on every
  movement being attributed to the right user and account.
- [Phase 1](../phases/phase-1.md)
