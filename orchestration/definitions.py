"""Top-level Dagster `Definitions` (T21): the bronze asset
(`orchestration/assets/bronze.py`) and the whole dbt project as one
multi-asset (`orchestration/assets/dbt_project.py`), wired with the real
bronze -> silver dependency edge `dagster-dbt` computes from
`dbt/models/sources.yml` plus `BronzeSourceDbtTranslator`.

`pyproject.toml`'s `[tool.dagster] module_name` block points `dagster dev`
(the local web UI) at this module with no flag needed. `dagster asset
materialize`/`dagster asset list` -- the commands CI and `make poc`-style
one-shot runs actually use -- resolve their target through a *different*
code path that block doesn't drive; they need `DAGSTER_MODULE_NAME` set
instead (`.env.example`, `SETUP.md` section 9, ADR 0021) -- confirmed by
reading `dagster`'s own CLI source (`dagster/_cli/asset.py`,
`dagster_shared/cli/__init__.py`), not assumed from either command's own
`--help` text. See `brain/components/dagster.md` for why the top-level
package here is named `orchestration`, not `dagster`: naming it `dagster`
would shadow the real library on `sys.path` for anything that adds the repo
root to it (`uv run pytest`, via this project's own `pythonpath = ["."]`) --
confirmed by reproducing the shadowing directly before choosing this name.
"""

import dagster as dg
from dagster_dbt import DbtCliResource

from orchestration.assets.bronze import bronze
from orchestration.assets.dbt_project import dbt_models, dbt_project

defs = dg.Definitions(
    assets=[bronze, dbt_models],
    resources={"dbt": DbtCliResource(project_dir=dbt_project)},
)
