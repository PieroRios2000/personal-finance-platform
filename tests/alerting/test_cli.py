import json
from datetime import datetime
from pathlib import Path

import pytest

from alerting import cli, queue

_NOW = datetime(2026, 9, 26, 9, 0)


class _Recorder:
    def __init__(self, error: str | None = None) -> None:
        self.sent: list[tuple[str, str]] = []
        self.error = error

    def send(self, subject: str, body: str) -> str | None:
        self.sent.append((subject, body))
        return self.error


def _run_results(tmp_path: Path, *statuses: str) -> Path:
    path = tmp_path / "run_results.json"
    path.write_text(
        json.dumps(
            {
                "results": [
                    {"status": s, "unique_id": f"test.p.test_{i}", "failures": 2}
                    for i, s in enumerate(statuses)
                ]
            }
        )
    )
    return path


def _dbt(
    tmp_path: Path,
    *statuses: str,
    channels: list[_Recorder],
    extra: list[str] | None = None,
) -> int:
    return cli.main(
        [
            "dbt",
            "--run-results",
            str(_run_results(tmp_path, *statuses)),
            *(extra or []),
        ],
        channels=channels,
        queue_path=tmp_path / "q.jsonl",
        now=_NOW,
    )


def test_a_clean_run_sends_and_queues_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    channel = _Recorder()

    assert _dbt(tmp_path, "pass", channels=[channel]) == 0

    assert channel.sent == []
    assert queue.read(tmp_path / "q.jsonl") == []
    assert "No alerts" in capsys.readouterr().out


