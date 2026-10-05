"""Rolling-origin backtest, model selection and empirical intervals (T58, ADR 0048,
spec 4.2).

At every origin from `MIN_TRAIN` months of training to the last closed month, each
candidate forecasts the next `HORIZONS` months from the months before the origin only
(no look-ahead). A candidate replaces the median baseline only if it beats it by at
least 5 % in mean absolute error at horizon 1 *and* is closer on at least 60 % of the
origins; otherwise `baseline_used`. Intervals are the point forecast plus the 10th and
90th percentile of the selected model's own signed errors, pooled from the other series
of the currency (scaled by level) when it has fewer than `MIN_ERRORS`. The coverage is
measured on the same errors, so it is optimistic.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from forecasting.candidates import BASELINE, CANDIDATES, SEASON, forecast
from forecasting.series import Series, add_months

MIN_TRAIN = 9
HORIZONS = 3
MIN_IMPROVEMENT = 0.05
MIN_WIN_RATE = 0.60
MIN_ERRORS = 12
MIN_NONZERO_MONTHS = 3
LOW_QUANTILE = 0.10
HIGH_QUANTILE = 0.90
LEVEL_MONTHS = 12


@dataclass(frozen=True)
class Interval:
    horizon: int
    target_month: date
    p10: float | None
    p50: float
    p90: float | None


@dataclass(frozen=True)
class BacktestPoint:
    target_month: date
    p10: float | None
    p50: float
    p90: float | None
    actual: float


@dataclass(frozen=True)
class SeriesFit:
    category: str
    currency: str
    model: str
    baseline_used: bool
    low_history: bool
    n_months: int
    n_origins: int
    mae_rel: float
    coverage: float | None
    future: tuple[Interval, ...]
    past: tuple[BacktestPoint, ...]


Rolling = dict[tuple[int, str, int], float]


def rolling_forecasts(values: np.ndarray) -> Rolling:
    """`(origin, model, horizon) -> forecast`, each from `values[:origin]` only. The
    seasonal model starts once a full year is available."""
    forecasts: Rolling = {}
    for origin in range(MIN_TRAIN, len(values)):
        history = values[:origin]
        for model in CANDIDATES:
            if model == "seasonal_naive_12" and origin < SEASON:
                continue
            for horizon, point in enumerate(forecast(model, history, HORIZONS), 1):
                if origin + horizon - 1 < len(values):
                    forecasts[(origin, model, horizon)] = float(point)
    return forecasts


def _absolute_errors(
    values: np.ndarray, rolling: Rolling, model: str
) -> dict[int, float]:
    return {
        origin: abs(float(values[origin]) - point)
        for (origin, name, horizon), point in rolling.items()
        if name == model and horizon == 1
    }


def _select(
    values: np.ndarray, rolling: Rolling, low_history: bool
) -> tuple[str, float]:
    """The model and its MAE ratio to the baseline (1.0 for the baseline)."""
    if low_history:
        return BASELINE, 1.0
    base = _absolute_errors(values, rolling, BASELINE)
    best: tuple[float, str, float] | None = None
    for model in CANDIDATES:
        if model == BASELINE:
            continue
        errors = _absolute_errors(values, rolling, model)
        origins = [o for o in errors if o in base]
        if not origins:
            continue
        mae = float(np.mean([errors[o] for o in origins]))
        mae_base = float(np.mean([base[o] for o in origins]))
        if mae_base <= 0:
            continue
        ratio = mae / mae_base
        wins = float(np.mean([errors[o] < base[o] for o in origins]))
        if best is None or ratio < best[0]:
            best = (ratio, model, wins)
    if best is None:
        return BASELINE, 1.0
    ratio, model, wins = best
    if ratio > 1 - MIN_IMPROVEMENT or wins < MIN_WIN_RATE:
        return BASELINE, 1.0
    return model, ratio


def _signed_errors(
    values: np.ndarray, rolling: Rolling, model: str, horizon: int
) -> list[float]:
    return [
        float(values[origin + horizon - 1]) - point
        for (origin, name, h), point in rolling.items()
        if name == model and h == horizon
    ]


def _level(values: np.ndarray) -> float:
    return float(values[-LEVEL_MONTHS:].mean())


def _relative_errors(values: np.ndarray, rolling: Rolling, model: str) -> list[float]:
    """Horizon-1 errors as a share of the series' level before each origin."""
    out: list[float] = []
    for (origin, name, horizon), point in rolling.items():
        if name != model or horizon != 1:
            continue
        scale = float(values[max(0, origin - LEVEL_MONTHS) : origin].mean())
        if scale > 0:
            out.append((float(values[origin]) - point) / scale)
    return out


