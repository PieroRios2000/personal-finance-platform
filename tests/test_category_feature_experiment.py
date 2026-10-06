"""Tests for categorization.feature_experiment: the T63 comparison harness
(ADR 0044 protocol, merchant-grouped repeated cross-validation). Synthetic data only."""

import random

import pytest

from categorization import feature_experiment as fx
from categorization.recurrence import Recurrence


def test_a_merchant_never_straddles_two_folds_and_seeds_are_reproducible() -> None:
    groups = [f"M{i % 12}" for i in range(60)]

    first = fx.merchant_folds(groups, folds=4, seed=1)

    for group in set(groups):
        assert len({f for g, f in zip(groups, first, strict=True) if g == group}) == 1
    assert fx.merchant_folds(groups, folds=4, seed=1) == first
    assert fx.merchant_folds(groups, folds=4, seed=2) != first


def test_the_frame_marks_missing_values_and_one_hot_encodes_the_kind() -> None:
    frame = fx.feature_frame(
        ["BCP A", "BCP B"],
        [Recurrence(6, 0.5, 0.2), Recurrence(0, None, None)],
        ["fixed", None],
    )

    first, second = frame.iloc[0], frame.iloc[1]
    assert (first["rate"], first["rate_missing"], first["kind_fixed"]) == (0.5, 0, 1)
    assert first["months_seen"] == pytest.approx(0.5)
    assert (second["rate"], second["rate_missing"]) == (0, 1)
    assert second["spread_missing"] == 1
    assert second[["kind_fixed", "kind_variable", "kind_ignore"]].sum() == 0


def _separable_by_number() -> tuple[list[str], list[Recurrence], list[str], list[str]]:
    rng = random.Random(0)
    texts: list[str] = []
    recs: list[Recurrence] = []
    labels: list[str] = []
    groups: list[str] = []
    for i in range(80):
        label = "A" if i % 2 else "B"
        texts.append("".join(rng.choices("abcdefgh", k=8)))
        recs.append(
            Recurrence(12 if label == "A" else 1, 1.0 if label == "A" else 0.1, 0.0)
        )
        labels.append(label)
        groups.append(f"G{i}")
    return texts, recs, labels, groups


def test_a_numeric_signal_that_text_lacks_lifts_the_score() -> None:
    texts, recs, labels, groups = _separable_by_number()
    frame = fx.feature_frame(texts, recs, [None] * len(texts))

    text_only = fx.evaluate(frame, labels, groups, fx.VARIANTS["text"], seeds=(0, 1))
    with_numbers = fx.evaluate(
        frame, labels, groups, fx.VARIANTS["recurrence"], seeds=(0, 1)
    )

    assert with_numbers.mean_f1 > text_only.mean_f1 + 0.2
    assert len(with_numbers.fold_f1) == 10


def _result(
    mean: float, fold_sd_values: list[float], precision: dict[str, float]
) -> fx.Result:
    return fx.Result(
        pooled_f1=[mean], fold_f1=fold_sd_values, precision=precision, folds=5
    )


def test_a_variant_is_adopted_only_beyond_one_fold_sd_and_without_weak_drops() -> None:
    base = _result(0.50, [0.40, 0.60, 0.45, 0.55], {"Servicios": 0.2, "Salud": 0.5})
    clear = _result(0.80, [0.8], {"Servicios": 0.3, "Salud": 0.5})
    noise = _result(0.52, [0.5], {"Servicios": 0.3, "Salud": 0.5})
    worse_weak = _result(0.80, [0.8], {"Servicios": 0.1, "Salud": 0.5})

    assert fx.verdict(base, clear, weak=["Servicios"]).adopt is True
    assert fx.verdict(base, noise, weak=["Servicios"]).adopt is False
    dropped = fx.verdict(base, worse_weak, weak=["Servicios"])
    assert dropped.adopt is False and dropped.dropped == ["Servicios"]
