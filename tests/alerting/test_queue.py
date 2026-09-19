from datetime import datetime
from pathlib import Path

from alerting import queue
from alerting.events import Event

_MONDAY = datetime(2026, 9, 21, 8, 0)
_FRIDAY = datetime(2026, 9, 25, 8, 0)


def test_an_empty_or_missing_queue_reads_as_nothing(tmp_path: Path) -> None:
    assert queue.read(tmp_path / "nope.jsonl") == []


def test_appended_warnings_are_read_back(tmp_path: Path) -> None:
    path = tmp_path / "q.jsonl"

    queue.append(path, [Event("warn", "dbt", "anomaly", 1)], _MONDAY)

    (record,) = queue.read(path)
    assert (record.source, record.name, record.count, record.at) == (
        "dbt",
        "anomaly",
        1,
        _MONDAY,
    )


def test_the_queue_directory_and_file_are_private(tmp_path: Path) -> None:
    path = tmp_path / "state" / "q.jsonl"

    queue.append(path, [Event("warn", "dbt", "anomaly", 1)], _MONDAY)

    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700  # created by us


def test_the_queue_only_ever_holds_names_counts_and_time(tmp_path: Path) -> None:
    path = tmp_path / "q.jsonl"

    queue.append(path, [Event("warn", "dbt", "anomaly", 3)], _MONDAY)

    assert set(__import__("json").loads(path.read_text()).keys()) == {
        "source",
        "name",
        "count",
        "at",
    }


def test_the_digest_sums_each_kind_over_the_week(tmp_path: Path) -> None:
    path = tmp_path / "q.jsonl"
    queue.append(path, [Event("warn", "dbt", "anomaly", 2)], _MONDAY)
    queue.append(
        path,
        [
            Event("warn", "dbt", "anomaly", 3),
            Event("warn", "ingest", "files need review", 1),
        ],
        _FRIDAY,
    )

    lines = {(d.source, d.name): d for d in queue.summarize(queue.read(path))}

    anomaly = lines[("dbt", "anomaly")]
    assert (anomaly.total, anomaly.runs, anomaly.first, anomaly.last) == (
        5,
        2,
        _MONDAY,
        _FRIDAY,
    )
    assert lines[("ingest", "files need review")].runs == 1


def test_clearing_empties_the_queue(tmp_path: Path) -> None:
    path = tmp_path / "q.jsonl"
    queue.append(path, [Event("warn", "dbt", "anomaly", 1)], _MONDAY)

    queue.clear(path)

    assert queue.read(path) == []


def test_a_torn_or_corrupt_line_is_skipped_and_counted(tmp_path: Path) -> None:
    path = tmp_path / "q.jsonl"
    queue.append(path, [Event("warn", "dbt", "anomaly", 1)], _MONDAY)
    with path.open("a") as handle:
        handle.write('{"source": "dbt", "na\n\n{"source": "x"}\n')

    records, skipped = queue.read_counting_skipped(path)

    assert len(records) == 1
    assert skipped == 2


def test_claiming_moves_the_queue_aside_so_new_warnings_are_not_lost(
    tmp_path: Path,
) -> None:
    path = tmp_path / "q.jsonl"
    queue.append(path, [Event("warn", "dbt", "anomaly", 1)], _MONDAY)

    claimed = queue.claim(path)
    queue.append(path, [Event("warn", "dbt", "later", 1)], _FRIDAY)

    assert claimed is not None
    assert [r.name for r in queue.read(claimed)] == ["anomaly"]
    assert [r.name for r in queue.read(path)] == ["later"]


def test_claiming_an_empty_queue_gives_nothing(tmp_path: Path) -> None:
    assert queue.claim(tmp_path / "q.jsonl") is None


def test_a_failed_digest_left_behind_is_claimed_again_together_with_new_warnings(
    tmp_path: Path,
) -> None:
    path = tmp_path / "q.jsonl"
    queue.append(path, [Event("warn", "dbt", "old", 1)], _MONDAY)
    first = queue.claim(path)  # the send failed: the claim is left as it is
    queue.append(path, [Event("warn", "dbt", "new", 1)], _FRIDAY)

    second = queue.claim(path)

    assert second is not None
    assert second == first
    assert sorted(r.name for r in queue.read(second)) == ["new", "old"]


def test_a_directory_the_user_pointed_at_keeps_its_permissions(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o755)

    queue.append(tmp_path / "q.jsonl", [Event("warn", "dbt", "a", 1)], _MONDAY)

    assert tmp_path.stat().st_mode & 0o777 == 0o755
