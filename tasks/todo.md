# Tareas — Fase 1: Fundación

> Contexto, decisiones y riesgos en [`plan.md`](plan.md). Cada tarea = 1 rama desde `develop` = 1 PR.
> Toda tarea cumple además la **Definition of Done** de `plan.md`.

## Prerrequisitos del entorno (no generan PR)

- [x] Instalar `uv` a nivel usuario (sin sudo) y Python 3.12 gestionado por uv.
- [x] Docker accesible sin sudo desde WSL (reiniciar WSL tras entrar al grupo `docker`).
- [x] PDFs reales en `~/finance-data/raw/{bcp,scotiabank}/`, fuera del repo.
- [ ] Tesseract OCR (`sudo apt install tesseract-ocr tesseract-ocr-spa`) antes de T11b.

---

## Bloque A — Fundación del repo

### T1: Guardas de seguridad — `chore/security-guards`

**Descripción:** Antes de cualquier código, impedir que datos o secretos lleguen a Git.

**Criterios de aceptación:**
- [x] `*.pdf`, `.env`, `*.duckdb`, `data/` y el lake local están ignorados.
- [x] pre-commit con gitleaks (+ detect-private-key, check-added-large-files) instalado.
- [x] `.env.example` documenta las variables sin valores reales.

**Verificación:**
- [x] `git check-ignore -v x.pdf .env` confirma las reglas.
- [x] Un secreto falso de prueba es bloqueado por el hook (y se descarta).
- [x] `pre-commit run --all-files` en verde.

**Dependencias:** ninguna · **Archivos:** `.gitignore`, `.env.example`, `.pre-commit-config.yaml` · **Tamaño:** S · **Skill:** security-and-hardening

### T2: Proyecto Python — `chore/python-project`

**Descripción:** Proyecto con uv y Python 3.12, herramientas de calidad configuradas y un smoke test.

**Criterios de aceptación:**
- [x] `pyproject.toml` (requires-python 3.12, pydantic; dev: pytest, pytest-cov, ruff, mypy), `.python-version`, `uv.lock`.
- [x] Paquetes `ingestion/` y `lakehouse/` importables; ruff en pre-commit.
- [x] Config de ruff, mypy (strict) y pytest en `pyproject.toml`.

**Verificación:**
- [x] `uv sync` limpio; `uv run ruff check .`, `uv run mypy .`, `uv run pytest` en verde.

**Dependencias:** T1 · **Archivos:** `pyproject.toml`, `uv.lock`, `.python-version`, `ingestion/__init__.py`, `lakehouse/__init__.py`, `tests/test_smoke.py` · **Tamaño:** S

### T3a: Cerebro del proyecto — `docs/brain-vault`

**Descripción:** Vault Markdown enlazado que explica el contexto y cómo se relacionan conceptos, componentes, decisiones y fases.

**Criterios de aceptación:**
- [ ] `brain/README.md` con mapa Mermaid, índice y convención de notas (frontmatter `tipo`, `fase`, `relacionado` + links relativos).
- [ ] Plantillas en `brain/_plantillas/`; conceptos base (medallón, idempotencia, business key, reconciliación, dedup por archivo).
- [ ] ADR 0001–0004 en `brain/decisiones/` y `brain/fases/fase-1.md` enlazando este plan.

**Verificación:**
- [ ] Los links navegan en la vista de GitHub del PR y el Mermaid se renderiza.
- [ ] Ningún link roto (comprobación con script o lychee en local).

**Dependencias:** T2 · **Archivos:** `brain/**` · **Tamaño:** M (solo Markdown) · **Skill:** documentation-and-adrs

### T3b: Contexto para agentes y PRs — `docs/claude-md`

**Descripción:** CLAUDE.md que apunta al cerebro y a las reglas; template de PR; PROJECT.md al día con las decisiones.

**Criterios de aceptación:**
- [ ] `CLAUDE.md`: flujo de ramas, "solo Piero mergea", datos nunca en Git, leer `brain/` y `CONSTRAINTS.md`.
- [ ] `.github/pull_request_template.md` con checklist (DoD + nota del cerebro).
- [ ] `PROJECT.md` refleja bancos BCP/Scotiabank, almacenamiento S3 y stack de Fase 1.

**Verificación:**
- [ ] Un PR de prueba (el propio) muestra el template; CLAUDE.md se carga en una sesión nueva.

**Dependencias:** T3a · **Archivos:** `CLAUDE.md`, `.github/pull_request_template.md`, `PROJECT.md` · **Tamaño:** S · **Skill:** context-engineering

### T4: Nivel de calidad — `chore/constraints`

**Descripción:** CONSTRAINTS.md con reglas, números y razones, y los comandos que las verifican.

