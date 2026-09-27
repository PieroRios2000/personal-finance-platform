"""Tests for categorization.model: the trained classifier and the baseline it has to
beat (T52, ADR 0044). Every description here is invented -- general, synthetic
merchant-style text, never the owner's real one, per his own instruction to prove the
structure first."""

import pytest

from categorization import model, rules

# General, synthetic training data: several examples per category, phrased with
# enough variety (and some noise) that a bag of character n-grams has something real
# to learn from, not just one repeated string per class.
_DESCRIPTIONS = [
    "GRIFO PRIMAX AV BRASIL",
    "TAXI SATELITAL LIMA",
    "PEAJE PUENTE PIEDRA",
    "UBER *TRIP HELP.UBER.COM",
    "RESTAURANT CHIFA WA LOK",
    "RAPPI PEDIDOS DELIVERY",
    "POLLERIA EL RANCHO",
    "PEDIDOSYA LIMA",
    "NETFLIX.COM 099999999",
    "SPOTIFY AB STOCKHOLM",
    "GIMNASIO SMARTFIT MIRAFLORES",
    "CLUB DEPORTIVO REGATAS",
    "HOTEL COSTA DEL SOL",
    "LATAM AIRLINES PERU",
]
_CATEGORIES = [
    "Transporte",
    "Transporte",
    "Transporte",
    "Transporte",
    "Restaurantes",
    "Restaurantes",
    "Restaurantes",
    "Restaurantes",
    "Servicios",
    "Servicios",
    "Deporte",
    "Deporte",
    "Viajes",
    "Viajes",
]


def test_too_few_examples_is_refused() -> None:
    with pytest.raises(model.NotEnoughDataError):
        model.train(["A", "B"], ["Gastos varios", "Gastos varios"])


def test_a_single_category_is_refused_even_with_enough_rows() -> None:
    with pytest.raises(model.NotEnoughDataError):
        model.train(["A"] * 10, ["Gastos varios"] * 10)


def test_a_category_with_too_few_examples_is_refused() -> None:
    descriptions = _DESCRIPTIONS + ["ONE OFF THING"]
    categories = _CATEGORIES + ["Gastos varios"]  # appears exactly once

    with pytest.raises(model.NotEnoughDataError, match="only 1 example"):
        model.train(descriptions, categories)


def test_mismatched_lengths_are_rejected() -> None:
    with pytest.raises(ValueError, match="same length"):
        model.train(["A", "B"], ["Gastos varios"])


def test_a_trained_model_predicts_a_known_category_for_similar_text() -> None:
    pipeline, metrics = model.train(_DESCRIPTIONS, _CATEGORIES)

    category, confidence = model.predict(pipeline, "TAXI HELP.UBER.COM")

    assert category == "Transporte"
    assert 0.0 < confidence <= 1.0
    assert metrics.examples == len(_DESCRIPTIONS)
    assert metrics.categories == len(set(_CATEGORIES))
    assert 0.0 <= metrics.macro_f1 <= 1.0
    assert set(metrics.precision_by_category) == set(_CATEGORIES)


def test_metrics_never_carry_a_description() -> None:
    _pipeline, metrics = model.train(_DESCRIPTIONS, _CATEGORIES)

    rendered = repr(metrics)
    for description in _DESCRIPTIONS:
        assert description not in rendered


def test_score_rules_reports_the_same_shape_of_metrics_for_the_baseline() -> None:
    metrics = model.score_rules(_DESCRIPTIONS, _CATEGORIES, rules.guess)

    assert metrics.examples == len(_DESCRIPTIONS)
    assert 0.0 <= metrics.macro_f1 <= 1.0
    # The rules-based guesser already recognizes most of this synthetic vocabulary
    # (it was written from the same keyword list), so it should score well here --
    # the interesting comparison is on the owner's own, messier real wording.
    assert metrics.macro_f1 > 0.5
