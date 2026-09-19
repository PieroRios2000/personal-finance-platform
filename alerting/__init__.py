"""Alerting (Phase 7): errors go out the moment they appear, warnings wait for a
weekly digest. Only names and counts ever leave the process (ADR 0004): nothing
in this package reads a dbt message, an amount, an account or a file name."""