**Criterios de aceptación:**
- [ ] `CONSTRAINTS.md` con piso, tabla de reglas numéricas (comando + dónde corre), métricas medidas y excepciones.
- [ ] `Makefile` con `check-fast` (< 5 s), `check-task` (< 90 s) y `check-full` (CI).
- [ ] floor-guard adaptado y contratos de import-linter para `ingestion` / `lakehouse`.

**Verificación:**
- [ ] `make check-full` en verde sobre el código actual.
- [ ] floor-guard detecta un `# type: ignore` inyectado en un diff de prueba.

**Dependencias:** T2 · **Archivos:** `CONSTRAINTS.md`, `Makefile`, `scripts/floor_guard*`, `pyproject.toml` · **Tamaño:** M · **Skill:** constraint-driven-development

### T5: CI de calidad — `ci/quality-gates`

**Descripción:** Workflow que ejecuta las reglas en cada PR, con bloqueo o aviso según CONSTRAINTS.md.

**Criterios de aceptación:**
- [ ] Jobs: `lint-types`, `tests` (+ diff-cover), `security` (gitleaks, pip-audit, bandit), `architecture`, `floor-guard`.
- [ ] Reglas numéricas con `continue-on-error` hasta 2026-09-26; acciones fijadas por SHA y `sha_pinning_required` activado.
- [ ] Checks bloqueantes agregados como obligatorios en el ruleset `protect-main-develop`.

**Verificación:**
- [ ] Un PR con un error de ruff falla y queda `BLOCKED`; el mismo PR corregido pasa.

**Dependencias:** T4 · **Archivos:** `.github/workflows/ci.yml` · **Tamaño:** M · **Skill:** ci-cd-and-automation

### ✅ Checkpoint A
- [ ] CI en verde en `develop` · [ ] pre-commit funciona en local · [ ] cerebro navegable · [ ] revisión con Piero

---

## Bloque B — Ingesta

### T6: Esquema de transacciones — `feat/transaction-schema`

**Descripción:** Modelos pydantic comunes a todos los bancos.

**Criterios de aceptación:**
- [ ] `Transaction` (banco, cuenta últimos 4, fecha, descripción, monto `Decimal` a 2 decimales, moneda PEN/USD, sha del archivo).
- [ ] `Statement` (periodo, saldos inicial/final, totales declarados, transacciones).
- [ ] `normalize_description()` estable (trim, mayúsculas, sin códigos de relleno).

**Verificación:**
- [ ] Tests TDD: montos inválidos, moneda desconocida y cuenta completa son rechazados.

**Dependencias:** T5 · **Archivos:** `ingestion/schema.py`, `tests/test_schema.py` · **Tamaño:** S · **Skill:** test-driven-development

### T7: Hash de archivo — `feat/file-hash`

**Descripción:** SHA-256 del contenido del PDF para no reprocesar el mismo archivo.

**Criterios de aceptación:**
- [ ] `file_sha256(path)` con `hashlib.file_digest` (streaming, stdlib).
- [ ] Mismo contenido con otro nombre → mismo hash.

**Verificación:**
- [ ] Tests con archivos temporales.

**Dependencias:** T5 · **Archivos:** `ingestion/dedup.py`, `tests/test_dedup.py` · **Tamaño:** XS

### T8: Reconciliación — `feat/reconciliation`

**Descripción:** Verificar que lo extraído cuadra con lo que declara el PDF.

**Criterios de aceptación:**
- [ ] `reconcile(statement)`: saldo inicial + Σ montos == saldo final, y totales de cargos/abonos cuando existan.
- [ ] `ReconciliationError` con esperado, obtenido y diferencia.

**Verificación:**
- [ ] Tests: cuadre exacto, descuadre de 0.01, statement sin transacciones.

**Dependencias:** T6 · **Archivos:** `ingestion/reconciliation.py`, `tests/test_reconciliation.py` · **Tamaño:** S · **Skill:** test-driven-development

### T9: Inspector de layout enmascarado — `chore/pdf-layout-inspector`

**Descripción:** Script local que describe la estructura de un PDF sin exponer datos personales, para diseñar parsers y fixtures.

**Criterios de aceptación:**
- [ ] Abre PDFs con bytes antes de `%PDF-` (el de BCP empieza con `$BOP$`) y los desbloquea con la contraseña de `.env`; imprime por página líneas y columnas con posiciones.
- [ ] Dígitos → `9`; textos fuera de una lista de encabezados conocidos → enmascarados.
- [ ] Reporta si el PDF está cifrado y qué páginas no tienen capa de texto (escaneadas).

**Verificación:**
- [ ] Piero lo corre sobre un PDF real y confirma que la salida no contiene datos personales antes de compartirla.

