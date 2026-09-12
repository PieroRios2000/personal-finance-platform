# Nivel de calidad

Qué tiene que cumplir un cambio para mergearse: cada regla con su número, el comando que la
comprueba, dónde corre y por qué. Léelo antes de escribir código. **Este archivo no se debilita
para que un cambio pase**: si una regla estorba, arregla el código o pide una excepción.

Última revisión: 2026-09-12, por Piero. Los comandos se agrupan en el [`Makefile`](Makefile);
si el Makefile y este archivo difieren, manda este archivo.

## Piso (bloquea desde el día 1)

| Regla | Comando | Dónde corre |
|---|---|---|
| Lint y formato sin errores | `uv run ruff check .` y `uv run ruff format --check .` | pre-commit, `make check-fast`, CI |
| Tipos: mypy estricto sin errores | `uv run mypy .` | `make check-fast`, CI |
| Sin secretos en el código | gitleaks (hook de pre-commit) | pre-commit, CI |
| Tests en verde, nunca desactivados ni debilitados | `uv run pytest` y `uv run python scripts/floor_guard.py --base origin/develop` | `make check-task`, CI |

[floor-guard](scripts/floor_guard.py) revisa el diff contra la rama base (commits, cambios sin
commitear y archivos nuevos) y sale con código 1 si encuentra alguna de estas reglas:

- `supresion`: un comentario nuevo que apaga un check: `# noqa`, `# type: ignore`, `# nosec`,
  `# pragma: no cover` o `gitleaks:allow`.
- `test-desactivado`: `pytest.mark.skip`, `skipif` o `xfail`, `pytest.skip()` o `unittest.skip`.
- `tests-quitados`: un `test_*.py` con menos tests o asserts que antes (borrarlo cuenta).
- `config-relajada`: en `pyproject.toml` o el `Makefile`, `strict = true` quitado o
  `strict = false`, o una clave nueva `ignore`, `extend-ignore`, `per-file-ignores`,
  `ignore_errors`, `ignore_missing_imports` o `disable_error_code`.
- `umbral-rebajado`: en esos mismos archivos, una línea igual a otra salvo por un número más
  bajo (por ejemplo `--fail-under=80` → `--fail-under=70`).

No revisa Markdown (la documentación puede nombrar estos marcadores) ni sus propios archivos
(sus patrones y tests los contienen). Sale con código 2 si no puede correr (por ejemplo, sin
`origin/develop`) e informa solo regla y ubicación, nunca el texto de la línea. Lo que no
detecta (subir el 20 % de rendimiento, mover la fecha de bloqueo o agregar un `ignore_imports`
a los contratos) cambia este archivo o `pyproject.toml`, y Piero lo revisa en el PR.

## Reglas numéricas

Avisan hasta el **2026-09-26** y bloquean desde ese día: dos semanas para calibrar los números
sin frenar el trabajo. En modo aviso la línea lleva `-` en el `Makefile` (muestra el fallo sin
cortar la receta) y `continue-on-error` en el CI (T5). El 2026-09-26 se quitan ambos.

| Regla | Umbral | Comando | Dónde corre | Modo | Por qué |
|---|---|---|---|---|---|
| Cobertura de las líneas cambiadas | ≥ 80 % | `uv run pytest --cov --cov-report=xml` y luego `uv run diff-cover coverage.xml --compare-branch=origin/develop --fail-under=80` | `make check-full`, CI | Aviso hasta 2026-09-26, luego bloquea | Obliga a testear lo nuevo sin exigirlo para cada línea de configuración |
| Seguridad: dependencias | 0 vulnerabilidades conocidas | `uv run pip-audit` | `make check-full`, CI | Aviso hasta 2026-09-26, luego bloquea | pip-audit no filtra por severidad, así que es más estricto que "sin severidad alta": cualquier vulnerabilidad publicada falla. Si no hay versión arreglada, se pide una excepción (`--ignore-vuln <ID>`) |
| Seguridad: código | 0 hallazgos de severidad alta | `uv run bandit -q -r . -x ./.venv --severity-level high` | `make check-full`, CI | Aviso hasta 2026-09-26, luego bloquea | Por debajo de alta suele ser ruido (por ejemplo, `assert` en los tests) |
| Rendimiento | La media no empeora más de 20 % | pytest-benchmark con `--benchmark-compare-fail=mean:20%`, base contra PR en el mismo runner | CI (T15) | Aviso hasta 2026-09-26, luego bloquea | Deja margen para el ruido del runner. **Pendiente de medir en T15** |
| Arquitectura | 0 contratos rotos | `uv run lint-imports` | `make check-task`, CI | Aviso hasta 2026-09-26, luego bloquea | Ver "Contratos de arquitectura" |

