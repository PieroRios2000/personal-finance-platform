# Quality-bar checks. Rules, thresholds and reasons live in CONSTRAINTS.md;
# if this file and CONSTRAINTS.md disagree, CONSTRAINTS.md wins.
# Lines with "-" are rules in warn mode until 2026-09-26: they show the failure but
# don't stop the recipe. That day the "-" comes off and they start blocking.

BASE ?= origin/develop

.PHONY: check-fast check-task check-full

# After every change (< 5 s): lint, format and types.
check-fast:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy .

# When finishing a task (< 90 s): the above + tests with coverage, floor-guard and architecture.
check-task: check-fast
	uv run pytest --cov --cov-report=term-missing --cov-report=xml
	uv run python scripts/floor_guard.py --base $(BASE)
	-uv run lint-imports --no-logo

# Before the PR: the above + security and coverage of the changed lines. This is what CI
# runs except gitleaks, which runs in pre-commit on every commit (and in CI from T5 on).
check-full: check-task
	-uv run pip-audit
	-uv run bandit -q -r . -x ./.venv --severity-level high
	-uv run diff-cover coverage.xml --compare-branch=$(BASE) --fail-under=80
