"""`pfp` command-line interface (T12, T12b, T14, T14c).

    uv run pfp parse <pdf> [--user <id>]
    uv run pfp organize [--user <id>] [--inbox-root DIR] [--archive-root DIR]
    uv run pfp ingest [--user <id>] [--inbox-root DIR] [--archive-root DIR]
    uv run pfp backfill [--user <id>] [--archive-root DIR] [--bank B]
                        [--account LAST4] [--dry-run]

`parse` detects the bank, parses and reconciles one statement, and prints a short
summary. Exits non-zero (with a message on stderr) if the bank isn't recognized,
the password is wrong, or the statement doesn't reconcile.

`organize` files every PDF in a user's inbox into the standard archive layout
(ADR 0009) and prints a report; see `ingestion.organizer` for what it does with
duplicates, unreadable files and regenerated statements.

`ingest` does what `organize` does, then writes every newly archived statement to
the bronze lakehouse (T14), skipping any file whose sha256 is already recorded in
`bronze/ingested_files` for that user.

`backfill` (T14c) goes the other way: it re-parses statements that are *already*
archived and already in bronze, replacing their rows with what today's parser
reads (ADR 0010). It's what makes a parser fix reach historical data, since
`ingest` only ever looks at the inbox and skips a file whose sha256 bronze
already knows. Nothing is moved or deleted on disk; `--dry-run` writes nothing
at all.
"""

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import pikepdf

