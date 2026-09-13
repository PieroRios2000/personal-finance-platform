"""Tests for the `pfp` CLI (T12)."""

from pathlib import Path

import pytest

from ingestion.cli import main
from tests.fixtures.synthetic_pdfs import bcp_statement_pdf


@pytest.fixture(autouse=True)
def account_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PFP_ACCOUNT_KEY", "test-key")


def _bcp_pdf(*, reconciles: bool = True) -> bytes:
    """A synthetic statement with BCP's real `$BOP$` byte prefix (T9), so
    `dispatcher.detect()` recognizes it the way it would a real BCP file."""
    return b"$BOP$" + bcp_statement_pdf(reconciles=reconciles)


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
