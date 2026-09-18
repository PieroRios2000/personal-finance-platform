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

import os
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

# dbt/profiles.yml's `path` defaults to the *relative* `dbt/pfp.duckdb`, resolved
# against the dbt CLI subprocess's own cwd -- correct for every existing manual/CI
# invocation (`uv run dbt build --project-dir dbt --profiles-dir dbt`, always run
# from the repo root), but `DbtCliResource.cli()` runs that subprocess from
# `project_dir` itself (`dbt/`), which would double the path to `dbt/dbt/pfp.duckdb`
# (confirmed by reproducing the crash before adding this). An absolute
# `PFP_DUCKDB_PATH` sidesteps cwd entirely; `setdefault` so an explicit value (tests'
# own `tmp_path`-scoped override, `PFP_DUCKDB_PATH` already exported in the shell)
# always wins.
os.environ.setdefault("PFP_DUCKDB_PATH", str(_DBT_PROJECT_DIR / "pfp.duckdb"))

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


def _dbt_build_args() -> list[str]:
    """`dbt build`'s own args, narrowed by `DBT_SELECT`/`DBT_STATE_PATH` when
    set (ADR 0008's impact-based CI, ADR 0021): the same env vars
    `.github/workflows/ci.yml`'s `changes` job (`DBT_SELECT`) and its own
    git-worktree-plus-`dbt parse` step (`DBT_STATE_PATH`, the resulting base
    manifest) already produce for the pre-T21 bare-subprocess `dbt build`
    call -- only *where* that selection gets applied moved into Dagster, not
    how it's computed. `DBT_SELECT` unset or `"all"` (every non-dbt-only
    change, ADR 0008) is a plain, unnarrowed build."""
    select = os.environ.get("DBT_SELECT")
    if not select or select == "all":
        return ["build"]
    args = ["build", "--select", select]
    state_path = os.environ.get("DBT_STATE_PATH")
    if state_path:
        args += ["--state", state_path]
    return args


@dbt_assets(
    manifest=dbt_project.manifest_path,
    project=dbt_project,
    dagster_dbt_translator=BronzeSourceDbtTranslator(),
)
def dbt_models(context: dg.AssetExecutionContext, dbt: DbtCliResource) -> Iterator[Any]:
    """Every dbt node in `dbt/models/` as one Dagster multi-asset, built with
    `dbt build` -- the identical command CI and a developer already run by
    hand, optionally narrowed by `_dbt_build_args()`."""
    yield from dbt.cli(_dbt_build_args(), context=context).stream()
