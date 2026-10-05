"""The monthly routine runbook (docs/monthly-routine.md) names real `make` targets,
in the order the data flows. A renamed or removed target must fail here, not on the
first of the month when the owner follows the steps."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNBOOK = ROOT / "docs" / "monthly-routine.md"

ORDER = [
    "ingest",
    "export-category-labels",
    "import-category-labels",
    "train-category-model",
    "categorize-new-movements",
    "monitor-category-drift",
    "export-plan",
    "import-plan",
    "forecast",
]


def _makefile_targets() -> set[str]:
    text = (ROOT / "Makefile").read_text()
    return set(re.findall(r"^([a-z][a-z0-9-]*):", text, flags=re.MULTILINE))


def _commands() -> list[str]:
    return re.findall(
        r"^make ([a-z][a-z0-9-]*)", RUNBOOK.read_text(), flags=re.MULTILINE
    )


def test_every_make_command_in_the_runbook_is_a_real_target() -> None:
    missing = [c for c in _commands() if c not in _makefile_targets()]
    assert not missing, f"docs/monthly-routine.md names unknown make targets: {missing}"


def test_the_runbook_lists_the_steps_in_order() -> None:
    commands = [c for c in _commands() if c in ORDER]
    assert commands == ORDER


def test_the_runbook_says_when_a_months_statements_appear() -> None:
    text = RUNBOOK.read_text()
    assert "first day of the next month" in text
    assert "first_day_of_current_month" in text


def test_the_runbook_has_the_plan_and_forecast_step_and_its_monitor() -> None:
    text = RUNBOOK.read_text()
    assert "Forecast: realized vs expected" in text
    assert "docs/where-to-look.md" in text
