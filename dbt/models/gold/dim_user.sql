-- gold.dim_user: one row per distinct user_id in silver.transactions
-- (T23).
--
-- Grain: one row per `user_id`. This project's only user attribute is the
-- id itself (brain/concepts/users-and-accounts.md) -- no name or email is
-- ever collected, so there's nothing else to carry here.

select distinct user_id
from {{ ref('transactions') }}
