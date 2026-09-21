"""Remove what an earlier import left behind (T35). Run by bi/start.sh after the import.

Before the exported uuids were stable, every import created new charts next to the old
ones (30 charts on a dashboard that has 8). This deletes, from our dashboard, the charts
that are not in the export, and then the datasets of our connection that are no longer
in the export and that no chart uses. Nothing else is touched: a chart or dataset the
owner made by hand in Superset stays, unless it is on our dashboard and not in the
export.

    python cleanup_stale.py /tmp/assets
"""

import importlib
import sys
from pathlib import Path

import yaml

DASHBOARD_SLUG = "pfp-finance"
DATABASE_NAME = "PFP gold (read-only)"


def uuids(assets: Path, kind: str) -> set[str]:
    return {
        str(yaml.safe_load(path.read_text())["uuid"])
        for path in (assets / kind).rglob("*.yaml")
    }


def main(assets: Path) -> None:
    keep_charts, keep_datasets = uuids(assets, "charts"), uuids(assets, "datasets")

    # Superset is only installed in its own image, not where the tests and the type
    # checker run, so it is imported by name (its models only inside an app context).
    app_module = importlib.import_module("superset.app")
    superset = importlib.import_module("superset")

    with app_module.create_app().app_context():
        session = superset.db.session
        models = {
            name: importlib.import_module(path)
            for name, path in {
                "sqla": "superset.connectors.sqla.models",
                "core": "superset.models.core",
                "dashboard": "superset.models.dashboard",
                "slice": "superset.models.slice",
            }.items()
        }
        Dataset, Database = models["sqla"].SqlaTable, models["core"].Database
        Dashboard, Chart = models["dashboard"].Dashboard, models["slice"].Slice

        dashboard = session.query(Dashboard).filter_by(slug=DASHBOARD_SLUG).first()
        stale_charts = [
            chart
            for chart in (dashboard.slices if dashboard else [])
            if str(chart.uuid) not in keep_charts
        ]
        for chart in stale_charts:
            session.delete(chart)
        session.commit()

        stale_datasets = 0
        database = (
            session.query(Database).filter_by(database_name=DATABASE_NAME).first()
        )
        for dataset in session.query(Dataset).filter_by(
            database_id=database.id if database else -1
        ):
            in_use = (
                session.query(Chart)
                .filter_by(datasource_id=dataset.id, datasource_type="table")
                .count()
            )
            if str(dataset.uuid) not in keep_datasets and not in_use:
                session.delete(dataset)
                stale_datasets += 1
        session.commit()
        print(
            f"cleanup: removed {len(stale_charts)} stale chart(s) and "
            f"{stale_datasets} stale dataset(s)"
        )


if __name__ == "__main__":
    main(Path(sys.argv[1]))
