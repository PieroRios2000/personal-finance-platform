"""floor-guard: falla si el diff contra la rama base baja el nivel de calidad.

Revisa las líneas agregadas y quitadas entre el merge-base con la rama base y el
árbol de trabajo (incluye archivos sin seguimiento). Se corre desde la raíz del repo:

    uv run python scripts/floor_guard.py [--base origin/develop]

Salida: 0 limpio, 1 el nivel bajó, 2 no se pudo correr. Las excepciones aprobadas
se leen de la tabla de excepciones de CONSTRAINTS.md. Nunca imprime el texto de la
línea (podría contener un secreto), solo la regla y la ubicación.
"""

import argparse
import re
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path

# Comentarios que apagan un check del nivel: ruff, mypy, bandit, cobertura, gitleaks.
SUPPRESSION = re.compile(
    r"#.*\b(noqa|type:\s*ignore|nosec|pragma:\s*no\s*cover)\b|gitleaks:allow"
)
SKIP = re.compile(r"\b(pytest|mark|unittest)\.(skip|xfail)")
TEST_OR_ASSERT = re.compile(r"\bdef test_|\bassert\b|pytest\.raises")
CONFIG = ("pyproject.toml", "Makefile", ".pre-commit-config.yaml")
# Archivos que pueden pisar la config de mypy, ruff, pytest o la cobertura.
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
# Checks del piso: no pueden desaparecer ni correr sin cortar ("-" o "|| true").
FLOOR_TOOL = re.compile(r"\b(ruff|mypy|pytest|floor_guard|gitleaks)\b")
IGNORED_FAILURE = re.compile(r"^\t-|\|\|\s*true")
NUMBER = re.compile(r"\d+(?:\.\d+)?")
VERSION_SPEC = re.compile(r"[<>=~!]=")  # "bandit>=1.9.4" es una versión, no un umbral
HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)")
# Diff con el mismo formato sin importar la config de git de quien lo corre
# (prefijos, rutas no ASCII, renames, diff externo).
DIFF = (
    *("-c", "core.quotePath=false", "diff", "--no-color", "--no-ext-diff"),
    *("--no-renames", "--src-prefix=a/", "--dst-prefix=b/", "--unified=0"),
)
EXCEPTION_ROW = re.compile(r"^\|\s*([\w-]+)\s*\|\s*`?([^|`]+?)`?\s*\|")
# Sus propios patrones y fixtures contienen los marcadores que busca.
SELF = ("scripts/floor_guard.py", "tests/test_floor_guard.py")

Line = tuple[str, int, str]  # (archivo, número de línea, texto)
Finding = tuple[str, str, str]  # (regla, archivo, ubicación)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout


def changes(base: str) -> tuple[list[Line], list[Line]]:
    """Líneas agregadas y quitadas desde el merge-base con `base`."""
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
            found.append(("supresion", path, f"{path}:{n}"))
        if SKIP.search(text):
            found.append(("test-desactivado", path, f"{path}:{n}"))
        floor_ignored = FLOOR_TOOL.search(text) and IGNORED_FAILURE.search(text)
        if path in CONFIG and (RELAXED.search(text) or floor_ignored):
            found.append(("config-relajada", path, f"{path}:{n}"))
    for path in sorted({p for p, _, _ in added if Path(p).name in OTHER_CONFIG}):
        found.append(("config-relajada", path, f"{path}: config fuera de pyproject"))

    for path, n, text in removed:
        if path not in CONFIG:
            continue
        same_file = [t for p, _, t in added if p == path]
        if STRICT.search(text) and not any(STRICT.search(t) for t in same_file):
            found.append(("config-relajada", path, f"{path}:{n} (quitada)"))
        for tool in FLOOR_TOOL.findall(text):
            if not any(tool in t for t in same_file):
                found.append(("config-relajada", path, f"{path}:{n} ({tool} quitado)"))
        for new_text in same_file:
            same_shape = NUMBER.sub("#", new_text) == NUMBER.sub("#", text)
            same_shape = same_shape and not VERSION_SPEC.search(text)
            if same_shape and nums(new_text) < nums(text):
                found.append(("umbral-rebajado", path, f"{path}:{n}"))

    balance: dict[str, int] = {}
    for sign, lines in ((1, added), (-1, removed)):
        for path, _, text in lines:
            if Path(path).name.startswith("test_") and TEST_OR_ASSERT.search(text):
                balance[path] = balance.get(path, 0) + sign
    found += [
        ("tests-quitados", path, f"{path}: {-count} tests o asserts menos")
        for path, count in balance.items()
        if count < 0
    ]
    return found


def nums(text: str) -> list[float]:
    return [float(n) for n in NUMBER.findall(text)]


def exceptions() -> list[tuple[str, str]]:
    """(regla, glob de archivo) de la tabla de excepciones de CONSTRAINTS.md.

    La fecha de revisión es un recordatorio para Piero y no se evalúa: una vez mergeada,
    la línea exceptuada ya está en la base y no vuelve a aparecer en el diff.
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
        print(f"floor-guard: no se pudo correr: {error.stderr}", file=sys.stderr)
        return 2

    allowed = exceptions()
    blocking = []
    for rule, path, where in findings(added, removed):
        if any(rule == r and fnmatch(path, glob) for r, glob in allowed):
            print(f"floor-guard: excepción aprobada [{rule}] {where}")
        else:
            blocking.append(f"  [{rule}] {where}")
    if not blocking:
        print("floor-guard: limpio")
        return 0
    print(f"floor-guard: el nivel bajó ({len(blocking)}):", file=sys.stderr)
    print("\n".join(blocking), file=sys.stderr)
    print("Corrige el código o pide una excepción en CONSTRAINTS.md.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
