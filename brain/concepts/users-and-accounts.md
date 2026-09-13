---
type: concept
phase: 1
---

# Users and accounts

Every movement belongs to a user and an account. One install serves several people, and each
one can hold several accounts, even at the same bank.

## How it applies here

- **User (`user_id`)**: comes from the ingestion context (`pfp ingest --user`, defaulting to
  `PFP_USER`), never from the PDF. The lake is partitioned by `user_id`, so deleting someone's
  data means dropping their partition.
- **Inbox and archive (T12b)**: PDFs are dropped with any name into
  `~/finance-data/inbox/<user>/` and get filed into
  `raw/<user>/<bank>/<last4>-<id6>/<start>_<end>.pdf`. Three `EECC.pdf` files from different
  accounts end up in three folders; a repeat goes to `_duplicates/`; an unreadable one goes to
  `_needs_review/`, with a report. A file is never deleted.
- **Account (`account_id`)**: HMAC-SHA256 of the bank and the full number, with the
  `PFP_ACCOUNT_KEY` secret from `.env`. It's unique per account and reveals nothing about the
  number; the last 4 digits are kept for display. A hash without a key wouldn't do: there are
  few possible account numbers, and they can be reversed by trying them all.
- **Content rules**: bank, account and period are read from the PDF. The file name doesn't
  matter and is never stored, since it can include account numbers.

## Open question

A joint account (two users, the same account) would end up duplicated, one copy per user.
Whether that decision needs revisiting depends on whether the case ever comes up.

## Related

- [Reconciliation](reconciliation.md) — continuity and inter-account reconciliation depend on knowing which account each movement belongs to.
- [Business key](business-key.md) — the key includes the account.
- [File-level dedup](file-level-dedup.md) — the file registry is per user.
- [ADR 0004: Real PDFs](../decisions/0004-real-pdfs-never-leave-your-machine.md) — the full number never leaves the parsing step's memory.
- [Phase 1](../phases/phase-1.md)
