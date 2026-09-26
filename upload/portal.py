"""Pure logic for the upload portal (T44, ADR 0040): which user_id someone gets, which
banks and sizes are accepted, and a per-person rate limit. Stdlib only, like
`dex-register/registration.py`, so it is importable and tested from the main project's
environment; `app.py` is the one file that needs the container's dependencies."""

import re
import secrets
import threading
import time

BANKS = ("BCP", "Scotiabank")  # must match ingestion.dispatcher (tested)
MAX_FILE_BYTES = 15 * 1024 * 1024
MAX_FILES_PER_UPLOAD = 12
MAX_UPLOADS_PER_HOUR = 40
WINDOW_SECONDS = 3600

_USER_ID = re.compile(r"[a-z0-9][a-z0-9_-]{2,40}")


def is_user_id(value: str) -> bool:
    """A name safe to be a folder under the inbox and the value Superset filters on."""
    return _USER_ID.fullmatch(value) is not None


def new_user_id(email: str, taken: set[str]) -> str:
    """`ana-3f2a` for `ana.perez@example.com`: the local part reduced to [a-z0-9], plus
    four random hex digits so two people named alike never share a folder, and one that
    no existing account already uses."""
    local = re.sub(r"[^a-z0-9]", "", email.split("@")[0].lower())[:20] or "user"
    while True:
        candidate = f"{local}-{secrets.token_hex(2)}"
        if candidate not in taken and is_user_id(candidate):
            return candidate


def is_unscoped(username: str) -> bool:
    """Accounts get their email as username until scoped (ADR 0036); an email has an
    `@`, and no user_id this project writes has one."""
    return "@" in username


class UploadLimit:
    """At most MAX_UPLOADS_PER_HOUR files per person per hour: the portal is public and
    every file is parsed, so it must not be a way to fill the owner's disk or CPU."""

    def __init__(self) -> None:
        self._seen: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, who: str, count: int, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self._lock:
            recent = [t for t in self._seen.get(who, []) if now - t < WINDOW_SECONDS]
            if len(recent) + count > MAX_UPLOADS_PER_HOUR:
                self._seen[who] = recent
                return False
            self._seen[who] = recent + [now] * count
            return True
