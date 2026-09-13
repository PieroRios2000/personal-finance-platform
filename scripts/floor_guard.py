"""floor-guard: fails if the diff against the base branch lowers the quality bar.

Checks the lines added and removed between the merge-base with the base branch and the
working tree (untracked files included). Run it from the repo root:

    uv run python scripts/floor_guard.py [--base origin/develop]

Exit codes: 0 clean, 1 the bar dropped, 2 could not run. Approved exceptions are read
from CONSTRAINTS.md's exceptions table. Never prints the line's text (it could hold a
secret), only the rule and the location.
"""

import argparse
import re
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path

# Comments that turn off a floor check: ruff, mypy, bandit, coverage, gitleaks.
SUPPRESSION = re.compile(
    r"#.*\b(noqa|type:\s*ignore|nosec|pragma:\s*no\s*cover|fmt:\s*(off|skip)"
    r"|mypy:\s*(ignore-errors|disable-error-code))\b|gitleaks:allow",
    re.IGNORECASE,
)
SKIP = re.compile(r"\b(pytest|mark|unittest)\.(skip|xfail)|\b(skipTest|importorskip)\b")
TEST_OR_ASSERT = re.compile(r"\bdef test_|\bassert\b|pytest\.raises")
CONFIG = ("pyproject.toml", "Makefile", ".pre-commit-config.yaml")
# Files that could override mypy's, ruff's, pytest's or coverage's config.
OTHER_CONFIG = (
    *("mypy.ini", ".mypy.ini", "setup.cfg", "tox.ini", "pytest.ini"),
    *("ruff.toml", ".ruff.toml", ".coveragerc"),
)
RELAXED = re.compile(
    r"^\s*(ignore|extend-ignore|ignore_errors|ignore_missing_imports|"
    r"disable_error_code)\s*=|per-file-ignores|\bstrict\s*=\s*false|"
    r"^\s*(disallow|warn)_\w+\s*=\s*false",
    re.IGNORECASE,
)
STRICT = re.compile(r"\bstrict\s*=\s*true", re.IGNORECASE)
# Floor checks: must not disappear, or run without stopping ("-" or "|| true").
FLOOR_TOOL = re.compile(r"\b(ruff|mypy|pytest|floor_guard|gitleaks)\b")
IGNORED_FAILURE = re.compile(r"^\t-|\|\|\s*true")
NUMBER = re.compile(r"\d+(?:\.\d+)?")
VERSION_SPEC = re.compile(r"[<>=~!]=")  # "bandit>=1.9.4" is a version, not a threshold
HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)")
# Same diff shape regardless of the runner's git config (prefixes, non-ASCII paths,
# renames, an external diff tool).
DIFF = (
    *("-c", "core.quotePath=false", "diff", "--no-color", "--no-ext-diff"),
    *("--no-renames", "--src-prefix=a/", "--dst-prefix=b/", "--unified=0"),
)
EXCEPTION_ROW = re.compile(r"^\|\s*([\w-]+)\s*\|\s*`?([^|`]+?)`?\s*\|")
# Its own patterns and fixtures contain the very markers it looks for.
SELF = ("scripts/floor_guard.py", "tests/test_floor_guard.py")

Line = tuple[str, int, str]  # (file, line number, text)
Finding = tuple[str, str, str]  # (rule, file, location)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout


def changes(base: str) -> tuple[list[Line], list[Line]]:
    """Lines added and removed since the merge-base with `base`."""
    merge_base = git("merge-base", base, "HEAD").strip()
    added: list[Line] = []
    removed: list[Line] = []
    path, header, old, new = "", False, 0, 0
    for line in git(*DIFF, merge_base).splitlines():
        if line.startswith("diff --git"):
            header = True
        elif header and line.startswith(("--- a/", "+++ b/")):
            path = line[6:]
        elif hunk := HUNK.match(line):
            header, old, new = False, int(hunk[1]), int(hunk[2])
        elif not header and line.startswith("+"):
            added.append((path, new, line[1:]))
            new += 1
        elif not header and line.startswith("-"):
            removed.append((path, old, line[1:]))
            old += 1
    untracked = git("ls-files", "-z", "--others", "--exclude-standard")
    for name in filter(None, untracked.split("\0")):
        text = Path(name).read_text(encoding="utf-8", errors="ignore")
        added += [(name, n, t) for n, t in enumerate(text.splitlines(), 1)]
    return added, removed


