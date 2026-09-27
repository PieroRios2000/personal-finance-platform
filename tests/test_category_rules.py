"""Tests for categorization.rules: the cold-start category guesser (T51)."""

from categorization import rules


def test_a_known_merchant_matches_its_category() -> None:
    assert rules.guess("COMPRA NETFLIX.COM") == "Servicios"
    assert rules.guess("GRIFO PRIMAX AV BRASIL") == "Transporte"
    assert rules.guess("RESTAURANT CHIFA WA LOK") == "Restaurantes"
    assert rules.guess("HOTEL COSTA DEL SOL") == "Viajes"
    assert rules.guess("GIMNASIO SMARTFIT MIRAFLORES") == "Deporte"
    assert rules.guess("COMISION MANTENIMIENTO DE CUENTA") == "Servicios"


def test_something_with_no_match_is_unknown() -> None:
    assert rules.guess("XYZ CORP SAC 00123") == rules.UNKNOWN


def test_groceries_income_transfers_and_card_payments_have_no_dedicated_rule() -> None:
    """The owner's six categories are spending-only (2026-09-27): these fall through
    to UNKNOWN on purpose, and the labeling template then defaults them to
    "Gastos varios" (categorization/labels.py)."""
    assert rules.guess("PLAZA VEA SAN MIGUEL") == rules.UNKNOWN
    assert rules.guess("SUELDO PLANILLA SEP") == rules.UNKNOWN
    assert rules.guess("TRANSFERENCIA A TERCEROS") == rules.UNKNOWN
    assert rules.guess("PAGO TARJETA DE CREDITO") == rules.UNKNOWN


def test_matching_is_case_insensitive_to_how_normalize_description_leaves_it() -> None:
    """The dispatcher/silver always upper-cases before this sees it
    (`ingestion.schema.normalize_description`); the patterns are written upper case,
    so this only has to be exact-case-sensitive, never re-normalize on its own."""
    assert rules.guess("UBER *TRIP HELP.UBER.COM") == "Transporte"


def test_the_first_matching_rule_wins_for_an_ambiguous_description() -> None:
    """'NETFLIX' never also contains a transport keyword in practice, but the order
    itself is what a reviewer should be able to trust: earlier, more specific rules
    are tried first."""
    assert rules.guess("PAGO NETFLIX Y SPOTIFY") == "Servicios"


def test_every_rule_produces_one_of_the_fixed_categories() -> None:
    from categorization.labels import CATEGORIES

    produced = {category for _pattern, category in rules._RULES}
    assert produced <= set(CATEGORIES)