def test_an_error_is_sent_right_away_to_every_channel(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first, second = _Recorder(), _Recorder()

    assert _dbt(tmp_path, "fail", channels=[first, second]) == 0

    assert first.sent == second.sent
    assert first.sent[0][0] == "[pfp] 1 error"
    assert "test_0 (2)" in capsys.readouterr().out


def test_a_warning_is_queued_for_the_weekly_digest_not_sent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    channel = _Recorder()

    assert _dbt(tmp_path, "warn", channels=[channel]) == 0

    assert channel.sent == []
    (record,) = queue.read(tmp_path / "q.jsonl")
    assert (record.name, record.count, record.at) == ("test_0", 2, _NOW)
    assert "queued 1 warning" in capsys.readouterr().out


def test_an_error_and_a_warning_together_send_only_the_error(tmp_path: Path) -> None:
    channel = _Recorder()

    _dbt(tmp_path, "fail", "warn", channels=[channel])

    assert channel.sent[0][0] == "[pfp] 1 error"
    assert "WARN" not in channel.sent[0][1]
    assert len(queue.read(tmp_path / "q.jsonl")) == 1


def test_files_needing_review_are_queued_as_a_warning(tmp_path: Path) -> None:
    channel = _Recorder()

    _dbt(tmp_path, "pass", channels=[channel], extra=["--needs-review", "3"])

    assert channel.sent == []
    (record,) = queue.read(tmp_path / "q.jsonl")
    assert (record.name, record.count) == ("files need review", 3)


def test_with_no_channel_an_error_is_still_printed_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _dbt(tmp_path, "fail", channels=[]) == 0

    out = capsys.readouterr().out
    assert "no alert channel configured" in out.lower()
    assert "test_0 (2)" in out


def test_a_channel_error_is_reported_and_fails_the_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _dbt(
        tmp_path, "fail", channels=[_Recorder(error="Teams: connection refused")]
    )

    assert code == 1
    assert "Teams: connection refused" in capsys.readouterr().err


def test_a_missing_run_results_file_is_a_clear_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(
        ["dbt", "--run-results", str(tmp_path / "nope.json")],
        channels=[],
        queue_path=tmp_path / "q.jsonl",
        now=_NOW,
    )

    assert code == 2
    assert "run_results.json" in capsys.readouterr().err


def _claimed_records(path: Path) -> list[queue.Record]:
    claimed = queue.claim(path)
    assert claimed is not None
    return queue.read(claimed)


def _queued(tmp_path: Path) -> Path:
    path = tmp_path / "q.jsonl"
    _dbt(tmp_path, "warn", "warn", channels=[])
    return path


def test_the_digest_sends_the_week_and_empties_the_queue(tmp_path: Path) -> None:
    path = _queued(tmp_path)
    channel = _Recorder()

    code = cli.main(["digest"], channels=[channel], queue_path=path, now=_NOW)

    assert code == 0
    assert channel.sent[0][0] == "[pfp] weekly digest: 2 kinds of warning"
    assert queue.read(path) == []


def test_an_empty_week_sends_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    channel = _Recorder()

    code = cli.main(
        ["digest"],
        channels=[channel],
        queue_path=tmp_path / "q.jsonl",
        now=_NOW,
    )

    assert code == 0
    assert channel.sent == []
    assert "No warnings" in capsys.readouterr().out


def test_a_failed_digest_keeps_the_queue_for_the_next_try(tmp_path: Path) -> None:
    path = _queued(tmp_path)

    code = cli.main(
        ["digest"],
        channels=[_Recorder(error="SMTP: refused")],
        queue_path=path,
        now=_NOW,
    )

    assert code == 1
    assert len(_claimed_records(path)) == 2


def test_a_failed_build_with_no_results_file_is_an_error_not_silence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    channel = _Recorder()

    code = cli.main(
        ["dbt", "--run-results", str(tmp_path / "gone.json"), "--dbt-returncode", "2"],
        channels=[channel],
        queue_path=tmp_path / "q.jsonl",
        now=_NOW,
    )

    assert code == 0
    assert "build did not complete" in channel.sent[0][1]


def test_a_failed_build_whose_errors_are_in_the_results_adds_nothing_extra(
    tmp_path: Path,
) -> None:
    channel = _Recorder()

    _dbt(tmp_path, "fail", channels=[channel], extra=["--dbt-returncode", "1"])

    assert "did not complete" not in channel.sent[0][1]


def test_invalid_results_json_is_a_clear_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "run_results.json"
    bad.write_text("{not json")

    code = cli.main(
        ["dbt", "--run-results", str(bad)],
        channels=[],
        queue_path=tmp_path / "q.jsonl",
        now=_NOW,
    )

    assert code == 2
    assert "not valid JSON" in capsys.readouterr().err


def test_an_empty_queue_path_variable_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ALERT_QUEUE_PATH", "")
    monkeypatch.setattr(queue, "DEFAULT_QUEUE_PATH", tmp_path / "default.jsonl")

    code = cli.main(["digest"], channels=[])

    assert code == 0
    assert "No warnings" in capsys.readouterr().out


def test_a_bad_alert_configuration_is_a_clear_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name, value in {
        "ALERT_SMTP_HOST": "h",
        "ALERT_EMAIL_FROM": "a@b",
        "ALERT_EMAIL_TO": "c@d",
        "ALERT_SMTP_PORT": "abc",
    }.items():
        monkeypatch.setenv(name, value)

    code = cli.main(["digest"])

    assert code == 2
    assert "ALERT_SMTP_PORT" in capsys.readouterr().err


def test_a_digest_one_channel_accepted_is_not_sent_again_to_it(tmp_path: Path) -> None:
    """One channel failing must not make the next digest repeat the message on
    the channel that already delivered it: the queue is emptied, and the failure
    is still reported."""
    path = _queued(tmp_path)

    code = cli.main(
        ["digest"],
        channels=[_Recorder(), _Recorder(error="Teams: refused")],
        queue_path=path,
        now=_NOW,
    )

    assert code == 1
    assert queue.read(path) == []
    assert not list(tmp_path.glob("*.sending"))


def test_a_digest_no_channel_accepted_stays_claimed_for_the_next_try(
    tmp_path: Path,
) -> None:
    path = _queued(tmp_path)

    cli.main(
        ["digest"],
        channels=[_Recorder(error="SMTP: refused")],
        queue_path=path,
        now=_NOW,
    )

    assert len(_claimed_records(path)) == 2
