# Plataforma de Datos de Finanzas Personales (End-to-End)

Proyecto personal de portafolio para demostrar competencias de **Data Lead / Data Engineer**: ingesta, modelado, orquestación, calidad y gobierno de datos, ML en producción e infraestructura como código — construido íntegramente con herramientas **open source** y ejecutable en local a costo cero.

> **Contexto de uso:** este documento es la especificación maestra del proyecto. Está pensado para desarrollarse con Claude Code, fase por fase. Cada fase es publicable en GitHub por sí sola y cierra un hueco técnico concreto.

---

## Objetivo

Ingerir estados de cuenta bancarios en PDF (BCP y Scotiabank), procesarlos y validarlos, modelarlos bajo arquitectura medallón, orquestar el flujo, correr modelos de ML encima y servirlos en un dashboard — replicando en open source lo que en entornos corporativos se hace con Azure Data Factory + ADLS + Synapse/Databricks.

**Equivalencia que demuestra el proyecto (para entrevistas):**

| Mundo Azure (trabajo) | Equivalente open source (este proyecto) |
|---|---|
| Azure Data Factory (orquestación) | Dagster |
| ADLS Gen2 / Blob (storage) | SeaweedFS (S3-compatible) |
| Delta/Parquet en el lake | Delta Lake sobre SeaweedFS |
| Synapse / Databricks (procesamiento) | DuckDB + delta-rs; Apache Spark (PySpark) cuando haya un motivo medible |
| Power BI | Streamlit + Power BI |

---

## Principios de diseño

1. **Los datos nunca tocan Git.** El repositorio contiene solo código. Los PDFs crudos y las tablas procesadas viven en SeaweedFS (S3 local). Cualquiera puede clonar el repo, levantar el stack y correrlo con *sus propios* PDFs.
2. **Todo open source y reproducible.** Un `docker compose up` levanta la plataforma completa.
3. **Idempotencia.** Subir el mismo reporte dos veces no duplica datos. Deduplicación en dos niveles (archivo y transacción).
4. **Reconciliación.** Cada PDF parseado se valida contra el saldo/total que el propio estado de cuenta declara.
5. **Costo cero en desarrollo.** Todo corre en local; la nube (Fase 4) es opcional y solo se despliega para demostración.

---

## Stack técnico

| Capa | Herramienta | Notas |
|---|---|---|
| Ingesta / parsing PDF | `pdfplumber`, `pikepdf`, `pytesseract` | `pikepdf` desbloquea PDFs con contraseña; `pytesseract` lee las páginas escaneadas (pdfplumber las renderiza a imagen, así que no hace falta PyMuPDF) |
| Validación de esquema | `pydantic` | Esquema `Transaction` común a todos los bancos |
| Storage / lakehouse | SeaweedFS + Delta Lake | Parquet + transacciones ACID + MERGE + time-travel. SeaweedFS reemplaza a MinIO, cuya edición Community quedó sin mantenimiento en 2025 |
| Procesamiento | DuckDB (embebido) + delta-rs | Fase 1 sin JVM ni cluster ni Postgres; Spark (PySpark) entra cuando el volumen o la demo den un motivo medible |
| Transformación | dbt | Medallón bronze/silver/gold; materialización `incremental` con estrategia `merge` |
| Orquestación | Dagster | (Alternativa: Airflow si se prioriza reconocimiento por ATS) |
| Calidad de datos | dbt tests + Great Expectations / Elementary | Tests de calidad y expectativas |
| Gobierno / linaje | OpenMetadata o DataHub | Catálogo y linaje |
| ML / MLOps | scikit-learn, MLflow, FastAPI, Evidently | Tracking, serving y monitoreo de drift |
| Serving | Streamlit (+ Power BI) | Dashboard y uploader de PDFs |
| Infra | Docker Compose, Terraform | IaC; cloud en free tier (Fase 4) |
| CI/CD | GitHub Actions | `dbt build`, tests y linters (`sqlfluff`, `ruff`) en cada PR; entorno efímero por PR y CI por impacto (solo corre lo caro si el cambio lo afecta) |
| Seguridad | `.gitignore` + `gitleaks` (pre-commit) | Red de seguridad para que datos/secretos nunca lleguen a Git |

---

## Arquitectura de datos

```
PDF (estado de cuenta)
   │
   ▼
[ Ingesta ]  detección de banco → parser específico → esquema Transaction (pydantic)
   │          + reconciliación (suma transacciones == total declarado en el PDF)
   │          + hash de archivo (SHA-256) para dedup a nivel archivo
   ▼
[ Bronze ]  Delta Lake sobre SeaweedFS — datos crudos parseados, append-only
   │
   ▼
[ Silver ]  dbt incremental + MERGE por business key (dedup a nivel transacción)
   │          descripción normalizada, tipos, moneda, cuenta
   ▼
[ Gold ]    dbt — modelo estrella: fact_transacciones + dims (fecha, categoría, cuenta)
   │
   ├──► [ ML / MLOps ]  categorización, pronóstico de gasto, detección de anomalías
   │
   └──► [ Serving ]  Streamlit dashboard + Power BI
```

Todo el flujo lo dispara y coordina **Dagster**; **CI/CD**, **IaC** y **gobierno** son la capa de plataforma transversal.

---

## Deduplicación (detalle clave del proyecto)

**Nivel archivo** — evita reprocesar el mismo PDF:
- SHA-256 del contenido del archivo.
- Registro de archivos ya ingeridos; si el hash existe, se salta.

