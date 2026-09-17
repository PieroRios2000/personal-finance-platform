"""The dbt project, wrapped as Dagster assets (T21).

One Dagster asset per dbt node (`dagster_dbt.dbt_assets`'s own mechanism --
https://docs.dagster.io/integrations/libraries/dbt/reference), selecting the
default `fqn:*` (the whole project): today that's `silver.transactions` and
T18b's internal-transfer models, and whatever gold models T23 adds later,
with no per-model selection to keep in sync here. `dbt build` is the command,
identical to what a developer or CI already runs by hand.

**The one piece of custom wiring:** `dbt/models/sources.yml` declares two dbt
sources, `bronze.transactions` and `bronze.statements`. `dagster-dbt`'s own
default translator would turn those into two separate stub assets (one dbt
source, one asset -- see `dagster_dbt.asset_utils.default_asset_key_fn`), but
both tables are written by a single call,
`lakehouse.bronze.write_statement()`, inside one Dagster asset,
`orchestration.assets.bronze.bronze`. `BronzeSourceDbtTranslator` collapses
both dbt sources onto that one asset's key instead, so the graph shows one
real edge (bronze -> silver) matching the actual data flow, not two upstream
stubs for tables Dagster never separately produces.
"""

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import dagster as dg
from dagster_dbt import (
    DagsterDbtTranslator,
    DagsterDbtTranslatorSettings,
    DbtCliResource,
    DbtProject,
    dbt_assets,
)

from orchestration.assets.bronze import bronze

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DBT_PROJECT_DIR = _REPO_ROOT / "dbt"

dbt_project = DbtProject(project_dir=_DBT_PROJECT_DIR, profiles_dir=_DBT_PROJECT_DIR)

# `prepare_if_dev()` only regenerates the manifest under `dagster dev`
# (`dagster_dbt.dbt_project.using_dagster_dev()`, gated on `DAGSTER_IS_DEV_CLI`);
# `dagster asset materialize`/`dagster asset list` are not "dev", so it's a
# no-op there. Falling back to an explicit `prepare()` the first time no
# manifest exists covers both: an editor session under `dagster dev` always
# gets a fresh one, and a one-shot CLI run (CI's own path) builds it once, on
# demand, then reuses it -- the same "generate once, don't recompile every
# run" tradeoff `dagster-dbt`'s own docs recommend for production, just
# triggered lazily instead of by a separate build step, since this project
# has none. `dbt/target/` is gitignored, so a fresh checkout or CI run always
# starts with no manifest to reuse.
dbt_project.prepare_if_dev()
if not dbt_project.manifest_path.exists():
    dbt_project.preparer.prepare(dbt_project)


class BronzeSourceDbtTranslator(DagsterDbtTranslator):
    """Maps dbt's `bronze` source group onto `orchestration.assets.bronze.bronze`'s
    own asset key -- see module docstring. `enable_duplicate_source_asset_keys`
    is what lets two distinct dbt sources (`transactions`, `statements`)
    collapse onto the one asset that really produces them without
    `dagster-dbt` treating it as a configuration error."""

    def __init__(self) -> None:
        super().__init__(
            settings=DagsterDbtTranslatorSettings(
                enable_duplicate_source_asset_keys=True
            )
        )

    def get_asset_key(self, dbt_resource_props: Mapping[str, Any]) -> dg.AssetKey:
        if (
            dbt_resource_props["resource_type"] == "source"
            and dbt_resource_props["source_name"] == "bronze"
        ):
            return bronze.key
        return super().get_asset_key(dbt_resource_props)


@dbt_assets(
    manifest=dbt_project.manifest_path,
    project=dbt_project,
    dagster_dbt_translator=BronzeSourceDbtTranslator(),
)
def dbt_models(context: dg.AssetExecutionContext, dbt: DbtCliResource) -> Iterator[Any]:
    """Every dbt node in `dbt/models/` as one Dagster multi-asset, built with
    `dbt build` -- the identical command CI and a developer already run by
    hand."""
    yield from dbt.cli(["build"], context=context).stream()
