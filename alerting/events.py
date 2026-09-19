"""What becomes an alert: a level, where it came from, a name and a count.

Built from dbt's `run_results.json` and from ingest's "needs review" count. The
name is a dbt node's own identifier and the count is a row/file count; dbt's
`message` field (which can quote a value) is deliberately never read.
"""

from dataclasses import dataclass
from typing import Any, Literal

Level = Literal["error", "warn"]

_ERROR_STATUSES = {"error", "fail"}


@dataclass(frozen=True)
class Event:
    level: Level
    source: str
    name: str
    count: int = 1


def _node_name(unique_id: str) -> str:
    """`test.<package>.<name>[.<hash>]` and `model.<package>.<name>` -> `<name>`."""
    parts = unique_id.split(".")
    return parts[2] if len(parts) > 2 else unique_id


def dbt_events(run_results: dict[str, Any]) -> list[Event]:
    events: list[Event] = []
    skipped = 0
    for result in run_results.get("results", []):
        status = result.get("status")
        if status == "skipped":
            skipped += 1
            continue
        if status in _ERROR_STATUSES:
            level: Level = "error"
        elif status == "warn":
            level = "warn"
        else:
            continue
        failures = result.get("failures")
        count = failures if isinstance(failures, int) and failures > 0 else 1
        name = _node_name(result["unique_id"]) if result.get("unique_id") else "unknown"
        events.append(Event(level, "dbt", name, count))
    if skipped:
        # Skipped nodes are the consequence of an error: silver and gold were
        # not built.
        events.append(Event("error", "dbt", "nodes skipped", skipped))
    return events


def ingest_events(*, needs_review: int) -> list[Event]:
    if needs_review <= 0:
        return []
    return [Event("warn", "ingest", "files need review", needs_review)]
