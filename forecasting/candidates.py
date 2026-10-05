"""The five simple forecasters and the baseline (T58, ADR 0048, spec 4.2).

Each takes a history of monthly totals (oldest first) and returns `horizon` point
forecasts. None is fitted by an optimizer: with about two years of monthly points a
fixed, explainable rule is what can be checked. `median_6` is the baseline every other
candidate has to beat.
"""

import numpy as np

BASELINE = "median_6"
CANDIDATES = ("naive_last", "mean_3", BASELINE, "ses", "seasonal_naive_12")
SES_ALPHA = 0.3
SEASON = 12


def forecast(model: str, history: np.ndarray, horizon: int) -> np.ndarray:
    """`horizon` months ahead of `history`; the flat models repeat one value."""
    if model == "seasonal_naive_12":
        if len(history) < SEASON:
            raise ValueError(f"seasonal_naive_12 needs {SEASON} months of history")
        return history[len(history) - SEASON : len(history) - SEASON + horizon].copy()
    return np.full(horizon, _level(model, history))


def _level(model: str, history: np.ndarray) -> float:
    if model == "naive_last":
        return float(history[-1])
    if model == "mean_3":
        return float(history[-3:].mean())
    if model == BASELINE:
        return float(np.median(history[-6:]))
    if model == "ses":
        level = float(history[0])
        for value in history[1:]:
            level = SES_ALPHA * float(value) + (1 - SES_ALPHA) * level
        return level
    raise ValueError(f"unknown model: {model}")
