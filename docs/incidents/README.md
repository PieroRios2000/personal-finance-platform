# Incidents

Every surprising error, data loss or near miss gets a short, **blameless** post-mortem here, in
the same PR that fixes its cause (or in its own docs PR): what happened, the impact, how it was
recovered (with the verification), the root cause and what changed so it cannot repeat. The point
is traceability: someone reading the history should be able to tell *why* a rule exists.

Use [`_template.md`](_template.md). One file per incident, named `YYYY-MM-DD-short-slug.md`. No real
data in them: counts and names only ([ADR 0004](../../brain/decisions/0004-real-pdfs-never-leave-your-machine.md)).

| Date | Incident | Impact |
|---|---|---|
| 2026-09-21 | [`make poc-down` wiped the real stack while testing on a throwaway one](2026-09-21-poc-down-wiped-the-real-stack.md) | Lake, tables and Superset metadata deleted; rebuilt from the archive, counts identical |

Operations run on the owner's real environment (pulls, builds, backfills, restarts) are recorded, one
line each, in [`../operations-log.md`](../operations-log.md).
