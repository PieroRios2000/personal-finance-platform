---
type: concept
phase: 1
---

# Business key

A transaction identifier built from its own data, not a generated id, so the same movement is
recognized even if it arrives in a different PDF.

## How it applies here

`date + amount + normalized description + account_id` (the account, see [Users and accounts](users-and-accounts.md)).

A transfer between two of your own accounts is two movements with different keys, one per
account: matching them is [inter-account reconciliation](reconciliation.md)'s job (T18b), not
deduplication's.

The description is normalized (no extra whitespace, uppercase, no filler codes) with
`normalize_description()` (T6), so the key stays stable across statements. In Phase 2, silver
uses this key to MERGE in Delta: if the key already exists, it isn't inserted again.

## Open question

Two legitimate purchases with the same amount at the same merchant on the same day would
produce the same key and merge into one. This gets resolved when the MERGE is designed in
Phase 2; one option is adding the occurrence number within the same PDF.

## Related

- [Idempotency](idempotency.md) — the business key is its second layer.
- [File-level dedup](file-level-dedup.md) — the earlier layer, which misses regenerated PDFs.
- [Medallion architecture](medallion.md) — the MERGE happens in silver.
- [Phase 1](../phases/phase-1.md)
