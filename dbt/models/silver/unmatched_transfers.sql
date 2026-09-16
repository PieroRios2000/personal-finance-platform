-- silver.unmatched_transfers: transfer candidates with no partner, for a
-- human to review -- never dropped (T18b).
--
-- A "candidate" is internal_transfer_matches.sql's own definition, made
-- explicit and testable there: any movement within the amount/date-window
-- neighborhood of another account's row (the account_kind-aware sign rule,
-- ADR 0015), whether or not it ended up matched. This model is exactly the
-- leftover half: a candidate that never became a mutual match, most commonly
-- because its only real-world partner was never ingested (the inflow half of
-- a transfer that hasn't reached bronze yet), because it lost out to a closer
-- candidate under the mutual-nearest-neighbor rule (see
-- internal_transfer_matches.sql's own docstring), or because its only
-- candidate was in a different currency -- cross-currency transfers are
-- explicitly out of scope for auto-matching (no FX conversion anywhere in
-- this project), but must still surface here rather than vanish.
--
-- An ordinary transaction with no plausible transfer partner at all is *not*
-- a candidate and never appears here -- this table is for plausible-but-
-- unpaired transfer halves, not a catch-all of everything unflagged.

select
    movement_id,
    user_id,
    bank,
    account_id,
    account_last4,
    date,
    description,
    amount,
    currency,
    account_kind,
    source_file_sha256
from {{ ref('internal_transfer_matches') }}
where
    is_transfer_candidate
    and not is_internal_transfer
