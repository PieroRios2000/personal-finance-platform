import json
import smtplib
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from alerting.channels import EmailChannel, TeamsChannel, channels_from_env


class _FakeSMTP:
    instances: list["_FakeSMTP"] = []

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host, self.port = host, port
        self.started_tls = False
        self.login_args: tuple[str, str] | None = None
        self.sent: list[Any] = []
        _FakeSMTP.instances.append(self)

    def __enter__(self) -> "_FakeSMTP":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def starttls(self) -> None:
        self.started_tls = True

    def login(self, user: str, password: str) -> None:
        self.login_args = (user, password)

    def send_message(self, message: Any) -> None:
        self.sent.append(message)


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)


def _email(env: dict[str, str]) -> EmailChannel:
    channel = EmailChannel.from_env(env)
    assert channel is not None
    return channel


_EMAIL_ENV = {
    "ALERT_SMTP_HOST": "smtp.example.test",
    "ALERT_SMTP_PORT": "2525",
    "ALERT_SMTP_USER": "me",
    "ALERT_SMTP_PASSWORD": "s3cret",
    "ALERT_EMAIL_FROM": "pfp@example.test",
    "ALERT_EMAIL_TO": "a@example.test, b@example.test",
}


def test_no_configuration_means_no_channels() -> None:
    assert channels_from_env({}) == []


def test_each_channel_turns_on_with_its_own_variables() -> None:
    env = {**_EMAIL_ENV, "ALERT_TEAMS_WEBHOOK_URL": "https://teams.example.test/hook"}

    kinds = {type(c) for c in channels_from_env(env)}

    assert kinds == {EmailChannel, TeamsChannel}
    assert [type(c) for c in channels_from_env(_EMAIL_ENV)] == [EmailChannel]


def test_an_email_goes_to_every_recipient_over_starttls_with_login() -> None:
    _email(_EMAIL_ENV).send("subject", "body")

    (smtp,) = _FakeSMTP.instances
    assert (smtp.host, smtp.port) == ("smtp.example.test", 2525)
    assert smtp.started_tls
    assert smtp.login_args == ("me", "s3cret")
    (message,) = smtp.sent
    assert message["Subject"] == "subject"
    assert message["To"] == "a@example.test, b@example.test"
    assert message.get_content().strip() == "body"


def test_email_without_credentials_skips_login() -> None:
    env = {k: v for k, v in _EMAIL_ENV.items() if k not in ("ALERT_SMTP_USER",)}

    _email(env).send("s", "b")

    assert _FakeSMTP.instances[0].login_args is None


class _Hook(BaseHTTPRequestHandler):
    received: list[dict[str, Any]] = []

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        _Hook.received.append(json.loads(self.rfile.read(length)))
        self.send_response(202)
        self.end_headers()

    def log_message(self, *args: object) -> None:
        return None


def test_teams_gets_an_adaptive_card_with_the_subject_and_body() -> None:
    _Hook.received.clear()
    server = HTTPServer(("127.0.0.1", 0), _Hook)
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/hook"

    TeamsChannel(url).send("[pfp] 1 error", "ERROR  dbt: a_test (4)")
    thread.join(timeout=5)
    server.server_close()

    (payload,) = _Hook.received
    assert payload["type"] == "message"
    card = payload["attachments"][0]["content"]
    assert card["type"] == "AdaptiveCard"
    texts = [block["text"] for block in card["body"]]
    assert texts == ["[pfp] 1 error", "ERROR  dbt: a_test (4)"]


def test_a_failing_channel_reports_without_leaking_its_secret() -> None:
    secret_url = "http://127.0.0.1:1/very-secret-token"

    error = TeamsChannel(secret_url).send("s", "b")

    assert error is not None
    assert "very-secret-token" not in error


def test_a_successful_send_reports_nothing() -> None:
    assert _email(_EMAIL_ENV).send("s", "b") is None


def test_a_failing_email_reports_the_error_type_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise ConnectionRefusedError("s3cret host details")

    monkeypatch.setattr(smtplib, "SMTP", refuse)

    error = _email(_EMAIL_ENV).send("s", "b")

    assert error == "email: ConnectionRefusedError"