**Dependencias:** T2 · **Archivos:** `scripts/inspect_pdf_layout.py`, `tests/test_inspect_pdf_layout.py` · **Tamaño:** S · **Skill:** security-and-hardening

### T10: Fixture sintético BCP — `test/bcp-synthetic-fixture`

**Descripción:** Generar en los tests un PDF falso con el layout de BCP (sin archivos binarios en Git).

**Criterios de aceptación:**
- [ ] Generador (fpdf2, dependencia dev) que produce un estado de cuenta BCP ficticio con totales coherentes.
- [ ] Fixture de pytest que lo crea en `tmp_path`.

**Verificación:**
- [ ] El volcado de T9 sobre el PDF sintético coincide estructuralmente con el del real.

**Dependencias:** T9 · **Archivos:** `tests/fixtures/synthetic_pdfs.py`, `tests/conftest.py` · **Tamaño:** S

### T11: Parser BCP — `feat/parser-bcp`

**Descripción:** Convertir un PDF de BCP en un `Statement` reconciliado.

**Criterios de aceptación:**
- [ ] `parsers/base.py` (protocolo `detect` + `parse`) y `parsers/bcp.py` con pdfplumber; desbloqueo con pikepdf.
- [ ] El parser sintético reconcilia; tests `real_pdf` (deseleccionados por defecto) reconcilian con tus PDFs.

**Verificación:**
- [ ] `uv run pytest` en verde; `uv run pytest -m real_pdf` en verde en tu máquina.

**Dependencias:** T6, T8, T10 · **Archivos:** `ingestion/parsers/{__init__,base,bcp}.py`, `tests/parsers/test_bcp.py` · **Tamaño:** M · **Skill:** test-driven-development

### T11b: OCR para páginas escaneadas — `feat/ocr-fallback`

**Descripción:** Algunos PDFs son escaneados; cuando una página no tiene capa de texto, obtenerlo con OCR.

**Criterios de aceptación:**
- [ ] `ingestion/ocr.py`: si `extract_text()` de una página viene vacío, se renderiza a 300 dpi (pdfplumber) y se lee con Tesseract en español.
- [ ] Los parsers reciben el texto sin saber si vino de OCR; la reconciliación detecta errores de lectura.
- [ ] El CI instala Tesseract y prueba con un PDF sintético rasterizado.

**Verificación:**
- [ ] `uv run pytest -m real_pdf` reconcilia el PDF escaneado real en tu máquina.

**Dependencias:** T9, T11 · **Archivos:** `ingestion/ocr.py`, `tests/test_ocr.py`, `.github/workflows/ci.yml` · **Tamaño:** M · **Skill:** source-driven-development

### T12: Dispatcher y CLI — `feat/dispatcher-cli`

**Descripción:** Detectar el banco de un PDF y exponer `pfp parse <pdf>`.

**Criterios de aceptación:**
- [ ] `dispatcher.py` elige el parser por `detect`; error claro si ningún parser lo reconoce.
- [ ] CLI con argparse (`[project.scripts] pfp`): imprime resumen y resultado de reconciliación.

**Verificación:**
- [ ] `uv run pfp parse <pdf real BCP>` muestra el resumen y "reconciliación OK".

**Dependencias:** T7, T11 · **Archivos:** `ingestion/dispatcher.py`, `ingestion/cli.py`, tests · **Tamaño:** S

### ✅ Checkpoint B
- [ ] Un PDF real de BCP se parsea y reconcilia en local · [ ] CI en verde · [ ] revisión con Piero

---

## Bloque C — Lakehouse

### T13: S3 local — `infra/s3-local`

**Descripción:** Levantar el almacenamiento S3 compatible con un solo comando.

**Criterios de aceptación:**
- [ ] `docker-compose.yml` con SeaweedFS (tag fijado), healthcheck y bucket `lakehouse` creado al iniciar.
- [ ] Credenciales solo desde `.env`; ADR 0003 actualizado con la configuración final.

**Verificación:**
- [ ] `docker compose up -d` → servicio `healthy`; escribir y leer un objeto de prueba.

**Dependencias:** T5 · **Archivos:** `docker-compose.yml`, `.env.example`, `Makefile` · **Tamaño:** S

### T14: Escritura bronze — `feat/bronze-writer`

**Descripción:** Guardar transacciones en Delta (append-only) y registrar archivos ingeridos; `pfp ingest`.

**Criterios de aceptación:**
- [ ] `lakehouse/` escribe `bronze/transactions` y `bronze/ingested_files` con `deltalake`, ubicación por `LAKEHOUSE_URI`.
- [ ] `pfp ingest <pdf>`: parsea → reconcilia → si el hash existe, lo salta → escribe bronze.
- [ ] Ingerir dos veces el mismo PDF no agrega filas.

