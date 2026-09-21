"""Separate environments on one machine (T38, ADR 0033).

Dev (real data, the code of develop) and prod (artificial data, the code of main)
are each their own Compose project, env file and ports, so a change is judged in dev
before it reaches main. Static and dry-run checks; the live behaviour is the PR's
verification."""

import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import init_env

_ROOT = Path(__file__).resolve().parent.parent
_MAKEFILE = (_ROOT / "Makefile").read_text()
_TEMPLATE = (_ROOT / ".env.example").read_text()


def _values(text: str) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in text.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    )


def _make(cwd: Path, *args: str, dry: bool = False) -> subprocess.CompletedProcess[str]:
    command = ["make", "--no-print-directory", *(["-n"] if dry else []), *args]
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True)


def _repo(tmp_path: Path, branch: str) -> Path:
    """A throwaway git repo on `branch` holding a copy of the Makefile."""
    shutil.copy(_ROOT / "Makefile", tmp_path / "Makefile")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", "-b", branch, str(tmp_path)], check=True)
    subprocess.run([*git, "add", "."], cwd=tmp_path, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "x"], cwd=tmp_path, check=True)
    return tmp_path


def test_the_environment_picks_the_project_and_the_env_file() -> None:
    dev = _make(_ROOT, "up", "PFP_ENV=dev", dry=True).stdout
    default = _make(_ROOT, "up", dry=True).stdout

    assert "-p pfp-dev" in dev and ". ./.env.dev" in dev and "pfp-poc" not in dev
    assert (
        "-p pfp-poc" in default and ". ./.env " in default
    )  # unchanged for today's stack


def test_no_recipe_hardcodes_the_env_file() -> None:
    assert "&& . ./.env &&" not in _MAKEFILE
    assert "&& . .env &&" not in _MAKEFILE


def test_the_port_offset_moves_every_published_port_together() -> None:
    values = _values(init_env.render(_TEMPLATE, port_offset=100))

    assert values["SEAWEEDFS_S3_PORT"] == "8433"
    assert values["AWS_ENDPOINT_URL"] == "http://localhost:8433"  # kept in step
    assert values["PFP_PG_PORT"] == "5532"
    assert values["PFP_BI_PORT"] == "8188"
    assert values["OPENMETADATA_PORT"] == "8685"


def test_no_offset_leaves_todays_ports() -> None:
    values = _values(init_env.render(_TEMPLATE))

    assert (values["PFP_PG_PORT"], values["PFP_BI_PORT"]) == ("5432", "8088")


def test_prod_only_runs_the_code_of_main(tmp_path: Path) -> None:
    on_main = _repo(tmp_path / "m", "main")
    on_feature = _repo(tmp_path / "f", "feat/x")

    assert _make(on_main, "env-guard", "PFP_ENV=prod").returncode == 0
    refused = _make(on_feature, "env-guard", "PFP_ENV=prod")
    assert refused.returncode == 2 and "main" in refused.stderr
    assert _make(on_feature, "env-guard", "PFP_ENV=prod", "FORCE=1").returncode == 0


def test_dev_never_runs_on_main(tmp_path: Path) -> None:
    on_main = _repo(tmp_path / "m", "main")
    on_develop = _repo(tmp_path / "d", "develop")

    assert _make(on_develop, "env-guard", "PFP_ENV=dev").returncode == 0
    assert _make(on_main, "env-guard", "PFP_ENV=dev").returncode == 2


@pytest.mark.parametrize(
    ("target", "user", "refused"),
    [("demo", "piero", True), ("demo", "demo", False), ("ingest", "demo", True)],
)
def test_demo_data_and_real_data_never_share_an_environment(
    tmp_path: Path, target: str, user: str, refused: bool
) -> None:
    """`make demo` writes fictional data, `make ingest` real statements.

    Each refuses the other's user, so a real dashboard never gets demo rows and the
    demo never gets real ones."""
    repo = _repo(tmp_path, "feat/x")
    (repo / ".env.t").write_text(f"PFP_USER={user}\n")

    result = _make(repo, "guard-user", f"TARGET={target}", "PFP_ENV=t")

    assert (result.returncode == 2) is refused
