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
| 2026-09-21 | `git pull` (PR #117, #118), `make bi-down && make bi-up` (the `% saved` card) | Superset healthy, 12 charts on the dashboard, 1,627 movements unchanged | recipe read with `make -n` first; no volume touched |
| 2026-09-21 | Clean-clone check for T33 on a **throwaway** project `pfp-t48` (own ports; the real `pfp-poc-*` containers and volumes checked before and after) | `make env`, `make up`, `make demo`: 24 statements + 6 fund months written, `dbt build` 166/166, 88 movements, 3 accounts reconciled with 0 differences, dashboard rendered | not the owner's data; torn down with `docker compose -p pfp-t48 ... down -v` |
| 2026-09-21 | Environments check for T38 on **two throwaway** environments `t51` (demo user) and `t52` (real-style user), own ports, running at the same time as the real `pfp-poc-*` stack (checked before and after) | `make demo` on t51: 24 statements + 6 fund months, `dbt build` 166/166, 88 movements; t52 refused `make demo`, t51 refused `make ingest`; t52 has 0 movements (isolated) | torn down with `docker compose -p pfp-t51 ... down -v` and the same for t52 |
| 2026-09-23 | Dex/Superset OIDC login check for T39 (PR #122) on a **throwaway** project `pfp-test-dex`, own ports, before opening the PR (real `pfp-poc-*` containers and volumes checked before and after) | Full login end to end via curl (Dex local form -> Superset session), `/api/v1/me/` returned the signed-in email with the Admin role; the `admin` REST API account unaffected; found and fixed two bugs (Dex's issuer needs to be the internal address, Superset needs `authlib`) before merging | torn down with `docker compose -p pfp-test-dex ... down -v` |
| 2026-09-23 | `git pull` (PR #122), added the four new Dex/OAuth variables to `.env` (`PFP_BI_OAUTH_CLIENT_SECRET` generated, `DEX_STATIC_PASSWORDS` left empty), `make up` on the real `pfp-poc` stack | `dex`, `postgres`, `seaweedfs`, `superset` all healthy (Superset rebuilt with `authlib`) | sign-in by email now live; no user added to `DEX_STATIC_PASSWORDS` yet |
