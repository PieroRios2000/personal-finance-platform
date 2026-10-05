"""`forecasting.backtest`: rolling-origin backtest, the selection rule against the
median baseline, and empirical intervals (T58, ADR 0048, spec 4.2). Series are
synthetic and seeded."""

from datetime import date

import numpy as np
import pytest

from forecasting.backtest import (
    MIN_TRAIN,
    SeriesFit,
    fit_all,
    rolling_forecasts,
    summarize,
)
from forecasting.series import Series


def _series(values: np.ndarray, *, category: str = "Alimentacion") -> Series:
    """`values` end in September 2026."""
    n = len(values)
    end = 2026 * 12 + 8
    months = tuple(date((end - i) // 12, (end - i) % 12 + 1, 1) for i in range(n))
    return Series(category, "PEN", tuple(reversed(months)), values.astype(float))


def _noisy_flat(n: int = 24, seed: int = 0) -> np.ndarray:
    return 1000 + np.random.default_rng(seed).normal(0, 100, n)


def _one(values: np.ndarray, **kwargs: str) -> SeriesFit:
    return fit_all([_series(values, **kwargs)])[0]


def test_a_flat_noisy_series_keeps_the_baseline() -> None:
    fit = _one(_noisy_flat())

    assert fit.model == "median_6"
    assert fit.baseline_used is True
    assert fit.mae_rel == 1.0
    assert not fit.low_history


def test_flat_noise_mostly_keeps_the_baseline() -> None:
    kept = sum(_one(_noisy_flat(36, seed=s)).baseline_used for s in range(20))

    assert kept >= 15


def test_a_planted_yearly_pattern_selects_seasonal_naive() -> None:
    months = np.arange(36)
    noise = np.random.default_rng(2).normal(0, 10, 36)
    values = 1000 + 400 * np.sin(2 * np.pi * months / 12) + noise

    fit = _one(values)

    assert fit.model == "seasonal_naive_12"
    assert fit.baseline_used is False
    assert fit.mae_rel < 0.5


def test_a_trend_is_not_beaten_by_the_baseline_alone() -> None:
    values = 500 + 40 * np.arange(30.0) + np.random.default_rng(3).normal(0, 5, 30)

    fit = _one(values)

    assert fit.model in {"naive_last", "ses", "mean_3"}
    assert fit.mae_rel < 0.95


def test_fewer_than_nine_months_is_low_history_on_the_baseline() -> None:
    fit = _one(np.array([100.0, 110, 90, 105, 95, 100, 102, 98]))

    assert fit.low_history is True
    assert fit.model == "median_6"
    assert fit.n_origins == 0
    assert fit.past == ()


def test_a_series_of_mostly_zeros_is_low_history() -> None:
    values = np.zeros(24)
    values[5] = 80
    values[17] = 60

    fit = _one(values)

    assert fit.low_history is True
    assert fit.model == "median_6"
    assert all(point.p50 >= 0 and (point.p10 or 0) >= 0 for point in fit.future)


def test_the_next_three_months_follow_the_last_closed_month() -> None:
    fit = _one(_noisy_flat())

    assert [i.target_month for i in fit.future] == [
        date(2026, 10, 1),
        date(2026, 11, 1),
        date(2026, 12, 1),
    ]
    assert [i.horizon for i in fit.future] == [1, 2, 3]


def test_intervals_are_ordered_and_never_below_zero() -> None:
    fit = _one(_noisy_flat())

    for i in fit.future:
        assert i.p10 is not None and i.p90 is not None
        assert 0 <= i.p10 <= i.p50 <= i.p90


def test_the_interval_covers_about_eighty_percent_of_its_own_errors() -> None:
    fit = _one(_noisy_flat(60, seed=4))

    assert fit.coverage is not None
    assert 0.7 <= fit.coverage <= 0.95


def test_there_is_one_backtest_point_per_origin_with_its_actual() -> None:
    values = _noisy_flat(24)

    fit = _one(values)

    assert fit.n_origins == 24 - MIN_TRAIN
    assert len(fit.past) == fit.n_origins
    assert fit.past[-1].target_month == date(2026, 9, 1)
    assert fit.past[-1].actual == pytest.approx(values[-1])


def test_a_short_series_borrows_the_errors_of_the_others_in_its_currency() -> None:
    short = _series(_noisy_flat(11, seed=5), category="Salud")
    long = _series(_noisy_flat(36, seed=6))

    with_peers = {f.category: f for f in fit_all([short, long])}["Salud"]
    alone = fit_all([short])[0]

    assert with_peers.future[0].p10 is not None
    assert alone.future[0].p10 is None


def test_forecasts_at_an_origin_ignore_later_months() -> None:
    values = _noisy_flat(24)
    changed = values.copy()
    changed[-1] += 5000
    changed[-2] += 5000

    before = rolling_forecasts(values)
    after = rolling_forecasts(changed)

    for (origin, model, horizon), forecast in before.items():
        if origin <= len(values) - 2:
            assert after[(origin, model, horizon)] == forecast


def test_the_same_input_gives_the_same_fit() -> None:
    values = _noisy_flat()
    assert fit_all([_series(values)]) == fit_all([_series(values)])


def test_the_summary_counts_baselines_and_weights_by_spend() -> None:
    beaten = _one(
        500 + 40 * np.arange(30.0) + np.random.default_rng(3).normal(0, 5, 30)
    )
    flat = _one(_noisy_flat())

    summary = summarize([beaten, flat], weights=[1.0, 3.0])

    assert summary["series"] == 2
    assert summary["baseline_used"] == 1
    expected = (beaten.mae_rel * 1 + flat.mae_rel * 3) / 4
    assert summary["mae_rel_weighted"] == pytest.approx(expected)
    assert summary["mae_rel_mean"] == pytest.approx((beaten.mae_rel + flat.mae_rel) / 2)
