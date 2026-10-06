"""Renders `bi/sql/goal_dynamic.sql` the way Superset does, for the tests: Jinja with
`filter_values` answering from a dict of native-filter values."""

from collections.abc import Mapping, Sequence
from pathlib import Path

from jinja2.sandbox import SandboxedEnvironment

SQL_FILE = Path(__file__).resolve().parent.parent / "bi" / "sql" / "goal_dynamic.sql"


def render(filters: Mapping[str, Sequence[object]] | None = None) -> str:
    values = filters or {}

    def filter_values(
        column: str,
        default: Sequence[object] | None = None,
        remove_filter: bool = False,
    ) -> list[object]:
        return list(values.get(column, default or []))

    return (
        SandboxedEnvironment()
        .from_string(SQL_FILE.read_text())
        .render(filter_values=filter_values, current_username=lambda: "piero")
    )
