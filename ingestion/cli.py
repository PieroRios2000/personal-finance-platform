"""`pfp` command-line interface (T12, T12b, T14).

    uv run pfp parse <pdf> [--user <id>]
    uv run pfp organize [--user <id>] [--inbox-root DIR] [--archive-root DIR]
    uv run pfp ingest [--user <id>] [--inbox-root DIR] [--archive-root DIR]

`parse` detects the bank, parses and reconciles one statement, and prints a short
summary. Exits non-zero (with a message on stderr) if the bank isn't recognized,
the password is wrong, or the statement doesn't reconcile.

`organize` files every PDF in a user's inbox into the standard archive layout
(ADR 0009) and prints a report; see `ingestion.organizer` for what it does with
duplicates, unreadable files and regenerated statements.

`ingest` does what `organize` does, then writes every newly archived statement to
the bronze lakehouse (T14), skipping any file whose sha256 is already recorded in
`bronze/ingested_files` for that user.
"""

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import pikepdf

from ingestion import dispatcher, organizer
from ingestion.dedup import file_sha256
from ingestion.reconciliation import ReconciliationError
from ingestion.schema import MissingAccountKeyError
from lakehouse import bronze
from lakehouse.storage import MissingLakehouseURIError, lakehouse_uri


def _run_parse(args: argparse.Namespace) -> int:
    user_id: str | None = args.user
    if not user_id:
        print("error: --user is required (or set PFP_USER)", file=sys.stderr)
        return 2

    path: Path = args.pdf
    try:
        entry = dispatcher.detect(path)
    except dispatcher.UnrecognizedBankError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    password = os.environ.get(entry.password_env, "")
    try:
        statement = entry.parse(
            path,
            user_id=user_id,
            file_sha256=file_sha256(path),
            password=password,
        )
    except pikepdf.PasswordError:
        print(
            f"error: wrong or missing password (checked {entry.password_env})",
            file=sys.stderr,
        )
        return 1
    except MissingAccountKeyError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except ReconciliationError as error:
        print(f"reconciliation FAILED: {error}", file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"error: could not parse the statement: {error}", file=sys.stderr)
        return 1

    print(f"Bank: {statement.bank}")
    print(f"Account: ...{statement.account_last4}")
    print(f"Period: {statement.period_start} to {statement.period_end}")
    print(f"Transactions: {len(statement.transactions)}")
    print("Reconciliation: OK")
    return 0


def _run_organize(args: argparse.Namespace) -> int:
    user_id: str | None = args.user
    if not user_id:
        print("error: --user is required (or set PFP_USER)", file=sys.stderr)
        return 2

    try:
        report = organizer.organize(
            user_id, inbox_root=args.inbox_root, archive_root=args.archive_root
        )
    except MissingAccountKeyError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(report.render())
    return 0


def _run_ingest(args: argparse.Namespace) -> int:
    user_id: str | None = args.user
    if not user_id:
        print("error: --user is required (or set PFP_USER)", file=sys.stderr)
        return 2

    try:
        lakehouse_uri()
    except MissingLakehouseURIError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    try:
        report = organizer.organize(
            user_id, inbox_root=args.inbox_root, archive_root=args.archive_root
        )
    except MissingAccountKeyError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(report.render())

    written = 0
    skipped = 0
    for item in report.archived:
        if bronze.is_ingested(user_id, item.sha256):
            skipped += 1
            continue
        bronze.write_statement(item.statement, item.sha256)
        written += 1

    print()
    print(f"Bronze: {written} statement(s) written, {skipped} already ingested")
    return 0


def _add_inbox_args(subcommand: argparse.ArgumentParser) -> None:
    """`--user`, `--inbox-root` and `--archive-root`: shared by every subcommand
    that walks a user's inbox (`organize`, `ingest`)."""
    subcommand.add_argument(
        "--user", default=os.environ.get("PFP_USER"), help="defaults to $PFP_USER"
    )
    subcommand.add_argument(
        "--inbox-root",
        type=Path,
        default=organizer.DEFAULT_INBOX_ROOT,
        help=f"defaults to {organizer.DEFAULT_INBOX_ROOT}",
    )
    subcommand.add_argument(
        "--archive-root",
        type=Path,
        default=organizer.DEFAULT_ARCHIVE_ROOT,
        help=f"defaults to {organizer.DEFAULT_ARCHIVE_ROOT}",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pfp")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parse_cmd = subparsers.add_parser(
        "parse", help="Parse one bank statement PDF and print a summary."
    )
    parse_cmd.add_argument("pdf", type=Path)
    parse_cmd.add_argument(
        "--user", default=os.environ.get("PFP_USER"), help="defaults to $PFP_USER"
    )
    parse_cmd.set_defaults(func=_run_parse)

    organize_cmd = subparsers.add_parser(
        "organize",
        help="File every PDF in the inbox into the standard archive layout and "
        "print a report.",
    )
    _add_inbox_args(organize_cmd)
    organize_cmd.set_defaults(func=_run_organize)

    ingest_cmd = subparsers.add_parser(
        "ingest",
        help="Organize the inbox and write newly archived statements to bronze.",
    )
    _add_inbox_args(ingest_cmd)
    ingest_cmd.set_defaults(func=_run_ingest)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
