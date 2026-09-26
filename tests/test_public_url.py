"""Public URL (T42, ADR 0037): the Cloudflare Tunnel connector, the extra Dex redirect
URI and Superset behind a proxy.

Static checks; the live behaviour (login through a public hostname) is the PR's
verification."""

from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parent.parent
_SUPERSET_CONFIG = (_ROOT / "bi" / "superset_config.py").read_text()
_MAKEFILE = (_ROOT / "Makefile").read_text()


def _services() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(
        (_ROOT / "bi" / "docker-compose.yml").read_text()
    )
    services: dict[str, Any] = loaded["services"]
    return services


def test_the_connector_is_pinned_opt_in_and_takes_its_token_from_the_environment() -> (
    None
):
    connector = _services()["cloudflared"]

    assert connector["profiles"] == ["tunnel"]
    assert connector["image"] == "cloudflare/cloudflared:2026.9.3"
    assert connector["environment"]["TUNNEL_TOKEN"] == "${PFP_TUNNEL_TOKEN:-}"
    assert "ports" not in connector


def test_the_connector_waits_for_the_three_services_it_routes_to() -> None:
    depends = _services()["cloudflared"]["depends_on"]

    assert set(depends) == {"superset", "dex", "dex-register"}
    assert all(d == {"condition": "service_healthy"} for d in depends.values())


def test_make_up_starts_the_connector_only_when_a_token_is_set() -> None:
    assert "${PFP_TUNNEL_TOKEN:+--profile tunnel}" in _MAKEFILE
    assert "${PFP_TUNNEL_TOKEN:+cloudflared}" in _MAKEFILE


def test_the_public_url_reaches_dex_and_superset() -> None:
    services = _services()

    for name in ("dex", "superset"):
        assert services[name]["environment"]["PFP_BI_PUBLIC_URL"] == (
            "${PFP_BI_PUBLIC_URL:-}"
        )


def test_superset_trusts_the_proxy_and_secures_the_cookie_when_public() -> None:
    assert "ENABLE_PROXY_FIX = True" in _SUPERSET_CONFIG
    assert '"x_proto": 1' in _SUPERSET_CONFIG
    assert 'startswith("https://")' in _SUPERSET_CONFIG


def test_no_personal_override_file_is_needed_any_more() -> None:
    assert not (_ROOT / "docker-compose.override.yml.dist").exists()


def test_dex_adds_the_public_redirect_uri_only_when_one_is_set() -> None:
    template = (_ROOT / "dex" / "config.yaml.tpl").read_text()

    assert 'getenv "PFP_BI_BASE_URL" }}/oauth-authorized/dex' in template
    assert '{{- if getenv "PFP_BI_PUBLIC_URL" }}' in template
    assert 'getenv "PFP_BI_PUBLIC_URL" }}/oauth-authorized/dex' in template
