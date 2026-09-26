"""What people uploaded that no parser reads yet (T46, ADR 0040), counted by kind.

    uv run python -m scripts.review_uploads [--inbox-root DIR]

The upload portal keeps a file for an unsupported bank or kind, unlocked, in
`<inbox>/<user_id>/_new_bank/` (the pipeline never looks there) tagged with what the
person said it is. This lists them -- bank, kind, currency, how many files and people --
and never a file name, an amount or a page: the next step for each is its own request,
where the owner looks at a sample (masked, ADR 0004) and decides how to extract it.
"""

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from ingestion.organizer import DEFAULT_INBOX_ROOT
from ingestion.unlock import tags

REVIEW_FOLDER = "_new_bank"  # the same name as upload/portal.py's (tested)


def pending(inbox_root: Path) -> Counter[tuple[str, str, str, str]]:
    """(bank, kind, currency, user_id) -> files waiting for review."""
    found: Counter[tuple[str, str, str, str]] = Counter()
    for pdf in sorted(inbox_root.glob(f"*/{REVIEW_FOLDER}/*.pdf")):
        bank, kind, currency = tags(pdf)
        found[
            (
                bank or "unknown",
                kind or "unknown",
                currency or "unknown",
                pdf.parents[1].name,
            )
        ] += 1
    return found


def render(found: Counter[tuple[str, str, str, str]]) -> str:
    if not found:
        return "Nothing waiting for review."
    groups: dict[tuple[str, str, str], list[int]] = {}
    for (bank, kind, currency, _user), count in found.items():
        groups.setdefault((bank, kind, currency), []).append(count)
    lines = ["bank | kind | currency | files | people"]
    for (bank, kind, currency), counts in sorted(groups.items()):
        lines.append(f"{bank} | {kind} | {currency} | {sum(counts)} | {len(counts)}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inbox-root", type=Path, default=DEFAULT_INBOX_ROOT)
    args = parser.parse_args(argv)
    print(render(pending(args.inbox_root)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
