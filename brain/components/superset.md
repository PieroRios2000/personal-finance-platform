---
type: component
phase: 2
status: built
task: T32
---

# Superset

Dashboards over the gold reporting tables: summary cards, cash flow, balances, and each fund's monthly
return with `closing_basis`, all under one calendar filter bar. Optional local infrastructure; CI never runs it. Design in
[ADR 0030](../decisions/0030-superset-for-dashboards-over-the-read-only-role.md).

## Pieces

| Piece | What it does |
|---|---|
| [`bi/docker-compose.yml`](../../bi/docker-compose.yml) | Project `pfp-bi`: `bi-init` (creates Superset's role and database) and `superset` (port 8088 on 127.0.0.1). Joins the network of PFP's Postgres (`pfp-poc_default`, `PFP_NETWORK`) |
| [`bi/Dockerfile`](../../bi/Dockerfile) | `apache/superset:5.0.0` plus the Postgres driver the official image lacks |
| [`bi/superset_config.py`](../../bi/superset_config.py) | Secret key and metadata database URI, from the environment |
| [`bi/init-metadata.sh`](../../bi/init-metadata.sh) | Idempotent: the `superset` role and database in PFP's Postgres |
| [`bi/start.sh`](../../bi/start.sh) | Migrate, create admin, import `bi/assets` (password filled in from the environment), serve |
| [`bi/assets/`](../../bi/assets) | The dashboards as code: Superset's export YAML (database, three `rpt_*` datasets, eight charts, one dashboard with its filters and CSS) |
| [`bi/templates/`](../../bi/templates) | The HTML (Handlebars) and CSS of the summary cards and the investments table, and the dashboard-wide CSS |
| [`bi/cleanup_stale.py`](../../bi/cleanup_stale.py) | Run by `start.sh` after the import: removes the dashboard's charts that are not in the export, and our datasets no chart uses |
| [`bi/build_dashboards.py`](../../bi/build_dashboards.py) | How the export is authored: REST API, then export. `make bi-export` |
| [`dbt/models/gold/fct_account_balance_monthly.sql`](../../dbt/models/gold/fct_account_balance_monthly.sql) | Closing balance per account, currency and month, for the savings chart |
| `make bi-up` / `bi-down` / `bi-reset` / `bi-export` | Start, stop, forget Superset's own state, re-export the dashboards |

## Related

[dbt gold](dbt-gold.md), [Investment tracking](investment-tracking.md),
[OpenMetadata](openmetadata.md) (same network trick), [ADR 0029](../decisions/0029-dbt-stores-silver-and-gold-in-postgres.md).
