-- Every movement is in at most one matched pair (T18b's own acceptance
-- criterion #1). internal_transfer_matches.sql's mutual-nearest-neighbor
-- algorithm guarantees this by construction (see that model's own
-- docstring); this is the same kind of insurance
-- assert_statement_continuity.sql already provides for its own rule -- proof
-- the guarantee holds on every real build, not just an assumption it does.
--
-- A singular test: one query about one relation (internal_transfers), with
-- nothing to parametrize.

with legs as (

    select first_leg_movement_id as movement_id from {{ ref('internal_transfers') }}
    union all
    select second_leg_movement_id as movement_id from {{ ref('internal_transfers') }}

)

select
    movement_id,
    count(*) as occurrences
from legs
group by movement_id
having count(*) > 1
