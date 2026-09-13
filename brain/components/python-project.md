---
type: component
phase: 1
status: built
task: T2
---

# Python project

The foundation for all the code: Python 3.12 managed by uv, pinned dependencies and quality tools.

## Pieces

| Piece | What it does |
|---|---|
| [`pyproject.toml`](../../pyproject.toml) | Direct dependencies (runtime: pydantic; dev: pytest, pytest-cov, ruff, mypy) and config for ruff, strict mypy and pytest |
| [`uv.lock`](../../uv.lock) | The exact version and hash of every library, including transitive ones |
| [`.python-version`](../../.python-version) | Pins Python 3.12 |
| `ingestion/`, `lakehouse/` | Pipeline packages, empty until Block B |
| [`tests/test_smoke.py`](../../tests/test_smoke.py) | Checks the packages import |

There is no `build-system` yet: tests find the packages via `pythonpath = ["."]`. Packaging
lands in T12, with the `pfp` command.

## How to use it and how to verify it

Full setup in [SETUP.md](../../SETUP.md). Checks:
`uv run ruff check . && uv run mypy . && uv run pytest`.

## Related

- [ADR 0001: Python 3.12 with uv](../decisions/0001-python-312-with-uv.md) — why this version and this tool.
- [Security guards](security-guards.md) — share the same pre-commit hooks.
- [CI](ci.md) — will run these same checks on every PR.
- [Phase 1](../phases/phase-1.md)
