"""Seeds one synthetic, fictional BCP statement into a user's inbox (T17).

`ephemeral-integration` (`.github/workflows/ci.yml`) runs `pfp ingest` twice in a
row against whatever this script drops in the inbox: the point is that the
*second* run adds 0 new rows to bronze, proving `pfp ingest` is idempotent
against the real platform, not a mock of it (ADR 0007). Run it again before the
second `pfp ingest` to put the same content back — `organize()` (T12b) always
moves a processed file out of the inbox, so there is nothing left for a second
`pfp ingest` to see otherwise.

Only ever synthetic, fictional data (`tests.fixtures.synthetic_pdfs`, T10) — the
same generator dozens of unit tests already depend on, never a real PDF
(CLAUDE.md's "Data and privacy").

    uv run python -m scripts.seed_synthetic_inbox --inbox-root DIR --user NAME
"""

import argparse
from collections.abc import Sequence
from pathlib import Path

from tests.fixtures.synthetic_pdfs import bcp_statement_pdf

# BCP's own real byte prefix (T9, confirmed from the masked layout inspection):
# ingestion.parsers.bcp.detect() looks for exactly this at the start of the
# file, and fpdf2's output never carries it, so a synthetic fixture that needs
# to be recognized as a BCP statement adds it by hand — the same trick
# tests/test_cli.py's _bcp_pdf() helper uses.
_BOP_PREFIX = b"$BOP$"

# A fixed filename: the fixture's bytes are already deterministic (T10's
# DEFAULT_MOVEMENTS), so re-running this script writes byte-identical content
# every time, which is what makes the second `pfp ingest` a real idempotency
# check rather than a fresh statement.
_FILENAME = "synthetic-statement.pdf"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inbox-root", type=Path, required=True, help="e.g. /tmp/pfp-ci-inbox"
    )
    parser.add_argument("--user", required=True)
    args = parser.parse_args(argv)

    inbox = args.inbox_root / args.user
    inbox.mkdir(parents=True, exist_ok=True)

    # Cached once per --inbox-root, next to (not inside) any user's inbox, so a
    # second call writes back byte-identical content. fpdf2 embeds a fresh
    # /CreationDate on every render, which would otherwise make each call look
    # like a *different*, regenerated statement (organize()'s version-2 path,
    # T12b) instead of the same file seen twice -- exactly what a second
    # `pfp ingest` needs to see to prove idempotent.
    cache = args.inbox_root / ".synthetic-statement-cache.pdf"
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(_BOP_PREFIX + bcp_statement_pdf())

    (inbox / _FILENAME).write_bytes(cache.read_bytes())
    print(f"seeded {inbox / _FILENAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
