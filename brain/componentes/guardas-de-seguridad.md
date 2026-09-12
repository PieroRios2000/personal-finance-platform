---
tipo: componente
fase: 1
estado: construido
tarea: T1
---

# Guardas de seguridad

Impiden que datos reales o secretos lleguen a Git, antes de que exista código que los maneje.

## Piezas

| Pieza | Qué hace |
|---|---|
| [`.gitignore`](../../.gitignore) | Ignora `.env`, claves, PDFs (sin distinguir mayúsculas), `data/`, bases DuckDB, Parquet y `_delta_log/` |
| [`.pre-commit-config.yaml`](../../.pre-commit-config.yaml) | Antes de cada commit: gitleaks y detect-private-key (secretos), check-added-large-files, `forbid-data-files` (bloquea PDF, DuckDB y Parquet aunque se use `git add -f`) y ruff |
| [`.env.example`](../../.env.example) | Plantilla de variables sin valores reales; los valores viven en `.env`, ignorado y con permisos 600 |

Las versiones de los hooks están fijadas a un SHA de commit, no a un tag que se pueda mover.

## Cómo se usa y cómo se verifica

`pre-commit run --all-files`. En T1 se probó que un token falso, una clave privada falsa y un PDF
forzado con `git add -f` quedan bloqueados. En el CI se vuelven obligatorios en T5.

## Relacionado

- [ADR 0004: PDFs reales](../decisiones/0004-pdfs-reales-no-salen-de-la-maquina.md) — la decisión que estas guardas hacen cumplir.
- [Proyecto Python](proyecto-python.md) — ruff corre en los mismos hooks.
- [CI](ci.md) — donde estos controles pasan a ser obligatorios.
- [Fase 1](../fases/fase-1.md)
