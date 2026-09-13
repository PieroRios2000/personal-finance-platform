"""Content-based file hashing, so the same PDF is never processed twice."""

import hashlib
from pathlib import Path


def file_sha256(path: Path) -> str:
    """Return the SHA-256 hex digest of the file's content.

    Streams the file with `hashlib.file_digest` instead of loading it into
    memory, so hashing scales to large PDFs.
    """
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()