**Verificación:**
- [ ] Tests con lake en `tmp_path`; test de integración (marker `integration`) contra el S3 local.

**Dependencias:** T12, T13 · **Archivos:** `lakehouse/{storage,bronze}.py`, `ingestion/cli.py`, tests · **Tamaño:** M · **Skill:** source-driven-development

### T15: Benchmarks — `perf/benchmarks`

**Descripción:** Medir parsing y escritura, y avisar si un PR los empeora.

**Criterios de aceptación:**
- [ ] Benchmarks de parsing (PDF sintético de N páginas) y append a bronze.
- [ ] Job de CI que compara base vs PR en el mismo runner (`--benchmark-compare-fail=mean:20%`), en modo aviso.
- [ ] Valores actuales anotados en CONSTRAINTS.md ("Medido").

**Verificación:**
- [ ] Un PR con un `sleep` artificial dispara el aviso (y se descarta).

**Dependencias:** T14 · **Archivos:** `tests/benchmarks/*`, `.github/workflows/ci.yml`, `CONSTRAINTS.md` · **Tamaño:** S · **Skill:** performance-optimization

### ✅ Checkpoint C
- [ ] `pfp ingest` real de punta a punta · [ ] reingestar no duplica · [ ] revisión con Piero

---

## Bloque D — Transformación

### T16: dbt silver — `feat/dbt-silver`

**Descripción:** Proyecto dbt-duckdb que lee bronze (Delta en S3) y produce silver con tests.

**Criterios de aceptación:**
- [ ] Prueba mínima de lectura `delta_scan` sobre el S3 local antes de modelar.
- [ ] Fuente `bronze.transactions`, modelo `silver/transactions` (tipos, descripción normalizada, moneda, cuenta).
- [ ] Tests dbt (not_null, accepted_values de moneda) y config de sqlfluff.

**Verificación:**
- [ ] `uv run dbt build` y `uv run sqlfluff lint dbt/models` en verde en local.

**Dependencias:** T14 · **Archivos:** `dbt/**`, `pyproject.toml` · **Tamaño:** M · **Skill:** source-driven-development

### T17: CI de dbt e integración — `ci/dbt-integration`

**Descripción:** En CI, levantar S3 local, ingerir el PDF sintético y correr dbt.

**Criterios de aceptación:**
- [ ] Job que inicia SeaweedFS, ejecuta `pfp ingest` con el fixture, `dbt build` y `sqlfluff lint`.
- [ ] Tests `integration` corren en este job.

**Verificación:**
- [ ] Job en verde; romper un test dbt a propósito lo pone en rojo (y se descarta).

**Dependencias:** T15, T16 · **Archivos:** `.github/workflows/ci.yml` · **Tamaño:** S · **Skill:** ci-cd-and-automation

### ✅ Checkpoint D
- [ ] `dbt build` en verde en local y en CI · [ ] revisión con Piero

---

## Bloque E — Segundo banco y cierre

### T18: Parser Scotiabank — `feat/parser-scotiabank`

**Descripción:** Segundo banco: valida que el diseño de parsers y dispatcher escala.

**Criterios de aceptación:**
- [ ] Layout enmascarado (T9), fixture sintético y `parsers/scotiabank.py` registrado en el dispatcher.
- [ ] Tests sintéticos en CI y `real_pdf` en local reconcilian.

**Verificación:**
- [ ] `uv run pfp ingest <pdf real Scotiabank>` escribe en bronze y `dbt build` lo incluye en silver.

**Dependencias:** T11b, T12, T14 · **Archivos:** `ingestion/parsers/scotiabank.py`, `tests/fixtures/…`, `tests/parsers/test_scotiabank.py` · **Tamaño:** M · **Skill:** test-driven-development

### T19: Cierre de fase — `docs/phase-1-close`

**Descripción:** Dejar la fase presentable y activar el bloqueo de las reglas numéricas.

**Criterios de aceptación:**
- [ ] README: qué es, diagrama, cómo correrlo, equivalencia Azure ↔ open source.
- [ ] Cerebro al día (fase-1 cerrada, mapa Mermaid, componentes).
- [ ] Reglas numéricas pasan a bloquear (si ya pasó 2026-09-26).

**Verificación:**
- [ ] Clonar el repo en una carpeta limpia y seguir el README hasta `dbt build` sin pasos faltantes.

**Dependencias:** T17, T18 · **Archivos:** `README.md`, `brain/**`, `.github/workflows/ci.yml` · **Tamaño:** S

### ✅ Checkpoint final
- [ ] Todos los criterios cumplidos · [ ] PR de release `develop → main` "Fase 1 — Fundación" · [ ] merge por Piero
