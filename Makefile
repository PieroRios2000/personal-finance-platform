# Checks del nivel de calidad. Las reglas, umbrales y razones están en CONSTRAINTS.md;
# si este archivo y CONSTRAINTS.md difieren, manda CONSTRAINTS.md.
# Las líneas con "-" son reglas en modo aviso hasta el 2026-09-26: muestran el fallo pero
# no cortan la receta. Ese día se quita el "-" y pasan a bloquear.

BASE ?= origin/develop

.PHONY: check-fast check-task check-full

# Tras cada cambio (< 5 s): lint, formato y tipos.
check-fast:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy .

# Al terminar una tarea (< 90 s): lo anterior + tests con cobertura, floor-guard y arquitectura.
check-task: check-fast
	uv run pytest --cov --cov-report=term-missing --cov-report=xml
	uv run python scripts/floor_guard.py --base $(BASE)
	-uv run lint-imports --no-logo

# Antes del PR: lo anterior + seguridad y cobertura de las líneas cambiadas. Es lo que corre
# el CI salvo gitleaks, que corre en pre-commit en cada commit (y en el CI desde T5).
check-full: check-task
	-uv run pip-audit
	-uv run bandit -q -r . -x ./.venv --severity-level high
	-uv run diff-cover coverage.xml --compare-branch=$(BASE) --fail-under=80
