"""Upload portal (T44, ADR 0040): the pure logic in `upload/portal.py` and static checks
on how the service is wired. `upload/server.py` (Flask, Dex's gRPC API) is exercised
live: see the PR."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

from ingestion import dispatcher

_ROOT = Path(__file__).resolve().parent.parent
_SERVER = (_ROOT / "upload" / "server.py").read_text()


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, _ROOT / "upload" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


portal = _load("portal")


def test_the_banks_offered_are_the_ones_the_pipeline_can_parse() -> None:
    assert set(portal.BANKS) == {parser.bank for parser in dispatcher._PARSERS}


def test_a_new_user_id_is_safe_as_a_folder_and_never_an_email() -> None:
    user_id = portal.new_user_id("Ana.Perez+x@example.com", set())

    assert user_id.startswith("anaperezx-")
    assert portal.is_user_id(user_id)
    assert "@" not in user_id


def test_a_new_user_id_avoids_the_ones_already_taken(monkeypatch: Any) -> None:
    hexes = iter(["aaaa", "aaaa", "bbbb"])
    monkeypatch.setattr(portal.secrets, "token_hex", lambda n: next(hexes))

    assert portal.new_user_id("ana@example.com", {"ana-aaaa"}) == "ana-bbbb"


def test_an_email_with_nothing_usable_still_gets_a_user_id() -> None:
    assert portal.is_user_id(portal.new_user_id("...@example.com", set()))


def test_what_counts_as_a_user_id() -> None:
    assert portal.is_user_id("piero")
    assert portal.is_user_id("ana-3f2a")
    for bad in ("", "ab", "../etc", "a b", "Ana", "ana@example.com", "-ana", "a" * 60):
        assert not portal.is_user_id(bad), bad


def test_an_account_is_unscoped_while_its_username_is_its_email() -> None:
    assert portal.is_unscoped("ana@example.com")
    assert not portal.is_unscoped("piero")


def test_uploads_are_limited_per_person_per_hour() -> None:
    limit = portal.UploadLimit()

    assert limit.allow("ana", portal.MAX_UPLOADS_PER_HOUR, now=0)
    assert not limit.allow("ana", 1, now=10)
    assert limit.allow("bea", 1, now=10)  # someone else is unaffected
    assert limit.allow("ana", 1, now=portal.WINDOW_SECONDS + 1)  # the hour passed


def test_the_destination_comes_from_the_account_never_from_the_form() -> None:
    assert "request.form" in _SERVER and "user_id = _user_id(session" in _SERVER
    assert 'request.form.get("user' not in _SERVER
    assert 'session["email"]' in _SERVER


def test_a_state_changing_post_needs_the_forms_own_token() -> None:
    assert "hmac.compare_digest(request.form.get" in _SERVER
    assert "SESSION_COOKIE_SAMESITE" in _SERVER


def test_the_password_is_used_once_and_never_stored_or_logged() -> None:
    assert _SERVER.count("password") >= 1
    assert "print(" not in _SERVER and "logging" not in _SERVER
    assert 'session["password"]' not in _SERVER


def _compose() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(
        (_ROOT / "bi" / "docker-compose.yml").read_text()
    )
    services: dict[str, Any] = loaded["services"]
    return services


def test_the_service_only_writes_the_inbox_and_is_reachable_locally_or_by_tunnel() -> (
    None
):
    upload = _compose()["upload"]

    assert upload["profiles"] == ["bi"]
    assert all(str(p).startswith("127.0.0.1:") for p in upload["ports"])
    assert upload["volumes"] == ["${PFP_INBOX_DIR:-${HOME}/finance-data/inbox}:/inbox"]
    assert upload["user"] == "${PFP_UID:-1000}:${PFP_GID:-1000}"
    assert upload["depends_on"]["dex"] == {"condition": "service_healthy"}


def test_every_secret_of_the_service_comes_from_the_environment() -> None:
    environment = _compose()["upload"]["environment"]
    secrets_ = [v for k, v in environment.items() if "SECRET" in k]

    assert secrets_ and all(str(v).startswith("${") for v in secrets_)


def test_dex_knows_the_portal_as_its_own_client_with_local_and_public_callbacks() -> (
    None
):
    template = (_ROOT / "dex" / "config.yaml.tpl").read_text()

    assert "id: portal" in template
    assert "secretEnv: PFP_UPLOAD_OAUTH_CLIENT_SECRET" in template
    assert 'getenv "PFP_UPLOAD_BASE_URL" }}/callback' in template
    assert 'getenv "PFP_UPLOAD_PUBLIC_URL" }}/callback' in template


def test_the_tunnel_connector_waits_for_the_portal_too() -> None:
    assert "upload" in _compose()["cloudflared"]["depends_on"]


def test_the_image_takes_only_the_two_shared_files_it_needs() -> None:
    dockerfile = (_ROOT / "upload" / "Dockerfile").read_text()

    assert "COPY ingestion/unlock.py" in dockerfile
    assert "COPY dex-register/api.proto" in dockerfile
    assert "grpc_tools.protoc" in dockerfile
    assert "USER nobody" in dockerfile
    assert not (_ROOT / "upload" / "api_pb2.py").exists()


def test_processing_what_was_uploaded_is_one_command_over_every_inbox_folder() -> None:
    makefile = (_ROOT / "Makefile").read_text()

    assert "ingest-uploads:" in makefile
    assert 'uv run pfp ingest --user "$$(basename "$$dir")"' in makefile
