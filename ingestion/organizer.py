"""Inbox organizer (T12b): files inbox PDFs into the standardized per-user archive.

`organize()` walks a per-user inbox directory for `*.pdf` files under any name (ADR
0009) and moves each one into `<archive_root>/<user>/<bank>/<last4>-<id6>/
<start>_<end>.pdf`, using the dispatcher (T12) to detect the bank and the matching
parser to read the account and period straight from the PDF's content. Nothing is
ever deleted: every file that leaves the inbox ends up somewhere under the archive
root, never in two places at once.

**Duplicate-detection scoping.** There's no persistent "already ingested" registry
yet — that's T14's bronze writer, which will track every file's hash against what's
already been written to the lake. Until then, `organize()` only catches two kinds of
duplicate, neither of which needs a database:

1. Two files in the *same inbox pass* with identical bytes: their shared sha256 is
   tracked in memory for the run, and the second (and any later) copy goes to
   `_duplicates/`.
2. A file whose content exactly matches what's *already sitting in the archive* at
   its own account/period destination (found by hashing the one file already at that
   path, not by a general index): this reuses the archive layout itself as a narrow,
   per-account version check — the flip side of the "regenerated statement" check
   below — not a real duplicate registry.

A duplicate that shows up in a *later, separate* run with no earlier match in that
run's inbox and no file yet archived at the same destination (for example, both
copies arrive in separate inbox passes before either is processed) is **not** caught
here — T14 closes that gap.

**Multi-account PDFs.** ADR 0009 and `tasks/plan.md` call out a bank statement that
covers more than one account, to be filed under `<bank>/_multi-account/`. Detecting
that case is out of reach today: `ingestion.parsers.bcp.parse()` (T11) returns
exactly one `Statement` per call — it reads the *first* "CUENTA NRO." it finds and
has no way to report "there was also a second one". `_multi-account/` isn't wired up
here: adding it now would be a dead branch this parser can never exercise, not a
placeholder worth keeping. It becomes reachable once a parser can either return
several statements for one PDF or at least flag "more than one account" — see the
brain note and this task's PR for the full explanation.
"""

import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pikepdf

from ingestion import dispatcher
from ingestion.dedup import file_sha256
from ingestion.reconciliation import ReconciliationError

DEFAULT_INBOX_ROOT = Path.home() / "finance-data" / "inbox"
DEFAULT_ARCHIVE_ROOT = Path.home() / "finance-data" / "raw"

# Matches the "<start>_<end>" prefix an archived filename always starts with,
# regardless of a trailing "_vN" (a regenerated statement's version suffix).
_PERIOD_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})")


@dataclass(frozen=True)
class ArchivedItem:
    """One PDF successfully filed into the archive."""

    bank: str
    account_last4: str
    period_start: date
    period_end: date
    dest: Path
    version: int  # 1 for the first copy of this account/period; 2+ if regenerated


@dataclass(frozen=True)
class SkippedItem:
    """One PDF moved aside instead of archived: a duplicate, or needing review."""

    sha256: str
    reason: str
    dest: Path


@dataclass(frozen=True)
class OrganizeReport:
    """What one `organize()` run did, and the state of the archive afterwards."""

    inbox: Path
    archived: list[ArchivedItem] = field(default_factory=list)
    duplicates: list[SkippedItem] = field(default_factory=list)
    needs_review: list[SkippedItem] = field(default_factory=list)

    def render(self) -> str:
        """A plain-text report: never a full account number or an amount, and
        never a raw inbox filename either — a file's original name can itself
        carry the real account number (ADR 0009), so duplicates and items sent
        to review are referenced by a short hash prefix instead."""
        lines = [
            f"Inbox: {self.inbox}",
            f"Archived: {len(self.archived)}  "
            f"Duplicates: {len(self.duplicates)}  "
            f"Needs review: {len(self.needs_review)}",
        ]

        if self.archived:
            lines.append("")
            lines.append("Archived:")
            for item in self.archived:
                note = (
                    f" (v{item.version}, regenerated: content differs from the "
                    "version already archived)"
                    if item.version > 1
                    else ""
                )
                lines.append(
                    f"  {item.bank} ...{item.account_last4}: "
                    f"{item.period_start} to {item.period_end} -> {item.dest}{note}"
                )

        for title, group in (
            ("Duplicates (moved to _duplicates/, nothing deleted)", self.duplicates),
            (
                "Needs review (moved to _needs_review/, nothing deleted)",
                self.needs_review,
            ),
        ):
            if group:
                lines.append("")
                lines.append(f"{title}:")
                for n, skipped in enumerate(group, start=1):
                    lines.append(
                        f"  #{n} (sha256 {skipped.sha256[:8]}...): {skipped.reason}"
                    )

        accounts: dict[tuple[str, str], Path] = {
            (item.bank, item.account_last4): item.dest.parent for item in self.archived
        }
        if accounts:
            lines.append("")
            lines.append("Per-account coverage:")
            for (bank, last4), account_dir in sorted(accounts.items()):
                periods = _account_periods(account_dir)
                span = f"{periods[0][0]} to {periods[-1][1]}" if periods else "n/a"
                gaps = _missing_months(periods)
                gap_note = (
                    f"; possible gap(s): {', '.join(gaps)}"
                    if gaps
                    else "; no gaps detected"
                )
                lines.append(
                    f"  {bank} ...{last4}: {len(periods)} period(s) archived, "
                    f"{span}{gap_note}"
                )

        return "\n".join(lines)


