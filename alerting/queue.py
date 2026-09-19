"""Warnings wait here until the weekly digest. A JSON-lines file outside the
repository holding only source, name, count and time: private to the user
(0700 directory, 0600 file), like the rest of `~/finance-data`."""

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from alerting.events import Event

DEFAULT_QUEUE_PATH = Path.home() / "finance-data" / "alerts" / "warnings.jsonl"


@dataclass(frozen=True)
class Record:
    source: str
    name: str
    count: int
    at: datetime


@dataclass(frozen=True)
class DigestLine:
    source: str
    name: str
    total: int
    runs: int
    first: datetime
    last: datetime


def append(path: Path, events: list[Event], now: datetime) -> None:
    # 0700 only on a directory created here, never on one the user pointed at.
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a") as handle:
        for event in events:
            record = {
                "source": event.source,
                "name": event.name,
                "count": event.count,
                "at": now.isoformat(),
            }
            handle.write(json.dumps(record) + "\n")
    path.chmod(0o600)


def read_counting_skipped(path: Path) -> tuple[list[Record], int]:
    """The records in `path`, and how many lines were skipped because they were
    blank, torn or not the expected shape (one bad line must not poison the
    queue for good)."""
    if not path.exists():
        return [], 0
    records: list[Record] = []
    skipped = 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            records.append(
                Record(
                    str(raw["source"]),
                    str(raw["name"]),
                    int(raw["count"]),
                    datetime.fromisoformat(raw["at"]),
                )
            )
        except (ValueError, KeyError, TypeError):
            skipped += 1
    return records, skipped


def read(path: Path) -> list[Record]:
    return read_counting_skipped(path)[0]


def claim(path: Path) -> Path | None:
    """Move the queue aside (`<name>.sending`) so warnings queued while a digest
    is being sent are not lost. A claim left by a digest that failed is kept:
    it is claimed again, together with whatever was queued since."""
    sending = path.with_name(path.name + ".sending")
    if path.exists():
        if sending.exists():
            with sending.open("a") as handle:
                handle.write(path.read_text())
            path.unlink()
        else:
            path.rename(sending)
    return sending if sending.exists() else None


def clear(path: Path) -> None:
    path.unlink(missing_ok=True)


def summarize(records: list[Record]) -> list[DigestLine]:
    grouped: dict[tuple[str, str], list[Record]] = {}
    for record in records:
        grouped.setdefault((record.source, record.name), []).append(record)
    return [
        DigestLine(
            source,
            name,
            sum(r.count for r in group),
            len(group),
            min(r.at for r in group),
            max(r.at for r in group),
        )
        for (source, name), group in sorted(grouped.items())
    ]
