---
type: decision
phase: 1
status: accepted
date: 2026-09-17
---

# ADR 0019: `ephemeral-integration` becomes a required check through an always-run gate job, not directly

## Context

Piero found, by testing it directly on a real PR, that `ephemeral-integration` (T17) — the one
CI job that actually runs a real `pfp ingest` and `dbt build` against live Delta tables — was
never added to the `develop` ruleset's required status checks. A PR touching `dbt/`,
`ingestion/` or `lakehouse/` could be approved and merged while that job sat red.

The obvious fix — add `ephemeral-integration` to the ruleset's required-checks list directly —
runs into the exact reasoning `brain/components/ci.md` already used to justify *not* requiring
`changes`/`benchmarks`: "a skipped job counts as successful even when required." That reasoning
is GitHub's own documented behavior for a job skipped by a job-level `if:` (which is exactly
`ephemeral-integration`'s own `if: needs.changes.outputs.integration == 'true'`, ADR 0008) — but
it is not reliably honored in practice. As of this writing there is an open, acknowledged
inconsistency specifically with *repository rulesets* (the newer replacement for classic branch
protection, which is what this repo uses): a required check left in a "skipped" conclusion is
sometimes not accepted as satisfying the rule, leaving an unrelated PR — one that never touches
the paths that would trigger `ephemeral-integration` at all — blocked from merging indefinitely,
with no clear reason surfaced anywhere in the PR UI. Confirmed via GitHub's own community
discussions and a directly analogous, contemporaneous bug report (a PR touching only
`scripts/`/`.github/workflows/` unable to merge because three required checks reported
`SKIPPED` and the ruleset rejected it), not assumed from the documented behavior alone.

## Decision

**A new job, `ephemeral-integration-gate`, is what the ruleset requires — not
`ephemeral-integration` itself.** It has no `if:` condition of its own beyond `if: always()`
(which overrides the default "only run if everything `needs:` succeeded," so it always runs
regardless of `ephemeral-integration`'s own outcome), reads `needs.ephemeral-integration.result`
directly, and turns that into a pass for `success` *or* `skipped`, a fail for anything else
(`failure`, `cancelled`). This job's own status is never conditional on anything else, so it can
never itself get stuck in the "skipped, and the ruleset won't accept that" state the search
above found — it always posts a real `success` or `failure`, which a ruleset always accepts.

A plain shell `if` inside one `run:` step — five lines — not a third-party action (several
exist for exactly this, e.g. `required-status-check-action`). Not worth a new dependency for
logic this short, the same reasoning this project applies everywhere else (ADR 0002's own "one
less service" preference, `SETUP.md`'s "Don't use `pip install`... never `requirements.txt`"
discipline extended to CI tooling too).

## Alternatives considered

- **Add `ephemeral-integration` to required checks directly**: rejected — the documented
  "skipped counts as success" behavior is exactly what's unreliable with rulesets right now;
  this would risk silently blocking every docs-only, scripts-only, or CI-only PR going forward,
  discovered only when someone hits it (as the linked bug report shows happened elsewhere).
- **Remove `ephemeral-integration`'s own `if:` and always run it, even for unrelated PRs**:
  rejected — defeats ADR 0008's entire point (expensive jobs only run when they can actually be
  affected); would make every PR pay the ~2-minute ephemeral-environment cost regardless of
  what it touches.
- **A third-party "required status check" GitHub Action**: rejected as unnecessary weight for a
  five-line conditional — see Decision.
- **Wrap every impact-based job (`changes`, `benchmarks`, `pr-data-diff`) in the same gate
  pattern, not just `ephemeral-integration`**: rejected for now. `benchmarks` and `pr-data-diff`
  are deliberately warn-only by design (`continue-on-error: true`, CONSTRAINTS.md and ADR 0014
  respectively) — they're not meant to block a merge even when they genuinely fail, so there's
  no correctness gap to close for them the way there was for `ephemeral-integration`. If a
  future task needs another impact-based job to actually gate merges, the same
  `<job>-gate` pattern applies directly; not built ahead of that need.

## Consequences

- The ruleset's required-checks list needs `ephemeral-integration-gate` added (not
  `ephemeral-integration`) — a repository-settings change, not something this PR can make
  itself; Piero applies it once this PR merges, the same way he's the only one who merges a PR
  in the first place.
- `ephemeral-integration-gate` itself has a `timeout-minutes: 2` and does no real work beyond
  one conditional — it should never meaningfully slow down a PR's checks, whether
  `ephemeral-integration` ran for real or was skipped.
- `brain/components/ci.md`'s own "never skip a required job with `if`" note is corrected: the
  documented behavior isn't reliably true for rulesets today, which is precisely why a required
  check now needs to be a job with no conditional skip path of its own, wrapping a job that does.

## Related

- [ADR 0007: Ephemeral per-PR environments](0007-ephemeral-per-pr-environments.md) — the job
  this gate protects.
- [ADR 0008: Impact-based CI](0008-impact-based-ci.md) — why `ephemeral-integration` is
  conditional in the first place, and why `pr-data-diff`/`benchmarks` stay outside this gate
  pattern.
- [ADR 0014: pr-data-diff isolates by URI prefix, not by environment, and always builds in full](0014-pr-data-diff-shared-instance-full-build.md)
  — the sibling job deliberately left ungated, and why.
- [CI](../components/ci.md)
- [Phase 1](../phases/phase-1.md)
