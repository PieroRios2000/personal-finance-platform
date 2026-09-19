from datetime import datetime

from alerting.events import Event
from alerting.queue import DigestLine
from alerting.render import render, render_digest


def test_the_subject_says_how_bad_it_is() -> None:
    subject, _ = render(
        [
            Event("error", "dbt", "a_test", 4),
            Event("warn", "ingest", "files need review", 2),
        ]
    )

    assert subject == "[pfp] 1 error, 1 warning"


def test_the_body_lists_every_event_with_its_count() -> None:
    _, body = render(
        [
            Event("error", "dbt", "a_test", 4),
            Event("warn", "ingest", "files need review", 2),
        ]
    )

    assert "ERROR  dbt: a_test (4)" in body
    assert "WARN  ingest: files need review (2)" in body


def test_a_name_that_is_not_a_plain_identifier_is_never_printed() -> None:
    """Names come from dbt node ids, which are identifiers. Anything else is
    not trusted to be free of data."""
    _, body = render([Event("error", "dbt", "amount 1234.56 for Juan", 1)])

    assert "1234.56" not in body
    assert "Juan" not in body
    assert "<unnamed>" in body


def test_the_weekly_digest_groups_each_warning_with_totals_and_dates() -> None:
    lines = [
        DigestLine(
            "dbt",
            "elementary_volume_anomalies",
            5,
            3,
            datetime(2026, 9, 21),
            datetime(2026, 9, 26),
        ),
        DigestLine(
            "ingest",
            "files need review",
            2,
            1,
            datetime(2026, 9, 22),
            datetime(2026, 9, 22),
        ),
    ]

    subject, body = render_digest(lines)

    assert subject == "[pfp] weekly digest: 2 kinds of warning"
    assert (
        "WARN  dbt: elementary_volume_anomalies (5 in 3 runs, 2026-09-21 to 2026-09-26)"
        in body
    )
    assert "WARN  ingest: files need review (2 in 1 run, 2026-09-22)" in body


def test_a_digest_name_that_is_not_a_plain_identifier_is_never_printed() -> None:
    line = DigestLine(
        "dbt", "amount 1234.56", 1, 1, datetime(2026, 9, 21), datetime(2026, 9, 21)
    )

    assert "1234.56" not in render_digest([line])[1]


def test_a_name_with_a_trailing_newline_is_not_a_plain_identifier() -> None:
    _, body = render([Event("error", "dbt", "a_test\nINJECTED", 1)])

    assert "INJECTED" not in body


def test_a_source_that_is_not_a_plain_identifier_is_never_printed() -> None:
    _, body = render([Event("error", "Juan 1234.56", "a_test", 1)])

    assert "1234.56" not in body
