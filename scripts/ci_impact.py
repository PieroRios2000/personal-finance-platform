"""ci-impact: which expensive CI jobs a change affects (T15, T17, ADR 0008).

Reads the changed paths, one per line, on stdin and writes the decisions as
GitHub Actions outputs — one per expensive job, plus how much of the dbt project
that job has to rebuild. In CI that's the whole `changes` job:

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


# What the ephemeral environment exercises (T17, ADR 0007): the code that runs
# inside it (`pfp ingest`, the bronze writer, the dbt project), the files that
# define the environment itself, and the job's own definition. It overlaps the
# list above on `ingestion/` and `lakehouse/` on purpose: these are two
# independent questions about the same diff, not two halves of one.
INTEGRATION_PATHS = (
    "ingestion/",
    "lakehouse/",
    "dbt/",
    ".github/",
    # The environment as it is brought up: the compose file CI runs directly,
    # and the Makefile, whose `poc` target runs the same flow locally.
    "docker-compose.yml",
    "Makefile",
    "pyproject.toml",
    "uv.lock",
)

# The `integration`-marked tests only ever run in this job. They don't live in a
# directory of their own (moving them would read as deleted tests to
# floor-guard), so the convention is the name, and every other test is left out:
# spinning up SeaweedFS to run a parser's unit test would be minutes spent to
# learn nothing.
_TESTS = "tests/"
_INTEGRATION_TEST_SUFFIX = "_integration.py"

# What the portal's end-to-end run exercises (T44, ADR 0040): the three services it
# brings up and everything they are built from, the ingestion code its uploads go
# through, the compose files that wire them, and the job's own definition. Its tests are
# the `_portal_e2e.py` ones, for the same reason as the suffix above.
PORTAL_PATHS = (
    "upload/",
    "dex/",
    "dex-register/",
    "ingestion/",
    "alerting/",
    "scripts/process_submissions.py",
    "scripts/review_uploads.py",
    "bi/docker-compose.yml",
    "docker-compose.yml",
    ".github/",
    "pyproject.toml",
    "uv.lock",
)
_PORTAL_TEST_SUFFIX = "_portal_e2e.py"

# The one trigger that can narrow the build. If a change touches the dbt project
# and nothing else this job cares about, dbt can rebuild just the modified models
# and their descendants, compared against a manifest parsed from the base branch.
# Anything else on the list can change what the *data* looks like without
# changing a single model, which no state comparison would see.
_DBT_PATHS = ("dbt/",)


def runs_benchmarks(changed_files: Iterable[str]) -> bool:
    """True if any of `changed_files` can affect what the benchmarks measure."""
    return any(path.startswith(BENCHMARK_PATHS) for path in changed_files)


def _affects_integration(path: str) -> bool:
    if path.startswith(_TESTS):
        return path.endswith(_INTEGRATION_TEST_SUFFIX)
    return path.startswith(INTEGRATION_PATHS)


def runs_integration(changed_files: Iterable[str]) -> bool:
    """True if any of `changed_files` can affect the ephemeral environment's run."""
    return any(_affects_integration(path) for path in changed_files)


def runs_portal(changed_files: Iterable[str]) -> bool:
    """True if any of `changed_files` can affect the portal's end-to-end run."""
    return any(
        path.endswith(_PORTAL_TEST_SUFFIX)
        if path.startswith(_TESTS)
        else path.startswith(PORTAL_PATHS)
        for path in changed_files
    )


def dbt_selection(changed_files: Iterable[str]) -> str:
    """What that job's `dbt build` should build: every model (`all`), or only
    what changed and whatever depends on it (`state:modified+`)."""
    affecting = [path for path in changed_files if _affects_integration(path)]
    if affecting and all(path.startswith(_DBT_PATHS) for path in affecting):
        return "state:modified+"
    return "all"


def main() -> int:
    changed = [line.strip() for line in sys.stdin if line.strip()]
    print(f"benchmarks={str(runs_benchmarks(changed)).lower()}")
    print(f"integration={str(runs_integration(changed)).lower()}")
    print(f"dbt_select={dbt_selection(changed)}")
    print(f"portal={str(runs_portal(changed)).lower()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
