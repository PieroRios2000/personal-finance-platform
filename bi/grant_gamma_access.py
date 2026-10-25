"""Grants the Gamma role read access to the gold datasets, for the cloud-only image
(T70, ADR 0050).

Cloud Run has a single shared `viewer` user (Gamma role, `bi/start_cloud.sh`), not one
account per owner (unlike the local image's Dex-mapped accounts): no per-user
row-level-security filter is needed here. But Gamma still needs the base
`datasource_access` grant on each gold dataset -- without it, Gamma has no data access
at all, and the dashboard is invisible to the one user who can ever log in. This is the
read-access half of `bi/setup_access.py` (T41), deliberately without its RLS half.

Idempotent, so a Cloud Run cold start after scaling to zero is safe, same as the rest of
`bi/start_cloud.sh`. Talks to the Superset ORM directly, inside its own app context, the
same way `bi/setup_access.py` does (no REST endpoint exists for role/permission grants).
"""

from superset.app import create_app

DATABASE_NAME = "PFP gold (read-only)"
TABLES = (
    "rpt_movements",
    "rpt_capital",
    "rpt_balances",
    "rpt_investments",
    "rpt_reconciliation",
    "goal_dynamic",
    "rpt_goal_headroom",
    "rpt_category_forecast",
    "rpt_category_variance",
    "rpt_forecast_realized",
    "rpt_income_statement",
)
# Datasets the dashboards no longer use (T65) but a stack that imported an older export
# still holds: granted when present, never required.
RETIRED = ("rpt_goal_projection", "rpt_goal_summary", "rpt_emergency_fund")


def main() -> None:
    app = create_app()
    with app.app_context():
        from superset.connectors.sqla.models import SqlaTable
        from superset.extensions import db, security_manager

        gamma = security_manager.find_role("Gamma")
        if gamma is None:
            raise RuntimeError("Gamma role missing: run after `superset init`")

        tables = (
            db.session.query(SqlaTable)
            .filter(SqlaTable.table_name.in_(TABLES + RETIRED))
            .join(SqlaTable.database)
            .filter_by(database_name=DATABASE_NAME)
            .all()
        )
        found = {t.table_name for t in tables}
        if not set(TABLES) <= found:
            raise RuntimeError(f"missing gold dataset(s): {set(TABLES) - found}")

        for table in tables:
            permission_view = security_manager.find_permission_view_menu(
                "datasource_access", table.get_perm()
            )
            if permission_view and permission_view not in gamma.permissions:
                gamma.permissions.append(permission_view)
        db.session.commit()
        print(f"Gamma granted read access on {len(tables)} gold tables")


if __name__ == "__main__":
    main()
