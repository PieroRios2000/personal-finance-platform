import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

from scripts import floor_guard

BASE_FILES = {
    "tests/test_a.py": "def test_a() -> None:\n    assert 1 + 1 == 2\n",
    "tests/test_señal.py": "def test_s() -> None:\n    assert True\n",
    "app.py": "x = 1\n",
    "pyproject.toml": "[tool.mypy]\nstrict = true\n",
    "Makefile": "cov:\n\tuv run diff-cover coverage.xml --fail-under=80\n",
}


def git(*args: str) -> None:
    subprocess.run(["git", *args], check=True, capture_output=True)


def write(path: str, text: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text)


@pytest.fixture(autouse=True)
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Repo de git con una rama base `main` y la rama de trabajo `feature`."""
    monkeypatch.chdir(tmp_path)
    git("init", "-q", "-b", "main")
    for path, text in BASE_FILES.items():
        write(path, text)
    git("config", "user.name", "t")
    git("config", "user.email", "t@t")
    git("add", ".")
    git("commit", "-qm", "base", "--no-gpg-sign")
    git("switch", "-qc", "feature")


def run(capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = floor_guard.main(["--base", "main"])
    out = capsys.readouterr()
    return code, out.out + out.err


def test_clean_change_passes(capsys: pytest.CaptureFixture[str]) -> None:
    write("app.py", "x = 2\n")
    write("tests/test_b.py", "def test_b() -> None:\n    assert True\n")

    assert run(capsys) == (0, "floor-guard: limpio\n")


@pytest.mark.parametrize(
    "line",
    [
        "y = f()  # type: ignore",
        "import os  # noqa: F401",
        "run()  # nosec",
        "if debug:  # pragma: no cover",
        "@pytest.mark.skip",
        "@pytest.mark.xfail(reason='x')",
        "pytest.skip('luego')",
    ],
)
def test_new_suppression_or_skip_fails(
    line: str, capsys: pytest.CaptureFixture[str]
) -> None:
    write("app.py", f"x = 1\n{line}\n")

    code, out = run(capsys)

    assert code == 1
    assert "app.py" in out


def test_untracked_file_is_checked(capsys: pytest.CaptureFixture[str]) -> None:
    write("new.py", "y = f()  # type: ignore\n")

    code, out = run(capsys)

    assert code == 1
    assert "new.py" in out


def test_markdown_may_mention_markers(capsys: pytest.CaptureFixture[str]) -> None:
    write("NOTES.md", "No uses `# type: ignore` ni `@pytest.mark.skip`.\n")

    assert run(capsys)[0] == 0


def test_deleted_test_file_fails(capsys: pytest.CaptureFixture[str]) -> None:
    Path("tests/test_a.py").unlink()

    code, out = run(capsys)

    assert code == 1
    assert "tests/test_a.py" in out


@pytest.mark.parametrize("option", ["diff.mnemonicPrefix", "diff.noprefix"])
def test_diff_does_not_depend_on_git_config(
    option: str, capsys: pytest.CaptureFixture[str]
) -> None:
    git("config", option, "true")
    git("rm", "-q", "tests/test_a.py")

    code, out = run(capsys)

    assert code == 1
    assert "tests/test_a.py" in out


def test_non_ascii_path_is_reported(capsys: pytest.CaptureFixture[str]) -> None:
    git("rm", "-q", "tests/test_señal.py")

    code, out = run(capsys)

    assert code == 1
    assert "tests/test_señal.py" in out


def test_renamed_test_file_counts_as_removed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    git("mv", "tests/test_a.py", "tests/a_checks.py")
    git("commit", "-qm", "rename", "--no-gpg-sign")

    assert run(capsys)[0] == 1


def test_removed_assertion_fails(capsys: pytest.CaptureFixture[str]) -> None:
    write("tests/test_a.py", "def test_a() -> None:\n    pass\n")

    assert run(capsys)[0] == 1


def test_rewritten_assertion_passes(capsys: pytest.CaptureFixture[str]) -> None:
    write("tests/test_a.py", "def test_a() -> None:\n    assert 2 + 2 == 4\n")

    assert run(capsys)[0] == 0


@pytest.mark.parametrize(
    ("path", "text"),
    [
        ("Makefile", "cov:\n\tuv run diff-cover coverage.xml --fail-under=70\n"),
        ("pyproject.toml", "[tool.mypy]\nstrict = false\n"),
        ("pyproject.toml", "[tool.mypy]\n"),
        ("pyproject.toml", "[tool.mypy]\nstrict = true\nignore_errors = true\n"),
    ],
)
def test_weakened_config_fails(
    path: str, text: str, capsys: pytest.CaptureFixture[str]
) -> None:
    write(path, text)

    code, out = run(capsys)

    assert code == 1
    assert path in out


def test_raised_threshold_passes(capsys: pytest.CaptureFixture[str]) -> None:
    write("Makefile", "cov:\n\tuv run diff-cover coverage.xml --fail-under=90\n")

    assert run(capsys)[0] == 0


@pytest.mark.parametrize(("days", "expected"), [(30, 0), (-1, 1)])
def test_exception_applies_until_review_date(
    days: int, expected: int, capsys: pytest.CaptureFixture[str]
) -> None:
    review = date.today() + timedelta(days=days)
    write("app.py", "x = 1\ny = f()  # type: ignore\n")
    write(
        "CONSTRAINTS.md",
        "| Regla | Archivo | Razón | Aprobó | Revisar el |\n"
        "|---|---|---|---|---|\n"
        f"| supresion | `app.py` | librería sin tipos | Piero | {review} |\n",
    )

    code, out = run(capsys)

    assert code == expected
    if expected == 0:
        assert "excepción" in out


def test_guard_cannot_run_without_base(capsys: pytest.CaptureFixture[str]) -> None:
    assert floor_guard.main(["--base", "no-existe"]) == 2
