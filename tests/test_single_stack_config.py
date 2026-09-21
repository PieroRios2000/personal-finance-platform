"""One Compose project for the whole platform (T37).

`make up` starts storage, Postgres and Superset, `make up-catalog` adds OpenMetadata and
`make down` stops them all. The BI and catalog files are `include`d by the root
docker-compose.yml and their services sit behind profiles, so CI (which only names
seaweedfs and postgres) and `make poc-up` are unchanged. Static checks: the live
behaviour is the PR's verification."""

import re
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parent.parent
_FILES = {
    "root": _ROOT / "docker-compose.yml",
    "bi": _ROOT / "bi" / "docker-compose.yml",
    "catalog": _ROOT / "openmetadata" / "docker-compose.yml",
}


def _load(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(_FILES[name].read_text())
    return loaded


def test_the_root_file_includes_the_bi_and_catalog_files() -> None:
    includes = [
        item["path"] if isinstance(item, dict) else item
        for item in _load("root")["include"]
    ]

    assert includes == ["bi/docker-compose.yml", "openmetadata/docker-compose.yml"]


def test_bi_and_catalog_services_sit_behind_their_profile() -> None:
    for name, profile in (("bi", "bi"), ("catalog", "catalog")):
        services = _load(name)["services"]
        assert services
        for service, definition in services.items():
            assert definition["profiles"] == [profile], (name, service)
    for service, definition in _load("root")["services"].items():
        assert "profiles" not in definition, service  # storage and Postgres always


def test_all_services_share_the_projects_own_network() -> None:
    """No external network to a "Postgres project" any more: it is one project."""
    for name in ("bi", "catalog"):
        loaded = _load(name)
        assert "networks" not in loaded, name
        for service, definition in loaded["services"].items():
            assert "networks" not in definition, (name, service)


def test_no_service_or_volume_name_is_defined_in_two_files() -> None:
    services = [s for name in _FILES for s in _load(name)["services"]]
    volumes = [v for name in _FILES for v in (_load(name).get("volumes") or {})]

    assert len(services) == len(set(services))
    assert len(volumes) == len(set(volumes))


def test_included_files_parse_without_the_optional_variables() -> None:
    """`${VAR:?}` in an included file fails the whole project when the variable is
    unset, even for a stopped profile: the Makefile checks them instead."""
    for name in ("bi", "catalog"):
        assert ":?" not in _FILES[name].read_text(), name


def test_the_makefile_has_one_command_up_and_down() -> None:
    makefile = (_ROOT / "Makefile").read_text()

    for target in ("up", "up-catalog", "down", "status"):
        assert re.search(rf"^{target}:", makefile, re.M), target
    up = makefile[makefile.index("\nup:") :].split("\n\n")[0]
    assert "--profile bi" in up
