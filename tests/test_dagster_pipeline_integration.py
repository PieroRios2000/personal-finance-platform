"""The whole pipeline, materialized through Dagster end to end (T21).

`dg.materialize([bronze, dbt_models], ...)` is exactly what `uv run dagster
asset materialize --select '*'` does -- this test proves T21's own
acceptance criteria for real: a fresh synthetic inbox, materialized through
Dagster, produces the identical bronze + silver row counts the equivalent
`pfp ingest` + `dbt build` sequence does (`DEFAULT_MOVEMENTS`,
`tests/fixtures/synthetic_pdfs.py`: 4 transactions, deterministic), and the
real bronze -> silver dependency edge (`test_dagster_definitions.py`) holds
up under an actual materialization, not just the static asset graph.

Reuses `tests/test_dbt_silver_integration.py`'s own `_skip_reason()`/
`_wipe_test_lake()` (plain functions, not the `lake` fixture object itself --
`lake` is redefined here for the same reason `test_dbt_internal_transfers_
integration.py`'s own docstring gives: an imported fixture object still has
to appear under its own parameter name for pytest's dependency injection to
find it, which trips ruff's F811 on every test that takes it) and
`tests/test_dagster_bronze.py`'s own synthetic-inbox setup.

Deselected by default, like the rest of the dbt integration suite: needs
SeaweedFS running (`make poc-up`, T13) with `.env` exported into the shell.
Run with `pytest -m integration`.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import dagster as dg
import pytest
from dagster_dbt import DbtCliResource

from orchestration.assets.bronze import BronzeIngestConfig, bronze
from orchestration.assets.dbt_project import dbt_models, dbt_project
from tests import pg_store
from tests.fixtures.synthetic_pdfs import DEFAULT_MOVEMENTS, bcp_statement_pdf
from tests.test_dbt_silver_integration import (
    _TEST_LAKE_SUFFIX,
    _skip_reason,
    _wipe_test_lake,
)

pytestmark = pytest.mark.integration

_USER_ID = "t21-pipeline-tests"


@pytest.fixture
def lake() -> Iterator[str]:
    reason = _skip_reason()
    if reason:
        pytest.skip(reason)

    uri = f"{os.environ['LAKEHOUSE_URI'].rstrip('/')}/{_TEST_LAKE_SUFFIX}"
    previous = os.environ["LAKEHOUSE_URI"]
    os.environ["LAKEHOUSE_URI"] = uri
    try:
        _wipe_test_lake()
        yield uri
        _wipe_test_lake()
    finally:
        os.environ["LAKEHOUSE_URI"] = previous


def _bcp_pdf() -> bytes:
    return b"$BOP$" + bcp_statement_pdf()


def _materialize_whole_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, pdf_bytes: bytes
) -> dg.ExecuteInProcessResult:
    """Seeds one real synthetic PDF into a real inbox and runs the exact same
    two assets, in the same dependency order, `dagster asset materialize
    --select '*'` would.

    `pdf_bytes` is generated once by the caller and passed in, never rebuilt
    here: `bcp_statement_pdf()` embeds a timestamp (reportlab's own default
    `/CreationDate`), so two separate calls seconds apart -- exactly the gap
    a real `dbt build` between two materializations leaves -- are not
    byte-identical. `organizer.organize()` would still file the second copy as
    a duplicate (since ADR 0024 it compares parsed content when the bytes
    differ), but only after re-parsing the archived one; identical bytes
    short-circuit at the hash check. `tests/test_dagster_bronze.py`'s own
    idempotency test does the same, generating its PDF once and reusing it.
    """
    inbox_root = tmp_path / "inbox"
    archive_root = tmp_path / "raw"
    inbox = inbox_root / _USER_ID
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "statement.pdf").write_bytes(pdf_bytes)

    # Isolated from the owner's real database and from any other test's: this
    # worker's own Postgres database and Elementary file, the same reason
    # _dbt_build() in test_dbt_silver_integration.py always overrides them.
    for name, value in pg_store.dbt_environment(tmp_path).items():
        if name in ("PFP_PG_DATABASE", "PFP_ELEMENTARY_DUCKDB_PATH"):
            monkeypatch.setenv(name, value)

    return dg.materialize(
        [bronze, dbt_models],
        resources={"dbt": DbtCliResource(project_dir=dbt_project)},
        run_config=dg.RunConfig(
            ops={
                "bronze": BronzeIngestConfig(
                    user_id=_USER_ID,
                    inbox_root=str(inbox_root),
                    archive_root=str(archive_root),
                )
            }
        ),
    )


def test_whole_pipeline_materializes_through_dagster_with_matching_row_counts(
    lake: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _materialize_whole_pipeline(tmp_path, monkeypatch, pdf_bytes=_bcp_pdf())

    assert result.success

    bronze_metadata = result.asset_materializations_for_node("bronze")[0].metadata
    assert bronze_metadata["archived"].value == 1
    assert bronze_metadata["statements_written"].value == 1

    with pg_store.connect() as connection:
        row = connection.execute("select count(*) from silver.transactions").fetchone()

    assert row is not None
    # DEFAULT_MOVEMENTS (tests/fixtures/synthetic_pdfs.py): the same 4
    # transactions `pfp ingest` + `dbt build` on this identical fixture would
    # produce -- the row count parity this task's own verification asks for.
    assert row[0] == len(DEFAULT_MOVEMENTS)


def test_second_materialization_of_the_whole_pipeline_adds_nothing_new(
    lake: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Dagster equivalent of CI's twice-`pfp ingest` idempotency check
    (T17), now proven through the whole materialized pipeline, not just the
    bronze asset alone (`test_dagster_bronze.py`'s own version of this)."""
    pdf_bytes = _bcp_pdf()
    first = _materialize_whole_pipeline(tmp_path, monkeypatch, pdf_bytes=pdf_bytes)
    assert first.success

    # organize() always moves a processed file out of the inbox (T12b), so
    # _materialize_whole_pipeline's own re-seed of the identical bytes on this
    # second call is what CI's own ephemeral-integration job does too,
    # re-seeding its fixture between its two ingest passes -- the *same*
    # pdf_bytes both times, never a fresh bcp_statement_pdf() call (see
    # _materialize_whole_pipeline's own docstring on why that matters).
    second = _materialize_whole_pipeline(tmp_path, monkeypatch, pdf_bytes=pdf_bytes)

    assert second.success
    bronze_metadata = second.asset_materializations_for_node("bronze")[0].metadata
    assert bronze_metadata["archived"].value == 0
    assert bronze_metadata["duplicates"].value == 1
    assert bronze_metadata["statements_written"].value == 0
