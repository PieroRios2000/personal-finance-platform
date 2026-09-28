"""A category classifier trained on the owner's own confirmed labels (T52, ADR 0044):
character n-grams (TF-IDF) over the movement description, then logistic regression --
built for this project's own vocabulary and scale (tens to low hundreds of distinct
descriptions), not a pretrained or off-the-shelf model. Character n-grams, not word
n-grams: short, noisy bank-statement text (abbreviations, run-together words, stray
digits) shares substrings even when it shares no whole word, and a small labeled set
has too few repeats of any one word to learn much from words alone.

Nothing here ever prints, logs or returns a description or the vectorizer's vocabulary:
a fitted model's vocabulary *is* the owner's real transaction text (ADR 0004 covers it
exactly as it covers a real PDF), so a trained model is a local artifact, same
discipline as the account key -- see `scripts/train_category_model.py`.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, precision_score
from sklearn.model_selection import GroupKFold, cross_val_predict
from sklearn.pipeline import Pipeline

MIN_EXAMPLES = 10
MIN_PER_CLASS = 2

# The one place this path is spelled out (`scripts/train_category_model.py` and
# `scripts/export_category_labels.py` both import it): under `~/finance-data/`, never
# in the repo, same discipline as the account key (ADR 0004) -- see this module's own
# docstring. No suffix here; callers that save append `.joblib` themselves
# (`train_category_model.py`), callers that only load expect it already appended.
DEFAULT_MODEL_PATH = Path.home() / "finance-data" / "models" / "category_classifier"

_DIGITS = re.compile(r"\d+")


class NotEnoughDataError(ValueError):
    """Too few labeled examples, too few distinct categories, or too few distinct
    merchants, to train on or cross-validate meaningfully."""


@dataclass(frozen=True)
class Metrics:
    """What training reports: counts and cross-validated scores, never a description
    or a class name -- safe to print, log to MLflow or hand to a caller that isn't as
    careful about privacy as this module has to be.

    `macro_f1`, not accuracy: with as few, uneven categories as a first labeling
    round has, a model that always guesses the biggest category scores high on
    accuracy and tells you nothing. Precision is per category
    (`{category: precision}`), so a bad category doesn't hide behind a good average.

    `folds`: how many cross-validation folds these scores are actually averaged over
    (reviewer feedback, 2026-09-27) -- with this project's realistic label counts it
    is often the legal minimum, 2, and a 2-fold macro-F1 deserves less trust than a
    5-fold one. Printed next to every metric for exactly that reason.
    """

    examples: int
    categories: int
    macro_f1: float
    precision_by_category: dict[str, float]
    folds: int


@dataclass(frozen=True)
class Bundle:
    """What gets saved and loaded (`scripts/train_category_model.py`,
    `scripts/export_category_labels.py`): the fitted pipeline plus the confidence
    threshold below which its own prediction isn't trusted, chosen empirically by
    `choose_confidence_threshold` -- never eyeballed, since a logistic regression's
    probabilities are not well calibrated on this few examples."""

    pipeline: Pipeline
    confidence_threshold: float


def _new_pipeline() -> Pipeline:
    return Pipeline(
        [
            (
                "tfidf",
                TfidfVectorizer(
                    analyzer="char_wb", ngram_range=(2, 4), min_df=1, sublinear_tf=True
                ),
            ),
            ("classifier", LogisticRegression(max_iter=1000, class_weight="balanced")),
        ]
    )


def _merchant_group(description: str) -> str:
    """`description` with every run of digits collapsed to one placeholder, so two
    rows of the same merchant that differ only by a transaction id or a masked card
    number ("UBER TRIP 4821" / "UBER TRIP 5530") count as one merchant for
    cross-validation grouping. Without this, a character n-gram model can partly
    "cheat": two near-duplicate rows of the same merchant land in different folds,
    and the model effectively grades itself on a row it has already half-seen
    (reviewer feedback, 2026-09-27)."""
    return _DIGITS.sub("#", description)


def _check(descriptions: list[str], categories: list[str]) -> dict[str, int]:
    if len(descriptions) != len(categories):
        raise ValueError("descriptions and categories must be the same length")
    if len(descriptions) < MIN_EXAMPLES:
        raise NotEnoughDataError(
            f"only {len(descriptions)} labeled example(s); need at least {MIN_EXAMPLES}"
        )
    counts: dict[str, int] = {}
    for category in categories:
        counts[category] = counts.get(category, 0) + 1
    if len(counts) < 2:
        raise NotEnoughDataError("only one category is represented; need at least 2")
    smallest = min(counts.values())
    if smallest < MIN_PER_CLASS:
        raise NotEnoughDataError(
            f"category with only {smallest} example(s); "
            f"need at least {MIN_PER_CLASS} each"
        )
    return counts


def _cv_split(
    descriptions: list[str], categories: list[str]
) -> tuple[GroupKFold, list[str], dict[str, int], int]:
    """The grouped cross-validation split every training/evaluation function shares:
    `(cv, groups, category_counts, folds)`. Raises `NotEnoughDataError` the same way
    `_check` does, plus one more case unique to grouping: fewer than 2 distinct
    merchants, which `GroupKFold` cannot split at all."""
    counts = _check(descriptions, categories)
    groups = [_merchant_group(description) for description in descriptions]
    distinct_groups = len(set(groups))
    if distinct_groups < 2:
        raise NotEnoughDataError(
            "only one merchant group is represented; need at least 2"
        )
    folds = max(2, min(5, min(counts.values()), distinct_groups))
    return GroupKFold(n_splits=folds), groups, counts, folds


def _metrics(
    categories: list[str], predicted: list[str], counts: dict[str, int], folds: int
) -> Metrics:
    labels = sorted(counts)
    precisions = precision_score(
        categories, predicted, labels=labels, average=None, zero_division=0
    )
    return Metrics(
        examples=len(categories),
        categories=len(counts),
        macro_f1=float(
            f1_score(categories, predicted, average="macro", zero_division=0)
        ),
        precision_by_category=dict(
            zip(labels, (float(p) for p in precisions), strict=True)
        ),
        folds=folds,
    )


def train(descriptions: list[str], categories: list[str]) -> tuple[Pipeline, Metrics]:
    """Fit a fresh pipeline on `descriptions`/`categories` (same length, one label
    each -- the owner's confirmed labels, one row per distinct description, never
    weighted by how many movements share it: every example the owner reviewed counts
    once). Raises `NotEnoughDataError` rather than silently training on too little to
    mean anything. Metrics come from cross-validated predictions grouped by merchant
    (`_merchant_group`), not the training accuracy of the final fit."""
    cv, groups, counts, folds = _cv_split(descriptions, categories)
    predicted = list(
        cross_val_predict(
            _new_pipeline(), descriptions, categories, cv=cv, groups=groups
        )
    )
    metrics = _metrics(categories, predicted, counts, folds)
    pipeline = _new_pipeline()
    pipeline.fit(descriptions, categories)
    return pipeline, metrics


def score_rules(
    descriptions: list[str], categories: list[str], guess: Callable[[str], str]
) -> Metrics:
    """The same metrics `train()` reports, for the rules-based guesser instead of the
    trained model -- the baseline a trained model has to beat before it is worth
    keeping (`scripts/train_category_model.py` reports both, side by side). No
    cross-validation needed (the guesser has nothing to fit), so `folds` is always 1 --
    every row scored once, deterministically."""
    counts = _check(descriptions, categories)
    predicted = [guess(description) for description in descriptions]
    return _metrics(categories, predicted, counts, folds=1)


def predict(pipeline: Pipeline, description: str) -> tuple[str, float]:
    """The predicted category and its confidence (the winning class' probability)."""
    (category,) = pipeline.predict([description])
    probabilities = pipeline.predict_proba([description])[0]
    confidence = float(max(probabilities))
    return str(category), confidence


def choose_confidence_threshold(
    descriptions: list[str], categories: list[str], guess: Callable[[str], str]
) -> tuple[float, int]:
    """The confidence cutoff below which the rules-based guesser's answer beats the
    model's own, chosen empirically from the same grouped cross-validation `train()`
    uses -- never eyeballed, since a logistic regression's probabilities are not
    well calibrated on this few examples (reviewer feedback, 2026-09-27). Returns
    `(threshold, folds actually used)`; `scripts/export_category_labels.py` falls
    back to `guess()` under the threshold (`suggest()`, below).

    Refits a pipeline per fold (rather than reusing `cross_val_predict`, which
    requires every class to appear in every fold's training split to aggregate
    `predict_proba` safely): each held-out row only ever needs its own probability
    vector, never one comparable across folds, so a fold missing a rare class is
    fine here."""
    cv, groups, _counts, folds = _cv_split(descriptions, categories)
    confidences = [0.0] * len(descriptions)
    model_predicted = [""] * len(descriptions)
    for train_idx, test_idx in cv.split(descriptions, categories, groups):
        pipeline = _new_pipeline()
        pipeline.fit(
            [descriptions[i] for i in train_idx], [categories[i] for i in train_idx]
        )
        probabilities = pipeline.predict_proba([descriptions[i] for i in test_idx])
        winners = probabilities.argmax(axis=1)
        for position, row in enumerate(test_idx):
            confidences[row] = float(probabilities[position, winners[position]])
            model_predicted[row] = str(pipeline.classes_[winners[position]])
    rule_predicted = [guess(description) for description in descriptions]

    labels = sorted(set(categories))
    best_threshold, best_f1 = 0.0, -1.0
    for threshold in sorted(set(confidences)) + [max(confidences) + 1e-9]:
        combined = [
            model_predicted[i] if confidences[i] >= threshold else rule_predicted[i]
            for i in range(len(descriptions))
        ]
        score = f1_score(
            categories, combined, labels=labels, average="macro", zero_division=0
        )
        if score > best_f1:
            best_f1, best_threshold = score, threshold
    return best_threshold, folds


def suggest(bundle: Bundle, description: str, guess: Callable[[str], str]) -> str:
    """The trained model's prediction when its confidence clears
    `bundle.confidence_threshold`, the rules-based guesser's otherwise -- the same
    calibrated fallback `choose_confidence_threshold` was chosen for."""
    category, confidence = predict(bundle.pipeline, description)
    if confidence >= bundle.confidence_threshold:
        return category
    return guess(description)


def load(path: Path) -> Bundle | None:
    """The bundle saved at `path` (`scripts/train_category_model.py`'s own
    `joblib.dump`), or `None` if nothing has been trained yet -- the cold start
    `scripts/export_category_labels.py` falls back to the rules-based guesser for."""
    if not path.exists():
        return None
    bundle = joblib.load(path)
    if not isinstance(bundle, Bundle):
        raise TypeError(f"{path} does not contain a categorization.model.Bundle")
    return bundle
