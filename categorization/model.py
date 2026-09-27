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

from collections.abc import Callable
from dataclasses import dataclass

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, precision_score
from sklearn.model_selection import cross_val_predict
from sklearn.pipeline import Pipeline

MIN_EXAMPLES = 10
MIN_PER_CLASS = 2


class NotEnoughDataError(ValueError):
    """Too few labeled examples, or too few distinct categories, to train on."""


@dataclass(frozen=True)
class Metrics:
    """What training reports: counts and cross-validated scores, never a description
    or a class name -- safe to print, log to MLflow or hand to a caller that isn't as
    careful about privacy as this module has to be.

    `macro_f1`, not accuracy: with as few, uneven categories as a first labeling
    round has, a model that always guesses the biggest category scores high on
    accuracy and tells you nothing. Precision is per category
    (`{category: precision}`), so a bad category doesn't hide behind a good average.
    """

    examples: int
    categories: int
    macro_f1: float
    precision_by_category: dict[str, float]


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


def _metrics(
    categories: list[str], predicted: list[str], counts: dict[str, int]
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
    )


def train(descriptions: list[str], categories: list[str]) -> tuple[Pipeline, Metrics]:
    """Fit a fresh pipeline on `descriptions`/`categories` (same length, one label
    each -- the owner's confirmed labels, one row per distinct description, never
    weighted by how many movements share it: every example the owner reviewed counts
    once). Raises `NotEnoughDataError` rather than silently training on too little to
    mean anything. Metrics come from cross-validated predictions, not the training
    accuracy of the final fit."""
    counts = _check(descriptions, categories)
    folds = max(2, min(5, min(counts.values())))
    predicted = list(
        cross_val_predict(_new_pipeline(), descriptions, categories, cv=folds)
    )
    metrics = _metrics(categories, predicted, counts)
    pipeline = _new_pipeline()
    pipeline.fit(descriptions, categories)
    return pipeline, metrics


def score_rules(
    descriptions: list[str], categories: list[str], guess: Callable[[str], str]
) -> Metrics:
    """The same metrics `train()` reports, for the rules-based guesser instead of the
    trained model -- the baseline a trained model has to beat before it is worth
    keeping (`scripts/train_category_model.py` reports both, side by side)."""
    counts = _check(descriptions, categories)
    predicted = [guess(description) for description in descriptions]
    return _metrics(categories, predicted, counts)


def predict(pipeline: Pipeline, description: str) -> tuple[str, float]:
    """The predicted category and its confidence (the winning class' probability)."""
    (category,) = pipeline.predict([description])
    probabilities = pipeline.predict_proba([description])[0]
    confidence = float(max(probabilities))
    return str(category), confidence
