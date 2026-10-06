"""The comparison harness behind T63 (ADR 0049): does adding recurrence features or the
owner's fixed/variable mark to the classifier beat text alone? Same protocol as ADR
0044 (merchant-grouped cross-validation, macro-F1), repeated over shuffles so the
run-to-run spread is visible. Pure functions over in-memory data; nothing here prints
a description."""

import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, precision_score
from sklearn.pipeline import Pipeline

from categorization.model import _merchant_group
from categorization.recurrence import Recurrence

RECURRENCE_COLUMNS = (
    "months_seen",
    "rate",
    "rate_missing",
    "spread",
    "spread_missing",
)
KIND_COLUMNS = ("kind_fixed", "kind_variable", "kind_ignore")
VARIANTS: dict[str, tuple[str, ...]] = {
    "text": (),
    "recurrence": RECURRENCE_COLUMNS,
    "plan_kind": KIND_COLUMNS,
    "all": RECURRENCE_COLUMNS + KIND_COLUMNS,
}
_WINDOW = 12


def merchant_folds(groups: Sequence[str], folds: int, seed: int) -> list[int]:
    """A fold number per row, every merchant group wholly inside one fold; `seed`
    reshuffles which groups land together."""
    distinct = sorted(set(groups))
    random.Random(seed).shuffle(distinct)
    fold_of = {group: i % folds for i, group in enumerate(distinct)}
    return [fold_of[group] for group in groups]


def feature_frame(
    texts: Sequence[str],
    recurrences: Sequence[Recurrence],
    kinds: Sequence[str | None],
) -> pd.DataFrame:
    """One row per movement: the text, the recurrence numbers (missing ones become 0
    plus a `*_missing` flag, so "never seen" is not mistaken for "steady") and the
    plan kind one-hot (`kind_*`, all zero when the merchant is not in the plan)."""
    rows = []
    for text, rec, kind in zip(texts, recurrences, kinds, strict=True):
        rows.append(
            {
                "text": text,
                "months_seen": rec.months_seen / _WINDOW,
                "rate": rec.rate or 0.0,
                "rate_missing": int(rec.rate is None),
                "spread": rec.amount_spread or 0.0,
                "spread_missing": int(rec.amount_spread is None),
                "kind_fixed": int(kind == "fixed"),
                "kind_variable": int(kind == "variable"),
                "kind_ignore": int(kind == "ignore"),
            }
        )
    return pd.DataFrame(rows)


@dataclass(frozen=True)
class Result:
    """`pooled_f1`: one macro-F1 per shuffle, over all its held-out predictions.
    `fold_f1`: the macro-F1 of every single fold of every shuffle.
    `precision`: per-category precision of the pooled predictions, averaged over
    shuffles. `row_accuracy`: per row, the share of shuffles that predicted it right."""

    pooled_f1: list[float]
    fold_f1: list[float]
    precision: dict[str, float]
    row_accuracy: list[float] = field(default_factory=list)

    @property
    def mean_f1(self) -> float:
        return statistics.fmean(self.pooled_f1)

    @property
    def fold_sd(self) -> float:
        return statistics.stdev(self.fold_f1) if len(self.fold_f1) > 1 else 0.0

    @property
    def run_spread(self) -> float:
        return max(self.pooled_f1) - min(self.pooled_f1)


def _pipeline(numeric: Sequence[str]) -> Pipeline:
    columns = ColumnTransformer(
        [
            (
                "text",
                TfidfVectorizer(
                    analyzer="char_wb", ngram_range=(2, 4), min_df=1, sublinear_tf=True
                ),
                "text",
            ),
            ("numbers", "passthrough", list(numeric)),
        ]
    )
    return Pipeline(
        [
            ("columns", columns),
            ("classifier", LogisticRegression(max_iter=1000, class_weight="balanced")),
        ]
    )


def evaluate(
    frame: pd.DataFrame,
    labels: Sequence[str],
    groups: Sequence[str],
    numeric: Sequence[str],
    seeds: Sequence[int] = (0, 1, 2, 3, 4),
    folds: int = 5,
) -> Result:
    """Cross-validate one feature set over `seeds` shuffles of the merchant folds.
    `groups` are the merchant keys (`merchant_groups`)."""
    y = list(labels)
    classes = sorted(set(y))
    pooled, per_fold = [], []
    precisions = []
    hits = [0.0] * len(y)
    for seed in seeds:
        fold_of = merchant_folds(groups, folds, seed)
        predicted = [""] * len(y)
        for fold in range(folds):
            test = [i for i, f in enumerate(fold_of) if f == fold]
            train = [i for i, f in enumerate(fold_of) if f != fold]
            if not test or len({y[i] for i in train}) < 2:
                continue
            model = _pipeline(numeric)
            model.fit(frame.iloc[train], [y[i] for i in train])
            guesses = model.predict(frame.iloc[test])
            for row, guess in zip(test, guesses, strict=True):
                predicted[row] = str(guess)
            per_fold.append(
                float(
                    f1_score(
                        [y[i] for i in test], guesses, average="macro", zero_division=0
                    )
                )
            )
        for row, guess in enumerate(predicted):
            hits[row] += float(guess == y[row]) / len(seeds)
        pooled.append(float(f1_score(y, predicted, average="macro", zero_division=0)))
        precisions.append(
            precision_score(y, predicted, labels=classes, average=None, zero_division=0)
        )
    mean_precision = [
        statistics.fmean(column) for column in zip(*precisions, strict=True)
    ]
    return Result(
        pooled_f1=pooled,
        fold_f1=per_fold,
        precision=dict(zip(classes, mean_precision, strict=True)),
        row_accuracy=hits,
    )


def merchant_groups(banks: Sequence[str], descriptions: Sequence[str]) -> list[str]:
    return [
        f"{b}|{_merchant_group(d)}" for b, d in zip(banks, descriptions, strict=True)
    ]


@dataclass(frozen=True)
class Verdict:
    adopt: bool
    margin: float
    dropped: list[str]


def verdict(base: Result, candidate: Result, weak: Sequence[str]) -> Verdict:
    """ADR 0044 / spec 4.8: adopt only if the mean macro-F1 beats the text-only baseline
    by more than one SD of the baseline's fold-to-fold spread and no weak category's
    precision falls."""
    margin = candidate.mean_f1 - base.mean_f1
    dropped = [
        category
        for category in weak
        if category in base.precision
        and category in candidate.precision
        and candidate.precision[category] < base.precision[category]
    ]
    return Verdict(
        adopt=margin > base.fold_sd and not dropped,
        margin=margin,
        dropped=dropped,
    )
