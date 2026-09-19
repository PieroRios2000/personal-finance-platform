"""What becomes an alert. Only names and counts: ADR 0004 applies to anything
that leaves the process, and dbt's own messages can quote data."""

from alerting.events import Event, dbt_events, ingest_events

_RUN_RESULTS = {
    "results": [
        {
            "status": "pass",
            "unique_id": "test.personal_finance_platform.not_null_x.abc123",
            "failures": 0,
            "message": None,
        },
        {
            "status": "fail",
            "unique_id": "test.personal_finance_platform.assert_statement_continuity",
            "failures": 4,
            "message": "Got 4 results, e.g. amount 1234.56 for account 9999",
        },
        {
            "status": "warn",
            "unique_id": "test.elementary.elementary_volume_anomalies_silver.f1",
            "failures": 1,
            "message": None,
        },
        {
            "status": "error",
            "unique_id": "model.personal_finance_platform.transactions",
            "failures": None,
            "message": "Runtime Error near 'Juan Perez 00012345'",
        },
        {"status": "skipped", "unique_id": "model.personal_finance_platform.a"},
        {"status": "skipped", "unique_id": "test.personal_finance_platform.b.c"},
    ]
}


def test_a_clean_run_has_no_events() -> None:
    assert dbt_events({"results": [{"status": "pass", "unique_id": "test.p.a"}]}) == []


def test_failures_errors_and_warnings_become_events_with_names_and_counts() -> None:
    events = dbt_events(_RUN_RESULTS)

    assert Event("error", "dbt", "assert_statement_continuity", 4) in events
    assert Event("error", "dbt", "transactions", 1) in events
    assert Event("warn", "dbt", "elementary_volume_anomalies_silver", 1) in events


def test_skipped_nodes_are_one_error_because_they_hide_silver_and_gold() -> None:
    events = dbt_events(_RUN_RESULTS)

    assert Event("error", "dbt", "nodes skipped", 2) in events


def test_no_dbt_message_ever_reaches_an_event() -> None:
    text = repr(dbt_events(_RUN_RESULTS))

    for leaked in ("1234.56", "9999", "Juan", "00012345", "Runtime Error"):
        assert leaked not in text


def test_files_needing_review_are_a_warning_with_a_count() -> None:
    assert ingest_events(needs_review=3) == [
        Event("warn", "ingest", "files need review", 3)
    ]
    assert ingest_events(needs_review=0) == []
