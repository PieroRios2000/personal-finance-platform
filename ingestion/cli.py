"""`pfp` command-line interface (T12).

    uv run pfp parse <pdf> [--user <id>]

Detects the bank, parses and reconciles the statement, and prints a short
summary. Exits non-zero (with a message on stderr) if the bank isn't
recognized, the password is wrong, or the statement doesn't reconcile.
"""

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import pikepdf

from ingestion import dispatcher
from ingestion.dedup import file_sha256
from ingestion.reconciliation import ReconciliationError
from ingestion.schema import MissingAccountKeyError


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

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
