"""Static checks on how PostgreSQL is wired as dbt's store (T26, ADR 0029): the
Compose service, the read-only role's init script, the dbt profile's target and
`.env.example`. The live behaviour is proven by `test_dbt_postgres_integration.py`."""

import re
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


def test_the_init_script_is_mounted_and_has_a_healthcheck() -> None:
    mounts = " ".join(str(v) for v in _postgres()["volumes"])

    assert "docker-entrypoint-initdb.d" in mounts
    assert "pg_isready" in " ".join(_postgres()["healthcheck"]["test"])


def test_the_bi_role_can_read_gold_only_and_keeps_doing_so_for_new_tables() -> None:
    script = (_ROOT / "postgres" / "init-roles.sh").read_text()

    assert "grant usage on schema gold to pfp_bi" in script
    assert "grant select on all tables in schema gold to pfp_bi" in script
    assert "alter default privileges" in script
    assert "in schema gold grant select on tables to pfp_bi" in script
    assert "silver to pfp_bi" not in script
    assert not re.search(r"grant (all|insert|update|delete|create)", script, re.I)


def test_the_init_script_takes_the_bi_password_from_the_environment() -> None:
    script = (_ROOT / "postgres" / "init-roles.sh").read_text()

    assert "PFP_PG_BI_PASSWORD" in script
    assert "bi_password" in script and ":'bi_password'" in script


def _profile() -> dict[str, Any]:
    text = (_ROOT / "dbt" / "profiles.yml").read_text()
    loaded: dict[str, Any] = yaml.safe_load(text)
    return loaded["personal_finance_platform"]


def test_the_default_dbt_target_is_still_the_duckdb_file() -> None:
    assert _profile()["target"] == "local"


def test_the_postgres_target_attaches_postgres_and_elementarys_own_file() -> None:
    output = _profile()["outputs"]["postgres"]

    assert output["type"] == "duckdb"
    assert output["path"] == ":memory:"
    attached = {a.get("type", "duckdb"): a for a in output["attach"]}
    assert "postgres" in attached
    assert "PFP_PG_PASSWORD" in attached["postgres"]["path"]
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
