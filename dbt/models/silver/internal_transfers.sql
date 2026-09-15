-- silver.internal_transfers: one row per matched transfer pair (T18b).
--
-- Built entirely from internal_transfer_matches.sql's own precomputed
-- `is_internal_transfer`/`matched_movement_id` -- no matching logic lives
-- here, only the reshape from "one row per movement" to "one row per pair".
--
-- Self-joined on `matched_movement_id`, restricted to `is_internal_transfer`
-- and deduplicated with `movement_id < matched_movement_id`: every matched
-- movement appears in `internal_transfer_matches` twice (once from each
-- side, see that model's own `match_lookup` CTE), so without the inequality
-- every pair would come out twice, mirrored.
--
-- `first_leg_*`/`second_leg_*` naming is deliberate, not "outbound"/"inbound":
-- which side sorts first is an arbitrary string comparison on a hash, never a
-- semantic "this one transferred to that one" -- for a same-account-kind pair
-- either leg could sort first. A human reviewing this table tells the
-- direction from the signs themselves (which side is negative), the same way
-- they would reading the two statements directly.

select
    leg_1.user_id,
    leg_1.movement_id as first_leg_movement_id,
    leg_1.bank as first_leg_bank,
    leg_1.account_id as first_leg_account_id,
    leg_1.account_last4 as first_leg_account_last4,
    leg_1.date as first_leg_date,
    leg_1.amount as first_leg_amount,
    leg_1.account_kind as first_leg_account_kind,
    leg_1.source_file_sha256 as first_leg_source_file_sha256,
    leg_2.movement_id as second_leg_movement_id,
    leg_2.bank as second_leg_bank,
    leg_2.account_id as second_leg_account_id,
    leg_2.account_last4 as second_leg_account_last4,
    leg_2.date as second_leg_date,
    leg_2.amount as second_leg_amount,
    leg_2.account_kind as second_leg_account_kind,
    leg_2.source_file_sha256 as second_leg_source_file_sha256,
    leg_1.currency,
    -- Both already computed once in internal_transfer_matches.sql's own
    -- candidates CTE, and symmetric between the two legs -- leg_1's copy is
    -- the pair's one true value, not recomputed here a second time.
    leg_1.day_diff,
    leg_1.amount_diff
from {{ ref('internal_transfer_matches') }} as leg_1
inner join {{ ref('internal_transfer_matches') }} as leg_2
    on leg_1.matched_movement_id = leg_2.movement_id
where
    leg_1.is_internal_transfer
    and leg_1.movement_id < leg_1.matched_movement_id
