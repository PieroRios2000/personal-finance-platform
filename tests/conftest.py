"""Shared pytest fixtures (T10)."""

from collections.abc import Iterator
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


@pytest.fixture(autouse=True)
def no_real_category_model(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Point the classifier path at an empty temp location, so no test ever loads the
    model trained on the owner's real labels under ~/finance-data (which exists on his
    machine and not in CI). A test that needs a model sets the variable itself.

    Its own MonkeyPatch, not the `monkeypatch` fixture: requesting that one here would
    set it up before every other fixture and undo it after them, which breaks
    teardowns that rely on a test's own env patches being gone by then."""
    empty = tmp_path_factory.mktemp("no-model") / "category_classifier"
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("PFP_CATEGORY_MODEL_PATH", str(empty))
        yield