def _offsets(errors: Sequence[float]) -> tuple[float, float]:
    return (
        float(np.quantile(errors, LOW_QUANTILE)),
        float(np.quantile(errors, HIGH_QUANTILE)),
    )


def fit_all(series: Sequence[Series]) -> list[SeriesFit]:
    """One fit per series, in the order given."""
    prepared = []
    pool: dict[str, list[float]] = defaultdict(list)
    for item in series:
        values = item.values
        low = (
            len(values) < MIN_TRAIN
            or int(np.count_nonzero(values)) < MIN_NONZERO_MONTHS
        )
        rolling = rolling_forecasts(values)
        model, ratio = _select(values, rolling, low)
        pool[item.currency].extend(_relative_errors(values, rolling, model))
        prepared.append((item, rolling, low, model, ratio))

    fits = []
    for item, rolling, low, model, ratio in prepared:
        values = item.values
        point = forecast(model, values, HORIZONS)
        offsets = {
            h: _offsets_for(values, rolling, model, h, pool[item.currency])
            for h in range(1, HORIZONS + 1)
        }
        future = tuple(
            Interval(
                h,
                add_months(item.months[-1], h),
                *_pair(float(point[h - 1]), offsets[h]),
            )
            for h in range(1, HORIZONS + 1)
        )
        origins = sorted(o for (o, m, h) in rolling if m == model and h == 1)
        past = tuple(
            BacktestPoint(
                item.months[o],
                *_pair(rolling[(o, model, 1)], offsets[1]),
                actual=float(values[o]),
            )
            for o in origins
        )
        fits.append(
            SeriesFit(
                category=item.category,
                currency=item.currency,
                model=model,
                baseline_used=model == BASELINE,
                low_history=low,
                n_months=len(values),
                n_origins=max(0, len(values) - MIN_TRAIN),
                mae_rel=ratio,
                coverage=_coverage(values, rolling, model, offsets[1]),
                future=future,
                past=past,
            )
        )
    return fits


def _offsets_for(
    values: np.ndarray,
    rolling: Rolling,
    model: str,
    horizon: int,
    borrowed: Sequence[float],
) -> tuple[float, float] | None:
    """Error quantiles for one horizon: the model's own, or the currency's pooled
    relative errors scaled by this series' level when it has too few."""
    own = _signed_errors(values, rolling, model, horizon)
    if len(own) >= MIN_ERRORS:
        return _offsets(own)
    level = _level(values)
    if len(borrowed) >= MIN_ERRORS and level > 0:
        low, high = _offsets(borrowed)
        return low * level, high * level
    return None


def _pair(
    point: float, offsets: tuple[float, float] | None
) -> tuple[float | None, float, float | None]:
    if offsets is None:
        return None, point, None
    return max(0.0, point + offsets[0]), point, max(0.0, point + offsets[1])


def _coverage(
    values: np.ndarray,
    rolling: Rolling,
    model: str,
    offsets: tuple[float, float] | None,
) -> float | None:
    errors = _signed_errors(values, rolling, model, 1)
    if offsets is None or not errors:
        return None
    return float(np.mean([offsets[0] <= e <= offsets[1] for e in errors]))


def summarize(fits: Sequence[SeriesFit], weights: Sequence[float]) -> dict[str, float]:
    """Counts and ratios for a run: no amount and no name (ADR 0004)."""
    covered = [f.coverage for f in fits if f.coverage is not None]
    ratios = np.array([f.mae_rel for f in fits])
    total = float(sum(weights))
    mean = float(ratios.mean()) if len(fits) else 0.0
    return {
        "series": float(len(fits)),
        "baseline_used": float(sum(f.baseline_used for f in fits)),
        "low_history": float(sum(f.low_history for f in fits)),
        "mae_rel_mean": mean,
        "mae_rel_weighted": float(np.dot(ratios, weights) / total)
        if total > 0
        else mean,
        "coverage_mean": float(np.mean(covered)) if covered else 0.0,
    }
