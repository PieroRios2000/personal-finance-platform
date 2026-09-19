"""Where alerts go: email (SMTP) and Microsoft Teams (a webhook URL). Each one
turns on when its own environment variables are set; both can be on at once.

A failed send returns a short description and never raises into the caller, and
never includes the webhook URL or the SMTP password (both are secrets).
"""

import json
import smtplib
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

_TIMEOUT_SECONDS = 15


class Channel(Protocol):
    def send(self, subject: str, body: str) -> str | None: ...


@dataclass(frozen=True)
class EmailChannel:
    host: str
    port: int
    sender: str
    recipients: tuple[str, ...]
    user: str | None = None
    password: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "EmailChannel | None":
        host, sender, to = (
            env.get("ALERT_SMTP_HOST"),
            env.get("ALERT_EMAIL_FROM"),
            env.get("ALERT_EMAIL_TO"),
        )
        if not (host and sender and to):
            return None
        return cls(
            host=host,
            port=int(env.get("ALERT_SMTP_PORT", "587")),
            sender=sender,
            recipients=tuple(r.strip() for r in to.split(",") if r.strip()),
            user=env.get("ALERT_SMTP_USER") or None,
            password=env.get("ALERT_SMTP_PASSWORD") or None,
        )

    def send(self, subject: str, body: str) -> str | None:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.sender
        message["To"] = ", ".join(self.recipients)
        message.set_content(body)
        try:
            with smtplib.SMTP(self.host, self.port, timeout=_TIMEOUT_SECONDS) as smtp:
                smtp.starttls()
                if self.user and self.password:
                    smtp.login(self.user, self.password)
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException) as error:
            return f"email: {type(error).__name__}"
        return None


@dataclass(frozen=True)
class TeamsChannel:
    """A Teams "Workflows" webhook (or any endpoint accepting the same JSON):
    an Adaptive Card with the subject and the body."""

    url: str

    def send(self, subject: str, body: str) -> str | None:
        card = {
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": [
                {
                    "type": "TextBlock",
                    "text": subject,
                    "weight": "Bolder",
                    "wrap": True,
                },
                {"type": "TextBlock", "text": body, "wrap": True},
            ],
        }
        payload = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": card,
                }
            ],
        }
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS):
                return None
        except (OSError, urllib.error.URLError) as error:
            return f"teams: {type(error).__name__}"


def channels_from_env(env: Mapping[str, str]) -> list[Channel]:
    found: list[Channel] = []
    email = EmailChannel.from_env(env)
    if email is not None:
        found.append(email)
    url = env.get("ALERT_TEAMS_WEBHOOK_URL")
    if url:
        found.append(TeamsChannel(url))
    return found
