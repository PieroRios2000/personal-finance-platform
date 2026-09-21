# Operations log

One line for each operation run on the owner's real environment (a pull, a build, a backfill, a
restart, a rebuild), newest last: **date · what · result (counts only) · why/where recorded**. Changes to the
code live in the PRs and ADRs; this file is for what was *run* on the real data, so the state of the
environment can be traced. No amounts, descriptions or account numbers ([ADR 0004](../brain/decisions/0004-real-pdfs-never-leave-your-machine.md)).

| Date | Operation | Result | Notes |
|---|---|---|---|
| 2026-09-20 | `git pull` (develop), `dbt build`, `make bi-down && make bi-up` after the Superset PR | dbt 156/156; Superset healthy | first dashboard on the real data |
| 2026-09-20 | `pfp backfill --dry-run`, then `pfp backfill` (BCP currency read from the PDF; Scotiabank card keeps the first date column, PRs #110, #111) | 83 files scanned, 83 replaced, 0 failed (5 Scotiabank files changed content: dates); `dbt build` 163/163 | BCP account in dollars now USD (144 movements, 24 statements) |
| 2026-09-20 | `dbt build` after "only closed months" (PR #113) | 163/163; last closed month 2026-08 | |
| 2026-09-21 | `git pull`, `dbt build`, `make bi-down && make bi-up` (PR #115: reconciliation) | 166/166; 8 accounts reconciled, 0 differences | |
| 2026-09-21 | **Incident:** `make poc-down` ran on the real stack | lake, Postgres, Superset metadata deleted | [post-mortem](incidents/2026-09-21-poc-down-wiped-the-real-stack.md) |
| 2026-09-21 | **Rebuild from the archive** ([runbook](runbook-rebuild-from-archive.md)) | 83 PDFs re-ingested (0 duplicates, 0 review), 88 statements; manual Excel: 3 savings statements, 7 investment months; `dbt build` 166/166 | per-account movement counts identical to before (1,627 in total), 8 accounts reconciled |
| 2026-09-21 | `git pull` (PR #116), `make up` | one project `pfp-poc`, Superset healthy; old `pfp-bi` stopped; 1,627 movements and 8 reconciled accounts after | first run of the one-command stack |
