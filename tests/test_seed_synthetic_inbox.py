"""Tests for scripts.seed_synthetic_inbox (T17).

`ephemeral-integration`'s idempotency proof (`.github/workflows/ci.yml`) depends
on this script writing back *byte-identical* content every time it runs, so a
second `pfp ingest` sees the same file, not a "regenerated" one. That property
is the one thing worth a unit test here — fpdf2 embeds a fresh /CreationDate on
every render, which would otherwise break it silently.
"""

from pathlib import Path

from scripts.seed_synthetic_inbox import _BOP_PREFIX, main


def test_seeds_a_bcp_recognizable_pdf_into_the_users_inbox(tmp_path: Path) -> None:
    inbox_root = tmp_path / "inbox"

    assert main(["--inbox-root", str(inbox_root), "--user", "ci"]) == 0

    seeded = list((inbox_root / "ci").glob("*.pdf"))
    assert len(seeded) == 1
    assert seeded[0].read_bytes().startswith(_BOP_PREFIX)


def test_seeding_twice_writes_back_byte_identical_content(tmp_path: Path) -> None:
    """The property `ephemeral-integration`'s second `pfp ingest` relies on:
    without this, fpdf2's own /CreationDate timestamp would make every call
    a file with different bytes, so the second `pfp ingest` would have to
    re-parse the archived copy to recognize it (ADR 0024) instead of stopping
    at the hash check, which is what makes "0 new rows" a cheap, exact proof."""
    inbox_root = tmp_path / "inbox"

    main(["--inbox-root", str(inbox_root), "--user", "ci"])
    first = (inbox_root / "ci" / "synthetic-statement.pdf").read_bytes()

    # organize() always moves a processed file out of the inbox (T12b), so
    # nothing is left here for the second pass to find until this seeds again.
    (inbox_root / "ci" / "synthetic-statement.pdf").unlink()
    main(["--inbox-root", str(inbox_root), "--user", "ci"])
    second = (inbox_root / "ci" / "synthetic-statement.pdf").read_bytes()

    assert first == second


def test_seeding_two_different_users_does_not_cross_contaminate(
    tmp_path: Path,
) -> None:
    inbox_root = tmp_path / "inbox"

    main(["--inbox-root", str(inbox_root), "--user", "alice"])
    main(["--inbox-root", str(inbox_root), "--user", "bob"])

    assert (inbox_root / "alice" / "synthetic-statement.pdf").exists()
    assert (inbox_root / "bob" / "synthetic-statement.pdf").exists()
