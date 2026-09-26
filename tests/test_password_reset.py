"""Password reset by email (T43, ADR 0038): the pure logic in `dex-register/reset.py`
and `registration.py`, and static checks on how it is wired. `app.py` (gRPC, the HTTP
server) and Dex rendering the login-form links are exercised live: see the PR."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parent.parent
_APP = (_ROOT / "dex-register" / "app.py").read_text()


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        name, _ROOT / "dex-register" / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


registration = _load("registration")
reset = _load("reset")


def test_a_token_belongs_to_its_email_and_works_until_it_expires() -> None:
    store = reset.TokenStore()
    token = store.issue("ana@example.com", now=1000)

    assert store.peek(token, now=1000 + 60) == "ana@example.com"
    assert store.peek(token, now=1000 + reset.TOKEN_LIFETIME_SECONDS) is None


def test_a_token_is_single_use_and_unknown_tokens_are_refused() -> None:
    store = reset.TokenStore()
    token = store.issue("ana@example.com")

    store.consume(token)

    assert store.peek(token) is None
    assert store.peek("never-issued") is None


def test_a_new_request_cancels_the_earlier_link_for_the_same_email() -> None:
    store = reset.TokenStore()
    first = store.issue("ana@example.com")
    second = store.issue("ana@example.com")
    other = store.issue("bea@example.com")

    assert store.peek(first) is None
    assert store.peek(second) == "ana@example.com"
    assert store.peek(other) == "bea@example.com"


def test_only_a_digest_of_the_token_is_kept() -> None:
    store = reset.TokenStore()
    token = store.issue("ana@example.com")

    assert token not in store._pending
    assert len(token) >= 43  # 32 random bytes, urlsafe


def test_the_mailer_needs_the_same_smtp_variables_as_the_alerting() -> None:
    assert reset.Mailer.from_env({}) is None
    assert reset.Mailer.from_env({"ALERT_SMTP_HOST": "smtp.example.com"}) is None
    mailer = reset.Mailer.from_env(
        {"ALERT_SMTP_HOST": "smtp.example.com", "ALERT_EMAIL_FROM": "me@example.com"}
    )

    assert mailer is not None and mailer.port == 587


def test_the_mail_goes_over_starttls_with_the_link_and_no_other_recipient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Any] = []

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            calls.append(("connect", host, port))

        def __enter__(self) -> "FakeSMTP":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def starttls(self, context: object) -> None:
            calls.append("starttls")

        def login(self, user: str, password: str) -> None:
            calls.append(("login", user))

        def send_message(self, message: Any) -> None:
            calls.append(message)

    monkeypatch.setattr(reset.smtplib, "SMTP", FakeSMTP)
    mailer = reset.Mailer("smtp.example.com", 587, "me@example.com", "u", "p")

    mailer.send("ana@example.com", "https://register.example.com/reset?token=abc")

    assert calls[:3] == [
        ("connect", "smtp.example.com", 587),
        "starttls",
        ("login", "u"),
    ]
    message = calls[3]
    assert message["To"] == "ana@example.com"
    assert "https://register.example.com/reset?token=abc" in message.get_content()


def test_sign_up_and_reset_share_one_password_rule() -> None:
    assert registration.validate_password("longenough1", "longenough1") is None
    assert registration.validate_password("short", "short") is not None
    assert registration.validate_password("longenough1", "different1") is not None


def test_a_throttle_can_be_stricter() -> None:
    throttle = registration.Throttle(max_attempts=2)
    throttle.record_failure("ip", now=1)
    throttle.record_failure("ip", now=2)

    assert throttle.blocked("ip", now=3)
    assert not registration.Throttle().blocked("ip", now=3)


def test_the_forgot_page_answers_the_same_and_sends_off_the_request_thread() -> None:
    """Whether the email has an account must not show in the answer or its timing:
    the lookup and the SMTP call run in a thread, the reply is one fixed message."""
    assert "target=_send_reset_link" in _APP
    assert _APP.count("If that email has an account") == 1


def test_a_failed_update_never_crashes_the_reset_request() -> None:
    assert "except grpc.RpcError" in _APP.split("UpdatePasswordReq(")[1]


def test_the_reset_page_keeps_the_token_out_of_referrers() -> None:
    assert '"Referrer-Policy", "no-referrer"' in _APP


def _compose() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(
        (_ROOT / "bi" / "docker-compose.yml").read_text()
    )
    services: dict[str, Any] = loaded["services"]
    return services


def test_dex_register_gets_the_smtp_settings_and_its_public_address() -> None:
    environment = _compose()["dex-register"]["environment"]

    for name in (
        "PFP_REGISTER_PUBLIC_URL",
        "ALERT_SMTP_HOST",
        "ALERT_SMTP_PASSWORD",
        "ALERT_EMAIL_FROM",
    ):
        assert environment[name].startswith("${"), name


def test_dex_shows_the_two_links_from_a_mounted_template() -> None:
    dex = _compose()["dex"]
    template = (_ROOT / "dex" / "templates" / "password.html").read_text()
    config = (_ROOT / "dex" / "config.yaml.tpl").read_text()

    mount = "../dex/templates/password.html:/srv/dex/web/templates/password.html:ro"
    assert mount in dex["volumes"]
    assert dex["environment"]["PFP_REGISTER_PUBLIC_URL"].startswith("${")
    assert 'extra "register_url" }}/forgot' in template
    assert 'extra "register_url" }}/"' in template
    assert 'name="password"' in template  # still Dex's own login form
    assert "dir: /srv/dex/web" in config
    assert 'register_url: {{ getenv "PFP_REGISTER_PUBLIC_URL" }}' in config
