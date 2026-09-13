---
type: decision
phase: 1
status: accepted
date: 2026-09-13
---

# ADR 0006: Lake location by URI (`LAKEHOUSE_URI`)

## Context

Bronze needs somewhere to write Delta tables: local S3 (SeaweedFS, ADR 0003) day to day, the
same local S3 inside an ephemeral per-PR environment (ADR 0007) in integration CI, and — for
unit tests — no S3 at all, since spinning up SeaweedFS for every `pytest` run would make the
fast feedback loop (`make check-fast`, under 5 s) impossible. `deltalake`'s `write_deltalake`
and `DeltaTable` already accept either a plain filesystem path or an `s3://...` URI as their
first argument; the only thing genuinely bank-specific is the S3 connection details a
non-AWS, plain-HTTP endpoint like SeaweedFS needs that a real AWS bucket wouldn't.

## Decision

- **One environment variable, `LAKEHOUSE_URI`, decides everything** (`lakehouse/storage.py`,
  T14): `s3://lakehouse` locally and in integration CI, or a disk path (a `pytest` `tmp_path`)
  in unit tests. `lakehouse_uri()` reads it and raises `MissingLakehouseURIError` — with the
  fix ("copy `.env.example` to `.env`") in the message — if it's unset, rather than silently
  writing somewhere unexpected.
- **`storage_options()` returns `None` for a plain path**, and only builds the S3-specific
  dict when `LAKEHOUSE_URI` starts with `s3://`: `AWS_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`,
  `AWS_SECRET_ACCESS_KEY` (all required, read straight from the environment — no defaults, so
  a missing credential fails loudly with a `KeyError` rather than silently trying an empty
  one), `AWS_REGION` (defaults to `"us-east-1"`, since SeaweedFS doesn't have real AWS regions
  but `deltalake`'s S3 backend still wants one), and three fixed, SeaweedFS-specific flags:
  `allow_http=true` (SeaweedFS serves plain HTTP, not TLS), `aws_virtual_hosted_style_request
  =false` (path-style bucket addressing — `http://host:port/bucket/key` — not
  `bucket.host:port/key`), and `aws_conditional_put=etag` (delta-rs's documented way to get
  safe concurrent writes on S3-compatible storage without a separate DynamoDB-style locking
  table). Every key is exactly what's documented at
  https://delta-io.github.io/delta-rs/integrations/object-storage/s3-like/ (verified against
  the installed `deltalake==1.6.3`'s own signatures with `inspect.signature()`, not written
  from memory).
- **Every bronze table lives under one fixed layout**, `table_uri(name)` ->
  `<LAKEHOUSE_URI>/bronze/<name>` — `bronze/transactions`, `bronze/statements`,
  `bronze/ingested_files` (T14) today.
- **Money columns use a fixed, explicit pyarrow `decimal128(18, 2)` schema on every write**,
  never inferred per-batch. This isn't part of the URI decision itself, but it was discovered
  while building the writer this ADR describes, so it's recorded here rather than nowhere:
  pyarrow's `Table.from_pylist()` infers a `decimal128` precision from each batch's own
  values, and `deltalake` rejects an `append` whose inferred precision differs from the
  table's existing one — reproduced directly against `deltalake==1.6.3` (`SchemaMismatchError:
  Cannot cast field amount from Decimal128(8, 2) to Decimal128(4, 2)`, writing `12.34` then
  `123456.78` in two separate `write_deltalake` calls). A fixed schema on every write
  sidesteps it entirely.

## Alternatives considered

- **Two separate code paths (one for tests, one for S3), chosen by an `if TESTING` flag or
  similar**: rejected — `deltalake` already treats a path and an `s3://` URI uniformly, so
  branching in application code would only duplicate what the library does for free. A single
  `storage_options()` that returns `None` for a plain path keeps `bronze.py`'s writer and
  reader functions identical regardless of where they're pointed.
- **Hardcoding the SeaweedFS endpoint/credentials in code**: rejected on ADR 0004's own
  grounds (no secret belongs in a file that reaches Git) and because it would make the same
  code unable to run in CI's ephemeral environment (ADR 0007), where the endpoint changes
  every run.
- **Letting pyarrow infer the decimal schema per write**: this is what the code did first; the
  cross-batch `SchemaMismatchError` above is exactly why it was rejected in favor of one fixed
  schema shared by every append.

## Consequences

- A missing or wrong `.env` value now fails fast and specifically (`MissingLakehouseURIError`,
  or a `KeyError` naming the exact missing S3 credential) instead of a confusing
  `deltalake`/`botocore` error several layers down.
- `lakehouse/bronze.py` and `lakehouse/storage.py` have no branch that behaves differently in
  tests versus production beyond what `LAKEHOUSE_URI`'s value itself implies — the same code
  path is what T14's S3 integration test (`tests/test_bronze_integration.py`, `integration`
  marker) exercises for real.
- 18 total digits on every money column comfortably covers any realistic transaction or
  statement-balance amount; a value that didn't fit would already have failed `ingestion.schema`
  validation (ADR 0005) long before it reached bronze.
- DuckDB's own read path against these Delta tables (ADR 0002) is unaffected: DuckDB reads
  Delta natively from either a disk path or an `s3://` URI, so nothing here needs to change
  when T15/T16 start querying bronze instead of only writing to it.

## Related

- [ADR 0002: DuckDB + delta-rs before Spark](0002-duckdb-and-delta-rs-before-spark.md)
- [ADR 0003: Local S3 with SeaweedFS](0003-local-s3-with-seaweedfs.md)
- [ADR 0007: Ephemeral per-PR environments](0007-ephemeral-per-pr-environments.md)
- [ADR 0009: Several users, several accounts: content over filename](0009-multi-user-multi-account-content-over-filename.md) —
  the lake's `user_id` partitioning this ADR's tables use
- [Phase 1](../phases/phase-1.md)