**Nivel transacción** — evita duplicados entre PDFs *distintos* con movimientos solapados (ej. reporte de enero vs. reporte "últimos 60 días"):
- Se construye una **business key** determinística: `fecha + monto + descripción_normalizada + cuenta`.
- La descripción se normaliza (trim, uppercase, quitar códigos de relleno) para que la clave sea estable entre reportes.
- Se usa `MERGE` (upsert) en Delta / dbt incremental: inserta si es nueva, ignora si es idéntica, actualiza si cambió.

> Esta es la operación que Delta Lake hace nativa y que un conjunto de parquets sueltos no puede hacer. Es lenguaje de ingeniería de datos senior.

---

## Reconciliación (conecta con perfiles de migración)

Cada parser valida que la suma de las transacciones extraídas cuadre con el saldo/total que declara el propio estado de cuenta. Si no cuadra, el parser falla y reporta la discrepancia. Es la contraparte personal del *"reconciliation and validation methodologies"* que piden roles de migración de datos.

---

## Fases

### Fase 1 — Fundación
**Objetivo:** demostrar orden y buenas prácticas desde el primer commit.
- Estructura del repo, `docker-compose` (SeaweedFS como S3 local; DuckDB embebido, sin Postgres), `.gitignore` + `gitleaks`.
- Esquema `Transaction` (pydantic) y parsers de BCP y Scotiabank con `pdfplumber` + `pikepdf`; OCR con `pytesseract` para páginas escaneadas.
- Hash de archivo (dedup nivel archivo) + reconciliación básica.
- Capa bronze en Delta (delta-rs) sobre SeaweedFS.
- Proyecto dbt inicial (bronze → silver) con tests.
- GitHub Actions: `dbt build`, tests, `ruff`, `sqlfluff` en cada PR.

**Cierra:** modelado, calidad básica, CI/CD, seguridad de datos.

### Fase 2 — Orquestación + Gobierno
**Objetivo:** el hueco más importante para roles de liderazgo de datos.
- Dagster orquestando: ingesta → dbt → tests → refresh.
- MERGE incremental por business key (dedup nivel transacción) en silver.
- Modelo gold (estrella): `fact_transacciones` + dimensiones.
- Great Expectations / Elementary para calidad.
- Catálogo y linaje (OpenMetadata o DataHub).

**Cierra:** orquestación, gobierno de datos, deduplicación idempotente.

### Fase 3 — ML en producción
**Objetivo:** desplegar y monitorear, no solo entrenar.
- Categorización automática de transacciones (clasificación).
- Pronóstico de gasto mensual (series temporales).
- Detección de cargos anómalos.
- MLflow (tracking), FastAPI (serving), Evidently (drift).

**Cierra:** MLOps.

### Fase 4 — Cloud + IaC
**Objetivo:** el "nice to have" de cloud que aparece en las vacantes.
- Terraform para provisionar infra en AWS o GCP (free tier).
- Despliegue del stack; secretos en secrets manager (nunca hardcodeados).

**Cierra:** cloud, infraestructura como código.

### Fase 5 — Serving + Uploader
**Objetivo:** hacer el repo demostrable y operable.
- Dashboard en Streamlit sobre las tablas gold.
- Uploader mínimo (`st.file_uploader`) → guarda en SeaweedFS → dispara el pipeline.
- (Opcional) Conexión Power BI.

**Cierra:** entrega end-to-end, vitrina para reclutadores.

> **Nota de scope:** el uploader se mantiene en su versión mínima y funcional. Ninguna de las vacantes objetivo valora skills de frontend; el valor está en lo que ocurre *después* de que el archivo entra (parsing, reconciliación, MERGE, orquestación, ML).

---

## Estructura de repositorio sugerida

```
.
├── docker-compose.yml
├── .gitignore
├── .pre-commit-config.yaml        # gitleaks, ruff, sqlfluff
├── README.md
├── PROJECT.md                     # este documento
├── pyproject.toml
├── ingestion/
│   ├── schema.py                  # Transaction (pydantic)
│   ├── dispatcher.py              # detecta banco → rutea al parser
│   ├── reconciliation.py
│   ├── dedup.py                   # hash de archivo + business key
│   ├── ocr.py                     # pytesseract para páginas escaneadas
│   └── parsers/
│       ├── base.py
│       ├── bcp.py
│       └── scotiabank.py
├── lakehouse/                     # utilidades Delta / S3
├── dbt/
│   ├── models/
│   │   ├── bronze/
│   │   ├── silver/
│   │   └── gold/
│   └── tests/
├── orchestration/                 # Dagster (assets, jobs, schedules)
├── ml/
│   ├── categorization/
│   ├── forecasting/
│   ├── anomaly/
│   └── serving/                   # FastAPI
├── app/                           # Streamlit (dashboard + uploader)
├── infra/                         # Terraform
└── .github/workflows/             # CI/CD
```

---

## Cómo demostrarlo (para el CV / entrevista)

- Repo público con README claro, diagrama de arquitectura y GIF/screenshots del dashboard corriendo.
- Frase de entrevista: *"En el trabajo uso ADF + ADLS + Synapse; en mi proyecto repliqué esa arquitectura con Dagster + SeaweedFS (S3) + Delta + DuckDB, con cargas incrementales idempotentes y deduplicación por business key vía MERGE en Delta."*
- Cada fase = un hito con su propio PR y descripción, mostrando historia de commits limpia.
