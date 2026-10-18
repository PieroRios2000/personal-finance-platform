"""Prompt-building and response-parsing for the Claude cost study (T_cost, ADR 0051).
Pure functions only -- no real API call here. The one real-API script
(scripts/claude_cost_study.py) is integration, not unit-tested."""

from categorization.llm_classifier import build_messages, parse_category

CATEGORIES = ("Alimentacion", "Transporte", "Gastos varios")


def test_build_messages_lists_every_category_and_the_description() -> None:
    system, user = build_messages(CATEGORIES, "SOME STORE")

    assert "Alimentacion" in system
    assert "Transporte" in system
    assert "Gastos varios" in system
    assert "SOME STORE" in user


def test_build_messages_never_duplicates_the_description_into_system() -> None:
    system, _user = build_messages(CATEGORIES, "SOME STORE")

    assert "SOME STORE" not in system


def test_parse_category_matches_an_exact_category() -> None:
    assert parse_category("Alimentacion", CATEGORIES) == "Alimentacion"


def test_parse_category_is_case_and_whitespace_tolerant() -> None:
    assert parse_category("  transporte \n", CATEGORIES) == "Transporte"


def test_parse_category_rejects_a_category_not_on_the_list() -> None:
    assert parse_category("Entretenimiento", CATEGORIES) is None


def test_parse_category_rejects_a_sentence_instead_of_one_category() -> None:
    assert parse_category("I think this is Alimentacion.", CATEGORIES) is None


def test_parse_category_rejects_an_empty_response() -> None:
    assert parse_category("", CATEGORIES) is None
