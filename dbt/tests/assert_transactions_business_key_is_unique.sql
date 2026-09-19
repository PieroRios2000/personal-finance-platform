-- The business key is actually unique in silver (T20).
--
-- `transactions.sql`'s own `unique_key` config tells the MERGE which rows
-- are "the same movement", but dbt's merge strategy doesn't itself refuse a
-- source batch with a duplicate key -- it would just apply the match
-- ambiguously, silently. This is the standing proof, the same kind
-- `assert_internal_transfers_are_one_to_one.sql` already provides for its
-- own one-to-one guarantee: no combination of `account_id`, `date`,
-- `amount`, `description` and `occurrence_number` ever repeats.
--
-- A plain singular test rather than a package's generic
-- "unique combination of columns" test: this project has no dbt package
-- dependency today (no `packages.yml`), and one query with a `group by` and
-- a `having` says the same thing without adding one just for this.

select
    account_id,
    date,
    amount,
    description,
    occurrence_number,
    count(*) as occurrences
from {{ ref('transactions') }}
group by account_id, date, amount, description, occurrence_number
having count(*) > 1
