"""Tests for the `pfp` CLI (T12, T14, T14c)."""

import io
from pathlib import Path

import pikepdf
import pytest
from fpdf import FPDF

from ingestion.cli import main
from tests.fixtures.synthetic_pdfs import bcp_statement_pdf


@pytest.fixture(autouse=True)
def account_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PFP_ACCOUNT_KEY", "test-key")


@pytest.fixture(autouse=True)
def lakehouse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A disk-backed lake for every test (see lakehouse.storage.storage_options:
    a plain path means no S3 storage_options are built)."""
    lake = tmp_path / "lake"
    monkeypatch.setenv("LAKEHOUSE_URI", str(lake))
    return lake


def _bcp_pdf(*, reconciles: bool = True) -> bytes:
    """A synthetic statement with BCP's real `$BOP$` byte prefix (T9), so
    `dispatcher.detect()` recognizes it the way it would a real BCP file."""
    return b"$BOP$" + bcp_statement_pdf(reconciles=reconciles)


def _unparseable_bcp_pdf() -> bytes:
    """A PDF that BCP's `detect()` claims (the `$BOP$` prefix) but its `parse()`
    can't read: a valid PDF with no transaction table in it at all."""
    pdf = FPDF(unit="pt")
    pdf.add_page()
    pdf.set_font("Helvetica", size=9)
    pdf.text(40, 50, "ESTADO DE CUENTA")
    return b"$BOP$" + bytes(pdf.output())


