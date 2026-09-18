"""Dagster orchestration (T21): the ingest -> dbt build sequence as one DAG,
wrapping `ingestion`/`lakehouse` and the `dbt/` project rather than
reimplementing either.

Discovered by the `dagster` CLI via `[tool.dagster]` in `pyproject.toml` --
see `orchestration/definitions.py`.
"""
