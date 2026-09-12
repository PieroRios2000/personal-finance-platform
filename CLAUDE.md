# CLAUDE.md

Reglas para agentes que trabajan en este repo. Si algo aquí choca con otro documento,
no elijas en silencio: pregunta a Piero.

## Qué es

Plataforma local de finanzas personales para un portafolio de Data Engineering: PDFs de
estados de cuenta (BCP y Scotiabank) → parser → bronze en Delta Lake → silver con dbt.
Todo open source, en local y a costo cero; los datos reales nunca salen de la máquina de Piero.

## Dónde está el contexto

Empieza por tu tarea en `tasks/todo.md` y lee solo lo que necesites:

| Necesitas | Lee |
|---|---|
| Cómo se relacionan conceptos, componentes y decisiones (ADR) | [brain/README.md](brain/README.md) |
| Plan de la fase, decisiones, riesgos, Definition of Done | [tasks/plan.md](tasks/plan.md) |
| Tu tarea: criterios, verificación, archivos, skill | [tasks/todo.md](tasks/todo.md) |
| Versiones, instalación y problemas conocidos | [SETUP.md](SETUP.md) |
| Reglas de calidad y umbrales | `CONSTRAINTS.md` (cuando exista, tarea T4) |
| Visión y fases del proyecto completo | [PROJECT.md](PROJECT.md) |

## Git y PRs

- `main` (producción) ← `develop` (integración) ← ramas `<tipo>/<nombre>` creadas desde
  `develop` (`feat/`, `fix/`, `test/`, `docs/`, `ci/`, `chore/`, `infra/`, `perf/`).
- **1 tarea = 1 rama = 1 PR hacia `develop`.** Nunca hagas commit directo en `main` ni en
  `develop`; a `main` solo llega `develop` (lo exige el check `branch-policy`).
- **Solo Piero aprueba y mergea.** Tú creas ramas, commits y PRs; nunca mergees, apruebes
  ni cierres un PR.
- Commits atómicos y pequeños, en inglés, con prefijo convencional (`feat:`, `fix:`,
  `test:`, `docs:`, `ci:`, `chore:`). Nunca uses `--no-verify`: los hooks deben pasar.
- **TDD en toda la lógica:** primero el commit con el test que falla, luego la implementación.
- El PR sigue `.github/pull_request_template.md` (Qué / Verificación / Notas + checklist),
  en español y con la salida real de los comandos que ejecutaste.
- Documentación en español (tuteo, neutro).

## Datos y privacidad

- **Los datos reales nunca van a Git ni al CI.** Los PDFs viven en
  `~/finance-data/raw/<usuario>/` y los secretos en `.env` (plantilla: `.env.example`).
  El CI usa PDFs sintéticos generados en los tests.
- **No leas, abras ni imprimas PDFs reales sin enmascarar ni el `.env`.** Para diseñar
  parsers usa solo el volcado enmascarado del inspector de T9, y solo después de que Piero
  lo haya revisado.
- gitleaks y el hook `forbid-data-files` son la red de seguridad, no el control: revisa tu diff.

## Herramientas

- Python 3.12 con uv: `uv sync --locked` y `uv run <comando>`.
- Librerías solo con `uv add <lib>` (o `uv add --dev <lib>`); nunca `pip install` ni
  `requirements.txt`. `pyproject.toml` y `uv.lock` se suben juntos.
- Checks: `uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest`
  y `pre-commit run --all-files` (`make check-task` cuando exista, T4).
- Skills por tipo de trabajo: las de "Forma de trabajo" en `tasks/plan.md`.
- Lo más simple que cumpla los criterios; nada especulativo.

## Definition of Done

La lista completa está en `tasks/plan.md` y en el template de PR. En corto:

- Criterios de la tarea cumplidos y sus casillas marcadas en `tasks/todo.md`.
- Checks en verde en local y en el CI; comportamiento verificado ejecutándolo, no solo con tests.
- Los tests nuevos fallan sin el cambio y pasan con él.
- Sin datos reales ni secretos en el diff.
- **Cerebro al día en cada PR:** la nota del componente o concepto que tocas,
  `brain/fases/fase-1.md` y un ADR en `brain/decisiones/` si tomaste una decisión.
- **`SETUP.md` al día** si agregas librerías, programas, versiones o variables de entorno.
- `ponytail-review` y `review` sin hallazgos pendientes antes de abrir el PR.

## Problemas conocidos

- `gh` 2.46: `gh pr edit` falla → `gh api --method PATCH repos/PieroRios2000/personal-finance-platform/pulls/<n> -f body=...`
- `gh` 2.46: `gh run view --log` y `--log-failed` salen vacíos →
  `gh api repos/PieroRios2000/personal-finance-platform/actions/jobs/<job_id>/logs`
- `git push` a veces falla con "Authentication failed" (Credential Manager de Windows):
  reintenta una vez y nunca imprimas credenciales.
- `uv` o `pre-commit` no se encuentran → `export PATH="$HOME/.local/bin:$PATH"`.
