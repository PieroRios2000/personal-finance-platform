"""Tests for the Dagster bronze asset (T21).

`orchestration.assets.bronze.bronze` wraps `organizer.organize()` and
`bronze.write_statement()` directly -- the same two functions
`ingestion.cli._run_ingest()` already calls -- so these tests use the same
boundary `tests/test_cli.py`'s own `ingest` tests do: a disk-backed
`LAKEHOUSE_URI` (no live S3 needed) and a real synthetic PDF, never a mock of
`organizer`/`bronze` themselves (those already have their own tests).
"""

from pathlib import Path

import dagster as dg
import pytest
from orchestration.assets.bronze import BronzeIngestConfig, bronze

from ingestion import organizer
from tests.fixtures.synthetic_pdfs import bcp_statement_pdf


def _bcp_pdf() -> bytes:
    """A synthetic statement with BCP's real `$BOP$` byte prefix (T9), so
    `dispatcher.detect()` recognizes it the way it would a real BCP file."""
    return b"$BOP$" + bcp_statement_pdf()


@pytest.fixture(autouse=True)
def account_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PFP_ACCOUNT_KEY", "test-key")


@pytest.fixture(autouse=True)
def lakehouse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A disk-backed lake (see `lakehouse.storage.storage_options`: a plain
    path means no S3 `storage_options` are built), the same boundary
    `tests/test_cli.py`'s own `lakehouse` fixture uses."""
    lake = tmp_path / "lake"
    monkeypatch.setenv("LAKEHOUSE_URI", str(lake))
    return lake


def test_bronze_config_defaults_come_from_the_same_env_vars_as_the_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_add_inbox_args` in `ingestion/cli.py` defaults `--user` from
    `$PFP_USER`; this config does the same, plus `$PFP_INBOX_ROOT`/
    `$PFP_ARCHIVE_ROOT` (which the CLI only ever gets as explicit flags, e.g.
    from CI) -- so the same environment already exported for `pfp ingest`
    configures the Dagster asset with no extra wiring."""
    monkeypatch.setenv("PFP_USER", "piero")
    monkeypatch.setenv("PFP_INBOX_ROOT", "/tmp/some-inbox")
    monkeypatch.setenv("PFP_ARCHIVE_ROOT", "/tmp/some-archive")

    config = BronzeIngestConfig()

    assert config.user_id == "piero"
    assert config.inbox_root == "/tmp/some-inbox"
    assert config.archive_root == "/tmp/some-archive"


def test_bronze_config_falls_back_to_organizer_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PFP_USER", raising=False)
    monkeypatch.delenv("PFP_INBOX_ROOT", raising=False)
    monkeypatch.delenv("PFP_ARCHIVE_ROOT", raising=False)

    config = BronzeIngestConfig()

    assert config.user_id == ""
    assert config.inbox_root == str(organizer.DEFAULT_INBOX_ROOT)
    assert config.archive_root == str(organizer.DEFAULT_ARCHIVE_ROOT)


def test_bronze_asset_fails_clearly_without_a_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PFP_USER", raising=False)

    with pytest.raises(dg.Failure, match="PFP_USER"):
        dg.materialize(
            [bronze],
            run_config=dg.RunConfig(ops={"bronze": BronzeIngestConfig(user_id="")}),
        )


def test_bronze_asset_organizes_the_inbox_and_writes_to_bronze(
    tmp_path: Path, lakehouse: Path
) -> None:
    from deltalake import DeltaTable

    inbox_root = tmp_path / "inbox"
    archive_root = tmp_path / "raw"
    inbox = inbox_root / "piero"
    inbox.mkdir(parents=True)
    (inbox / "statement.pdf").write_bytes(_bcp_pdf())

    result = dg.materialize(
        [bronze],
        run_config=dg.RunConfig(
            ops={
                "bronze": BronzeIngestConfig(
                    user_id="piero",
                    inbox_root=str(inbox_root),
                    archive_root=str(archive_root),
                )
            }
        ),
    )

    assert result.success
    materialization = result.asset_materializations_for_node("bronze")[0]
    metadata = materialization.metadata
    assert metadata["archived"].value == 1
    assert metadata["statements_written"].value == 1
    assert metadata["files_already_ingested"].value == 0

    table = DeltaTable(str(lakehouse / "bronze" / "transactions")).to_pyarrow_table()
    assert table.num_rows > 0


def test_bronze_asset_second_materialization_writes_nothing_new(
    tmp_path: Path, lakehouse: Path
) -> None:
    """The Dagster equivalent of CI's twice-`pfp ingest` idempotency check
    (T17): re-materializing `bronze` with the identical statement back in the
    inbox must add 0 rows the second time, the same guarantee
    `bronze.is_ingested()` already gives `_run_ingest()`."""
    inbox_root = tmp_path / "inbox"
    archive_root = tmp_path / "raw"
    inbox = inbox_root / "piero"
    inbox.mkdir(parents=True)
    content = _bcp_pdf()
    (inbox / "statement.pdf").write_bytes(content)

    config = BronzeIngestConfig(
        user_id="piero", inbox_root=str(inbox_root), archive_root=str(archive_root)
    )
    dg.materialize([bronze], run_config=dg.RunConfig(ops={"bronze": config}))

    # organize() always moves a processed file out of the inbox (T12b), so the
    # identical bytes are re-seeded before the second pass -- the same reason
    # CI's own ephemeral-integration job re-seeds the fixture between its two
    # `pfp ingest` calls.
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "statement.pdf").write_bytes(content)

    second = dg.materialize([bronze], run_config=dg.RunConfig(ops={"bronze": config}))

    assert second.success
    metadata = second.asset_materializations_for_node("bronze")[0].metadata
    assert metadata["statements_written"].value == 0
    assert metadata["files_already_ingested"].value == 1
