---
type: component
phase: 1
status: built
task: T4
---

# Quality bar

Writes down what "ready to merge" means, with numbers and the command that checks them, so
neither a person nor an agent can lower the bar without it being noticed.

## Pieces

| Piece | What it does |
|---|---|
| [`CONSTRAINTS.md`](../../CONSTRAINTS.md) | The contract: the floor, a table of numeric rules (threshold, command, where it runs, warn or block), measured metrics and exceptions |
| [`Makefile`](../../Makefile) | `check-fast` (< 5 s), `check-task` (< 90 s) and `check-full` (what CI runs except gitleaks, which runs in pre-commit), all through `uv run` |
| [`scripts/floor_guard.py`](../../scripts/floor_guard.py) | Checks the diff against the base branch and fails if the bar dropped: new suppressions, disabled or deleted tests, relaxed config, lowered thresholds |
| [`tests/test_floor_guard.py`](../../tests/test_floor_guard.py) | Tests every move floor-guard must catch, in a temporary git repo |
| [`pyproject.toml`](../../pyproject.toml) | import-linter contracts between `ingestion` and `lakehouse`, and the coverage source |

## How to use it and how to verify it

- After every change: `make check-fast`. When finishing a task: `make check-task` (part of
  the Definition of Done). Before opening the PR: `make check-full`.
- Numeric rules carry a `-` in the Makefile: they show the failure without stopping the recipe
  until 2026-09-26; that day the `-` comes off and they start blocking.
- If a rule can't be met, an exception is requested in `CONSTRAINTS.md` (rule, file, reason,
  who approved it, review date). floor-guard honors it while the row exists; the date is a
  reminder to review it.
- Verification: all three recipes pass on the current code, and a `# type: ignore` injected on
  purpose makes floor-guard fail with exit code 1.

## Related

- [Python project](../components/python-project.md) — ruff, mypy and pytest this bar uses.
- [CI](../components/ci.md) — will run `check-full` on every PR (T5).
- [Phase 1](../phases/phase-1.md)
