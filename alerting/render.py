"""The text of an alert. Names are only printed if they are plain identifiers;
anything else is not trusted to be free of data."""

import re

from alerting.events import Event
from alerting.queue import DigestLine

_IDENTIFIER = re.compile(r"[A-Za-z0-9_]+")
_PLAIN_NAMES = {"nodes skipped", "files need review", "build did not complete"}


def _safe(name: str) -> str:
    if name in _PLAIN_NAMES or _IDENTIFIER.fullmatch(name):
        return name
    return "<unnamed>"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def render(events: list[Event]) -> tuple[str, str]:
    errors = sum(1 for e in events if e.level == "error")
    warnings = sum(1 for e in events if e.level == "warn")
    parts = []
    if errors:
        parts.append(_plural(errors, "error"))
    if warnings:
        parts.append(_plural(warnings, "warning"))
    lines = [
        f"{'ERROR' if e.level == 'error' else 'WARN'}  {_safe(e.source)}: "
        f"{_safe(e.name)} ({e.count})"
        for e in events
    ]
    return f"[pfp] {', '.join(parts)}", "\n".join(lines)


def render_digest(lines: list[DigestLine]) -> tuple[str, str]:
    body = []
    for line in lines:
        first, last = f"{line.first:%Y-%m-%d}", f"{line.last:%Y-%m-%d}"
        span = first if first == last else f"{first} to {last}"
        body.append(
            f"WARN  {_safe(line.source)}: {_safe(line.name)} "
            f"({line.total} in {_plural(line.runs, 'run')}, {span})"
        )
    return f"[pfp] weekly digest: {_plural(len(lines), 'kind')} of warning", "\n".join(
        body
    )
