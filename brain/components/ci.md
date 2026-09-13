---
type: component
phase: 1
status: in-progress
task: T5
---

# CI

Automated GitHub Actions checks on every PR. Today only the branch policy exists; the rest
lands in T5, T15, T17 and T17b (details in the [plan](../../tasks/plan.md)).

## Pieces

| Piece | Status | What it does |
|---|---|---|
| [`branch-policy.yml`](../../.github/workflows/branch-policy.yml) | Built | Only `develop` from this repo may open PRs into `main`; the `check-source-branch` check is required in the `main` and `develop` ruleset |
| Quality checks (T5) | Planned | Lint, types, tests with coverage, security and architecture; failures annotated on the PR line |
| Impact-based CI (T15, ADR 0008) | Planned | Expensive jobs run only when the change affects them |
| Ephemeral environment (T17, T17b, ADR 0007) | Planned | Temporary per-PR platform with synthetic data and a base-vs-PR comparison |

## Details that must not break

- `branch-policy` uses `pull_request_target`: it runs the workflow version already in the repo,
  so a PR cannot edit it to approve itself; it never checks out the PR's code or gets any permissions.
- Never skip it with `if`: a skipped job counts as successful even when it is required.
- No `paths` filters on workflows with required checks: they leave the check in "Pending" and
  block the merge.

## How to use it and how to verify it

`gh pr checks <n>` and `gh run view <run_id>`; a failed job's log is fetched from the API (see
"Known issues" in [SETUP.md](../../SETUP.md)).

## Related

- [Python project](python-project.md) — what CI validates.
- [Security guards](security-guards.md) — the local hooks CI will make mandatory.
- [Phase 1](../phases/phase-1.md)
