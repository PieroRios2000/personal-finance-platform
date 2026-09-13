"""Tests for ingestion.dedup: content-based file hashing (T7)."""

import hashlib
from pathlib import Path

from ingestion.dedup import file_sha256


def test_same_content_under_different_names_hashes_the_same(tmp_path: Path) -> None:
    content = b"same statement content"
    file_a = tmp_path / "statement.pdf"
    file_b = tmp_path / "statement (1).pdf"
    file_a.write_bytes(content)
    file_b.write_bytes(content)

    assert file_sha256(file_a) == file_sha256(file_b)


def test_different_content_hashes_differently(tmp_path: Path) -> None:
    file_a = tmp_path / "january.pdf"
    file_b = tmp_path / "february.pdf"
    file_a.write_bytes(b"january statement")
    file_b.write_bytes(b"february statement")

    assert file_sha256(file_a) != file_sha256(file_b)


def test_hashes_a_large_file_correctly(tmp_path: Path) -> None:
    large_file = tmp_path / "large.bin"
    content = b"0123456789" * 1_000_000  # 10 MB
    large_file.write_bytes(content)

    assert file_sha256(large_file) == hashlib.sha256(content).hexdigest()
