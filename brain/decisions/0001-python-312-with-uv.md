---
type: decision
phase: 1
status: accepted
date: 2026-09-12
---

# ADR 0001: Python 3.12 managed with uv

## Context

The system ships Python 3.14. That's too new for part of the stack: dbt has only recently
supported it, with dependency caveats, and Phase 2-3 tools tend to lag behind. The project also
needs to reproduce identically on another machine without depending on the system's Python.

## Decision

Python 3.12 installed and managed by uv, with dependencies in `pyproject.toml` and exact
versions in `uv.lock`, which is committed. Everything installs with `uv sync --locked`.

## Alternatives considered

- **The system's Python 3.14**: risk of incompatibilities with dbt and later-phase tools.
- **pyenv + pip-tools**: two tools for the same job, and pyenv compiles Python from source,
  which requires system-level build dependencies.
- **conda**: heavy, with its own package ecosystem, unnecessary for a Python-only project.

## Consequences

- One tool installs both Python and the libraries, no sudo required (see [SETUP.md](../../SETUP.md)).
- `uv.lock` guarantees the same versions on every machine and in CI; it's committed alongside
  `pyproject.toml`. No `pip install`, no `requirements.txt`.
- Moving to a newer Python means changing `.python-version` and `requires-python`, then passing the checks again.

## Related

- [Python project](../components/python-project.md) — where this applies.
- [Phase 1](../phases/phase-1.md)