### Contratos de arquitectura

Están en `pyproject.toml` (`[tool.importlinter]`):

1. **El parsing no importa `lakehouse`.** Ningún módulo de `ingestion` puede importar
   `lakehouse`, salvo `ingestion.cli`, que orquesta "parsear → escribir en bronze". Así los
   parsers se prueban solos, sin S3 ni Delta, y un banco nuevo no toca el almacenamiento.
2. **`lakehouse` solo depende del esquema.** No puede importar nada de `ingestion` salvo
   `ingestion.schema`. El lakehouse escribe transacciones ya validadas; si importara un parser,
   un cambio de layout de un banco podría romper la escritura.

Por qué tienen esta forma (probado con import-linter 2.15):

- Prohibir submódulos que aún no existen, como `ingestion.parsers`, pasa en silencio: un typo
  o un módulo nuevo que nadie agregó a la lista quedaría sin vigilar. Por eso cada contrato
  prohíbe el paquete entero (existe hoy) y los módulos nuevos quedan cubiertos solos.
- La única dependencia permitida va en `ignore_imports`. Si esa importación no existe,
  import-linter falla por defecto ("No matches for ignored import"), y hoy `ingestion.cli` e
  `ingestion.schema` todavía no existen. Con `unmatched_ignore_imports_alerting = "warn"` solo
  avisa. El aviso desaparece cuando T14 crea esas importaciones, y vuelve si algún día
  desaparecen, indicando que la excepción sobra.
- Comprobado en una copia con el layout futuro: `ingestion.parsers.bcp → lakehouse.bronze` y
  `lakehouse.bronze → ingestion.parsers.bcp` rompen los contratos; `ingestion.cli →
  lakehouse.bronze` y `lakehouse.bronze → ingestion.schema` los cumplen.

## Checks

| Receta | Qué corre | Presupuesto | Por qué |
|---|---|---|---|
| `make check-fast` | ruff check, ruff format --check, mypy | < 5 s | Se corre tras cada cambio; si tarda más, se deja de correr |
| `make check-task` | check-fast + pytest con cobertura + floor-guard + import-linter | < 90 s | Al terminar una tarea (Definition of Done) |
| `make check-full` | check-task + pip-audit + bandit + diff-cover contra `origin/develop` | Sin límite | Lo que corre el CI; pip-audit necesita red |

`BASE` cambia la rama de comparación: `make check-full BASE=origin/main`.

## Medido (2026-09-12, sobre el código actual)

| Métrica | Hoy | Nota |
|---|---|---|
| Cobertura del proyecto (`ingestion`, `lakehouse`, `scripts`) | 98 % (167 sentencias, 3 sin cubrir) | Sin cubrir: los `sys.exit(main())` de los scripts y una rama del inspector de T9 |
| Cobertura de las líneas cambiadas (diff-cover) | 99 % | Sobre el diff de T4 |
| Duración de `make check-fast` | 0,6 s con la caché de mypy; 12,2 s la primera vez | La primera corrida (sin caché, mypy revisa también pdfplumber y pikepdf) pasa de 5 s |
| Duración de `make check-task` | 9,4 s | 34 tests |
| Duración de `make check-full` | 11,2 s | Incluye la consulta de pip-audit por red |
| pip-audit / bandit | 0 vulnerabilidades / 0 hallazgos altos | |
| Rendimiento de parsing y escritura | Pendiente de medir (T15) | |

## Excepciones

Si una regla no se puede cumplir por una razón real (por ejemplo, una librería sin tipos):

1. Agrega una fila a la tabla en el mismo PR: regla, archivo (acepta globs como `tests/*`),
   razón, quién aprobó y fecha de revisión, como máximo a 90 días.
2. Piero la aprueba al revisar el PR. Si no la aprueba, la fila se quita.
3. floor-guard lee esta tabla: no bloquea esa regla en ese archivo hasta la fecha de revisión
   y la muestra como "excepción aprobada" para que se vea. Pasada la fecha vuelve a bloquear:
   o se arregla el código o se renueva con una razón nueva.
4. En las reglas numéricas, la excepción se configura en la herramienta (por ejemplo,
   `--ignore-vuln <ID>` en pip-audit) y también se anota aquí.

La regla es una de las de floor-guard (`supresion`, `test-desactivado`, `tests-quitados`,
`config-relajada`, `umbral-rebajado`) o el nombre de una regla numérica.

| Regla | Archivo | Razón | Aprobó | Revisar el |
|---|---|---|---|---|

Ninguna por ahora.