def _archived(archive_root: Path, relative: str, content: bytes | None = None) -> Path:
    """Put a PDF where `pfp organize` would already have filed it:
    `<archive_root>/<user>/<bank>/<last4>-<id6>/<start>_<end>.pdf` (ADR 0009)."""
    dest = archive_root / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_bcp_pdf() if content is None else content)
    return dest


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    code = main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_parse_prints_a_summary_and_reconciliation_ok(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "statement.pdf"
    path.write_bytes(_bcp_pdf())

    code, out, _ = run(capsys, "parse", str(path), "--user", "piero")

    assert code == 0
    assert "BCP" in out
    assert "0000" in out  # last 4 of the fixture's fake account
    assert "2026-01-05" in out and "2026-01-28" in out
    assert "Reconciliation: OK" in out


def test_parse_uses_pfp_user_when_no_flag_is_given(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PFP_USER", "piero")
    path = tmp_path / "statement.pdf"
    path.write_bytes(_bcp_pdf())

    code, out, _ = run(capsys, "parse", str(path))

    assert code == 0
    assert "Reconciliation: OK" in out


def test_parse_fails_clearly_without_a_user(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PFP_USER", raising=False)
    path = tmp_path / "statement.pdf"
    path.write_bytes(_bcp_pdf())

    code, _, err = run(capsys, "parse", str(path))

    assert code != 0
    assert "--user" in err


def test_parse_reports_an_unrecognized_bank(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "unknown.pdf"
    path.write_bytes(b"not a recognizable statement at all")

    code, _, err = run(capsys, "parse", str(path), "--user", "piero")

    assert code != 0
    assert err  # some error explaining nothing recognized it


def test_parse_reports_a_reconciliation_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "broken.pdf"
    path.write_bytes(_bcp_pdf(reconciles=False))

    code, _, err = run(capsys, "parse", str(path), "--user", "piero")

    assert code != 0
    assert "reconciliation" in err.lower()


def test_parse_gives_the_same_result_under_an_arbitrary_file_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    content = _bcp_pdf()
    normal = tmp_path / "statement.pdf"
    odd = tmp_path / "EECC (3).pdf"
    normal.write_bytes(content)
    odd.write_bytes(content)

    _, out_normal, _ = run(capsys, "parse", str(normal), "--user", "piero")
    _, out_odd, _ = run(capsys, "parse", str(odd), "--user", "piero")

    assert out_normal == out_odd


def test_organize_files_the_inbox_and_prints_the_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inbox_root = tmp_path / "inbox"
    archive_root = tmp_path / "raw"
    inbox = inbox_root / "piero"
    inbox.mkdir(parents=True)
    (inbox / "statement.pdf").write_bytes(_bcp_pdf())

    code, out, _ = run(
        capsys,
        "organize",
        "--user",
        "piero",
        "--inbox-root",
        str(inbox_root),
        "--archive-root",
        str(archive_root),
    )

    assert code == 0
    assert "Archived: 1" in out
    assert list((archive_root / "piero").rglob("*.pdf"))
    assert not list(inbox.glob("*.pdf"))


def test_organize_fails_clearly_without_a_user(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PFP_USER", raising=False)

    code, _, err = run(
        capsys,
        "organize",
        "--inbox-root",
        str(tmp_path / "inbox"),
        "--archive-root",
        str(tmp_path / "raw"),
    )

    assert code != 0
    assert "--user" in err


def test_organize_reports_a_missing_account_key_clearly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PFP_ACCOUNT_KEY", raising=False)
    inbox_root = tmp_path / "inbox"
    archive_root = tmp_path / "raw"
    inbox = inbox_root / "piero"
    inbox.mkdir(parents=True)
    (inbox / "statement.pdf").write_bytes(_bcp_pdf())

    code, _, err = run(
        capsys,
        "organize",
        "--user",
        "piero",
        "--inbox-root",
        str(inbox_root),
        "--archive-root",
        str(archive_root),
    )

    assert code != 0
    assert "PFP_ACCOUNT_KEY" in err


def test_ingest_reports_a_missing_lakehouse_uri_clearly_before_touching_the_inbox(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failing fast on a missing LAKEHOUSE_URI, before organize() moves anything
    out of the inbox, matters: once a file is archived it's no longer picked up
    by a later `pfp ingest` run (organize() only looks at the inbox), so
    crashing mid-run after archiving but before writing to bronze would leave
    that statement stuck outside bronze with no automatic retry."""
    monkeypatch.delenv("LAKEHOUSE_URI", raising=False)
    inbox_root = tmp_path / "inbox"
    archive_root = tmp_path / "raw"
    inbox = inbox_root / "piero"
    inbox.mkdir(parents=True)
    (inbox / "statement.pdf").write_bytes(_bcp_pdf())

    code, _, err = run(
        capsys,
        "ingest",
        "--user",
        "piero",
        "--inbox-root",
        str(inbox_root),
        "--archive-root",
        str(archive_root),
    )

    assert code != 0
    assert "LAKEHOUSE_URI" in err
    assert list(inbox.glob("*.pdf")), "the file must stay in the inbox, untouched"


def test_ingest_organizes_the_inbox_and_writes_to_bronze(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], lakehouse: Path
) -> None:
    from deltalake import DeltaTable

    inbox_root = tmp_path / "inbox"
    archive_root = tmp_path / "raw"
    inbox = inbox_root / "piero"
    inbox.mkdir(parents=True)
    (inbox / "statement.pdf").write_bytes(_bcp_pdf())

    code, out, _ = run(
        capsys,
        "ingest",
        "--user",
        "piero",
        "--inbox-root",
        str(inbox_root),
        "--archive-root",
        str(archive_root),
    )

    assert code == 0
    assert "Archived: 1" in out
    assert "Bronze: 1 statement(s) written, 0 already ingested" in out

    table = DeltaTable(str(lakehouse / "bronze" / "transactions")).to_pyarrow_table()
    assert table.num_rows > 0


def test_ingest_fails_clearly_without_a_user(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PFP_USER", raising=False)

    code, _, err = run(
        capsys,
        "ingest",
        "--inbox-root",
        str(tmp_path / "inbox"),
        "--archive-root",
        str(tmp_path / "raw"),
    )

    assert code != 0
    assert "--user" in err


def test_ingest_reports_a_missing_account_key_clearly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PFP_ACCOUNT_KEY", raising=False)
    inbox_root = tmp_path / "inbox"
    archive_root = tmp_path / "raw"
    inbox = inbox_root / "piero"
    inbox.mkdir(parents=True)
    (inbox / "statement.pdf").write_bytes(_bcp_pdf())

    code, _, err = run(
        capsys,
        "ingest",
        "--user",
        "piero",
        "--inbox-root",
        str(inbox_root),
        "--archive-root",
        str(archive_root),
    )

    assert code != 0
    assert "PFP_ACCOUNT_KEY" in err


def test_ingest_does_not_duplicate_rows_for_a_file_already_in_bronze(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], lakehouse: Path
) -> None:
    """Ingesting the same PDF content twice adds 0 rows the second time (T14),
    even in the edge case organizer.py's own dedup can't catch on its own: the
    previously archived file is gone from raw/ (e.g. manually deleted), so the
    same PDF dropped into the inbox again gets re-archived, but bronze still
    remembers its sha256 and skips writing it again."""
    from deltalake import DeltaTable

    inbox_root = tmp_path / "inbox"
    archive_root = tmp_path / "raw"
    inbox = inbox_root / "piero"
    inbox.mkdir(parents=True)
    content = _bcp_pdf()
    (inbox / "statement.pdf").write_bytes(content)

    run(
        capsys,
        "ingest",
        "--user",
        "piero",
        "--inbox-root",
        str(inbox_root),
        "--archive-root",
        str(archive_root),
    )
    for archived_pdf in (archive_root / "piero").rglob("*.pdf"):
        archived_pdf.unlink()

    (inbox / "statement.pdf").write_bytes(content)
    code, out, _ = run(
        capsys,
        "ingest",
        "--user",
        "piero",
        "--inbox-root",
        str(inbox_root),
        "--archive-root",
        str(archive_root),
    )

    assert code == 0
    assert "Bronze: 0 statement(s) written, 1 already ingested" in out

    table = DeltaTable(str(lakehouse / "bronze" / "statements")).to_pyarrow_table()
    assert table.num_rows == 1


def test_backfill_re_parses_the_archive_and_replaces_the_bronze_rows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], lakehouse: Path
) -> None:
    """The point of T14c: a statement already ingested gets re-parsed from the
    archive and its rows replaced, not appended a second time."""
    from deltalake import DeltaTable

    inbox_root = tmp_path / "inbox"
    archive_root = tmp_path / "raw"
    inbox = inbox_root / "piero"
    inbox.mkdir(parents=True)
    (inbox / "statement.pdf").write_bytes(_bcp_pdf())
    run(
        capsys,
        "ingest",
        "--user",
        "piero",
        "--inbox-root",
        str(inbox_root),
        "--archive-root",
        str(archive_root),
    )
    before = DeltaTable(str(lakehouse / "bronze" / "transactions")).to_pyarrow_table()

    code, out, _ = run(
        capsys, "backfill", "--user", "piero", "--archive-root", str(archive_root)
    )

    assert code == 0
    assert "Scanned: 1" in out
    assert "Replaced: 1" in out
    after = DeltaTable(str(lakehouse / "bronze" / "transactions")).to_pyarrow_table()
    assert after.num_rows == before.num_rows
    statements = DeltaTable(str(lakehouse / "bronze" / "statements")).to_pyarrow_table()
    assert statements.num_rows == 1
    ingested = DeltaTable(
        str(lakehouse / "bronze" / "ingested_files")
    ).to_pyarrow_table()
    assert ingested.num_rows == 1


def test_backfill_walks_the_archive_and_never_the_inbox(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], lakehouse: Path
) -> None:
    """`pfp ingest` is what processes the inbox; backfill only ever looks at
    what `organize()` already filed, and never moves a file."""
    inbox_root = tmp_path / "inbox"
    archive_root = tmp_path / "raw"
    inbox = inbox_root / "piero"
    inbox.mkdir(parents=True)
    (inbox / "statement.pdf").write_bytes(_bcp_pdf())

    code, out, _ = run(
        capsys, "backfill", "--user", "piero", "--archive-root", str(archive_root)
    )

    assert code == 0
    assert "Scanned: 0" in out
    assert (inbox / "statement.pdf").exists()
    assert not (lakehouse / "bronze").exists()


def test_backfill_skips_duplicates_and_needs_review(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`_duplicates/` and `_needs_review/` hold files that were never ingested
    as statements in the first place; re-parsing them isn't backfill's job."""
    archive_root = tmp_path / "raw"
    _archived(archive_root, "piero/BCP/0000-abc123/2026-01-05_2026-01-28.pdf")
    _archived(archive_root, "piero/_duplicates/EECC (1).pdf")
    _archived(archive_root, "piero/_needs_review/EECC (2).pdf")

    code, out, _ = run(
        capsys, "backfill", "--user", "piero", "--archive-root", str(archive_root)
    )

    assert code == 0
    assert "Scanned: 1" in out
    assert "Replaced: 1" in out


def test_backfill_dry_run_reports_what_would_change_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], lakehouse: Path
) -> None:
    archive_root = tmp_path / "raw"
    _archived(archive_root, "piero/BCP/0000-abc123/2026-01-05_2026-01-28.pdf")

    code, out, _ = run(
        capsys,
        "backfill",
        "--user",
        "piero",
        "--archive-root",
        str(archive_root),
        "--dry-run",
    )

    assert code == 0
    assert "Would replace: 1" in out
    assert "0 -> 4 transaction(s)" in out  # nothing in bronze yet vs the fresh parse
    assert not (lakehouse / "bronze").exists(), "a dry run must write nothing"


def test_backfill_bank_filter_matches_the_archive_directory_case_insensitively(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive_root = tmp_path / "raw"
    _archived(archive_root, "piero/BCP/0000-abc123/2026-01-05_2026-01-28.pdf")
    _archived(archive_root, "piero/SCOTIABANK/0000-def456/2026-01-05_2026-01-28.pdf")

    code, out, _ = run(
        capsys,
        "backfill",
        "--user",
        "piero",
        "--archive-root",
        str(archive_root),
        "--bank",
        "bcp",
    )

    assert code == 0
    assert "Scanned: 1" in out
    assert "Replaced: 1" in out


def test_backfill_account_filter_narrows_to_one_account(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], lakehouse: Path
) -> None:
    from deltalake import DeltaTable

    archive_root = tmp_path / "raw"
    _archived(archive_root, "piero/BCP/0000-abc123/2026-01-05_2026-01-28.pdf")
    _archived(
        archive_root,
        "piero/BCP/1111-def456/2026-01-05_2026-01-28.pdf",
        b"$BOP$" + bcp_statement_pdf(account_number="111-11111111-1-11"),
    )

    code, out, _ = run(
        capsys,
        "backfill",
        "--user",
        "piero",
        "--archive-root",
        str(archive_root),
        "--account",
        "1111",
    )

    assert code == 0
    assert "Scanned: 1" in out
    table = DeltaTable(str(lakehouse / "bronze" / "statements")).to_pyarrow_table()
    assert table.column("account_last4").to_pylist() == ["1111"]


def test_backfill_reports_files_it_cannot_re_parse_without_aborting_the_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], lakehouse: Path
) -> None:
    """One bad file must never kill the whole run (the same standard the BCP
    parser's own crash-safety fix set), and its reason is reported by sha256
    prefix, never by the raw content that made it fail."""
    from deltalake import DeltaTable

    archive_root = tmp_path / "raw"
    account = "piero/BCP/0000-abc123"
    _archived(archive_root, f"{account}/2026-01-01_2026-01-02.pdf", b"not a statement")
    _archived(
        archive_root, f"{account}/2026-02-01_2026-02-02.pdf", _unparseable_bcp_pdf()
    )
    _archived(
        archive_root,
        f"{account}/2026-03-01_2026-03-02.pdf",
        _bcp_pdf(reconciles=False),
    )
    _archived(archive_root, f"{account}/2026-04-05_2026-04-28.pdf")

    code, out, _ = run(
        capsys, "backfill", "--user", "piero", "--archive-root", str(archive_root)
    )

    assert code == 0
    assert "Scanned: 4" in out
    assert "Replaced: 1" in out
    assert "Failed: 3" in out
    assert "no bank recognized this file's content" in out
    assert "did not reconcile" in out
    table = DeltaTable(str(lakehouse / "bronze" / "transactions")).to_pyarrow_table()
    assert table.num_rows == 4  # only the one good statement's transactions


def test_backfill_reports_an_archived_statement_it_cannot_unlock(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real BCP statements are password-protected: an archived one whose
    password env var isn't set on this machine is one reported file, not a
    crashed run."""
    monkeypatch.delenv("BCP_PDF_PASSWORD", raising=False)
    locked = io.BytesIO()
    with pikepdf.open(io.BytesIO(bcp_statement_pdf())) as plain:
        plain.save(locked, encryption=pikepdf.Encryption(owner="x", user="synthetic"))
    archive_root = tmp_path / "raw"
    _archived(
        archive_root,
        "piero/BCP/0000-abc123/2026-01-05_2026-01-28.pdf",
        b"$BOP$" + locked.getvalue(),
    )

    code, out, _ = run(
        capsys, "backfill", "--user", "piero", "--archive-root", str(archive_root)
    )

    assert code == 0
    assert "Failed: 1" in out
    assert "BCP_PDF_PASSWORD" in out


def test_backfill_fails_clearly_without_a_user(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PFP_USER", raising=False)

    code, _, err = run(capsys, "backfill", "--archive-root", str(tmp_path / "raw"))

    assert code != 0
    assert "--user" in err


def test_backfill_reports_a_missing_lakehouse_uri_clearly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LAKEHOUSE_URI", raising=False)
    archive_root = tmp_path / "raw"
    _archived(archive_root, "piero/BCP/0000-abc123/2026-01-05_2026-01-28.pdf")

    code, _, err = run(
        capsys, "backfill", "--user", "piero", "--archive-root", str(archive_root)
    )

    assert code != 0
    assert "LAKEHOUSE_URI" in err


def test_backfill_reports_a_missing_account_key_clearly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`PFP_ACCOUNT_KEY` unset isn't a per-file problem — every file would fail
    the same way — so it stops the run, exactly like `organize`/`ingest`."""
    monkeypatch.delenv("PFP_ACCOUNT_KEY", raising=False)
    archive_root = tmp_path / "raw"
    _archived(archive_root, "piero/BCP/0000-abc123/2026-01-05_2026-01-28.pdf")

    code, _, err = run(
        capsys, "backfill", "--user", "piero", "--archive-root", str(archive_root)
    )

    assert code != 0
    assert "PFP_ACCOUNT_KEY" in err
