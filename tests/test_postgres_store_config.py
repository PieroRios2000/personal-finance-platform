"""Static checks on how PostgreSQL is wired as dbt's store (T26, ADR 0029): the
Compose service, the read-only role's init script, the dbt profile's target and
`.env.example`. The live behaviour is proven by `test_dbt_postgres_integration.py`."""

import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parent.parent


def _compose() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load((_ROOT / "docker-compose.yml").read_text())
    return loaded


def _postgres() -> dict[str, Any]:
    service: dict[str, Any] = _compose()["services"]["postgres"]
    return service


def test_the_postgres_image_is_pinned_to_an_exact_version() -> None:
    assert re.fullmatch(r"postgres:\d+\.\d+-alpine", _postgres()["image"])


def test_postgres_is_only_reachable_from_this_machine() -> None:
    assert all(str(p).startswith("127.0.0.1:") for p in _postgres()["ports"])


def test_no_postgres_credential_is_hardcoded_in_the_compose_file() -> None:
    environment = _postgres()["environment"]

    for name in ("POSTGRES_PASSWORD", "PFP_PG_BI_PASSWORD"):
        assert str(environment[name]).startswith("${PFP_PG_"), name
    assert str(environment["POSTGRES_USER"]).startswith("${PFP_PG_")


def test_the_data_lives_in_a_named_volume_that_down_removes() -> None:
    assert "postgres-data" in _compose()["volumes"]
    assert any(str(v).startswith("postgres-data:") for v in _postgres()["volumes"])


def test_the_init_script_and_the_grants_are_mounted() -> None:
    mounts = " ".join(str(v) for v in _postgres()["volumes"])

    assert "docker-entrypoint-initdb.d" in mounts
    assert "postgres/grants.sql" in mounts


def test_the_healthcheck_uses_tcp_so_it_is_not_healthy_during_first_time_init() -> None:
    """The entrypoint's temporary server (while init scripts run) listens on the
    unix socket only: a socket check would let `--wait` return before init ends."""
    command = " ".join(_postgres()["healthcheck"]["test"])

    assert "pg_isready" in command
    assert "-h 127.0.0.1" in command


def _grants() -> str:
    return (_ROOT / "postgres" / "grants.sql").read_text()


def test_the_bi_role_can_read_gold_only_and_keeps_doing_so_for_new_tables() -> None:
    grants = _grants()

    assert "grant usage on schema gold to pfp_bi" in grants
    assert "grant select on all tables in schema gold to pfp_bi" in grants
    assert 'alter default privileges for role :"owner" in schema gold' in grants
    assert "grant select on tables to pfp_bi" in grants
    assert "silver" not in grants
    assert not re.search(r"grant (all|insert|update|delete|create)", grants, re.I)


def test_only_the_owner_and_the_bi_role_may_connect_to_the_database() -> None:
    grants = _grants()

    assert 'revoke connect on database :"database" from public' in grants
    assert 'grant connect on database :"database" to pfp_bi' in grants


def test_the_init_script_creates_the_role_once_read_only_and_applies_the_grants() -> (
    None
):
    script = (_ROOT / "postgres" / "init-roles.sh").read_text()

    assert "PFP_PG_BI_PASSWORD" in script and ":'bi_password'" in script
    assert "not exists (select 1 from pg_roles where rolname = 'pfp_bi')" in script
    assert "set default_transaction_read_only = on" in script
    assert "/grants.sql" in script


def _profile() -> dict[str, Any]:
    text = (_ROOT / "dbt" / "profiles.yml").read_text()
    loaded: dict[str, Any] = yaml.safe_load(text)
    profile: dict[str, Any] = loaded["personal_finance_platform"]
    return profile


def test_the_default_dbt_target_is_postgres_and_local_stays_selectable() -> None:
    """T27: silver and gold live in Postgres by default; `PFP_DBT_TARGET=local`
    still selects the DuckDB file (CI's data diff uses it until T29)."""
    target = _profile()["target"]

    assert "PFP_DBT_TARGET" in target and "'postgres'" in target
    assert "local" in _profile()["outputs"]


