"""Decide what people uploaded, and tell them (T48, ADR 0041).

    uv run python -m scripts.process_submissions run
    uv run python -m scripts.process_submissions list
    uv run python -m scripts.process_submissions decide <id> reject|release

`run` takes every submission waiting (`received`) and reads **every** file as the
kind, bank and currency the person said. Only if all of them read, reconcile and match
does it move them into that person's inbox and run `pfp ingest`: the person gets an
"accepted" email with counts. If any file fails, the **whole** submission is rejected,
nothing is loaded, and the person gets a "rejected" email saying which file numbers
failed and how. Duplicates are not failures: the pipeline already ignores a file it has
(ADR 0024), and the email says how many.

A submission for a bank, kind or currency no parser reads (`review`) waits for the
owner: `decide <id> reject` tells the person no; `decide <id> release` puts it back in
`run`'s queue once support exists. Emails go over the alerting's SMTP variables and only
ever say counts and file numbers, never a file name, an amount or a page (ADR 0004).
"""

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from alerting.channels import EmailChannel
from ingestion import dispatcher, submissions
from ingestion.dedup import file_sha256
from ingestion.organizer import DEFAULT_INBOX_ROOT
from ingestion.reconciliation import ReconciliationError
from ingestion.schema import MissingAccountKeyError, Statement

_ASSET_KINDS = {"account": "asset", "card": "liability"}
_SUMMARY = re.compile(r"Archived: (\d+)\s+Duplicates: (\d+)\s+Needs review: (\d+)")
_WRITTEN = re.compile(r"Bronze: (\d+) statement\(s\) written")

Parse = Callable[..., list[Statement]]
Ingest = Callable[[str], "tuple[int, int, int, int] | None"]
Notify = Callable[[str, tuple[str, str]], str | None]


def check_file(
    path: Path, *, user_id: str, kind: str, currency: str, parse: Parse
) -> str:
    """Why this file must be rejected, or "" if it reads as what was said."""
    try:
        statements = parse(path, user_id=user_id, file_sha256=file_sha256(path))
    except MissingAccountKeyError:
        raise
    except ReconciliationError:
        return "its balances do not add up"
    except Exception:  # an unreadable or hostile file is a rejection, never a crash
        return "it could not be read as a statement of the bank you chose"
    if not statements:
        return "it holds no statement"
    if any(s.account_kind != _ASSET_KINDS[kind] for s in statements):
        what = "credit card" if kind == "card" else "bank account"
        return f"it is not a {what} statement"
    allowed = {"PEN", "USD"} if currency == "BOTH" else {currency}
    if any(s.currency not in allowed for s in statements):
        return (
            f"its currency is not {currency} "
            "(choose 'Both' for a card with soles and dollars)"
        )
    return ""


def check_submission(
    folder: Path, manifest: submissions.Manifest, user_id: str, parse: Parse
) -> str:
    """The reason the whole submission is rejected, or "" if every file passes."""
    reasons = []
    for number, path in enumerate(sorted(folder.glob("*.pdf")), start=1):
        why = check_file(
            path,
            user_id=user_id,
            kind=manifest.kind,
            currency=manifest.currency,
            parse=parse,
        )
        if why:
            reasons.append(f"file {number}: {why}")
    return "; ".join(reasons)


def ingest_with_pfp(user_id: str) -> tuple[int, int, int, int] | None:
    """(archived, duplicates, needs review, written) from `pfp ingest`, or None."""
    done = subprocess.run(
        ["uv", "run", "pfp", "ingest", "--user", user_id],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        return None
    summary, written = _SUMMARY.search(done.stdout), _WRITTEN.search(done.stdout)
    if summary is None or written is None:
        return None
    archived, duplicates, review = (int(g) for g in summary.groups())
    return archived, duplicates, review, int(written.group(1))


def notify_by_email(email: str, message: tuple[str, str]) -> str | None:
    channel = EmailChannel.from_env(os.environ)
    if channel is None:
        return "email is not configured (ALERT_SMTP_HOST, ALERT_EMAIL_TO...)"
    return channel.to(email).send(*message)


def run(
    inbox_root: Path,
    *,
    parse: Parse = dispatcher.parse,
    ingest: Ingest = ingest_with_pfp,
    notify: Notify = notify_by_email,
) -> list[str]:
    """One line per submission decided: `<id> accepted|rejected ...`."""
    lines = []
    for user_id, folder, manifest in submissions.find(inbox_root, submissions.RECEIVED):
        reason = check_submission(folder, manifest, user_id, parse)
        if reason:
            manifest.status, manifest.reason = submissions.REJECTED, reason
            submissions.write(folder, manifest)
            error = notify(manifest.email, submissions.rejected_mail(manifest))
            lines.append(f"{manifest.id} rejected ({reason})" + _mail_note(error))
            continue
        for number, path in enumerate(sorted(folder.glob("*.pdf")), start=1):
            path.rename(inbox_root / user_id / f"{manifest.id}-{number:02d}.pdf")
        manifest.status = submissions.ACCEPTED
        result = ingest(user_id)
        if result is None:
            manifest.reason = (
                "ingest failed: run `pfp ingest` for this user, then tell them"
            )
            submissions.write(folder, manifest)
            lines.append(f"{manifest.id} accepted but ingest FAILED: not emailed")
            continue
        _archived, manifest.duplicates, review, manifest.loaded = result
        if review:
            manifest.reason = f"{review} file(s) need a second look (_needs_review)"
        submissions.write(folder, manifest)
        error = notify(manifest.email, submissions.accepted_mail(manifest))
        lines.append(
            f"{manifest.id} accepted: {manifest.loaded} statement(s), "
            f"{manifest.duplicates} duplicate(s)" + _mail_note(error)
        )
    return lines


def decide(
    inbox_root: Path, submission_id: str, decision: str, *, notify: Notify
) -> str:
    """The owner's call on a submission waiting in `review`."""
    for _user, folder, manifest in submissions.find(inbox_root, submissions.REVIEW):
        if manifest.id != submission_id:
            continue
        if decision == "release":
            manifest.status = submissions.RECEIVED
            submissions.write(folder, manifest)
            return f"{submission_id} released: the next `run` processes it"
        manifest.status = submissions.REJECTED
        manifest.reason = "we cannot read this bank, kind or currency"
        submissions.write(folder, manifest)
        error = notify(manifest.email, submissions.rejected_mail(manifest))
        return f"{submission_id} rejected" + _mail_note(error)
    return f"no submission {submission_id} waiting for review"


def _mail_note(error: str | None) -> str:
    return f" (email not sent: {error})" if error else " (emailed)"


def listing(inbox_root: Path) -> str:
    rows = ["id | status | bank | kind | currency | files"]
    for _user, _folder, m in submissions.find(inbox_root, *submissions.STATUSES):
        rows.append(
            f"{m.id} | {m.status} | {m.bank} | {m.kind} | {m.currency} | {m.files}"
        )
    return "\n".join(rows) if len(rows) > 1 else "No submissions."


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inbox-root", type=Path, default=DEFAULT_INBOX_ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run")
    commands.add_parser("list")
    decide_parser = commands.add_parser("decide")
    decide_parser.add_argument("id")
    decide_parser.add_argument("decision", choices=("reject", "release"))
    args = parser.parse_args(argv)

    if args.command == "list":
        print(listing(args.inbox_root))
    elif args.command == "decide":
        print(decide(args.inbox_root, args.id, args.decision, notify=notify_by_email))
    else:
        try:
            lines = run(args.inbox_root)
        except MissingAccountKeyError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        print("\n".join(lines) if lines else "Nothing waiting to process.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
