"""ci-impact: which expensive CI jobs a change affects (T15, ADR 0008).

Reads the changed paths, one per line, on stdin and writes the decision as a
GitHub Actions output. In CI that's the whole `changes` job:

    git diff --name-only origin/<base>...HEAD \
        | python3 scripts/ci_impact.py >> "$GITHUB_OUTPUT"

Standard library only, and run with the runner's own `python3`: the `changes`
job has to answer before (and without) `uv sync`, which is most of what makes
skipping the expensive job worth it.

A push to `develop` and the weekly schedule never ask: they run everything, so
a relationship this map misses gets caught there (see the workflow, and ADR
0008's "Consequences").
"""

import sys
from collections.abc import Iterable

# What the benchmarks measure: the parsing and bronze-write code itself, the
# benchmarks' own code, and the things no map can see inside — the dependency
# set, the platform, and the pipeline definition (tasks/plan.md's impact table).
# Directory entries end in "/" so they only ever match a whole directory.
BENCHMARK_PATHS = (
    "ingestion/",
    "lakehouse/",
    "tests/benchmarks/",
    ".github/",
    "docker-compose.yml",
    "pyproject.toml",
    "uv.lock",
)


def runs_benchmarks(changed_files: Iterable[str]) -> bool:
    """True if any of `changed_files` can affect what the benchmarks measure."""
    return any(path.startswith(BENCHMARK_PATHS) for path in changed_files)


def main() -> int:
    changed = [line.strip() for line in sys.stdin if line.strip()]
    print(f"benchmarks={str(runs_benchmarks(changed)).lower()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
