---
type: decision
phase: 2
status: accepted
date: 2026-09-17
---

# ADR 0018: Incremental `MERGE` in silver, an occurrence-number business key, and two mechanisms for "the same movement reappeared"

## Context

`silver.transactions` (T16) was a full-refresh model: every `dbt build` recomputed it from
every row in `bronze.transactions`. Phase 2's first task, T20, makes it incremental — only new
or changed bronze rows get processed — keyed on the business key `brain/concepts/
business-key.md` already named back in T3a: `date + amount + normalized description +
account_id`, with an explicitly tracked open question left for this exact moment: "two
legitimate purchases with the same amount at the same merchant on the same day would produce
the same key and merge into one... one option is adding the occurrence number within the same
PDF."

A second thing surfaced while implementing this, not originally scoped as part of T20:
`dbt/macros/movement_id.sql` (T18b, the content-based row identity `internal_transfer_matches.sql`
uses) already documented, word for word, the identical gap — "two genuinely identical bronze
rows... hash to the same key and collapse into one for matching purposes... out of scope to fix
here." Two different models, built by two different tasks, independently hit the same unsolved
problem and each deferred it once.

## Decision

**One shared `occurrence_number` macro (`dbt/macros/occurrence_number.sql`), used by both
`movement_id` and the new business key — not two parallel identity schemes.** A `row_number()`
scoped to one `source_file_sha256`, parameterized by the caller's own description expression
(raw for `movement_id`, normalized for the business key — the two callers need to partition by
different things, so the macro takes an expression rather than assuming a column). Extending
`movement_id` to include it resolves T18b's own documented gap as a direct, deliberate side
effect: two identical bronze rows in one statement now get two distinct `movement_id`s, so
`internal_transfer_matches.sql`'s matching can no longer silently collapse them. Its `tx` CTE's
`select distinct` (added for that exact reason during T18b) is now a harmless no-op — left in
place rather than removed, since removing it earns nothing and touches tested, working code for
no functional gain.

**`silver.transactions` is `materialized='incremental'`, `incremental_strategy='merge'`,
`unique_key=['account_id', 'date', 'amount', 'description', 'occurrence_number']`.** The
incremental filter (which bronze rows this run even looks at) is: every row on a first build or
`--full-refresh`, or — once incremental — only rows whose `(source_file_sha256, ingested_at)`
pair isn't already present in `{{ this }}`. `lakehouse/bronze.py`'s `write_statement()` stamps
one `ingested_at` per file, not per row, so a touched file's rows are always picked up together,
never partially.

**Two distinct mechanisms for two distinct "the same movement showed up again" cases**, kept
deliberately separate rather than unified into one:

1. **A `pre_hook: purge_reprocessed_files()`** deletes a run's touched files' *existing* silver
   rows before the MERGE inserts their fresh ones. This is what a `pfp backfill` (ADR 0010)
   needs when a parser fix changes a row's own description, and so its business key: a plain
   `MERGE` can insert a new-keyed row and update a matching one, but it can never *delete* a
   target row whose key no longer appears anywhere in this run's own source data — without the
   purge, the row's *old* key would sit in silver forever, orphaned next to the corrected row's
   new key. Scoped by `source_file_sha256`, so it only ever touches the file(s) actually being
   reprocessed in this run.
2. **The `MERGE`'s own `WHEN MATCHED` branch** handles a *different* file (a new
   `source_file_sha256`, past T7's file-level dedup — e.g. a bank regenerating a statement PDF
   with different bytes) that parses back to the exact same business key as a period already in
   silver. That file was never in silver before, so the purge (scoped to files with *existing*
   rows) has nothing of its own to delete; the `MERGE` matching on the business key itself,
   not the file, is what correctly updates that row in place instead.

Verified as two genuinely different, both-real code paths — not the same case described twice —
via dedicated integration tests for each (`test_backfill_with_a_corrected_description_updates_the_row_in_place`
and `test_regenerated_file_with_the_same_business_key_updates_in_place`).