def _move_without_overwrite(src: Path, dest_dir: Path) -> Path:
    """Move `src` into `dest_dir`, keeping its name unless that would silently
    overwrite something already there (a numeric suffix is added instead)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    counter = 2
    while dest.exists():
        dest = dest_dir / f"{src.stem}-{counter}{src.suffix}"
        counter += 1
    shutil.move(str(src), str(dest))
    return dest


def _account_periods(account_dir: Path) -> list[tuple[date, date]]:
    """Every (period_start, period_end) already archived in `account_dir`, read
    back from the filenames themselves (there's no separate index)."""
    periods = set()
    for path in account_dir.glob("*.pdf"):
        match = _PERIOD_PREFIX.match(path.stem)
        if match:
            periods.add((date.fromisoformat(match[1]), date.fromisoformat(match[2])))
    return sorted(periods)


def _missing_months(periods: list[tuple[date, date]]) -> list[str]:
    """Calendar months with no archived period between the earliest and the
    latest one, as "YYYY-MM" strings. Assumes one statement roughly covers one
    calendar month (true of every statement layout seen so far), using each
    period's start date as the month it represents."""
    if len(periods) < 2:
        return []
    months = sorted({(start.year, start.month) for start, _ in periods})
    year, month = months[0]
    end_year, end_month = months[-1]
    present = set(months)
    missing = []
    while (year, month) <= (end_year, end_month):
        if (year, month) not in present:
            missing.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            month, year = 1, year + 1
    return missing


def organize(
    user_id: str,
    *,
    inbox_root: Path = DEFAULT_INBOX_ROOT,
    archive_root: Path = DEFAULT_ARCHIVE_ROOT,
) -> OrganizeReport:
    """Process every `*.pdf` in `<inbox_root>/<user_id>/` and file it under
    `<archive_root>/<user_id>/...` (ADR 0009). Safe to re-run: never deletes
    anything, and a missing or empty inbox just produces an empty report."""
    inbox = inbox_root / user_id
    archive = archive_root / user_id
    archived: list[ArchivedItem] = []
    duplicates: list[SkippedItem] = []
    needs_review: list[SkippedItem] = []
    seen_hashes: set[str] = set()

    for pdf in sorted(inbox.glob("*.pdf")):
        digest = file_sha256(pdf)

        if digest in seen_hashes:
            dest = _move_without_overwrite(pdf, archive / "_duplicates")
            duplicates.append(
                SkippedItem(
                    digest,
                    "identical content to another file already seen in this inbox pass",
                    dest,
                )
            )
            continue
        seen_hashes.add(digest)

        try:
            entry = dispatcher.detect(pdf)
        except dispatcher.UnrecognizedBankError:
            dest = _move_without_overwrite(pdf, archive / "_needs_review")
            needs_review.append(
                SkippedItem(digest, "no bank recognized this file's content", dest)
            )
            continue

        password = os.environ.get(entry.password_env, "")
        try:
            statement = entry.parse(
                pdf, user_id=user_id, file_sha256=digest, password=password
            )
        except pikepdf.PasswordError:
            dest = _move_without_overwrite(pdf, archive / "_needs_review")
            needs_review.append(
                SkippedItem(
                    digest,
                    f"wrong or missing password (checked {entry.password_env})",
                    dest,
                )
            )
            continue
        except ReconciliationError as error:
            dest = _move_without_overwrite(pdf, archive / "_needs_review")
            needs_review.append(
                SkippedItem(digest, f"the statement did not reconcile: {error}", dest)
            )
            continue
        except ValueError as error:
            dest = _move_without_overwrite(pdf, archive / "_needs_review")
            needs_review.append(
                SkippedItem(digest, f"could not parse the statement: {error}", dest)
            )
            continue

        id6 = statement.account_id[:6]
        account_dir = archive / statement.bank / f"{statement.account_last4}-{id6}"
        base_name = f"{statement.period_start}_{statement.period_end}"
        dest_path = account_dir / f"{base_name}.pdf"
        version = 1

        if dest_path.exists():
            if file_sha256(dest_path) == digest:
                dest = _move_without_overwrite(pdf, archive / "_duplicates")
                duplicates.append(
                    SkippedItem(
                        digest,
                        "identical content to the statement already archived for "
                        f"{statement.bank} ...{statement.account_last4}, "
                        f"{statement.period_start} to {statement.period_end}",
                        dest,
                    )
                )
                continue
            version = 2
            while (account_dir / f"{base_name}_v{version}.pdf").exists():
                version += 1
            dest_path = account_dir / f"{base_name}_v{version}.pdf"

        account_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(pdf), str(dest_path))
        archived.append(
            ArchivedItem(
                bank=statement.bank,
                account_last4=statement.account_last4,
                period_start=statement.period_start,
                period_end=statement.period_end,
                dest=dest_path,
                version=version,
            )
        )

    return OrganizeReport(
        inbox=inbox, archived=archived, duplicates=duplicates, needs_review=needs_review
    )
