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
-- `ingestion.schema.normalize_description()`'s rules (`normalize_description.sql`)
-- rather than trusting that every bronze row went through the current version of
-- that function. The rules are idempotent: a no-op for a correctly written row, a
-- repair for anything else.
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
--
-- Incremental MERGE (T20, ADR 0018): this model reads the amount of bronze it
-- always used to, but only ever *writes* what's new or changed, keyed on the
-- business key `brain/concepts/business-key.md` describes -- account_id,
-- date, amount, normalized description and `occurrence_number` (T20,
-- `dbt/macros/occurrence_number.sql`), the last one disambiguating two
-- otherwise-identical rows within one source file. `new_bronze_transactions`
-- below is every bronze row this run needs to look at: all of them on a first
-- build or `--full-refresh`, or -- once incremental -- only rows whose
-- `(source_file_sha256, ingested_at)` pair isn't already in `{{ this }}`,
-- which is every row of a file `pfp ingest` or `pfp backfill` (ADR 0010)
-- wrote with a *new* `ingested_at` (bronze stamps one `ingested_at` per file,
-- not per row -- `lakehouse/bronze.py`'s `write_statement()`), so a touched
-- file's rows are always picked up together, never partially.
--
-- `pre_hook: purge_reprocessed_files()` (`dbt/macros/purge_reprocessed_files.sql`)
-- runs first and deletes this run's touched files' *existing* silver rows
-- before the MERGE inserts their fresh ones. A plain MERGE alone can insert a
-- new-keyed row and update a matching one, but it can never delete a target
-- row whose key no longer appears in this run's own source data -- exactly
-- what a `pfp backfill` needs when a parser fix changes a row's own
-- description, and so its business key: without the purge, the row's *old*
-- key would sit in silver forever, orphaned next to the corrected row's new
-- key. The purge is scoped by `source_file_sha256`, so it only ever touches
-- the file(s) actually being reprocessed.
--
-- That purge is deliberately *not* what handles a *different* case that can
-- look similar: a bank regenerating a statement PDF (a new `source_file_sha256`,
-- past T7's file-level dedup) that parses back to the exact same business
-- key as a period already in silver. That file was never in silver before,
-- so the purge (scoped to files with *existing* rows) has nothing of its own
-- to delete -- the MERGE's own `WHEN MATCHED` branch, matching on the
-- business key itself rather than the file, is what correctly updates that
-- row in place instead (new `source_file_sha256`, same everything else).
-- Two different mechanisms for two different "the same movement showed up
-- again" scenarios, on purpose -- see ADR 0018 for both side by side.

{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key=['account_id', 'date', 'amount', 'description', 'occurrence_number'],
        pre_hook="{{ purge_reprocessed_files() }}"
    )
}}

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

),

new_bronze_transactions as (

    -- `movement_id` and `occurrence_number` are computed here, once, as real
    -- columns -- not inline where they're used below. Both are window
    -- functions under the hood (`row_number() over (...)`), and a window
    -- function can only appear in a SELECT list, never inside a JOIN's own
    -- `on` clause; `transfer_matches` is joined on `movement_id` below, so it
    -- has to already be a plain column by the time that join runs.
    select
        bronze_transactions.*,
        {{ occurrence_number(
            'bronze_transactions',
            normalize_description('bronze_transactions.description')
        ) }} as occurrence_number,
        {{ movement_id('bronze_transactions') }} as movement_id
    from {{ source('bronze', 'transactions') }} as bronze_transactions
    {% if is_incremental() %}
    where not exists (
        select 1
        from {{ this }} as existing
        where
            existing.source_file_sha256 = bronze_transactions.source_file_sha256
            and existing.ingested_at = bronze_transactions.ingested_at
    )
    {% endif %}

)

select
    new_bronze_transactions.user_id,
    new_bronze_transactions.bank,
    new_bronze_transactions.account_id,
    new_bronze_transactions.account_last4,
    new_bronze_transactions.date,
    new_bronze_transactions.amount,
    new_bronze_transactions.currency,
    new_bronze_transactions.source_file_sha256,
    new_bronze_transactions.ingested_at,
    new_bronze_transactions.occurrence_number,
    account_kinds.account_kind,
    coalesce(transfer_matches.is_internal_transfer, false) as is_internal_transfer,
    {{ normalize_description('new_bronze_transactions.description') }} as description
from new_bronze_transactions
left join account_kinds
    on new_bronze_transactions.account_id = account_kinds.account_id
left join transfer_matches
    on new_bronze_transactions.movement_id = transfer_matches.movement_id
