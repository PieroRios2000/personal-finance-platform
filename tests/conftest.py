"""Shared pytest fixtures (T10)."""

from pathlib import Path

import pytest

from tests.fixtures.synthetic_pdfs import bcp_statement_pdf


@pytest.fixture
def bcp_pdf(tmp_path: Path) -> Path:
    """Path to a fictional, unlocked BCP statement PDF with coherent totals.

    Ready for a parser test to read directly (T11): a valid, non-encrypted PDF, no
    password needed. Use `synthetic_pdfs.bcp_statement_pdf` directly for tests that
    need custom movements, an unreconciled statement, or an explicit closing balance.
    """
    path = tmp_path / "bcp-statement.pdf"
    path.write_bytes(bcp_statement_pdf())
    return path
