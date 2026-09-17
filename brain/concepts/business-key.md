---
type: concept
phase: 1
---

# Business key

A transaction identifier built from its own data, not a generated id, so the same movement is
recognized even if it arrives in a different PDF.

## How it applies here

`date + amount + normalized description + account_id + occurrence_number` (the account, see
[Users and accounts](users-and-accounts.md)).

A transfer between two of your own accounts is two movements with different keys, one per
account: matching them is [inter-account reconciliation](reconciliation.md)'s job (T18b), not
deduplication's.

The description is normalized (no extra whitespace, uppercase, no filler codes) with
`normalize_description()` (T6, ported to SQL as `dbt/macros/normalize_description.sql` for T20),
so the key stays stable across statements. `silver.transactions` (T20, [ADR 0018](../decisions/0018-incremental-merge-business-key-occurrence-number.md))
uses this key to `MERGE`: a row whose key already exists gets updated in place, not
re-inserted.

**`occurrence_number`** is this open question's own resolution: a `row_number()`
(`dbt/macros/occurrence_number.sql`) scoped to *one source file*. Two rows that would
otherwise share every other part of the key get different numbers, so both survive as
separate rows — but the same-looking row reappearing in a *different* file (a bank
regenerating a PDF for the same period) is deliberately left free to collide with whatever's
already there under a different occurrence slot, since that really is the same movement,
re-declared. `dbt/macros/movement_id.sql` ([ADR 0017](../decisions/0017-internal-transfer-matching-mutual-nearest-neighbor.md))
shares the same mechanism for its own, different identity need — full reasoning for both in
[ADR 0018](../decisions/0018-incremental-merge-business-key-occurrence-number.md).

## Related

- [Idempotency](idempotency.md) — the business key is its second layer.
- [File-level dedup](file-level-dedup.md) — the earlier layer, which misses regenerated PDFs.
- [Medallion architecture](medallion.md) — the MERGE happens in silver.
- [ADR 0018: Incremental MERGE, occurrence-number business key](../decisions/0018-incremental-merge-business-key-occurrence-number.md)
- [dbt silver](../components/dbt-silver.md)
- [Phase 1](../phases/phase-1.md)
