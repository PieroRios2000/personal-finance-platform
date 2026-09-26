"""Pure logic for the upload portal (T44, ADR 0040): which user_id someone gets, which
banks and sizes are accepted, and a per-person rate limit. Stdlib only, like
`dex-register/registration.py`, so it is importable and tested from the main project's
environment; `app.py` is the one file that needs the container's dependencies."""

import re
import secrets
import threading
import time

# Must match ingestion.dispatcher (tested).
BANKS = ("BCP", "Scotiabank")
OTHER_BANK = "Other bank"
# What someone can say a file is: a bank account statement (estado de cuenta) or a
# credit card statement (tarjeta de credito).
KINDS = {
    "account": "Bank account statement (estado de cuenta)",
    "card": "Credit card statement (tarjeta de credito)",
}
# The (bank, kind) pairs a parser reads today: BCP's account statements, and both of
# Scotiabank's (its card and its savings account, one parser, ADR 0012). Anything
# else -- another bank, or BCP's credit card -- is kept for the owner to study in a
# separate request (ADR 0040), never fed to the pipeline.
SUPPORTED = frozenset(
    {("BCP", "account"), ("Scotiabank", "account"), ("Scotiabank", "card")}
)
REVIEW_FOLDER = (
    "_new_bank"  # under the person's inbox folder: the pipeline never looks in it
)
_BANK_NAME = re.compile(r"[^A-Za-z0-9 .&-]")
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


def clean_bank_name(raw: str) -> str:
    """What someone typed as their bank, reduced to letters, digits and a few marks and
    cut short: it ends up in a file name and in the file's metadata."""
    return " ".join(_BANK_NAME.sub("", raw).split())[:40]


def route(bank: str, kind: str, other_bank: str) -> tuple[bool, str] | None:
    """Where an upload goes: `(True, bank)` to the pipeline, `(False, name)` to the
    review folder, or None when the form is invalid (an unknown kind or bank, or "other"
    with no name)."""
    if kind not in KINDS:
        return None
    if bank in BANKS:
        return ((bank, kind) in SUPPORTED, bank)
    if bank == OTHER_BANK:
        name = clean_bank_name(other_bank)
        return (False, name) if name else None
    return None


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
