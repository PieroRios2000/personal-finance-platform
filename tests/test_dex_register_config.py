"""dex-register (T40, ADR 0035): a friendly sign-up page gated by an invite code.

Static checks on the Compose service and the Dockerfile; the live behaviour (a real
sign-up, then a real login with the new account) is the PR's verification."""

from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parent.parent
_DOCKERFILE = (_ROOT / "dex-register" / "Dockerfile").read_text()
_APP = (_ROOT / "dex-register" / "app.py").read_text()


def _compose() -> dict[str, Any]:
    text = (_ROOT / "bi" / "docker-compose.yml").read_text()
    loaded: dict[str, Any] = yaml.safe_load(text)
    return loaded


def _service() -> dict[str, Any]:
    service: dict[str, Any] = _compose()["services"]["dex-register"]
    return service


def test_only_reachable_locally_and_the_invite_code_is_not_hardcoded() -> None:
    service = _service()

    assert all(str(p).startswith("127.0.0.1:") for p in service["ports"])
    assert service["environment"]["PFP_DEX_INVITE_CODE"] == "${PFP_DEX_INVITE_CODE:-}"


def test_it_waits_for_a_healthy_dex() -> None:
    assert _service()["depends_on"]["dex"] == {"condition": "service_healthy"}


def test_it_talks_to_dexs_grpc_api_over_the_compose_network_not_a_published_port() -> (
    None
):
    """Dex's gRPC API (dex/config.yaml.tpl) grants full control over every account, so
    it must never be a published port -- only reachable from here, container to
    container. Checked against the whole file: no service publishes 5557."""
    service = _service()

    assert service["environment"]["PFP_DEX_GRPC_ADDR"] == "dex:5557"
    every_port = [
        str(p) for s in _compose()["services"].values() for p in s.get("ports", [])
    ]
    assert not any(":5557" in p for p in every_port)


def test_its_own_image_is_pinned_and_its_dependencies_are_exact_versions() -> None:
    assert _service()["image"] == "pfp-dex-register:1.0.0"
    for package in ("grpcio", "grpcio-tools", "protobuf", "bcrypt"):
        assert f"{package}==" in _DOCKERFILE, package


def test_the_generated_grpc_stubs_are_never_committed() -> None:
    """api_pb2*.py come from api.proto, generated at image build time (protoc), not
    checked in -- they are Dex's own wire format, not this project's code."""
    assert not (_ROOT / "dex-register" / "api_pb2.py").exists()
    assert not (_ROOT / "dex-register" / "api_pb2_grpc.py").exists()
    assert "grpc_tools.protoc" in _DOCKERFILE


def test_the_password_is_only_ever_used_to_validate_and_to_hash() -> None:
    """The submitted password is read exactly twice: passed to `validate`, then
    hashed. `_page(...)` is never built from an f-string or a `fields[...]` value, so
    nothing user-typed -- the password least of all -- reaches the HTML response."""
    assert _APP.count('fields.get("password"') == 1
    assert _APP.count('fields["password"]') == 1
    assert '_page(f"' not in _APP
    assert "_page(fields[" not in _APP
