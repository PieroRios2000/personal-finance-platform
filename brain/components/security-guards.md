---
type: component
phase: 1
status: built
task: T1
---

# Security guards

Keep real data or secrets from ever reaching Git, before any code exists to handle them.

## Pieces

| Piece | What it does |
|---|---|
| [`.gitignore`](../../.gitignore) | Ignores `.env`, keys, PDFs (case-insensitive), `data/`, DuckDB files, Parquet and `_delta_log/` |
| [`.pre-commit-config.yaml`](../../.pre-commit-config.yaml) | Before every commit: gitleaks and detect-private-key (secrets), check-added-large-files, `forbid-data-files` (blocks PDF, DuckDB and Parquet even with `git add -f`), and ruff |
| [`.env.example`](../../.env.example) | Variable template with no real values; the values live in `.env`, gitignored and chmod 600 |

Hook versions are pinned to a commit SHA, not to a tag that could move.

## How to use it and how to verify it

`pre-commit run --all-files`. T1 proved that a fake token, a fake private key and a PDF forced
in with `git add -f` all get blocked. They become mandatory in CI in T5.

## Related

- [ADR 0004: Real PDFs](../decisions/0004-real-pdfs-never-leave-your-machine.md) — the decision these guards enforce.
- [Python project](python-project.md) — ruff runs in the same hooks.
- [CI](ci.md) — where these checks become mandatory.
- [Phase 1](../phases/phase-1.md)
