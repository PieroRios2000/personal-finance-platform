"""The monthly round trip, export -> the owner edits only the new rows -> import, must
leave every label the owner already had exactly as it was, trust included.

Found 2026-11-07 on real data: the export prefilled every row with the model's guess
and the import replaces the whole label set, with `is_trusted` read off the suggestion,
so an unedited round trip overwrote reviewed labels and flipped their trust. Both
scripts run for real here; only gold (`fetch_groups`), the suggestion and bronze are
stand-ins.
"""

from pathlib import Path
from typing import Any

import pytest

from lakehouse import bronze
from scripts import export_category_labels as ecl
from scripts import import_category_labels as icl

EXISTING = {
    ("BCP", "NETFLIX.COM"): ("Entretenimiento", True),  # reviewed, model disagrees
    ("BCP", "UBER TRIP"): ("Transporte", True),  # reviewed, model agrees
    ("BCP", "PLAZA VEA"): ("Alimentacion", False),  # accepted guess, model agrees
    ("BCP", "TAMBO"): ("Alimentacion", False),  # accepted guess, model disagrees
}
SUGGESTIONS = {
    "NETFLIX.COM": "Servicios",
    "UBER TRIP": "Transporte",
    "PLAZA VEA": "Alimentacion",
    "TAMBO": "Gastos varios",
    "NEW SHOP": "Ropa",
}


def test_an_unedited_round_trip_keeps_every_existing_label_and_its_trust(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name, value in {
        "PFP_PG_DATABASE": "pfp",
        "PFP_PG_USER": "pfp",
        "PFP_PG_PASSWORD": "secret",
        "LAKEHOUSE_URI": "s3://lakehouse",
    }.items():
        monkeypatch.setenv(name, value)
    groups = [(bank, description, 1) for bank, description in EXISTING]
    monkeypatch.setattr(
        ecl, "fetch_groups", lambda user_id: [*groups, ("BCP", "NEW SHOP", 1)]
    )
    monkeypatch.setattr(
        ecl, "_suggest", lambda description, bundle: SUGGESTIONS[description]
    )
    monkeypatch.setattr(bronze, "category_labels", lambda user_id: EXISTING)
    stored: list[Any] = []
    monkeypatch.setattr(
        bronze, "replace_category_labels", lambda user_id, labels: stored.append(labels)
    )
    out = tmp_path / "labels.xlsx"

    assert ecl.main(["--user", "piero", "--out", str(out)]) == 0
    assert icl.main([str(out), "--user", "piero"]) == 0

    labels = {(bank, desc): (cat, trusted) for bank, desc, cat, trusted in stored[0]}
    assert {key: labels[key] for key in EXISTING} == EXISTING
    assert labels[("BCP", "NEW SHOP")] == ("Ropa", False)
