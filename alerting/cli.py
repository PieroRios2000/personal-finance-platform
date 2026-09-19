"""`python -m alerting`: send errors now, keep warnings for the weekly digest.

    python -m alerting dbt --run-results dbt/target/run_results.json [--needs-review N]
    python -m alerting digest

`dbt` sends the errors of a run immediately and queues its warnings; `digest`
sends everything queued since the last digest as one message and empties the
queue (only if every channel accepted it). Meant to run after `dbt build` and,
for `digest`, on a weekly schedule (SETUP.md).
"""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from alerting import queue
from alerting.channels import Channel, channels_from_env
from alerting.events import Event, dbt_events, ingest_events
from alerting.render import render, render_digest


def _deliver(channels: Sequence[Channel], subject: str, body: str) -> tuple[int, int]:
    """Print the message and send it to every channel. Returns how many channels
    accepted it and how many did not (both 0 with no channel configured)."""
    print(subject)
    print(body)
    if not channels:
        print("(no alert channel configured: set the ALERT_* variables in .env)")
        return 0, 0
    delivered = failed = 0
    for channel in channels:
        error = channel.send(subject, body)
        if error:
            print(f"alert not delivered: {error}", file=sys.stderr)
            failed += 1
        else:
            delivered += 1
    return delivered, failed


def _dbt(
    args: argparse.Namespace,
    channels: Sequence[Channel],
    queue_path: Path,
    now: datetime,
) -> int:
    path = Path(args.run_results)
    build_failed = args.dbt_returncode not in (None, 0)
    results: list[Event] = []
    if path.exists():
        try:
            results = dbt_events(json.loads(path.read_text()))
        except ValueError:
            print(f"alerting: {path} is not valid JSON", file=sys.stderr)
            return 2
    elif not build_failed:
        print(
            f"alerting: {path} not found "
            "(expected dbt's run_results.json; run dbt first)",
            file=sys.stderr,
        )
        return 2
    events: list[Event] = [*results, *ingest_events(needs_review=args.needs_review)]
    if build_failed and not any(e.level == "error" for e in results):
        # dbt failed before it could write a result (a parse or connection
        # error): that is an error too.
        events.append(Event("error", "dbt", "build did not complete", 1))
    errors = [e for e in events if e.level == "error"]
    warnings = [e for e in events if e.level == "warn"]
    if not events:
        print("No alerts.")
        return 0
    code = 0
    if errors:
        _, failed = _deliver(channels, *render(errors))
        code = 1 if failed else 0
    if warnings:
        queue.append(queue_path, warnings, now)
        print(f"queued {len(warnings)} warning(s) for the weekly digest")
    return code


def _digest(channels: Sequence[Channel], queue_path: Path) -> int:
    claimed = queue.claim(queue_path)
    records, skipped = queue.read_counting_skipped(claimed) if claimed else ([], 0)
    if skipped:
        print(f"skipped {skipped} unreadable line(s) in the warnings queue")
    lines = queue.summarize(records)
    if not lines:
        print("No warnings queued this week.")
        if claimed:
            queue.clear(claimed)
        return 0
    delivered, failed = _deliver(channels, *render_digest(lines))
    # Emptied as soon as one channel accepted it (sending it again would repeat
    # the message where it already arrived); kept only if none did.
    if claimed and (delivered or not channels):
        queue.clear(claimed)
    return 1 if failed else 0


def main(
    argv: Sequence[str] | None = None,
    *,
    channels: Sequence[Channel] | None = None,
    queue_path: Path | None = None,
    now: datetime | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="alerting")
    sub = parser.add_subparsers(dest="command", required=True)
    dbt = sub.add_parser("dbt", help="alert on a dbt build's results")
    dbt.add_argument("--run-results", default="dbt/target/run_results.json")
    dbt.add_argument("--needs-review", type=int, default=0)
    dbt.add_argument(
        "--dbt-returncode",
        type=int,
        default=None,
        help="dbt's exit code, so a build that wrote no results is still reported",
    )
    sub.add_parser("digest", help="send the queued warnings as one message")
    args = parser.parse_args(argv)

    try:
        chosen = channels_from_env(os.environ) if channels is None else channels
    except ValueError as error:
        print(f"alerting: {error}", file=sys.stderr)
        return 2
    path = queue_path or Path(
        os.environ.get("ALERT_QUEUE_PATH") or str(queue.DEFAULT_QUEUE_PATH)
    )
    if args.command == "dbt":
        return _dbt(args, chosen, path, now or datetime.now())
    return _digest(chosen, path)


if __name__ == "__main__":
    sys.exit(main())
