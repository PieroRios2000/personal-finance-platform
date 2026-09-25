# Rebuild the lake and the tables from your archive

Use this when the lake (S3) or PostgreSQL is gone or wrong (a `make poc-down`, a broken volume, a new
machine). **Nothing here needs anything but what already lives outside the containers**: your archived
statement PDFs (`~/finance-data/raw/<user>/`, never deleted), the manual Excel
(`~/finance-data/manual/`), `.env` and the repository. Everything else (bronze, silver, gold, the
dashboards) is derived and comes back. Print only counts when you compare ([ADR 0004](../brain/decisions/0004-real-pdfs-never-leave-your-machine.md)).

**Before you start:** write down the per-account movement counts from the dashboard or with
`select bank, currency, account_last4, count(*) from gold.fact_transactions group by 1,2,3`, to compare at
the end. If a volume is already gone, use the last counts you recorded in [`operations-log.md`](operations-log.md).

## Steps

For a non-default environment add `PFP_ENV=dev` (or `prod`) to every `make` command and use `make ingest` /
`make build` instead of sourcing `.env` by hand ([SETUP.md section 14](../SETUP.md#14-dev-and-prod-environments-t38)).

```bash
git pull                                   # be on the latest develop, with `uv sync --locked`
make up                                    # storage + Postgres + Superset, empty (SETUP.md section 13)
set -a && source .env && set +a

# 1. archived PDFs back to the inbox (`mv`, never `cp`: an inbox copy of an archived file is a duplicate)
mkdir -p ~/finance-data/inbox/$PFP_USER && i=0
find ~/finance-data/raw/$PFP_USER -type f -name '*.pdf' -not -path '*/_duplicates/*' -not -path '*/_needs_review/*' |
  while read -r f; do i=$((i+1)); mv "$f" ~/finance-data/inbox/$PFP_USER/restored-$i.pdf; done

# 2. bronze from the PDFs (they are filed back into the archive)
uv run pfp ingest --user "$PFP_USER"
# expect: "Archived: N  Duplicates: 0  Needs review: 0"; N is the number of files you moved

# 3. the manual Excel (savings and investments), if you use it
uv run pfp import-manual ~/finance-data/manual/<your-workbook>.xlsx --user "$PFP_USER"

# 4. silver and gold
uv run dbt build --project-dir dbt --profiles-dir dbt
# expect: PASS=all, ERROR=0

make bi-down && make bi-up                 # only if Superset was running: re-imports bi/assets
```

## Verify

- The per-account movement counts equal the ones you wrote down.
- `select count(*) filter (where difference <> 0) from gold.rpt_reconciliation` is 0 (every account
  reconciles to its opening balance).
- The dashboard opens and shows the last closed month.

## What is not recovered

Superset's own users and anything built by hand in its UI (dashboards are code and come back), and
Elementary's anomaly baselines (they start over; the tests run in warn mode).