from ingestion import dispatcher, manual_excel, organizer
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
        statements = entry.parse(
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

    # One PDF can hold several statements (T18: one per currency); the
    # "Statement N of M" line only shows up when there really is more than one,
    # so a single-statement bank's output is unchanged.
    for number, statement in enumerate(statements, start=1):
        if len(statements) > 1:
            if number > 1:
                print()
            print(f"Statement {number} of {len(statements)}")
        print(f"Bank: {statement.bank}")
        print(f"Account: ...{statement.account_last4}")
        print(f"Period: {statement.period_start} to {statement.period_end}")
        print(f"Transactions: {len(statement.transactions)}")
        print("Reconciliation: OK")
    return 0


def _run_import_manual(args: argparse.Namespace) -> int:
    workbook: Path = args.workbook
    if not workbook.exists():
        print("error: workbook not found", file=sys.stderr)
        return 2
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
        savings = manual_excel.read_savings(workbook, user_id=user_id)
        investments = manual_excel.read_investments(workbook, user_id=user_id)
    except MissingAccountKeyError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    problems = list(dict.fromkeys([*savings.problems, *investments.problems]))
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        print("nothing was written", file=sys.stderr)
        return 1
    for entry in savings.entries:
        bronze.replace_statement(entry.statement, entry.file_sha256)
    for month in investments.months:
        bronze.replace_investment_month(month)
    print(
        f"Ahorros: {len(savings.entries)} statement(s) written "
        f"(a month already loaded is replaced, not added)"
    )
    if savings.missing_months:
        print(
            f"Ahorros: {savings.missing_months} month(s) missing "
            "between the first and last"
        )
    if investments.months:
        print(f"Inversiones: {len(investments.months)} month(s) written")
        if investments.months_without_valuation:
            print(
                f"Inversiones: {investments.months_without_valuation} month(s) "
                "without a valuation (their return cannot be computed)"
            )
        if investments.missing_months:
            print(
                f"Inversiones: {investments.missing_months} month(s) missing "
                "between the first and last"
            )
    else:
        print("Inversiones: nothing to load")
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

    # `written` counts statements and `skipped` counts files: a file is either
    # skipped whole or written whole, but one file can carry several statements
    # (T18). `write_statement()` registers the file in `ingested_files` only
    # once (T14c), so calling it per statement with the same sha256 appends
    # every statement's rows while registering that file exactly once.
    written = 0
    skipped = 0
    for item in report.archived:
        if bronze.is_ingested(user_id, item.sha256):
            skipped += 1
            continue
        for statement in item.statements:
            bronze.write_statement(statement, item.sha256)
            written += 1

    print()
    print(f"Bronze: {written} statement(s) written, {skipped} already ingested")
    return 0


# Where `organize()` puts what it couldn't file as a statement. Neither holds an
# archived statement, so neither is backfill's to re-parse: a `_needs_review/`
# file was never ingested in the first place, and the way to retry one is to move
# it back to the inbox and run `pfp ingest` again.
_NOT_ARCHIVED_STATEMENTS = ("_duplicates", "_needs_review")


def _backfill_targets(
    archive: Path, *, bank: str | None, account: str | None
) -> list[Path]:
    """Every archived PDF under `archive` the filters keep.

    Both filters match the directory layout `organize()` already produced —
    `<bank>/<last4>-<id6>/<start>_<end>.pdf` (ADR 0009) — so narrowing a run
    never costs a parse. A path that isn't that shape (anything not exactly
    bank/account/file deep) isn't an archived statement and is left alone.
    """
    targets = []
    for pdf in sorted(archive.rglob("*.pdf")):
        parts = pdf.relative_to(archive).parts
        if len(parts) != 3 or parts[0] in _NOT_ARCHIVED_STATEMENTS:
            continue
        if bank is not None and parts[0].lower() != bank.lower():
            continue
        if account is not None and parts[1].split("-")[0] != account:
            continue
        targets.append(pdf)
    return targets


def _backfill_report(
    archive: Path,
    scanned: int,
    replaced: list[str],
    failures: list[tuple[str, str]],
    *,
    dry_run: bool,
) -> str:
    """A plain-text report, under the same rule as `OrganizeReport.render()`:
    counts, dates, sha256 prefixes and a bank plus last 4 digits, never an
    extracted value (a description, an amount, a full account number) and never
    a file's name on disk."""
    label = "Would replace" if dry_run else "Replaced"
    lines = [
        f"Archive: {archive}",
        f"Scanned: {scanned}  {label}: {len(replaced)}  Failed: {len(failures)}",
    ]
    if dry_run:
        lines.append("(dry run: nothing was written)")

    if replaced:
        lines.append("")
        lines.append(f"{label}:")
        lines.extend(replaced)

    if failures:
        lines.append("")
        lines.append("Failed to re-parse (their bronze rows are left untouched):")
        for n, (digest, reason) in enumerate(failures, start=1):
            lines.append(f"  #{n} (sha256 {digest[:8]}...): {reason}")

    return "\n".join(lines)


def _run_backfill(args: argparse.Namespace) -> int:
    user_id: str | None = args.user
    if not user_id:
        print("error: --user is required (or set PFP_USER)", file=sys.stderr)
        return 2

    try:
        lakehouse_uri()
    except MissingLakehouseURIError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    archive: Path = args.archive_root / user_id
    targets = _backfill_targets(archive, bank=args.bank, account=args.account)
    replaced: list[str] = []
    failures: list[tuple[str, str]] = []

    for pdf in targets:
        digest = file_sha256(pdf)
        try:
            entry = dispatcher.detect(pdf)
        except dispatcher.UnrecognizedBankError:
            failures.append((digest, "no bank recognized this file's content"))
            continue

        password = os.environ.get(entry.password_env, "")
        try:
            statements = entry.parse(
                pdf, user_id=user_id, file_sha256=digest, password=password
            )
        except MissingAccountKeyError as error:
            # Not a per-file problem: every file would fail the same way.
            print(f"error: {error}", file=sys.stderr)
            return 1
        except pikepdf.PasswordError:
            failures.append(
                (digest, f"wrong or missing password (checked {entry.password_env})")
            )
            continue
        except ReconciliationError as error:
            failures.append((digest, f"the statement did not reconcile: {error}"))
            continue
        except ValueError as error:
            failures.append((digest, f"could not parse the statement: {error}"))
            continue

        # Bronze stores rows per *file*, so a file's statements are compared and
        # replaced together, not one by one.
        in_bronze = bronze.transactions_for_file(user_id, digest)
        fresh = sorted(
            (transaction.date, transaction.description, transaction.amount)
            for statement in statements
            for transaction in statement.transactions
        )
        verdict = (
            "dates, descriptions and amounts unchanged"
            if in_bronze == fresh
            else "dates, descriptions or amounts differ"
        )
        first = statements[0]
        replaced.append(
            f"  {first.bank} ...{first.account_last4} "
            f"{first.period_start} to {first.period_end} "
            f"(sha256 {digest[:8]}...): "
            f"{len(in_bronze)} -> {len(fresh)} transaction(s), {verdict}"
        )
        if not args.dry_run:
            # Only the first call may replace: `replace_statement()` starts by
            # deleting every row this file already has in bronze, so calling it
            # again for the second statement would wipe the first one's
            # freshly written rows. The rest are plain appends onto the now
            # empty slate.
            bronze.replace_statement(first, digest)
            for statement in statements[1:]:
                bronze.write_statement(statement, digest)

    print(
        _backfill_report(
            archive, len(targets), replaced, failures, dry_run=args.dry_run
        )
    )
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

    import_cmd = subparsers.add_parser(
        "import-manual",
        help="Load the manual Excel's savings sheet (Banco Ripley, ...) into "
        "bronze; safe to run again with an updated workbook.",
    )
    import_cmd.add_argument("workbook", type=Path)
    import_cmd.add_argument(
        "--user", default=os.environ.get("PFP_USER"), help="defaults to $PFP_USER"
    )
    import_cmd.set_defaults(func=_run_import_manual)

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

    backfill_cmd = subparsers.add_parser(
        "backfill",
        help="Re-parse already-archived statements with today's parser and "
        "replace their rows in bronze.",
    )
    backfill_cmd.add_argument(
        "--user", default=os.environ.get("PFP_USER"), help="defaults to $PFP_USER"
    )
    backfill_cmd.add_argument(
        "--archive-root",
        type=Path,
        default=organizer.DEFAULT_ARCHIVE_ROOT,
        help=f"defaults to {organizer.DEFAULT_ARCHIVE_ROOT}",
    )
    backfill_cmd.add_argument(
        "--bank", help="only re-parse this bank's archived statements"
    )
    backfill_cmd.add_argument(
        "--account", help="only re-parse this account (its last 4 digits)"
    )
    backfill_cmd.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change and write nothing",
    )
    backfill_cmd.set_defaults(func=_run_backfill)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
