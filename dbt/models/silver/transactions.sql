-- silver.transactions: one clean, typed row per bank movement (T16).
--
-- There is nothing to cast. Bronze writes every table with one fixed pyarrow
-- schema (ADR 0006), and `delta_scan()` hands those types straight to DuckDB:
-- date -> DATE, amount -> DECIMAL(18, 2), ingested_at -> TIMESTAMP WITH TIME
-- ZONE. A cast here would only restate what bronze already guarantees.
--
-- The description is the one column silver does rework. Bronze is append-only and
-- long-lived, so rows written months apart by different parser versions sit side
-- by side; silver is where the column contract is enforced, so it re-applies
-- `ingestion.schema.normalize_description()`'s rules rather than trusting that
-- every bronze row went through the current version of that function. The rules
-- are idempotent: a no-op for a correctly written row, a repair for anything
-- else. Keep the two in step -- collapse runs of padding characters, collapse
-- whitespace, trim, upper case.
--
-- account_kind (T18a, ADR 0014) lives on bronze.statements, not
-- bronze.transactions -- an account's kind doesn't vary per movement, the same
-- reason opening_balance/closing_balance never made it to bronze.transactions
-- either. account_kinds below collapses statements down to one row per
-- account_id before the join: a single account can have many statements (one
-- per period, and Scotiabank writes one per currency for the very same
-- period), and joining transactions to bronze.statements directly on
-- account_id would fan every one of its transactions out into as many
-- duplicate rows as that account has statements. account_kind is a constant
-- per account in practice (set once per parser, keyed off the bank baked into
-- account_id's own hash), so `max()` never has more than one real value to
-- pick from -- it exists to make the join's cardinality safe by construction,
-- not to arbitrate a genuine disagreement.
--
-- is_internal_transfer (T18b, ADR 0017) is a left join to
-- internal_transfer_matches.sql on that model's own movement_id -- the
-- matching logic itself lives there, once, not here. A left join (not inner)
-- for the same "never silently drop a row" reason account_kinds uses one;
-- coalesce(..., false) turns "no match found" into a real false rather than
-- null, since every transaction either is or isn't a transfer, with no third
-- state to represent.

with account_kinds as (

    select
        account_id,
        max(account_kind) as account_kind
    from {{ source('bronze', 'statements') }}
    group by account_id

),

transfer_matches as (

    select
        movement_id,
        is_internal_transfer
    from {{ ref('internal_transfer_matches') }}

)

select
    bronze_transactions.user_id,
    bronze_transactions.bank,
    bronze_transactions.account_id,
    bronze_transactions.account_last4,
    bronze_transactions.date,
    bronze_transactions.amount,
    bronze_transactions.currency,
    bronze_transactions.source_file_sha256,
    bronze_transactions.ingested_at,
    account_kinds.account_kind,
    coalesce(transfer_matches.is_internal_transfer, false) as is_internal_transfer,
    upper(trim(regexp_replace(
        regexp_replace(bronze_transactions.description, '[.\-_*#]{2,}', ' ', 'g'),
        '\s+', ' ', 'g'
    ))) as description
from {{ source('bronze', 'transactions') }} as bronze_transactions
left join account_kinds
    on bronze_transactions.account_id = account_kinds.account_id
left join transfer_matches
    on transfer_matches.movement_id = {{ movement_id('bronze_transactions') }}
