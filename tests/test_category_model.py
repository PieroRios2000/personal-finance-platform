"""Tests for categorization.model: the trained classifier and the baseline it has to
beat (T52, ADR 0044). Every description here is invented -- general, synthetic
merchant-style text, never the owner's real one, per his own instruction to prove the
structure first."""

from pathlib import Path

import joblib
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
    assert metrics.folds >= 2


def test_merchant_group_strips_digits_so_near_duplicates_collapse() -> None:
    """ "UBER TRIP 4821" and "UBER TRIP 5530" are the same merchant once the id that
    varies per transaction is gone -- otherwise a character n-gram model can partly
    "cheat" in cross-validation by having seen a sibling row of the same merchant in
    a different fold (reviewer feedback, 2026-09-27)."""
    assert model._merchant_group("UBER TRIP 4821") == model._merchant_group(
        "UBER TRIP 5530"
    )
    assert model._merchant_group("UBER TRIP 4821") != model._merchant_group(
        "TAXI SATELITAL 4821"
    )


def test_near_duplicate_merchants_count_as_one_group_for_cv_folds() -> None:
    """Two rows of the same merchant, differing only by a digit, must not let the
    fold count grow past what the number of *distinct* merchants supports."""
    descriptions = [
        "UBER TRIP 1111",
        "UBER TRIP 2222",
        "TAXI SATELITAL 3333",
        "TAXI SATELITAL 4444",
        "RESTAURANT WA LOK 111",
        "RESTAURANT WA LOK 222",
        "NETFLIX.COM 111",
        "NETFLIX.COM 222",
        "HOTEL COSTA DEL SOL 111",
        "HOTEL COSTA DEL SOL 222",
    ]
    categories = (
        ["Transporte"] * 4 + ["Restaurantes"] * 2 + ["Servicios"] * 2 + ["Viajes"] * 2
    )

    _pipeline, metrics = model.train(descriptions, categories)

    # 5 distinct merchants, smallest category has 2 examples: folds = min(5, 2, 5) = 2.
    assert metrics.folds == 2


def test_a_single_merchant_group_is_refused_even_with_enough_categories() -> None:
    descriptions = [f"UBER TRIP {i}" for i in range(10)]
    categories = ["Transporte"] * 5 + ["Restaurantes"] * 5

    with pytest.raises(model.NotEnoughDataError, match="merchant group"):
        model.train(descriptions, categories)


def test_metrics_never_carry_a_description() -> None:
    _pipeline, metrics = model.train(_DESCRIPTIONS, _CATEGORIES)

    rendered = repr(metrics)
    for description in _DESCRIPTIONS:
        assert description not in rendered


def test_load_returns_none_when_no_model_has_been_saved_yet(tmp_path: Path) -> None:
    assert model.load(tmp_path / "does-not-exist.joblib") is None


def test_load_returns_a_usable_bundle(tmp_path: Path) -> None:
    pipeline, _metrics = model.train(_DESCRIPTIONS, _CATEGORIES)
    bundle = model.Bundle(pipeline=pipeline, confidence_threshold=0.5)
    path = tmp_path / "model.joblib"
    joblib.dump(bundle, path)

    loaded = model.load(path)

    assert loaded is not None
    assert loaded.confidence_threshold == 0.5
    category, confidence = model.predict(loaded.pipeline, "TAXI HELP.UBER.COM")
    assert category == "Transporte"
    assert 0.0 < confidence <= 1.0


def test_choose_confidence_threshold_returns_a_valid_cutoff_and_fold_count() -> None:
    threshold, folds = model.choose_confidence_threshold(
        _DESCRIPTIONS, _CATEGORIES, rules.guess
    )

    assert 0.0 <= threshold <= 1.0 + 1e-6
    assert folds >= 2


def test_choose_confidence_threshold_requires_enough_data() -> None:
    with pytest.raises(model.NotEnoughDataError):
        model.choose_confidence_threshold(
            ["A", "B"], ["Gastos varios", "Gastos varios"], rules.guess
        )


def test_suggest_uses_the_model_when_confidence_clears_the_threshold() -> None:
    pipeline, _metrics = model.train(_DESCRIPTIONS, _CATEGORIES)
    bundle = model.Bundle(pipeline=pipeline, confidence_threshold=0.0)

    category = model.suggest(bundle, "TAXI HELP.UBER.COM", rules.guess)

    assert category == "Transporte"


def test_suggest_falls_back_to_rules_below_the_threshold() -> None:
    pipeline, _metrics = model.train(_DESCRIPTIONS, _CATEGORIES)
    # No real confidence ever reaches above 1.0: forces the rules-based fallback.
    bundle = model.Bundle(pipeline=pipeline, confidence_threshold=1.1)

    category = model.suggest(bundle, "GRIFO PRIMAX AV BRASIL", rules.guess)

    assert category == rules.guess("GRIFO PRIMAX AV BRASIL")


def test_score_rules_reports_the_same_shape_of_metrics_for_the_baseline() -> None:
    metrics = model.score_rules(_DESCRIPTIONS, _CATEGORIES, rules.guess)

    assert metrics.examples == len(_DESCRIPTIONS)
    assert 0.0 <= metrics.macro_f1 <= 1.0
    # The rules-based guesser already recognizes most of this synthetic vocabulary
    # (it was written from the same keyword list), so it should score well here --
    # the interesting comparison is on the owner's own, messier real wording.
    assert metrics.macro_f1 > 0.5
