---
tipo: componente
fase: 1
estado: construido
tarea: T2
---

# Proyecto Python

La base de todo el código: Python 3.12 gestionado por uv, dependencias fijadas y herramientas de calidad.

## Piezas

| Pieza | Qué hace |
|---|---|
| [`pyproject.toml`](../../pyproject.toml) | Dependencias directas (runtime: pydantic; dev: pytest, pytest-cov, ruff, mypy) y configuración de ruff, mypy estricto y pytest |
| [`uv.lock`](../../uv.lock) | Versión exacta y hash de cada librería, incluidas las indirectas |
| [`.python-version`](../../.python-version) | Fija Python 3.12 |
| `ingestion/`, `lakehouse/` | Paquetes del pipeline, vacíos hasta el Bloque B |
| [`tests/test_smoke.py`](../../tests/test_smoke.py) | Comprueba que los paquetes se importan |

Todavía no hay `build-system`: los tests encuentran los paquetes con `pythonpath = ["."]`. El
empaquetado llega en T12, con el comando `pfp`.

## Cómo se usa y cómo se verifica

Instalación completa en [SETUP.md](../../SETUP.md). Checks:
`uv run ruff check . && uv run mypy . && uv run pytest`.

## Relacionado

- [ADR 0001: Python 3.12 con uv](../decisiones/0001-python-312-con-uv.md) — por qué esta versión y esta herramienta.
- [Guardas de seguridad](guardas-de-seguridad.md) — comparten los hooks de pre-commit.
- [CI](ci.md) — ejecutará estos mismos checks en cada PR.
- [Fase 1](../fases/fase-1.md)
