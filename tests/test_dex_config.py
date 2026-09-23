"""Dex (T39, ADR 0034): local OIDC provider so people sign in with their own email.

Static checks on the Compose service, the config template and the Superset OAuth wiring;
the live behaviour (a real login) is the PR's verification."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATE = (_ROOT / "dex" / "config.yaml.tpl").read_text()
_SUPERSET_CONFIG = (_ROOT / "bi" / "superset_config.py").read_text()
_INTERNAL_ISSUER = "http://dex:5556/dex"


def _compose() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(
        (_ROOT / "bi" / "docker-compose.yml").read_text()
    )
    return loaded


def test_dex_is_pinned_to_an_exact_version_and_only_reachable_locally() -> None:
    dex = _compose()["services"]["dex"]

    assert dex["image"] == "ghcr.io/dexidp/dex:v2.43.1"
    assert all(str(p).startswith("127.0.0.1:") for p in dex["ports"])


def test_superset_waits_for_a_healthy_dex() -> None:
    superset = _compose()["services"]["superset"]

    assert superset["depends_on"]["dex"] == {"condition": "service_healthy"}


def test_no_credential_is_hardcoded() -> None:
    environment = {
        **_compose()["services"]["dex"]["environment"],
        **_compose()["services"]["superset"]["environment"],
    }
    secrets = [v for k, v in environment.items() if "SECRET" in k or "PASSWORD" in k]

    assert secrets and all(str(v).startswith("${") for v in secrets)


def test_the_template_never_hardcodes_a_user_or_a_client_secret() -> None:
    # The client id (below) is public, an OAuth client secret is not: only the latter is
    # indirected through the environment.
    assert "staticClients" in _TEMPLATE and "id: superset" in _TEMPLATE
    assert "secretEnv: PFP_BI_OAUTH_CLIENT_SECRET" in _TEMPLATE
    assert "enablePasswordDB: true" in _TEMPLATE
    # Real users only ever come from the environment, never from this committed file.
    assert "@" not in _TEMPLATE.split("staticPasswords:", 1)[1]


def test_dexs_own_issuer_is_the_internal_address_not_the_published_one() -> None:
    """Confirmed by actually running the login (see ADR 0034): every URL Dex's own
    discovery document hands back -- token, userinfo, jwks -- comes from whatever
    `issuer` says, and those are all calls Superset's backend makes, never the
    browser. Pointing this at the published port instead left the token exchange
    connecting to itself (the Superset container), not Dex."""
    assert f"issuer: {_INTERNAL_ISSUER}" in _TEMPLATE
    assert 'getenv "DEX_ISSUER"' not in _TEMPLATE


def test_superset_reaches_dex_internally_but_browser_hits_the_published_port() -> None:
    assert f"{_INTERNAL_ISSUER}/.well-known/openid-configuration" in _SUPERSET_CONFIG
    assert "f\"{os.environ['DEX_ISSUER']}/auth\"" in _SUPERSET_CONFIG


@pytest.mark.skipif(shutil.which("gomplate") is None, reason="gomplate not installed")
def test_the_template_renders_valid_dex_config() -> None:
    """The official image templates this file through its bundled gomplate before
    `dex serve` reads it (cmd/docker-entrypoint in dexidp/dex); render it the same
    way here."""
    env = {
        "PFP_BI_BASE_URL": "http://localhost:8088",
        "DEX_STATIC_PASSWORDS": (
            "piero@example.com:$2b$12$abcxyzHASH:piero:"
            "5f2f0000-0000-0000-0000-000000000001"
        ),
    }
    rendered = subprocess.run(
        ["gomplate", "-f", str(_ROOT / "dex" / "config.yaml.tpl")],
        capture_output=True,
        text=True,
        env={**os.environ, **env},
        check=True,
    ).stdout
    config = yaml.safe_load(rendered)

    assert config["issuer"] == _INTERNAL_ISSUER
    assert config["enablePasswordDB"] is True
    assert config["staticPasswords"] == [
        {
            "email": "piero@example.com",
            "hash": "$2b$12$abcxyzHASH",
            "username": "piero",
            "userID": "5f2f0000-0000-0000-0000-000000000001",
        }
    ]


@pytest.mark.skipif(shutil.which("gomplate") is None, reason="gomplate not installed")
def test_the_template_renders_with_no_users_configured_yet() -> None:
    env = {
        "PFP_BI_BASE_URL": "http://localhost:8088",
        "DEX_STATIC_PASSWORDS": "",
    }
    rendered = subprocess.run(
        ["gomplate", "-f", str(_ROOT / "dex" / "config.yaml.tpl")],
        capture_output=True,
        text=True,
        env={**os.environ, **env},
        check=True,
    ).stdout

    assert yaml.safe_load(rendered)["staticPasswords"] == []
