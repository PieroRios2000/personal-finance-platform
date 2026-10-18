"""The deferred Phase 3 cost study (ADR 0051): Claude as a per-transaction
classifier, against the trained model's own already-reported numbers (ADR 0044,
README's ML-results section).

    set -a && . ~/finance-data/.env-claude-cost-study && set +a
    uv run python -m scripts.claude_cost_study --user piero

Reads the owner's trusted (reviewed) labels and the fixed category list from
`pfp-poc`'s gold/silver (read-only), classifies each one with two real models
(`claude-haiku-4-5`, `claude-sonnet-5-5`), and reports macro-F1, per-category
precision, latency and the real cost (from `response.usage`, never estimated)
next to the trained model's own numbers. Never prints a description or a raw
model reply -- only counts, category names and scores. Writes nothing to the
lake or the model file; this is read-only end to end."""

import argparse
import os
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass

import anthropic
import psycopg
from psycopg.conninfo import make_conninfo
from sklearn.metrics import f1_score, precision_score

from categorization.llm_classifier import build_messages, parse_category

_TRUSTED_LABELS = """
    select bank, description, category from silver.category_labels
    where user_id = %(user)s and is_trusted
"""
_CATEGORIES = "select category from gold.dim_category order by 1"
_NEW_PER_MONTH = """
    with first_seen as (
        select bank, description, min(date_trunc('month', date)) as first_month
        from gold.rpt_movements
        where user_id = %(user)s and not is_internal_transfer
        group by bank, description
    )
    select round(count(*)::numeric / greatest(count(distinct first_month), 1), 1)
    from first_seen
"""

# $ per million tokens, cached 2026-10, from the Claude API pricing page -- never
# estimated from the real run, only multiplied against real `response.usage` counts.
PRICE_PER_MTOK = {
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00},
}
MODELS = tuple(PRICE_PER_MTOK)
MAX_TOKENS = 30


@dataclass(frozen=True)
class ModelRun:
    model: str
    examples: int
    macro_f1: float
    precision_by_category: dict[str, float]
    parse_failures: int
    mean_latency_s: float
    input_tokens: int
    output_tokens: int
    cost_usd: float


def _conninfo() -> str:
    return make_conninfo(
        dbname=os.environ["PFP_PG_DATABASE"],
        host=os.environ.get("PFP_PG_HOST", "127.0.0.1"),
        port=os.environ.get("PFP_PG_PORT", "5432"),
        user=os.environ["PFP_PG_USER"],
        password=os.environ["PFP_PG_PASSWORD"],
    )


def fetch(user_id: str) -> tuple[list[tuple[str, str, str]], list[str], float]:
    """Trusted (bank, description, category) rows, the fixed category list, and
    the real average of new distinct descriptions per month."""
    with psycopg.connect(_conninfo()) as conn, conn.cursor() as cursor:
        cursor.execute(_TRUSTED_LABELS, {"user": user_id})
        rows = [(str(b), str(d), str(c)) for b, d, c in cursor.fetchall()]
        cursor.execute(_CATEGORIES)
        categories = [str(row[0]) for row in cursor.fetchall()]
        cursor.execute(_NEW_PER_MONTH, {"user": user_id})
        row = cursor.fetchone()
        new_per_month = float(row[0]) if row else 0.0
    return rows, categories, new_per_month


def classify_one(
    client: anthropic.Anthropic, model: str, categories: Sequence[str], description: str
) -> tuple[str | None, float, int, int]:
    """One real API call: the parsed category (or `None` if unparseable), latency
    in seconds, input tokens, output tokens -- never the raw reply or the
    description beyond this one call's own argument."""
    system, user = build_messages(categories, description)
    started = time.monotonic()
    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    latency = time.monotonic() - started
    raw = "".join(block.text for block in response.content if block.type == "text")
    return (
        parse_category(raw, categories),
        latency,
        response.usage.input_tokens,
        response.usage.output_tokens,
    )


def run_model(
    client: anthropic.Anthropic,
    model: str,
    rows: Sequence[tuple[str, str, str]],
    categories: Sequence[str],
) -> ModelRun:
    predicted: list[str] = []
    truth: list[str] = []
    latencies: list[float] = []
    failures = 0
    total_in = 0
    total_out = 0
    for i, (_bank, description, category) in enumerate(rows, start=1):
        guess, latency, in_tok, out_tok = classify_one(
            client, model, categories, description
        )
        latencies.append(latency)
        total_in += in_tok
        total_out += out_tok
        truth.append(category)
        if guess is None:
            failures += 1
            predicted.append("")  # counts as a miss against every real category
        else:
            predicted.append(guess)
        if i % 100 == 0:
            print(f"  {model}: {i}/{len(rows)}", file=sys.stderr)

    labels = sorted(set(truth))
    precisions = precision_score(
        truth, predicted, labels=labels, average=None, zero_division=0
    )
    prices = PRICE_PER_MTOK[model]
    cost = (
        total_in / 1_000_000 * prices["input"]
        + total_out / 1_000_000 * prices["output"]
    )
    return ModelRun(
        model=model,
        examples=len(rows),
        macro_f1=float(f1_score(truth, predicted, average="macro", zero_division=0)),
        precision_by_category=dict(
            zip(labels, (float(p) for p in precisions), strict=True)
        ),
        parse_failures=failures,
        mean_latency_s=sum(latencies) / len(latencies) if latencies else 0.0,
        input_tokens=total_in,
        output_tokens=total_out,
        cost_usd=cost,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default=os.environ.get("PFP_USER"))
    args = parser.parse_args(argv)
    if not args.user:
        print("error: --user is required (or set PFP_USER)", file=sys.stderr)
        return 2

    rows, categories, new_per_month = fetch(args.user)
    print(f"{len(rows)} trusted labels, {len(categories)} categories")
    print(f"real monthly volume: {new_per_month} new distinct descriptions/month")

    client = anthropic.Anthropic()
    runs = [run_model(client, model, rows, categories) for model in MODELS]

    print()
    for run in runs:
        monthly_cost = (
            run.cost_usd / run.examples * new_per_month if run.examples else 0.0
        )
        print(
            f"{run.model}: macro-F1 = {run.macro_f1:.3f}, "
            f"{run.parse_failures} parse failure(s), "
            f"mean latency {run.mean_latency_s:.2f}s, "
            f"measured cost ${run.cost_usd:.4f} for {run.examples} calls "
            f"({run.input_tokens} in / {run.output_tokens} out tokens), "
            f"projected ${monthly_cost:.4f}/month at real volume"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
