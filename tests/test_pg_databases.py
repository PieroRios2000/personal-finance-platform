"""`scripts/pg_databases.py`: create the throwaway databases the PR data diff
builds into (T29, ADR 0029). No Postgres needed here."""

from typing import Any

import psycopg
import pytest

from scripts import pg_databases


class _FakeConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, statement: str) -> None:
        self.statements.append(statement)


@pytest.fixture
def environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "PFP_PG_DATABASE": "pfp",
        "PFP_PG_USER": "pfp",
        "PFP_PG_PASSWORD": "a'b c",
    }.items():
        monkeypatch.setenv(name, value)


def test_each_database_is_dropped_if_it_exists_and_created_fresh(
    environment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeConnection()
    seen: dict[str, Any] = {}

    def connect(conninfo: str, **kwargs: Any) -> _FakeConnection:
        seen["conninfo"] = conninfo
        seen["kwargs"] = kwargs
        return fake

    monkeypatch.setattr(psycopg, "connect", connect)

    assert pg_databases.main(["pfp_diff_base", "pfp_diff_pr"]) == 0

    assert fake.statements == [
        'drop database if exists "pfp_diff_base" with (force)',
        'create database "pfp_diff_base"',
        'drop database if exists "pfp_diff_pr" with (force)',
        'create database "pfp_diff_pr"',
    ]
    assert seen["kwargs"] == {"autocommit": True}
    assert "dbname=pfp " in seen["conninfo"] + " "


def test_the_password_is_quoted_by_the_connection_string_builder(
    environment: None,
) -> None:
    conninfo = pg_databases.conninfo("pfp")

    assert "password='a\\'b c'" in conninfo


@pytest.mark.parametrize(
    "name",
    ["pfp; drop database x", "pfp-diff", "", "a b", "postgres", "template1", "pfp"],
)
def test_a_name_that_is_not_a_plain_identifier_is_refused(
    environment: None, name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("must not connect")

    monkeypatch.setattr(psycopg, "connect", refuse)

    assert pg_databases.main([name]) == 2


def test_the_database_the_owner_works_in_is_never_dropped(
    environment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("must not connect")

    monkeypatch.setattr(psycopg, "connect", refuse)

    assert pg_databases.main(["pfp"]) == 2
