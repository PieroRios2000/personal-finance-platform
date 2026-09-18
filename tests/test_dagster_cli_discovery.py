"""Proves `DAGSTER_MODULE_NAME` is what `dagster asset list`/`dagster asset
materialize` actually need to find `orchestration.definitions` with no
`-m`/`-f` flag -- T21's own acceptance criteria ask for exactly this,
literally as `uv run dagster asset materialize --select '*'` (no flag).

Not `pyproject.toml`'s own `[tool.dagster] module_name` block: that only
drives `dagster dev`'s target resolution (`WorkspaceOpts`,
`dagster/_cli/dev.py`), a different code path from `asset list`/`asset
materialize` (`PythonPointerOpts`, `dagster/_cli/asset.py`) -- confirmed by
reading `dagster`'s own installed source (ADR 0021), not assumed from either
command's own `--help` text. This file is the real, subprocess-level
regression test for that finding: a future `dagster` upgrade that changes
this behavior should fail these tests, not go unnoticed until CI's own
`ephemeral-integration` job breaks in a way that's harder to localize.

A real subprocess invocation of the installed `dagster` CLI, needing a real
dbt manifest (triggered by `orchestration.assets.dbt_project`'s own
import-time `dbt parse` fallback) but no live S3/SeaweedFS -- `dagster asset
list` never materializes anything, and `dbt parse` alone needs no
AWS_*/LAKEHOUSE_URI env vars (confirmed directly; dbt-duckdb's own
`secrets:` Jinja isn't rendered until a real connection opens). Not
`integration`-marked for the same reason `test_dagster_dbt_translator.py`
isn't.
"""

import os
import subprocess
import sys
from pathlib import Path

_DAGSTER = str(Path(sys.executable).parent / "dagster")


def _run(*, module_name_env: bool) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    if module_name_env:
        environment["DAGSTER_MODULE_NAME"] = "orchestration.definitions"
    else:
        environment.pop("DAGSTER_MODULE_NAME", None)
    return subprocess.run(
        [_DAGSTER, "asset", "list"],
        capture_output=True,
        text=True,
        env=environment,
        timeout=120,
    )


def test_asset_list_with_no_flag_needs_dagster_module_name_env_var() -> None:
    result = _run(module_name_env=True)

    assert result.returncode == 0, result.stdout + result.stderr
    listed = set(result.stdout.split())
    assert {"bronze", "transactions"} <= listed


def test_asset_list_with_no_flag_and_no_env_var_fails_clearly() -> None:
    """The exact gotcha ADR 0021 documents: `pyproject.toml`'s own
    `[tool.dagster]` block alone is not enough for this command."""
    result = _run(module_name_env=False)

    assert result.returncode != 0
    assert "Invalid set of CLI arguments" in result.stdout + result.stderr
