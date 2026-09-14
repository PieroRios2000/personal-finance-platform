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

select
    user_id,
    bank,
    account_id,
    account_last4,
    date,
    amount,
    currency,
    source_file_sha256,
    ingested_at,
    upper(trim(regexp_replace(
        regexp_replace(description, '[.\-_*#]{2,}', ' ', 'g'), '\s+', ' ', 'g'
    ))) as description
from {{ source('bronze', 'transactions') }}
