# Plan de implementación — Fase 1: Fundación

> Especificación maestra: [`PROJECT.md`](../PROJECT.md). Tareas detalladas: [`tasks/todo.md`](todo.md).
> Estado: **aprobado** (PR #6); los cambios posteriores entran por PR.

## Resumen

La Fase 1 deja una plataforma que se puede correr en local de punta a punta:
un PDF de estado de cuenta (BCP o Scotiabank) se parsea al esquema `Transaction`,
se reconcilia contra los totales que declara el propio PDF, se descarta si ya fue
ingerido (hash SHA-256) y se escribe en la capa **bronze** (Delta Lake sobre S3 local).
dbt transforma bronze → **silver** con tests. El CI valida calidad, seguridad,
rendimiento y arquitectura en cada PR, y el **cerebro** (`brain/`) documenta
el contexto y cómo se relaciona cada pieza.

**Resultado verificable al cerrar la fase:**

```bash
docker compose up -d                  # S3 local
uv run pfp ingest ~/finance-data/raw/bcp/2026-08.pdf   # → bronze
uv run pfp ingest ~/finance-data/raw/bcp/2026-08.pdf   # → "ya ingerido", 0 filas nuevas
uv run dbt build --project-dir dbt    # → silver + tests en verde
```

## Cambios respecto a PROJECT.md

| PROJECT.md | Este plan | Motivo |
|---|---|---|
| Bancos BCP, BBVA, Interbank | **BCP y Scotiabank** | Decisión de Piero (2026-09-12) |
| MinIO | **SeaweedFS** (aprobado 2026-09-12) | MinIO Community dejó de publicar imágenes (oct-2025), entró en mantenimiento (dic-2025) y su repo está archivado (2026): sin parches de seguridad |
| Postgres / DuckDB | Solo **DuckDB** embebido | Un servicio menos; DuckDB cubre la Fase 1 |
| PySpark / DuckDB / Polars | **DuckDB + delta-rs** en Fase 1; Spark cuando haya un motivo medible | 7 GB de RAM en WSL; evitar tres motores para el mismo trabajo |
| PyMuPDF, pytesseract | **pytesseract** para páginas escaneadas (T11b); sin PyMuPDF | Hay PDFs escaneados; pdfplumber ya renderiza páginas a imagen para el OCR |

`PROJECT.md` se actualiza con estos cambios en la tarea T3b.

## Decisiones de arquitectura

Cada decisión se registra como ADR en `brain/decisiones/` en la tarea donde se toma.

| ADR | Decisión | Por qué |
|---|---|---|
| 0001 | Python **3.12** gestionado con **uv** (`pyproject.toml` + `uv.lock`) | El 3.14 del sistema es muy nuevo para parte del stack (dbt lo soporta hace poco y con caveats de dependencias; herramientas de fases 2–3 suelen ir detrás). uv instala Python sin sudo y fija versiones con lockfile |
| 0002 | **DuckDB + delta-rs** (`deltalake`) antes que Spark | Mismo formato Delta, sin JVM ni cluster; Spark entra cuando el volumen o la demo lo justifiquen |
| 0003 | S3 local con **SeaweedFS** en vez de MinIO | Mantenido, Apache 2.0, API S3 estándar: cambiar de servidor es cambiar un endpoint |
| 0004 | **Los PDFs reales nunca salen de tu máquina** | El CI usa PDFs sintéticos generados en los tests; los parsers se diseñan con un volcado de layout enmascarado |
| 0005 | `Transaction` con `Decimal` y cuenta enmascarada (últimos 4 dígitos) | Sin errores de coma flotante en montos; mínimo dato personal almacenado |
| 0006 | Ubicación del lake por URI (`LAKEHOUSE_URI`) | `s3://…` en local/CI de integración, ruta de disco en tests unitarios |
| 0007 | **Entornos efímeros por PR**: el mismo `docker-compose.yml` en local y en CI, con nombre de proyecto único, datos sintéticos y destrucción siempre al final | Probar cada mejora sobre la plataforma real sin servidores fijos ni costo, y ver su efecto en los datos (base vs PR), no solo si los tests pasan |

## Estructura al cerrar la Fase 1

```
.
├── .github/
│   ├── workflows/{branch-policy,ci}.yml
│   └── pull_request_template.md
├── brain/                    # cerebro: conceptos, componentes, decisiones, fases
├── dbt/                      # proyecto dbt (bronze → silver)
├── ingestion/
│   ├── schema.py  dedup.py  reconciliation.py  dispatcher.py  cli.py
│   └── parsers/{base,bcp,scotiabank}.py
├── lakehouse/                # escritura Delta + registro de archivos ingeridos
├── scripts/                  # inspect_pdf_layout.py, floor_guard, data_diff.py
├── tests/                    # unit, fixtures sintéticas, benchmarks, integración
├── tasks/{plan,todo}.md
├── CLAUDE.md  CONSTRAINTS.md  Makefile  PROJECT.md  README.md
├── docker-compose.yml  pyproject.toml  uv.lock  .python-version
└── .gitignore  .env.example  .pre-commit-config.yaml
```

## Forma de trabajo

- **1 tarea = 1 rama desde `develop` = 1 PR hacia `develop`.** Ramas `<tipo>/<nombre>`
  (`feat/`, `fix/`, `test/`, `docs/`, `ci/`, `chore/`, `infra/`, `perf/`).
- **Commits atómicos** con prefijo convencional (`feat:`, `test:`, `docs:`…); en tareas
  con lógica, primero el commit del test que falla y luego la implementación.
- **Cada PR actualiza el cerebro**: la nota del componente o concepto que toca y
  `brain/fases/fase-1.md`. El template de PR lo recuerda.
- **Solo Piero aprueba y mergea.** Claude crea ramas, commits y PRs; nunca mergea.
- **Skills por tipo de trabajo:** `test-driven-development` en toda la lógica,
  `source-driven-development` para deltalake / dbt-duckdb / DuckDB-S3,
  `security-and-hardening` en PDFs y secretos, `performance-optimization` en benchmarks,
  `documentation-and-adrs` en el cerebro, y `ponytail-review` + `review` antes de abrir cada PR.
- **Release de fase:** al cerrar, PR `develop → main` titulado "Fase 1 — Fundación".

## Calidad (se detalla en CONSTRAINTS.md, tarea T4)

| Regla | Herramienta | Modo |
|---|---|---|
| Mínimo: lint, formato, tipos, secretos, tests sin desactivar | ruff, mypy, gitleaks, floor-guard | **Bloquea** desde el día 1 |
| Cobertura ≥ 80 % en líneas nuevas | pytest-cov + diff-cover | Avisa hasta **2026-09-26**, luego bloquea |
| Seguridad: nada de severidad alta | pip-audit (dependencias), bandit (código) | Avisa hasta 2026-09-26, luego bloquea |
| Rendimiento: no empeorar > 20 % | pytest-benchmark (base vs PR en el mismo runner) | Avisa hasta 2026-09-26, luego bloquea |
| Arquitectura: quién puede importar a quién | import-linter | Avisa hasta 2026-09-26, luego bloquea |

## Definition of Done (para cada tarea)

- [ ] Criterios de aceptación de la tarea cumplidos.
- [ ] `make check-task` en verde en local y checks bloqueantes del CI en verde.
- [ ] Comportamiento verificado ejecutándolo, no solo con tests.
- [ ] Los tests nuevos fallan sin el cambio y pasan con él.
- [ ] Sin datos reales ni secretos en el diff.
- [ ] Nota del cerebro actualizada (y ADR si hubo una decisión).
- [ ] `SETUP.md` al día si la tarea añade librerías, programas, versiones o variables de entorno.
- [ ] `ponytail-review` y `review` sin hallazgos pendientes.
- [ ] PR revisado y mergeado por Piero.

## Tareas

Detalle, criterios y verificación de cada una en [`todo.md`](todo.md).

**Bloque A — Fundación del repo**
- T1 `chore/security-guards` — .gitignore, .env.example, pre-commit con gitleaks
- T2 `chore/python-project` — pyproject + uv + ruff/mypy/pytest + smoke test
- T3a `docs/brain-vault` — cerebro: estructura, mapa, conceptos, ADR 0001–0004
- T3b `docs/claude-md` — CLAUDE.md, template de PR, PROJECT.md actualizado
- T4 `chore/constraints` — CONSTRAINTS.md, Makefile de checks, floor-guard, import-linter
- T5 `ci/quality-gates` — workflow de CI + checks obligatorios en el ruleset
- ✅ **Checkpoint A** — CI en verde en `develop`, cerebro navegable en GitHub

**Bloque B — Ingesta**
- T6 `feat/transaction-schema` — modelos `Transaction` / `Statement` + normalización
- T7 `feat/file-hash` — SHA-256 del archivo (dedup nivel archivo)
- T8 `feat/reconciliation` — cuadre contra saldos y totales declarados
- T9 `chore/pdf-layout-inspector` — volcado enmascarado del layout de un PDF
- T10 `test/bcp-synthetic-fixture` — generador de PDF sintético estilo BCP
- T11 `feat/parser-bcp` — parser BCP + desbloqueo con contraseña
- T11b `feat/ocr-fallback` — OCR con Tesseract para páginas escaneadas
- T12 `feat/dispatcher-cli` — detección de banco + CLI `pfp parse`
- ✅ **Checkpoint B** — un PDF real de BCP se parsea y reconcilia en local

**Bloque C — Lakehouse**
- T13 `infra/s3-local` — docker-compose con SeaweedFS + bucket, aislable por proyecto (`make poc-up` / `poc-down`)
- T14 `feat/bronze-writer` — bronze en Delta + registro de archivos + `pfp ingest`
- T15 `perf/benchmarks` — benchmarks de parsing y escritura + job de CI
- ✅ **Checkpoint C** — `pfp ingest` de punta a punta; reingestar no duplica

**Bloque D — Transformación**
- T16 `feat/dbt-silver` — proyecto dbt-duckdb, fuente bronze, modelo silver + tests
- T17 `ci/ephemeral-integration` — entorno efímero en CI: compose por PR + ingesta sintética + `dbt build` + sqlfluff + destrucción; `make poc` en local
- T17b `ci/pr-data-diff` — comparación base vs PR de los datos, publicada en el resumen del job
- ✅ **Checkpoint D** — `dbt build` en verde en local y en CI; cada PR muestra su efecto en los datos

**Bloque E — Segundo banco y cierre**
- T18 `feat/parser-scotiabank` — fixture + parser Scotiabank
- T19 `docs/phase-1-close` — README, cerebro al día, activar bloqueo de reglas numéricas
- ✅ **Checkpoint final** → PR de release `develop → main`

## Entornos efímeros (ADR 0007)

Cada PR que toque datos se prueba en una plataforma temporal que se crea, se usa y se destruye:

1. **Levantar** — `docker compose -p pfp-pr-<n> up -d --wait` (en local: `make poc-up`).
   El nombre de proyecto aísla contenedores, redes y volúmenes.
2. **Ejecutar** — ingesta y transformación con datos **sintéticos** en CI; con tus PDFs
   **reales solo en local** (`make poc`), mostrando únicamente pass/fail y diferencias de reconciliación.
3. **Comparar** — la misma corrida con la rama base y con la del PR; las diferencias
   (filas por modelo, esquema, valores) se publican en el resumen del job.
4. **Destruir siempre** — `docker compose -p pfp-pr-<n> down -v`, también si algo falló (`if: always()`).

Estos jobs no usan secretos, así que funcionan igual para PRs desde forks. Los entornos en
la nube (Fase 4) solo corren en ramas del propio repo, se destruyen siempre y llevan expiración.

| Fase | Qué se prueba en el entorno efímero | Dónde se planifica |
|---|---|---|
| 1 | Ingesta sintética (reingestar no duplica) + `dbt build` + comparación base vs PR | T13, T17, T17b |
| 1 | Rendimiento base vs PR en el mismo runner | T15 |
| 2 | Pipeline completo en Dagster y sus checks | Plan de la Fase 2 |
| 3 | Entrenamiento con datos sintéticos (MLflow temporal) y métricas vs el modelo base | Plan de la Fase 3 |
| 3 y 5 | FastAPI y Streamlit en contenedores + pruebas de humo | Planes de las Fases 3 y 5 |
| 4 | `terraform plan` en cada PR; crear y destruir infraestructura real solo a pedido | Plan de la Fase 4 |

## Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Diseñar parsers con PDFs reales expone datos personales (lo que yo leo sale de tu máquina) | Alto | T9: volcado de layout con dígitos y textos enmascarados; nunca leo un PDF real sin enmascarar sin tu OK |
| El PDF sintético no refleja el real | Medio | Tests locales marcados `real_pdf` contra tus PDFs + la reconciliación como red de seguridad |
| MinIO sin mantenimiento | Alto | SeaweedFS (ADR 0003); API S3 estándar, cambio de servidor = cambio de endpoint |
| DuckDB leyendo Delta en S3 local (endpoint, path-style, SSL) | Medio | Prueba mínima al inicio de T16 antes de modelar |
| delta-rs sobre S3 sin locking | Bajo en Fase 1 (un solo escritor) | Documentado en ADR 0006; se revisa en Fase 2 con Dagster |
| PDFs con contraseña y al menos uno escaneado (confirmado) | Alto | pikepdf + contraseña en `.env`; T9 detecta páginas sin texto; OCR con Tesseract (T11b); la reconciliación detecta errores de lectura del OCR |
| Benchmarks ruidosos en CI | Medio | Base y PR en el mismo runner, margen 20 %, 2 semanas en modo aviso |
| Un entorno efímero queda vivo (contenedores, volúmenes) o alarga demasiado el CI | Bajo | Nombre de proyecto por PR, `down -v` con `if: always()` y `timeout-minutes` en el job; la verificación de T17 comprueba que no queda nada |
| 7 GB de RAM para Fase 2 (Spark + catálogo) | Medio | Se evalúa al planificar Fase 2 (`.wslconfig`, alternativas livianas) |
| `gh` 2.46 falla en `gh pr edit` | Bajo | Usar la API REST (`gh api`) |

## Decisiones confirmadas (2026-09-12)

1. **Almacenamiento S3:** SeaweedFS.
2. **Privacidad:** los parsers se diseñan con el volcado enmascarado de T9; Claude no lee PDFs reales sin enmascarar.
3. **PDFs:** tienen contraseña y al menos uno es escaneado → OCR entra en la Fase 1 (T11b).
4. **Ubicación:** `~/finance-data/raw/{bcp,scotiabank}/`, fuera del repo y con permisos solo para tu usuario.

## Preguntas abiertas

1. **Fecha para pasar de aviso a bloqueo:** propuesta 2026-09-26.
2. **Qué PDFs o páginas son escaneados:** lo responde el inspector de T9.
