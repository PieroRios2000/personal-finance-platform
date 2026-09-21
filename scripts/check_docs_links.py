"""Check that every relative link and `#anchor` in the Markdown docs resolves (T33).

    uv run python -m scripts.check_docs_links [--root .]

Scans the repository's Markdown (README, SETUP, PROJECT, CLAUDE, `docs/`, `brain/`,
`tasks/`), skips code blocks and external links, and reports a link whose file does not
exist or whose `#anchor` matches no heading of the target, using GitHub's own slug rules
(lower case, punctuation dropped, spaces to hyphens, a `-1`, `-2` suffix for repeats).
Exit code 0 when everything resolves, 1 when something is broken.
"""

import argparse
import re
import sys
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

_SKIP_DIRS = {".git", ".venv", "node_modules", ".claude", "dbt_packages", "target"}
_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_INLINE_CODE = re.compile(r"`[^`]*`")


@dataclass(frozen=True)
class Problem:
    file: str
    target: str
    reason: str


def slug(heading: str) -> str:
    """GitHub's anchor for a heading's text."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)  # links keep their text
    text = re.sub(r"[`*_~]", "", text)
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def _lines(path: Path) -> list[str]:
    """The file's lines outside code fences."""
    kept, inside = [], False
    for line in path.read_text().splitlines():
        if _FENCE.match(line):
            inside = not inside
            continue
        if not inside:
            kept.append(line)
    return kept


def anchors(path: Path) -> set[str]:
    found: set[str] = set()
    seen: dict[str, int] = {}
    for line in _lines(path):
        match = _HEADING.match(line)
        if not match:
            continue
        base = slug(match.group(2))
        count = seen.get(base, 0)
        seen[base] = count + 1
        found.add(base if count == 0 else f"{base}-{count}")
    return found


def _markdown_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.md")
        if not any(part in _SKIP_DIRS for part in path.relative_to(root).parts)
    )


def check(root: Path) -> list[Problem]:
    problems = []
    cache: dict[Path, set[str]] = {}
    for path in _markdown_files(root):
        name = str(path.relative_to(root))
        for line in _lines(path):
            for target in _LINK.findall(_INLINE_CODE.sub("", line)):
                if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):  # http:, mailto:
                    continue
                file_part, _, anchor = target.partition("#")
                destination = (path.parent / file_part).resolve() if file_part else path
                if not destination.exists():
                    problems.append(Problem(name, target, "no such file"))
                elif anchor and destination.suffix == ".md":
                    found = cache.setdefault(destination, anchors(destination))
                    if anchor.lower() not in found:
                        problems.append(Problem(name, target, "no such heading"))
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    problems = check(args.root.resolve())
    for problem in problems:
        print(f"{problem.file}: {problem.target}  ({problem.reason})", file=sys.stderr)
    print(f"docs links: {len(problems)} broken")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
