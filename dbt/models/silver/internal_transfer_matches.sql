-- silver.internal_transfer_matches: one row per bronze.transactions row, with
-- whether it's a plausible transfer half and, if so, which other movement it
-- was matched with (T18b).
--
-- The single shared computation `internal_transfers.sql`, `unmatched_transfers.sql`
-- and `transactions.sql`'s own `is_internal_transfer` column all build on, so the
-- matching logic below is written -- and has to be reasoned about -- exactly
-- once. It reads bronze directly, never dbt's ref() of the transactions model,
-- specifically so that transactions.sql can join back to *this* model without
-- creating a dependency cycle (transactions.sql -> internal_transfer_matches.sql
-- -> bronze, never the other way around). `account_kinds` below is the same
-- dedup'd join `transactions.sql` already uses (ADR 0015) -- duplicated here
-- rather than factored out for that one reason, and kept in step with it
-- deliberately.
--
-- **Two different questions, two different predicates:**
--
-- 1. Is this row a *candidate* at all -- "within the amount/date-window
--    neighborhood of another account's row" (this model's own definition,
--    the one `unmatched_transfers.sql` is built on)? Same user, a different
--    account, within the day window, and the account_kind-aware sign rule
--    below on the amount -- deliberately *not* requiring the same currency.
--    A cross-currency pair that's otherwise a dead ringer for a transfer
--    (same day, same numeric amount) must still surface for a human to look
--    at, not vanish just because nothing here does FX conversion (Piero
--    explicitly rejected currency conversion anywhere in this project,
--    tasks/plan-phase2.md).
-- 2. Is this row *matched* -- a real `is_internal_transfer=true`? The same
--    rule, but currency-restricted this time: cross-currency candidates are
--    never eligible to become an actual match, only to be flagged for review.
--
-- **The sign rule itself (ADR 0015), applied to a pair of movements a/b:**
-- - Same account_kind (asset-asset or liability-liability): opposite signs,
--   same absolute value -- `abs(a.amount + b.amount) <= tolerance`. Amounts
--   are never zero (ingestion.schema.Transaction rejects a zero amount), so
--   at zero tolerance this can only hold when the two signs are opposite.
-- - Different account_kind (asset-liability): *both* negative, same absolute
--   value -- `abs(a.amount - b.amount) <= tolerance`, restricted to
--   `a.amount < 0 and b.amount < 0`. Only this direction is a real transfer
--   in this project's domain: a checking outflow funding a debt-reducing
--   card payment. The reverse (both positive -- an asset inflow coinciding
--   with a liability charge) isn't a transfer and is deliberately excluded,
--   not just "same sign" in the abstract.
--
-- **Matching algorithm: mutual nearest neighbor, not a global optimum.**
-- "Every movement is in at most one pair" (T18b's own acceptance criterion)
-- needs *some* one-to-one assignment, and computing a true maximum-cardinality
-- bipartite matching in plain SQL is real complexity this project's own scale
-- doesn't justify (thousands of rows, and in practice at most a small handful
-- of candidates share a given amount/date neighborhood). Instead: each
-- candidate movement ranks its own partners by closeness (smallest amount
-- difference, then smallest date difference, then a deterministic tie-break),
-- and a pair is only ever selected when each side is the *other's* own best
-- candidate too (`best_partner` self-joined on itself). That's enough to
-- guarantee the one-to-one property by construction -- a movement's own best
-- partner is a single row, so it can be *someone's* mutual match at most
-- once -- without needing a global solver. It can leave a movement unmatched
-- even when *some* valid pairing existed for it (e.g. three same-amount
-- candidates: the "middle" one loses to whichever of its two neighbors it's
-- closer to, see `assert_internal_transfers_are_one_to_one.sql` and
-- `tests/test_dbt_internal_transfers_integration.py`'s own three-candidate
-- test) -- an accepted, documented trade-off, not a bug.

