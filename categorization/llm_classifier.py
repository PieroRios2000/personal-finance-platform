"""Prompt and response parsing for the Claude-as-classifier cost study (ADR 0051).

Pure functions only: no API client, no network call. `scripts/claude_cost_study.py`
wires these to the real Anthropic SDK and the owner's real labels; neither this
module nor its tests ever see or print a real description."""

from collections.abc import Sequence


def build_messages(categories: Sequence[str], description: str) -> tuple[str, str]:
    """The (system, user) prompt pair for one classification call. The category
    list is the only thing in the system prompt, so it is stable across calls and
    cacheable; the one varying description is the whole user turn."""
    category_list = "\n".join(f"- {category}" for category in categories)
    system = (
        "You categorize one personal-finance transaction description into exactly "
        "one of the categories below. Reply with the category name only, exact "
        "spelling, nothing else -- no punctuation, no explanation.\n\n"
        f"Categories:\n{category_list}"
    )
    user = description
    return system, user


def parse_category(raw: str, categories: Sequence[str]) -> str | None:
    """The matched category, or `None` if the model's reply isn't exactly one of
    them (case/whitespace-insensitive) -- a sentence, an unlisted category or an
    empty reply all count as a miss against this model, not a guess we coerce."""
    cleaned = raw.strip().casefold()
    for category in categories:
        if cleaned == category.casefold():
            return category
    return None