def findings(added: list[Line], removed: list[Line]) -> list[Finding]:
    found: list[Finding] = []
    for path, n, text in added:
        if path.endswith(".md") or path in SELF:
            continue
        if SUPPRESSION.search(text):
            found.append(("suppression", path, f"{path}:{n}"))
        if SKIP.search(text):
            found.append(("disabled-test", path, f"{path}:{n}"))
        floor_ignored = FLOOR_TOOL.search(text) and IGNORED_FAILURE.search(text)
        if path in CONFIG and (RELAXED.search(text) or floor_ignored):
            found.append(("relaxed-config", path, f"{path}:{n}"))
    for path in sorted({p for p, _, _ in added if Path(p).name in OTHER_CONFIG}):
        found.append(("relaxed-config", path, f"{path}: config outside pyproject"))

    for path, n, text in removed:
        if path not in CONFIG:
            continue
        same_file = [t for p, _, t in added if p == path]
        if STRICT.search(text) and not any(STRICT.search(t) for t in same_file):
            found.append(("relaxed-config", path, f"{path}:{n} (removed)"))
        for tool in FLOOR_TOOL.findall(text):
            if not any(tool in t for t in same_file):
                found.append(("relaxed-config", path, f"{path}:{n} ({tool} removed)"))
        for new_text in same_file:
            same_shape = NUMBER.sub("#", new_text) == NUMBER.sub("#", text)
            same_shape = same_shape and not VERSION_SPEC.search(text)
            if same_shape and nums(new_text) < nums(text):
                found.append(("lowered-threshold", path, f"{path}:{n}"))

    balance: dict[str, int] = {}
    for sign, lines in ((1, added), (-1, removed)):
        for path, _, text in lines:
            if Path(path).name.startswith("test_") and TEST_OR_ASSERT.search(text):
                balance[path] = balance.get(path, 0) + sign
    found += [
        ("removed-tests", path, f"{path}: {-count} fewer tests or asserts")
        for path, count in balance.items()
        if count < 0
    ]
    return found


def nums(text: str) -> list[float]:
    return [float(n) for n in NUMBER.findall(text)]


def exceptions() -> list[tuple[str, str]]:
    """(rule, file glob) from CONSTRAINTS.md's exceptions table.

    The review date is a reminder for Piero and is not evaluated: once merged, the
    excepted line is already in the base branch and never shows up in a diff again.
    """
    path = Path("CONSTRAINTS.md")
    if not path.exists():
        return []
    rows = (EXCEPTION_ROW.match(line.strip()) for line in path.read_text().splitlines())
    return [(m[1], m[2]) for m in rows if m]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/develop")
    base = parser.parse_args(argv).base
    try:
        added, removed = changes(base)
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or f"no common history with {base}"
        print(
            f"floor-guard: could not run against {base}: {detail}\n"
            "Fetch the base branch with its history (`git fetch origin` or "
            "`git fetch --unshallow`); in CI, set `fetch-depth: 0` on the checkout.",
            file=sys.stderr,
        )
        return 2

    allowed = exceptions()
    blocking = []
    for rule, path, where in findings(added, removed):
        if any(rule == r and fnmatch(path, glob) for r, glob in allowed):
            print(f"floor-guard: approved exception [{rule}] {where}")
        else:
            blocking.append(f"  [{rule}] {where}")
    if not blocking:
        print("floor-guard: clean")
        return 0
    print(f"floor-guard: the bar dropped ({len(blocking)}):", file=sys.stderr)
    print("\n".join(blocking), file=sys.stderr)
    print("Fix the code or request an exception in CONSTRAINTS.md.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
