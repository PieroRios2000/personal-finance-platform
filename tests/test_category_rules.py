"""Tests for categorization.rules: the cold-start category guesser (T51)."""

from categorization import rules


def test_a_known_merchant_matches_its_category() -> None:
    assert rules.guess("COMPRA NETFLIX.COM") == "Servicios"
    assert rules.guess("GRIFO PRIMAX AV BRASIL") == "Transporte"
    assert rules.guess("RESTAURANT CHIFA WA LOK") == "Restaurantes"
    assert rules.guess("PLAZA VEA SAN MIGUEL") == "Alimentacion"
    assert rules.guess("HOTEL COSTA DEL SOL") == "Viajes"
    assert rules.guess("GIMNASIO SMARTFIT MIRAFLORES") == "Deporte"
    assert rules.guess("COMISION MANTENIMIENTO DE CUENTA") == "Servicios"
    assert rules.guess("SUELDO PLANILLA SEP") == "Ingresos"
    assert rules.guess("TRANSFERENCIA A TERCEROS") == "Transferencias"


def test_something_with_no_match_is_unknown() -> None:
    assert rules.guess("XYZ CORP SAC 00123") == rules.UNKNOWN


def test_a_transfer_to_the_owners_own_card_has_no_dedicated_rule() -> None:
    """This description can never actually reach `guess` in practice --
    `export_category_labels.py` excludes every `is_internal_transfer` movement first
    (ADR 0017), and paying off the owner's own card is exactly that. Guarded here
    anyway: no keyword rule should ever claim to recognize "paying my own card" as a
    spending category, since it isn't one."""
    assert rules.guess("PAGO TARJETA DE CREDITO PROPIA") == rules.UNKNOWN


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