**A new dbt test, `assert_statement_balance_reconciliation.sql`**, re-checks `ingestion/
reconciliation.py`'s (T8) same arithmetic — opening balance + movements = closing balance — at
the model layer, per account/period/currency (following `assert_statement_continuity.sql`'s own
currency-partitioning pattern, T18c, for Scotiabank's multi-currency-statements-per-file case).
This exists specifically to catch what this task's own new `MERGE`/`pre_hook` interaction could
get wrong (a row silently dropped or duplicated) that a check upstream of the `MERGE` — T8's own
Python-level one — runs before the `MERGE` even exists and so could never see.

**A second new dbt test, `assert_transactions_business_key_is_unique.sql`**, is the standing
proof the `unique_key` config actually holds: dbt's merge strategy doesn't itself refuse a
source batch with a duplicate key, it just applies the match ambiguously and silently.

## Alternatives considered

- **A wholly separate business-key computation, leaving `movement_id` and its documented gap
  alone**: rejected. Would have shipped two different, disagreeing answers to "is this bronze
  row the same as that one" in the same silver layer, and left T18b's own already-documented,
  already-known bug sitting there unfixed for no reason once the exact mechanism to fix it
  already existed one file over.
- **Unifying `movement_id` and the business key into one identity entirely** (same partition,
  raw or normalized, for both): rejected. `movement_id` is a *bookkeeping* identity — "is this
  the literal same PDF row I matched before" — while the business key is a *business* identity —
  "is this the same real-world movement, even across two statements' differently-cased or
  padded renderings of its description." Collapsing them would make `movement_id` change
  whenever a parser's normalization rules changed, breaking `internal_transfer_matches.sql`'s
  own stability guarantee for no reason connected to T20's actual goal.
- **A generic dbt `unique_combination_of_columns` test** (via `dbt_utils` or similar) for the
  business-key-uniqueness proof: rejected — this project has no dbt package dependency today,
  and one query with `group by`/`having count(*) > 1` says the same thing without adding one
  just for this, the same reasoning `assert_statement_continuity.sql`'s own "singular test, not
  a generic one" comment already used.

## Consequences

- `occurrence_number`'s own tie-break (which of two truly-identical rows gets labeled "1" vs.
  "2") is not stable across separate query executions — DuckDB's `row_number()` over ties with
  no fully-discriminating `order by` key has no further column to break the tie with (no PDF
  row/line number is captured anywhere in this project, unchanged by this task). This is
  provably harmless: two rows identical in every column this project can observe are
  interchangeable in every way it can observe, and the whole-file purge-then-reinsert design
  means nothing downstream ever depends on a specific label surviving between two runs — each
  run recomputes both sides fresh.
- The business key inherits `brain/concepts/business-key.md`'s own pre-existing definition
  verbatim (no `user_id`, no `currency`) — a known, *inherited*, not new, limitation: two
  accounts of the same user, in different currencies, could in principle collide on `account_id
  + date + amount + description` if `account_id` weren't already unique per account (it is, by
  construction, ADR 0005) — noted here for completeness, not a new gap this task introduces.
- `internal_transfer_matches.sql`'s `tx` CTE keeps a `select distinct` that no longer collapses
  anything (movement_id is unique per row now, by construction) — a harmless no-op, documented
  as such in that CTE's own comment, not removed.

## Related

- [Business key](../concepts/business-key.md) — the concept this ADR resolves the open question
  in.
- [ADR 0005: Schema scoped to user/account](0005-transaction-schema-with-user-and-account.md)
- [ADR 0010: Bronze backfill replaces, not versions](0010-bronze-backfill-replaces-not-versions.md) —
  the backfill semantics this task's `pre_hook` makes correct at the silver layer too.
- [ADR 0012: Scotiabank password fallback; `list[Statement]`](0012-scotiabank-password-fallback-detection.md) —
  why one PDF can produce more than one `Statement`/currency.
- [ADR 0016: Currency-aware statement continuity](0016-currency-aware-statement-continuity.md) —
  the currency-partitioning pattern `assert_statement_balance_reconciliation.sql` follows.
- [ADR 0017: Internal-transfer matching](0017-internal-transfer-matching-mutual-nearest-neighbor.md) —
  `movement_id`, extended here.
- [dbt silver](../components/dbt-silver.md)
- [Reconciliation](../concepts/reconciliation.md)
- [Idempotency](../concepts/idempotency.md)
