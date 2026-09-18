"""The bronze Dagster asset (T21).

Wraps `organizer.organize()` and `bronze.write_statement()` directly -- the
same two calls `ingestion.cli._run_ingest()` already makes to implement `pfp
ingest` -- as one Dagster asset. Not a reimplementation of either function and
not a shelled-out `subprocess.run(["pfp", "ingest"])`: this is that same loop,
returned as Dagster materialization metadata instead of printed to stdout.

`BronzeIngestConfig` defaults from the same `PFP_USER`/`PFP_INBOX_ROOT`/
`PFP_ARCHIVE_ROOT` environment variables `ingestion/cli.py`'s
`_add_inbox_args()` (`PFP_USER`) and CI's own `ephemeral-integration` job
(all three, as explicit `pfp ingest` flags) already use -- so the same
environment already exported for the CLI configures this asset with no
separate wiring to keep in sync. See `brain/components/dagster.md` for why
env vars, not Dagster run-config JSON, carry these three values.
"""

import os
from pathlib import Path

import dagster as dg
from pydantic import Field

from ingestion import organizer
from lakehouse import bronze as bronze_lakehouse


class BronzeIngestConfig(dg.Config):
    """Same three inputs `pfp ingest` takes, defaulted from the environment
    the same way. Each `default_factory` reads its env var at config
    construction time (once per materialization), not at import time, so a
    run started after exporting `.env` picks up its values."""

    user_id: str = Field(default_factory=lambda: os.environ.get("PFP_USER", ""))
    inbox_root: str = Field(
        default_factory=lambda: os.environ.get(
            "PFP_INBOX_ROOT", str(organizer.DEFAULT_INBOX_ROOT)
        )
    )
    archive_root: str = Field(
        default_factory=lambda: os.environ.get(
            "PFP_ARCHIVE_ROOT", str(organizer.DEFAULT_ARCHIVE_ROOT)
        )
    )


@dg.asset(
    description=(
        "Organizes a user's inbox (ingestion.organizer.organize) and writes every "
        "newly archived statement to bronze (lakehouse.bronze.write_statement) -- "
        "the same two calls `pfp ingest` makes."
    )
)
def bronze(
    context: dg.AssetExecutionContext, config: BronzeIngestConfig
) -> dg.MaterializeResult[None]:
    if not config.user_id:
        raise dg.Failure("PFP_USER is required (config.user_id, or set $PFP_USER)")

    report = organizer.organize(
        config.user_id,
        inbox_root=Path(config.inbox_root),
        archive_root=Path(config.archive_root),
    )
    context.log.info(report.render())

    # Mirrors `ingestion.cli._run_ingest()`'s own loop verbatim: `written`
    # counts statements, `skipped` counts files already in bronze
    # (`bronze.is_ingested()`), since one archived file can carry several
    # statements (T18).
    written = 0
    skipped = 0
    for item in report.archived:
        if bronze_lakehouse.is_ingested(config.user_id, item.sha256):
            skipped += 1
            continue
        for statement in item.statements:
            bronze_lakehouse.write_statement(statement, item.sha256)
            written += 1

    return dg.MaterializeResult(
        metadata={
            "archived": len(report.archived),
            "duplicates": len(report.duplicates),
            "needs_review": len(report.needs_review),
            "statements_written": written,
            "files_already_ingested": skipped,
        }
    )
