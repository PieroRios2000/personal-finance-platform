"""Password reset by email for the Dex sign-up page (T43, ADR 0038): the pure logic --
single-use tokens, the email, and whether SMTP is configured. Stdlib only, like
`registration.py`, so the main project's environment can import and test it; `app.py`
is the one file that needs the container's gRPC client.

The token is 32 random bytes; only its SHA-256 is kept, in memory, for
`TOKEN_LIFETIME_SECONDS`. A restart forgets pending tokens (the person asks again),
which is cheaper than a database for a link that lives 30 minutes.
"""

import hashlib
import secrets
import smtplib
import ssl
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from email.message import EmailMessage

TOKEN_LIFETIME_SECONDS = 1800
_SMTP_TIMEOUT_SECONDS = 15


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class TokenStore:
    def __init__(self) -> None:
        self._pending: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def issue(self, email: str, now: float | None = None) -> str:
        """A new token for `email`; any earlier one for the same email stops working."""
        now = time.time() if now is None else now
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._pending = {
                d: (e, t)
                for d, (e, t) in self._pending.items()
                if e != email and now - t < TOKEN_LIFETIME_SECONDS
            }
            self._pending[_digest(token)] = (email, now)
        return token

    def peek(self, token: str, now: float | None = None) -> str | None:
        """The email a live token belongs to, without using it up."""
        now = time.time() if now is None else now
        with self._lock:
            found = self._pending.get(_digest(token))
        if found is None or now - found[1] >= TOKEN_LIFETIME_SECONDS:
            return None
        return found[0]

    def consume(self, token: str) -> None:
        with self._lock:
            self._pending.pop(_digest(token), None)


@dataclass(frozen=True)
class Mailer:
    host: str
    port: int
    sender: str
    user: str | None
    password: str | None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Mailer | None":
        """The same `ALERT_SMTP_*` variables as the alerting (Phase 7); `None` when
        they are not set, so the page can say reset by email is not available."""
        host, sender = env.get("ALERT_SMTP_HOST"), env.get("ALERT_EMAIL_FROM")
        if not (host and sender):
            return None
        return cls(
            host=host,
            port=int(env.get("ALERT_SMTP_PORT") or "587"),
            sender=sender,
            user=env.get("ALERT_SMTP_USER") or None,
            password=env.get("ALERT_SMTP_PASSWORD") or None,
        )

    def send(self, to: str, link: str) -> None:
        message = EmailMessage()
        message["Subject"] = "Reset your password"
        message["From"] = self.sender
        message["To"] = to
        message.set_content(
            "Someone asked to reset the password for this email.\n\n"
            f"Open this link within {TOKEN_LIFETIME_SECONDS // 60} minutes:\n{link}\n\n"
            "If it was not you, ignore this message: nothing changes."
        )
        with smtplib.SMTP(self.host, self.port, timeout=_SMTP_TIMEOUT_SECONDS) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if self.user and self.password:
                smtp.login(self.user, self.password)
            smtp.send_message(message)
