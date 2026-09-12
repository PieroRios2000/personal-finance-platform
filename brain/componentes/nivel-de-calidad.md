---
tipo: componente
fase: 1
estado: construido
tarea: T4
---

# Nivel de calidad

Deja por escrito qué significa "listo para mergear", con números y el comando que lo
comprueba, para que ni una persona ni un agente bajen el nivel sin que se note.

## Piezas

| Pieza | Qué hace |
|---|---|
| [`CONSTRAINTS.md`](../../CONSTRAINTS.md) | El contrato: piso, reglas numéricas (umbral, comando, dónde corre, aviso o bloqueo), métricas medidas y excepciones |
| [`Makefile`](../../Makefile) | `check-fast` (< 5 s), `check-task` (< 90 s) y `check-full` (lo que corre el CI salvo gitleaks, que va en pre-commit), todo con `uv run` |
| [`scripts/floor_guard.py`](../../scripts/floor_guard.py) | Revisa el diff contra la rama base y falla si el nivel bajó: supresiones nuevas, tests desactivados o borrados, config relajada, umbrales rebajados |
| [`tests/test_floor_guard.py`](../../tests/test_floor_guard.py) | Prueba cada movimiento que floor-guard debe detectar, en un repo de git temporal |
| [`pyproject.toml`](../../pyproject.toml) | Contratos de import-linter entre `ingestion` y `lakehouse` y la fuente de la cobertura |

## Cómo se usa y cómo se verifica

- Tras cada cambio: `make check-fast`. Al terminar una tarea: `make check-task` (es parte de
  la Definition of Done). Antes de abrir el PR: `make check-full`.
- Las reglas numéricas llevan `-` en el Makefile: muestran el fallo sin cortar la receta hasta
  el 2026-09-26; ese día se quita el `-` y pasan a bloquear.
- Si una regla no se puede cumplir, se pide una excepción en `CONSTRAINTS.md` (regla, archivo,
  razón, quién aprobó, fecha de revisión). floor-guard la respeta mientras la fila exista; la
  fecha es un recordatorio para revisarla.
- Verificación: las tres recetas en verde sobre el código actual, y un `# type: ignore`
  inyectado a propósito hace que floor-guard falle con código 1.

## Relacionado

- [Proyecto Python](../componentes/proyecto-python.md) — ruff, mypy y pytest que este nivel usa.
- [CI](../componentes/ci.md) — correrá `check-full` en cada PR (T5).
- [Fase 1](../fases/fase-1.md)
