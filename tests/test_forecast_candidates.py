"""`forecasting.candidates`: the five simple forecasters and the baseline (T58,
ADR 0048, spec 4.2). Pure functions over a plain array, checked by hand."""

import numpy as np
import pytest

from forecasting.candidates import BASELINE, CANDIDATES, forecast


def _y(*values: float) -> np.ndarray:
    return np.array(values, dtype=float)


def test_the_baseline_is_the_trailing_six_month_median() -> None:
    assert BASELINE == "median_6"
    assert set(CANDIDATES) == {
        "naive_last",
        "mean_3",
        "median_6",
        "ses",
        "seasonal_naive_12",
    }


def test_naive_last_repeats_the_last_month() -> None:
    assert forecast("naive_last", _y(5, 9, 7), 3).tolist() == [7, 7, 7]


def test_mean_3_averages_the_last_three_months() -> None:
    assert forecast("mean_3", _y(100, 3, 6, 9), 2).tolist() == [6, 6]


def test_median_6_ignores_one_large_month() -> None:
    history = _y(10, 10, 10, 10, 10, 500)
    assert forecast("median_6", history, 1).tolist() == [10]


def test_median_6_uses_what_exists_when_the_history_is_short() -> None:
    assert forecast("median_6", _y(4, 8), 1).tolist() == [6]


def test_ses_is_the_smoothed_level_with_alpha_point_three() -> None:
    # level: 10 -> 0.3*20 + 0.7*10 = 13 -> 0.3*0 + 0.7*13 = 9.1
    assert forecast("ses", _y(10, 20, 0), 2) == pytest.approx([9.1, 9.1])


def test_seasonal_naive_repeats_the_same_month_of_last_year() -> None:
    history = np.arange(1.0, 15.0)  # 14 months: 1..14
    # next month is index 14; one year earlier is index 2 (value 3), then 4, 5
    assert forecast("seasonal_naive_12", history, 3).tolist() == [3, 4, 5]


def test_seasonal_naive_needs_a_full_year() -> None:
    with pytest.raises(ValueError, match="12"):
        forecast("seasonal_naive_12", _y(1, 2, 3), 1)


def test_an_unknown_model_is_an_error() -> None:
    with pytest.raises(ValueError, match="unknown"):
        forecast("prophet", _y(1, 2, 3), 1)


def test_seasonal_naive_repeats_its_last_year_beyond_twelve_months() -> None:
    year = [float(m) for m in range(1, 13)]

    out = forecast("seasonal_naive_12", _y(99, *year), 30)

    assert out.tolist() == (year * 3)[:30]
