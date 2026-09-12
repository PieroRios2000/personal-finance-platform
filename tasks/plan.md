# Plan de implementación — Fase 1: Fundación

> Especificación maestra: [`PROJECT.md`](../PROJECT.md). Tareas detalladas: [`tasks/todo.md`](todo.md).
> Estado: **borrador pendiente de aprobación** (PR `docs/phase-1-plan`).

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
| MinIO | **SeaweedFS** *(pendiente de aprobación)* | MinIO Community dejó de publicar imágenes (oct-2025), entró en mantenimiento (dic-2025) y su repo está archivado (2026): sin parches de seguridad |
| Postgres / DuckDB | Solo **DuckDB** embebido | Un servicio menos; DuckDB cubre la Fase 1 |
| PySpark / DuckDB / Polars | **DuckDB + delta-rs** en Fase 1; Spark cuando haya un motivo medible | 7 GB de RAM en WSL; evitar tres motores para el mismo trabajo |
| PyMuPDF, pytesseract | Solo si un PDF real lo exige | `pdfplumber` + `pikepdf` cubren PDFs de texto con contraseña |

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
├── scripts/                  # inspect_pdf_layout.py, floor_guard
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
- T12 `feat/dispatcher-cli` — detección de banco + CLI `pfp parse`
- ✅ **Checkpoint B** — un PDF real de BCP se parsea y reconcilia en local

**Bloque C — Lakehouse**
- T13 `infra/s3-local` — docker-compose con SeaweedFS + bucket
- T14 `feat/bronze-writer` — bronze en Delta + registro de archivos + `pfp ingest`
- T15 `perf/benchmarks` — benchmarks de parsing y escritura + job de CI
- ✅ **Checkpoint C** — `pfp ingest` de punta a punta; reingestar no duplica

**Bloque D — Transformación**
- T16 `feat/dbt-silver` — proyecto dbt-duckdb, fuente bronze, modelo silver + tests
- T17 `ci/dbt-integration` — job de CI: S3 local + ingesta sintética + `dbt build` + sqlfluff
- ✅ **Checkpoint D** — `dbt build` en verde en local y en CI

**Bloque E — Segundo banco y cierre**
- T18 `feat/parser-scotiabank` — fixture + parser Scotiabank
- T19 `docs/phase-1-close` — README, cerebro al día, activar bloqueo de reglas numéricas
- ✅ **Checkpoint final** → PR de release `develop → main`

## Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Diseñar parsers con PDFs reales expone datos personales (lo que yo leo sale de tu máquina) | Alto | T9: volcado de layout con dígitos y textos enmascarados; nunca leo un PDF real sin enmascarar sin tu OK |
| El PDF sintético no refleja el real | Medio | Tests locales marcados `real_pdf` contra tus PDFs + la reconciliación como red de seguridad |
| MinIO sin mantenimiento | Alto | SeaweedFS (ADR 0003); API S3 estándar, cambio de servidor = cambio de endpoint |
| DuckDB leyendo Delta en S3 local (endpoint, path-style, SSL) | Medio | Prueba mínima al inicio de T16 antes de modelar |
| delta-rs sobre S3 sin locking | Bajo en Fase 1 (un solo escritor) | Documentado en ADR 0006; se revisa en Fase 2 con Dagster |
| PDFs con contraseña o escaneados | Medio | pikepdf + contraseña en `.env`; OCR solo si aparece un escaneo |
| Benchmarks ruidosos en CI | Medio | Base y PR en el mismo runner, margen 20 %, 2 semanas en modo aviso |
| 7 GB de RAM para Fase 2 (Spark + catálogo) | Medio | Se evalúa al planificar Fase 2 (`.wslconfig`, alternativas livianas) |
| `gh` 2.46 falla en `gh pr edit` | Bajo | Usar la API REST (`gh api`) |

## Preguntas abiertas

1. **Almacenamiento S3:** ¿apruebas SeaweedFS? Alternativas: RustFS (reemplazo directo de MinIO, más nuevo) o fijar la última imagen de MinIO (sin parches).
2. **Privacidad:** ¿de acuerdo con diseñar los parsers a partir de un volcado enmascarado (T9) en lugar de que yo lea tus PDFs reales?
3. **PDFs:** ¿tienen contraseña? ¿Alguno es escaneado (imagen) en vez de texto?
4. **Ubicación de los PDFs reales:** propuesta `~/finance-data/raw/{bcp,scotiabank}/`, fuera del repo.
5. **Fecha para pasar de aviso a bloqueo:** propuesta 2026-09-26.
