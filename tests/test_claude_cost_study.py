"""`scripts/claude_cost_study.py`: the queries' scoping, the fake-API wiring and the
printed report, with a fake psycopg connection and a fake Anthropic client. Every
description here is invented."""

from typing import Any, cast

import anthropic
import psycopg
import pytest

from scripts import claude_cost_study as study

_CATEGORIES = ["Alimentacion", "Servicios"]
# (bank, description, category) -- every description invented, matching this
# repo's own convention for a lookalike fixture.
_LABELS = [
    ("BCP", "COMERCIO ALIMENTACION Aa", "Alimentacion"),
    ("BCP", "COMERCIO ALIMENTACION Bb", "Alimentacion"),
    ("BCP", "COMERCIO SERVICIOS Cc", "Servicios"),
]


class _Cursor:
    def __init__(self) -> None:
        self.seen: list[tuple[str, dict[str, Any]]] = []

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, query: str, params: dict[str, Any] | None = None) -> None:
        self.seen.append((query, params or {}))

    def fetchall(self) -> list[tuple[Any, ...]]:
        query = self.seen[-1][0]
        if "category_labels" in query:
            return list(_LABELS)
        if "dim_category" in query:
            return [(c,) for c in _CATEGORIES]
        return []

    def fetchone(self) -> tuple[Any, ...]:
        return (10.0,)


class _Connection:
    def __init__(self) -> None:
        self.cursor_ = _Cursor()

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def cursor(self) -> _Cursor:
        return self.cursor_


class _TextBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _Usage:
    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _Response:
    def __init__(
        self, text: str, input_tokens: int = 200, output_tokens: int = 5
    ) -> None:
        self.content = [_TextBlock(text)]
        self.usage = _Usage(input_tokens, output_tokens)


class _Messages:
    def __init__(self, replies: list[str]) -> None:
        self._replies = iter(replies)

    def create(self, **_kwargs: Any) -> _Response:
        return _Response(next(self._replies))


class _FakeClient:
    def __init__(self, replies: list[str]) -> None:
        self.messages = _Messages(replies)


@pytest.fixture
def connection(monkeypatch: pytest.MonkeyPatch) -> _Connection:
    for name, value in {
        "PFP_PG_DATABASE": "pfp",
        "PFP_PG_USER": "pfp",
        "PFP_PG_PASSWORD": "secret",
    }.items():
        monkeypatch.setenv(name, value)
    fake = _Connection()
    monkeypatch.setattr(psycopg, "connect", lambda conninfo: fake)
    return fake


def test_fetch_scopes_every_query_to_the_user(connection: _Connection) -> None:
    rows, categories, new_per_month = study.fetch("piero")

    assert rows == _LABELS
    assert categories == _CATEGORIES
    assert new_per_month == 10.0
    assert connection.cursor_.seen[0][1] == {"user": "piero"}
    assert connection.cursor_.seen[-1][1] == {"user": "piero"}


def test_run_model_scores_correct_guesses_and_counts_a_miss_as_wrong() -> None:
    # Two right, one wrong (the model guesses the other category).
    client = cast(
        anthropic.Anthropic,
        _FakeClient(["Alimentacion", "Alimentacion", "Alimentacion"]),
    )

    run = study.run_model(client, "claude-haiku-4-5", _LABELS, _CATEGORIES)

    assert run.examples == 3
    assert run.parse_failures == 0
    assert run.precision_by_category["Alimentacion"] == pytest.approx(2 / 3)
    assert run.input_tokens == 600
    assert run.output_tokens == 15
    assert run.cost_usd == pytest.approx(600 / 1_000_000 * 1.00 + 15 / 1_000_000 * 5.00)


def test_run_model_counts_an_unparseable_reply_as_a_parse_failure_and_a_miss() -> None:
    client = cast(
        anthropic.Anthropic,
        _FakeClient(["not a category", "Alimentacion", "Servicios"]),
    )

    run = study.run_model(client, "claude-haiku-4-5", _LABELS, _CATEGORIES)

    assert run.parse_failures == 1
    assert run.macro_f1 < 1.0


def test_main_prints_scores_and_cost_but_never_a_description(
    connection: _Connection,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    replies = ["Alimentacion", "Alimentacion", "Servicios"] * len(study.MODELS)
    monkeypatch.setattr(
        anthropic, "Anthropic", lambda: cast(anthropic.Anthropic, _FakeClient(replies))
    )

    code = study.main(["--user", "piero"])

    out = capsys.readouterr().out
    assert code == 0
    assert "3 trusted labels, 2 categories" in out
    assert "10.0 new distinct descriptions/month" in out
    for model in study.MODELS:
        assert f"{model}: macro-F1" in out
        assert "measured cost $" in out
        assert "projected $" in out
    assert "COMERCIO" not in out


def test_main_requires_a_user(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("PFP_USER", raising=False)

    assert study.main([]) == 2
    assert "--user is required" in capsys.readouterr().err
