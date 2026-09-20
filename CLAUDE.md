# CLAUDE.md

Rules for agents working in this repo. If something here conflicts with another document,
don't pick silently — ask Piero.

## What this is

A local personal-finance platform for a Data Engineering portfolio: bank statement PDFs
(BCP and Scotiabank) → parser → bronze in Delta Lake → silver with dbt.
Fully open source, local, zero cost; real data never leaves Piero's machine.

## Where the context is

Start with your task in `tasks/todo.md` and read only what you need:

| You need | Read |
|---|---|
| How concepts, components and decisions (ADRs) relate | [brain/README.md](brain/README.md) |
| The phase plan, decisions, risks, Definition of Done | [tasks/plan.md](tasks/plan.md) |
| Your task: criteria, verification, files, skill | [tasks/todo.md](tasks/todo.md) |
| Versions, install steps and known issues | [SETUP.md](SETUP.md) |
| Quality rules and thresholds | [CONSTRAINTS.md](CONSTRAINTS.md) |
| The full project's vision and phases | [PROJECT.md](PROJECT.md) |

## Git and PRs

- `main` (production) ← `develop` (integration) ← `<type>/<name>` branches cut from
  `develop` (`feat/`, `fix/`, `test/`, `docs/`, `ci/`, `chore/`, `infra/`, `perf/`).
- **1 task = 1 branch = 1 PR into `develop`.** Never commit directly to `main` or
  `develop`; only `develop` may reach `main` (enforced by the `branch-policy` check).
- **Only Piero approves and merges.** You create branches, commits and PRs; never merge,
  approve or close a PR.
- Small, atomic commits, in English, with a conventional prefix (`feat:`, `fix:`,
  `test:`, `docs:`, `ci:`, `chore:`). Never use `--no-verify`: hooks must pass.
- **TDD for all logic:** commit the failing test first, then the implementation.
- The PR follows `.github/pull_request_template.md` (What / Verification / Notes + checklist),
  with the real output of the commands you ran.
- **All project documentation and code (comments, docstrings, identifiers) is in English**,
  so anyone can pick up the repo. Exception: `HEADERS` in `scripts/inspect_pdf_layout.py` stays
  in Spanish on purpose — those are the literal words printed on the real bank statements.

## Data and privacy

- **Real data never goes into Git or CI.** PDFs live in
  `~/finance-data/` (inbox at `inbox/<user>/`, archive at `raw/<user>/`) and secrets in `.env`
  (template: `.env.example`).
  CI uses synthetic PDFs generated in the tests.
- **Never read, open, or print a real PDF unmasked, or `.env`.** To design parsers, use only
  the masked dump from T9's inspector, and only after Piero has reviewed it.
- gitleaks and the `forbid-data-files` hook are the safety net, not the control: review your diff.

## Tools

- Python 3.12 with uv: `uv sync --locked` and `uv run <command>`.
- Libraries only via `uv add <lib>` (or `uv add --dev <lib>`); never `pip install` or
  `requirements.txt`. `pyproject.toml` and `uv.lock` are committed together.
- Checks: `uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest`
  and `pre-commit run --all-files`, or `make check-task` (lint + types + tests + floor-guard + architecture).
- **`make ci-local` before opening or updating a PR**: it runs CI's own jobs (their steps and
  environment come from `.github/workflows/ci.yml`) in a clean clone of what is committed, with only
  each job's own variables, so a difference between your machine and CI (a missing variable, a file
  that only exists locally) fails there and not on the PR. `make ci-local-full` adds
  `ephemeral-integration` (Docker, ports 8333 and 5432 free) for changes to `dbt/`, `ingestion/`,
  `lakehouse/`, `docker-compose.yml`, `Makefile` or CI itself.
- Skills by kind of work: see "Ways of working" in `tasks/plan.md`.
- The simplest thing that meets the criteria; nothing speculative.

## Definition of Done

The full list is in `tasks/plan.md` and the PR template. In short:

- Task acceptance criteria met and their boxes checked in `tasks/todo.md`.
- Checks green locally (`make ci-local` included) and in CI; behavior verified by running it, not just tests.
- New tests fail without the change and pass with it.
- No real data or secrets in the diff.
- **Brain updated on every PR:** the component or concept note it touches,
  `brain/phases/phase-1.md`, and an ADR in `brain/decisions/` if a decision was made.
- **`SETUP.md` kept current** if the task adds libraries, programs, versions or env vars.
- `ponytail-review` and `review` with no pending findings before opening the PR.

## Known issues

- `gh` 2.46: `gh pr edit` fails → `gh api --method PATCH repos/PieroRios2000/personal-finance-platform/pulls/<n> -f body=...`
- `git push` sometimes fails with "Authentication failed" (Windows Credential Manager):
  retry once, and never print credentials.
- `uv` or `pre-commit` not found → `export PATH="$HOME/.local/bin:$PATH"`.
