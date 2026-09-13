"""Parsing benchmark: a multi-page synthetic BCP statement (T15).

Deselected from the normal test run (`benchmark` marker, see `pyproject.toml`'s
`addopts`) and run on its own by CI's `benchmarks` job, which measures the base
branch and the PR on the same runner and fails if the mean gets more than 20%
worse (CONSTRAINTS.md's "Performance" rule).

The statement is the same synthetic fixture the parser tests use (T10, ADR
0004: no real PDF ever reaches Git or CI), just with enough movements to span
several pages — a real statement is 4 pages, and per-page word extraction and
line grouping are most of what `bcp.parse()` spends its time on.
"""

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path

import pdfplumber
import pytest
from pytest_benchmark.fixture import BenchmarkFixture

from ingestion.parsers import bcp
from tests.fixtures.synthetic_pdfs import Movement, bcp_statement_pdf

pytestmark = pytest.mark.benchmark

# Enough rows to fill more than two pages of the fixture's table.
ROWS = 120
PAGES = 3

MOVEMENTS = tuple(
    Movement(
        date(2026, 1, 1 + index % 28),
        f"MOVIMIENTO FICTICIO {index:03d}",
        Decimal("-1.50") if index % 2 else Decimal("2.50"),
    )
    for index in range(ROWS)
)


@pytest.fixture(scope="module")
def statement_pdf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A fictional BCP statement with `ROWS` movements, rendered once."""
    path = tmp_path_factory.mktemp("benchmarks") / "bcp-statement.pdf"
    path.write_bytes(bcp_statement_pdf(movements=MOVEMENTS))
    return path


def test_the_benchmarked_statement_really_spans_several_pages(
    statement_pdf: Path,
) -> None:
    """Guards the benchmark's own premise: if the fixture ever stopped
    paginating, this would quietly become a single-page measurement."""
    with pdfplumber.open(statement_pdf) as document:
        assert len(document.pages) >= PAGES


def test_parse_a_multipage_statement(
    benchmark: BenchmarkFixture,
    statement_pdf: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PFP_ACCOUNT_KEY", "benchmark-key")
    file_sha256 = hashlib.sha256(statement_pdf.read_bytes()).hexdigest()

    statement = benchmark(
        bcp.parse, statement_pdf, user_id="benchmark", file_sha256=file_sha256
    )

    assert len(statement.transactions) == ROWS
