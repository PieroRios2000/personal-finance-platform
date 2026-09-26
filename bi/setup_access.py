"""Row-level access for the gold datasets (T41, ADR 0036).

Runs inside the Superset container, after the dashboard import (`bi/start.sh`): it
needs each dataset's live id, which the export in `bi/assets` does not carry
(dataset/role permissions and row-level-security rules are not part of a dashboard
export). Idempotent, so a restart is safe -- same as the rest of `start.sh`.

Grants the `Gamma` role read access to the five gold datasets (everyone but the
owner gets Gamma, `bi/superset_config.py`), and creates the one row-level security
rule that filters every query against them to `user_id = '{{ current_username() }}'`,
except for the `Admin` role (the owner). No REST endpoint exists for role/permission
grants (only Superset's own domain objects -- dashboards, charts, datasets -- are in
`/api/v1/`), so this talks to the Superset ORM directly, inside its own app context,
the same way its own `superset fab` and `superset shell` commands do.
"""

from superset.app import create_app

DATABASE_NAME = "PFP gold (read-only)"
TABLES = (
    "rpt_movements",
    "rpt_capital",
    "rpt_balances",
    "rpt_investments",
    "rpt_reconciliation",
)
RLS_NAME = "Per-user data (T41)"
RLS_CLAUSE = "user_id = '{{ current_username() }}'"


def main() -> None:
    app = create_app()
    with app.app_context():
        from superset.connectors.sqla.models import RowLevelSecurityFilter, SqlaTable
        from superset.extensions import db, security_manager
        from superset.utils.core import RowLevelSecurityFilterType

        gamma = security_manager.find_role("Gamma")
        admin = security_manager.find_role("Admin")
        if gamma is None or admin is None:
            raise RuntimeError(
                "Gamma/Admin role missing: run after `superset init` has created them"
            )

        tables = (
            db.session.query(SqlaTable)
            .filter(SqlaTable.table_name.in_(TABLES))
            .join(SqlaTable.database)
            .filter_by(database_name=DATABASE_NAME)
            .all()
        )
        if len(tables) != len(TABLES):
            found = {t.table_name for t in tables}
            raise RuntimeError(f"missing gold dataset(s): {set(TABLES) - found}")

        for table in tables:
            permission_view = security_manager.find_permission_view_menu(
                "datasource_access", table.get_perm()
            )
            if permission_view and permission_view not in gamma.permissions:
                gamma.permissions.append(permission_view)

        rls = (
            db.session.query(RowLevelSecurityFilter)
            .filter_by(name=RLS_NAME)
            .one_or_none()
        ) or RowLevelSecurityFilter(name=RLS_NAME)
        rls.filter_type = RowLevelSecurityFilterType.BASE
        rls.clause = RLS_CLAUSE
        rls.tables = tables
        rls.roles = [admin]
        db.session.add(rls)
        db.session.commit()
        print(f"row-level access: Gamma granted on {len(tables)} gold tables")


if __name__ == "__main__":
    main()
