"""T63 experiment: do recurrence features or the owner's fixed/variable mark help the
category classifier? (ADR 0049, spec 4.8)

    uv run python -m scripts.experiment_recurrence_features --user piero

Reads the owner's movements and trusted (reviewed) labels from gold/silver, builds the
point-in-time recurrence features over every movement of the user, then compares four
feature sets with the same merchant-grouped folds over several shuffles
(`categorization.feature_experiment`). Prints counts, scores and category names only,
never a description or an amount. Writes nothing and never touches the saved model."""

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import date

import psycopg
from psycopg.conninfo import make_conninfo

from categorization import feature_experiment as fx
from categorization import recurrence

_MOVEMENTS = """
    select m.bank, m.description, m.date, m.amount,
           case when l.is_trusted then l.category end as category
    from gold.rpt_movements m
    left join silver.category_labels l
        on l.user_id = m.user_id and l.bank = m.bank and l.description = m.description
    where m.user_id = %(user)s and not m.is_internal_transfer
    order by m.date
"""
_PLAN = """
    select bank, description, kind from silver.plan_fixed_items
    where user_id = %(user)s and kind is not null
"""
WEAK = ("Servicios", "Alimentacion", "Transporte", "Restaurantes")


def _conninfo() -> str:
    return make_conninfo(
        dbname=os.environ["PFP_PG_DATABASE"],
        host=os.environ.get("PFP_PG_HOST", "127.0.0.1"),
        port=os.environ.get("PFP_PG_PORT", "5432"),
        user=os.environ["PFP_PG_USER"],
        password=os.environ["PFP_PG_PASSWORD"],
    )


def _normalize(name: str) -> str:
    return name.lower().replace("ó", "o").replace("í", "i").replace("é", "e")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default=os.environ.get("PFP_USER"))
    parser.add_argument("--seeds", type=int, default=5)
    args = parser.parse_args(argv)
    if not args.user:
        print("error: --user is required (or set PFP_USER)", file=sys.stderr)
        return 2

    with psycopg.connect(_conninfo()) as conn, conn.cursor() as cursor:
        cursor.execute(_MOVEMENTS, {"user": args.user})
        rows = cursor.fetchall()
        cursor.execute(_PLAN, {"user": args.user})
        marks = recurrence.kind_by_merchant(cursor.fetchall())

    occurrences = [
        recurrence.Occurrence(
            str(bank), str(description), date(d.year, d.month, 1), float(amount)
        )
        for bank, description, d, amount, _category in rows
    ]
    features = recurrence.recurrence_features(occurrences)
    labeled = [i for i, row in enumerate(rows) if row[4] is not None]
    banks = [occurrences[i].bank for i in labeled]
    descriptions = [occurrences[i].description for i in labeled]
    labels = [str(rows[i][4]) for i in labeled]
    kinds = [
        marks.get(recurrence.merchant_key(b, d))
        for b, d in zip(banks, descriptions, strict=True)
    ]
    frame = fx.feature_frame(
        [f"{b} {d}" for b, d in zip(banks, descriptions, strict=True)],
        [features[i] for i in labeled],
        kinds,
    )
    groups = fx.merchant_groups(banks, descriptions)

    seen_twice = [features[i].months_seen >= 2 for i in labeled]
    print(
        f"rows: {len(labeled)} trusted movements of {len(rows)}; "
        f"{len(set(groups))} merchants; {len(set(labels))} categories"
    )
    print(
        f"coverage: {sum(seen_twice)} rows with >=2 prior months, "
        f"{sum(k is not None for k in kinds)} rows with a plan mark "
        f"({len(marks)} marked merchants)"
    )

    results = {
        name: fx.evaluate(
            frame, labels, groups, columns, seeds=range(args.seeds), folds=5
        )
        for name, columns in fx.VARIANTS.items()
    }
    base = results["text"]
    weak = [c for c in sorted(set(labels)) if _normalize(c) in map(_normalize, WEAK)]
    print(f"weak categories found: {', '.join(weak) or 'none'}")
    print(f"folds: 5 x {args.seeds} shuffles; baseline fold SD = {base.fold_sd:.3f}")
    for name, result in results.items():
        line = (
            f"{name}: macro-F1 = {result.mean_f1:.3f} "
            f"(run-to-run range {result.run_spread:.3f})"
        )
        if name != "text":
            outcome = fx.verdict(base, result, weak)
            line += (
                f", margin {outcome.margin:+.3f}, "
                f"{'ADOPT' if outcome.adopt else 'no adoption'}"
            )
            if outcome.dropped:
                line += f", precision dropped: {', '.join(outcome.dropped)}"
        print(line)
        for category in weak:
            print(
                f"  precision[{category}] = {result.precision[category]:.3f} "
                f"(text-only {base.precision[category]:.3f})"
            )
    for label, selector in (("seen >=2 months", True), ("seen <2 months", False)):
        picked = [i for i, seen in enumerate(seen_twice) if seen is selector]
        if not picked:
            continue
        accuracies = {
            name: sum(r.row_accuracy[i] for i in picked) / len(picked)
            for name, r in results.items()
        }
        print(
            f"accuracy on rows {label} (n={len(picked)}): "
            + ", ".join(f"{n} {a:.3f}" for n, a in accuracies.items())
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
