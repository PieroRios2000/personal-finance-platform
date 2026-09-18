"""Top-level Dagster `Definitions` (T21): the bronze asset
(`orchestration/assets/bronze.py`) and the whole dbt project as one
multi-asset (`orchestration/assets/dbt_project.py`), wired with the real
bronze -> silver dependency edge `dagster-dbt` computes from
`dbt/models/sources.yml` plus `BronzeSourceDbtTranslator`.

Discovered by the `dagster` CLI via `pyproject.toml`'s `[tool.dagster]`
block (`module_name = "orchestration.definitions"`), so `uv run dagster
asset materialize --select '*'` needs no `-m`/`-f` flag -- confirmed against
the installed `dagster` package's own auto-discovery code
(`dagster._core.workspace.load_target.get_target_from_toml_data`), not
assumed from docs. See `brain/components/dagster.md` for why the top-level
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
