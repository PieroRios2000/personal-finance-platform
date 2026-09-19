# Backlog (what is next, in order)

Not a plan: a list so nothing agreed in conversation is lost. Each item becomes its own
branch and PR when it is picked up; see [`CLAUDE.md`](../CLAUDE.md) for how.

## Found on the first real run (2026-09)

- [ ] `scripts/poc.py`: `_safe_dbt_lines` shows no dbt lines on real output (timestamp prefix and
      ANSI colours). Test first with a realistic fixture. Goes with Phase 7.
- [ ] Inbox organizer only reads `inbox/<user>/*.pdf`; PDFs pasted in nested folders are ignored
      silently. Either read subfolders or say so in the report.
- [ ] Decide whether a failing continuity test should skip every downstream node (today one
      failing source test skipped 93 of 127 nodes, silver and gold included).
- [ ] Numeric CI rules leave warn-mode on 2026-09-26 (two-line change).

## Next phases (planned, nothing built)

- [ ] [Phase 7 — Alerting](../brain/phases/phase-7.md): errors and warnings by email or Microsoft
      Teams.
- [ ] [Phase 6 — Savings-goal projection](../brain/phases/phase-6.md): first the Banco Ripley
      parser, then the projection. Scope in [ADR 0025](../brain/decisions/0025-savings-goal-projection-counts-liquid-savings-only.md).
- [ ] Phase 3 (ML), 4 (cloud), 5 (dashboard): see [PROJECT.md](../PROJECT.md).