def test_the_postgres_target_attaches_postgres_and_elementarys_own_file() -> None:
    output = _profile()["outputs"]["postgres"]

    assert output["type"] == "duckdb"
    assert output["path"] == ":memory:"
    attached = {a.get("type", "duckdb"): a for a in output["attach"]}
    assert "postgres" in attached
    assert "PFP_PG_PASSWORD" in attached["postgres"]["path"]
    # libpq's own quoting: a backslash or a quote in the password must not break it
    assert "replace" in attached["postgres"]["path"]
    assert output["database"] == attached["postgres"]["alias"]
    assert any(a["alias"] == "elem" for a in output["attach"])
    assert "postgres" in output["extensions"] and "delta" in output["extensions"]


def test_the_postgres_target_keeps_the_lake_credentials_of_the_local_target() -> None:
    outputs = _profile()["outputs"]

    assert outputs["postgres"]["secrets"] == outputs["local"]["secrets"]


def test_elementary_moves_to_its_own_file_only_on_the_postgres_target() -> None:
    project = (_ROOT / "dbt" / "dbt_project.yml").read_text()

    assert "target.name == 'postgres'" in project
    assert "'elem'" in project


def test_env_example_lists_every_postgres_variable_with_no_secret_value() -> None:
    lines = (_ROOT / ".env.example").read_text().splitlines()
    values = dict(
        line.split("=", 1) for line in lines if re.match(r"^PFP_PG_\w+=", line)
    )

    assert set(values) == {
        "PFP_PG_HOST",
        "PFP_PG_PORT",
        "PFP_PG_DATABASE",
        "PFP_PG_USER",
        "PFP_PG_PASSWORD",
        "PFP_PG_BI_PASSWORD",
    }
    assert values["PFP_PG_PASSWORD"] == "" and values["PFP_PG_BI_PASSWORD"] == ""


def test_make_has_targets_to_start_and_stop_postgres_without_touching_the_lake() -> (
    None
):
    makefile = (_ROOT / "Makefile").read_text()

    assert re.search(r"^pg-up:\n\t.*up -d --wait postgres", makefile, re.M)
    assert re.search(r"^pg-down:\n\t.*stop postgres", makefile, re.M)


def test_make_poc_up_starts_postgres_with_the_local_s3() -> None:
    makefile = (_ROOT / "Makefile").read_text()

    assert re.search(r"^poc-up:.*\n\t.*up -d --wait seaweedfs postgres", makefile, re.M)


def test_the_orchestration_module_gives_elementary_an_absolute_file_by_default() -> (
    None
):
    """Dagster runs dbt from the project directory, so a relative default would
    resolve against the wrong cwd (the reason PFP_DUCKDB_PATH gets one too)."""
    source = (_ROOT / "orchestration" / "assets" / "dbt_project.py").read_text()

    assert re.search(r'setdefault\(\s*"PFP_ELEMENTARY_DUCKDB_PATH"', source)


def test_starting_the_local_environment_checks_the_postgres_secrets_first() -> None:
    """Otherwise compose starts Postgres with an empty password, the container
    exits, and `make poc` aborts before its teardown trap with a generic error."""
    makefile = (_ROOT / "Makefile").read_text()

    assert re.search(r"^poc-up: .*pg-check", makefile, re.M)
    assert re.search(r"^pg-up: .*pg-check", makefile, re.M)


def _make_pg_check(tmp_path: Path, env_file: str) -> "subprocess.CompletedProcess[str]":
    (tmp_path / ".env").write_text(env_file)
    return subprocess.run(
        ["make", "-f", str(_ROOT / "Makefile"), "pg-check"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )


def test_pg_check_names_the_missing_secrets_and_stops(tmp_path: Path) -> None:
    result = _make_pg_check(tmp_path, "PFP_PG_PASSWORD=\nPFP_PG_BI_PASSWORD=x\n")

    assert result.returncode != 0
    assert "PFP_PG_PASSWORD" in result.stdout + result.stderr


def test_pg_check_passes_when_both_secrets_are_set(tmp_path: Path) -> None:
    result = _make_pg_check(tmp_path, "PFP_PG_PASSWORD=a\nPFP_PG_BI_PASSWORD=b\n")

    assert result.returncode == 0


def test_poc_down_also_forgets_elementarys_file_so_it_matches_the_fresh_database() -> (
    None
):
    makefile = (_ROOT / "Makefile").read_text()

    assert re.search(
        r"^poc-down:\n(\t.*\n)*\t.*rm -f dbt/elementary\.duckdb", makefile, re.M
    )