with account_kinds as (

    select
        account_id,
        max(account_kind) as account_kind
    from {{ source('bronze', 'statements') }}
    group by account_id

),

tx as (

    select
        {{ movement_id('bronze_transactions') }} as movement_id,
        bronze_transactions.user_id,
        bronze_transactions.bank,
        bronze_transactions.account_id,
        bronze_transactions.account_last4,
        bronze_transactions.date,
        bronze_transactions.description,
        bronze_transactions.amount,
        bronze_transactions.currency,
        bronze_transactions.source_file_sha256,
        account_kinds.account_kind
    from {{ source('bronze', 'transactions') }} as bronze_transactions
    left join account_kinds
        on bronze_transactions.account_id = account_kinds.account_id

),

candidates as (

    select
        a.movement_id,
        b.movement_id as candidate_movement_id,
        a.currency = b.currency as same_currency,
        abs(date_diff('day', a.date, b.date)) as day_diff,
        case
            when a.account_kind = b.account_kind then abs(a.amount + b.amount)
            else abs(a.amount - b.amount)
        end as amount_diff
    from tx as a
    inner join tx as b
        on
            a.movement_id != b.movement_id
            and a.user_id = b.user_id
            and a.account_id != b.account_id
            and abs(date_diff('day', a.date, b.date))
            <= {{ var('internal_transfer_day_window_days', 3) }}
            and (
                (
                    a.account_kind = b.account_kind
                    and abs(a.amount + b.amount)
                    <= {{ var('internal_transfer_amount_tolerance', 0) }}
                )
                or (
                    a.account_kind != b.account_kind
                    and a.amount < 0
                    and b.amount < 0
                    and abs(a.amount - b.amount)
                    <= {{ var('internal_transfer_amount_tolerance', 0) }}
                )
            )

),

best_partner as (

    select
        movement_id,
        candidate_movement_id,
        amount_diff,
        day_diff,
        row_number() over (
            partition by movement_id
            order by amount_diff, day_diff, candidate_movement_id
        ) as rank
    from candidates
    where same_currency

),

matched_pairs as (

    select
        a.movement_id as first_movement_id,
        a.candidate_movement_id as second_movement_id,
        -- Symmetric either way (both are abs()-based), so either side's own
        -- copy is the pair's one true value -- carried through so
        -- internal_transfers.sql can select it instead of recomputing the
        -- same case expression a second time.
        a.amount_diff,
        a.day_diff
    from best_partner as a
    inner join best_partner as b
        on
            a.movement_id = b.candidate_movement_id
            and a.candidate_movement_id = b.movement_id
    where
        a.rank = 1
        and b.rank = 1
        -- Each mutual pair would otherwise appear twice (once from either
        -- side); this keeps exactly one direction. Purely a dedup tie-break
        -- on the hash string, not a semantic "who transferred to whom".
        and a.movement_id < a.candidate_movement_id

),

match_lookup as (

    select
        first_movement_id as movement_id,
        second_movement_id as matched_movement_id,
        amount_diff,
        day_diff
    from matched_pairs
    union all
    select
        second_movement_id as movement_id,
        first_movement_id as matched_movement_id,
        amount_diff,
        day_diff
    from matched_pairs

),

candidate_movement_ids as (

    select distinct movement_id
    from candidates

)

select
    tx.movement_id,
    tx.user_id,
    tx.bank,
    tx.account_id,
    tx.account_last4,
    tx.date,
    tx.description,
    tx.amount,
    tx.currency,
    tx.account_kind,
    tx.source_file_sha256,
    match_lookup.matched_movement_id,
    match_lookup.amount_diff,
    match_lookup.day_diff,
    candidate_movement_ids.movement_id is not null as is_transfer_candidate,
    match_lookup.movement_id is not null as is_internal_transfer
from tx
left join candidate_movement_ids
    on tx.movement_id = candidate_movement_ids.movement_id
left join match_lookup
    on tx.movement_id = match_lookup.movement_id
