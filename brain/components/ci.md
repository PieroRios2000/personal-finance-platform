---
type: component
phase: 1
status: in-progress
task: T5
---

# CI

Automated GitHub Actions checks on every PR. Branch policy and quality gates are built; the
rest lands in T15, T17 and T17b (details in the [plan](../../tasks/plan.md)).

## Pieces

| Piece | Status | What it does |
|---|---|---|
| [`branch-policy.yml`](../../.github/workflows/branch-policy.yml) | Built | Only `develop` from this repo may open PRs into `main`; the `check-source-branch` check is required in the `main` and `develop` ruleset |
| [`ci.yml`](../../.github/workflows/ci.yml) (T5) | Built | Five jobs: `lint-types`, `tests` (+ diff-cover), `security` (gitleaks, pip-audit, bandit), `architecture` (import-linter), `floor-guard`; all five required in the ruleset |
| Impact-based CI (T15, ADR 0008) | Planned | Expensive jobs run only when the change affects them |
| Ephemeral environment (T17, T17b, ADR 0007) | Planned | Temporary per-PR platform with synthetic data and a base-vs-PR comparison |

## Details that must not break

- `branch-policy` uses `pull_request_target`: it runs the workflow version already in the repo,
  so a PR cannot edit it to approve itself; it never checks out the PR's code or gets any permissions.
- Never skip a required job with `if`: a skipped job counts as successful even when required.
- No `paths` filters on workflows with required checks: they leave the check in "Pending" and
  block the merge.
- `ci.yml`'s numeric-rule steps (`diff-cover`, `pip-audit`, `bandit`, `import-linter`) carry
  `continue-on-error: true` until 2026-09-26 (per [Quality bar](quality-bar.md)); the job stays
  required in the ruleset the whole time, but only starts actually blocking once T19 removes
  that flag.
- All third-party actions are pinned to a full commit SHA (repo setting
  `sha_pinning_required` enforces this); ruff annotates lines via `--output-format=github`,
  mypy via the problem matcher in `.github/matchers/mypy.json`.

## How to use it and how to verify it

`gh pr checks <n>` and `gh run view <run_id> --log-failed`; see "Reviewing CI" in
[SETUP.md](../../SETUP.md).

## Related

- [Python project](python-project.md) — what CI validates.
- [Security guards](security-guards.md) — the local hooks CI will make mandatory.
- [Phase 1](../phases/phase-1.md)
