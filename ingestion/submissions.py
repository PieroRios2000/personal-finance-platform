"""A submission: one upload request, accepted or rejected as a whole (T48, ADR 0041).

Someone can send up to 10 PDFs at once (say, several months of one bank's statements).
They are all checked when they arrive; if one fails, nothing is kept. What arrives is
stored as a folder, `<inbox>/<user_id>/_submissions/<id>/`, with the unlocked files and
a `submission.json` saying who sent it, what they said it is and where it stands. The
owner's `make ingest-uploads` decides each one: every file must read as the kind, bank
and currency the person said, or the whole submission is rejected; otherwise the files
move into the inbox for the normal pipeline. The person is emailed at each step.

Stdlib only: the upload portal (a container) and the owner's scripts share this file.
What is written down and emailed is names and counts, never a file name or a page
(ADR 0004).
"""

import json
import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

FOLDER = "_submissions"  # under a person's inbox folder: the pipeline never looks in it
MANIFEST = "submission.json"

RECEIVED = "received"  # waiting for the owner to process it
REVIEW = "review"  # a bank, kind or currency no parser reads yet: waiting for the owner
ACCEPTED = "accepted"  # every file read as said, and is now in the pipeline
REJECTED = "rejected"  # a file failed: nothing was loaded
STATUSES = (RECEIVED, REVIEW, ACCEPTED, REJECTED)

MAX_FILES = 10
EXCEL = "excel"  # the kind of a workbook of savings and investments (T49)


@dataclass
class Manifest:
    id: str
    email: str
    kind: str
    bank: str
    currency: str
    files: int
    status: str
    created: str
    reason: str = ""  # why it was rejected: which file numbers, and the kind of failure
    loaded: int = 0  # how many statements reached the pipeline (accepted only)
    duplicates: int = 0  # files the pipeline already had (accepted only)


def new_id() -> str:
    return secrets.token_hex(4)


def create(
    inbox_user_dir: Path,
    *,
    email: str,
    kind: str,
    bank: str,
    currency: str,
    contents: list[bytes],
    review: bool,
    suffix: str = ".pdf",
) -> Manifest:
    """Write a submission's folder: its files (unlocked) and its manifest."""
    manifest = Manifest(
        id=new_id(),
        email=email,
        kind=kind,
        bank=bank,
        currency=currency,
        files=len(contents),
        status=REVIEW if review else RECEIVED,
        created=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    folder = inbox_user_dir / FOLDER / manifest.id
    folder.mkdir(mode=0o700, parents=True)
    for number, content in enumerate(contents, start=1):
        _write_private(folder / f"{number:02d}{suffix}", content)
    write(folder, manifest)
    return manifest


def write(folder: Path, manifest: Manifest) -> None:
    _write_private(
        folder / MANIFEST, json.dumps(asdict(manifest), indent=2).encode(), replace=True
    )


def read(folder: Path) -> Manifest:
    return Manifest(**json.loads((folder / MANIFEST).read_text()))


def find(inbox_root: Path, *statuses: str) -> list[tuple[str, Path, Manifest]]:
    """(user_id, folder, manifest) of every submission in one of `statuses`."""
    found = []
    for manifest_path in sorted(inbox_root.glob(f"*/{FOLDER}/*/{MANIFEST}")):
        folder = manifest_path.parent
        manifest = read(folder)
        if manifest.status in statuses:
            found.append((folder.parents[1].name, folder, manifest))
    return found


def _write_private(path: Path, content: bytes, *, replace: bool = False) -> None:
    flags = "wb" if replace else "xb"
    with path.open(flags) as handle:
        handle.write(content)
    path.chmod(0o600)


# What the person is told. English, like the portal; no file name, no amount.
def _what(manifest: Manifest) -> str:
    if manifest.kind == EXCEL:
        return "a workbook of savings and investments"
    return (
        f"{manifest.files} file(s): {manifest.bank}, {manifest.kind}, "
        f"{manifest.currency}"
    )


def received_mail(manifest: Manifest) -> tuple[str, str]:
    subject = f"We received your files (request {manifest.id})"
    if manifest.status == REVIEW:
        state = (
            "This bank, kind or currency is not read automatically yet, so the "
            "owner will look at how to read it first. You will get another email "
            "with the decision."
        )
    else:
        state = (
            "They are under review. You will get another email when they are processed."
        )
    return (
        subject,
        f"Your request {manifest.id} arrived: {_what(manifest)}.\n\n{state}\n",
    )


def accepted_mail(manifest: Manifest) -> tuple[str, str]:
    body = (
        f"Your request {manifest.id} ({_what(manifest)}) was accepted and "
        f"processed: {manifest.loaded} "
        f"{'month(s) or statement(s)' if manifest.kind == EXCEL else 'statement(s)'}"
        " are now in your dashboard."
    )
    if manifest.duplicates:
        body += f"\n{manifest.duplicates} file(s) were already loaded and were ignored."
    return f"Your request {manifest.id} was processed", body + "\n"


def rejected_mail(manifest: Manifest) -> tuple[str, str]:
    body = (
        f"Your request {manifest.id} ({_what(manifest)}) was rejected as a whole, "
        f"and nothing was loaded.\n\nWhy: {manifest.reason}\n\nCheck the files, "
        "the kind, the bank and the currency you chose, and send the request again."
    )
    return f"Your request {manifest.id} was rejected", body + "\n"
