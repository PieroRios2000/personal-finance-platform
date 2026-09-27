"""What people uploaded that no parser reads yet (T46, T48, ADR 0041), by request.

    uv run python -m scripts.review_uploads [--inbox-root DIR]

A request for a bank, kind or currency no parser reads waits in `review` (the upload
portal keeps it, unlocked, in `<inbox>/<user_id>/_submissions/<id>/`, which the pipeline
never looks in). This lists them -- request id, bank, kind, currency, how many files --
and never a file name, an amount, a page or a person: the next step for each is its own
request, where the owner looks at a masked sample (ADR 0004) and decides how to extract
it, then `make decide-submission ID=<id> DECISION=reject|release`.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from ingestion import submissions
from ingestion.organizer import DEFAULT_INBOX_ROOT


def render(inbox_root: Path) -> str:
    waiting = submissions.find(inbox_root, submissions.REVIEW)
    if not waiting:
        return "Nothing waiting for review."
    lines = ["id | bank | kind | currency | files"]
    for _user, _folder, m in waiting:
        lines.append(f"{m.id} | {m.bank} | {m.kind} | {m.currency} | {m.files}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inbox-root", type=Path, default=DEFAULT_INBOX_ROOT)
    args = parser.parse_args(argv)
    print(render(args.inbox_root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
