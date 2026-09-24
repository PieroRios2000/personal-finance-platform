"""Pure logic for the self-service Dex registration page (T40, ADR 0035): whether a
submission is good to create an account, and a per-IP throttle on wrong invite codes.
No grpc/bcrypt here on purpose -- `app.py` is the one file that needs a container's
dependencies (grpc, the generated Dex API stubs); this one is plain stdlib so it can be
imported and tested from the main project's environment."""

import hmac
import re
import threading
import time

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8
MAX_ATTEMPTS = 5
WINDOW_SECONDS = 300


def validate(
    email: str, password: str, confirm: str, invite_code: str, expected_code: str
) -> str | None:
    """`None` when the submission is good to create; otherwise the message to show.

    The invite code is checked first and in constant time: it is the one thing that
    keeps this page (public, gated by nothing else) from letting a stranger create an
    account -- everyone who can reach the page can already see whether an email or a
    password looks wrong, but never whether the code was close."""
    if not hmac.compare_digest(invite_code, expected_code):
        return "That invite code is wrong."
    if not EMAIL.fullmatch(email):
        return "That doesn't look like an email address."
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Use a password of at least {MIN_PASSWORD_LENGTH} characters."
    if password != confirm:
        return "The two passwords don't match."
    return None


class Throttle:
    """At most `MAX_ATTEMPTS` failed submissions per IP in `WINDOW_SECONDS`: the page
    is public, so the invite code is the only thing standing between a stranger and an
    account, and a code long enough to be safe is still worth slowing brute force on."""

    def __init__(self) -> None:
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def blocked(self, ip: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self._lock:
            recent = [t for t in self._failures.get(ip, []) if now - t < WINDOW_SECONDS]
            self._failures[ip] = recent
            return len(recent) >= MAX_ATTEMPTS

    def record_failure(self, ip: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            self._failures.setdefault(ip, []).append(now)
