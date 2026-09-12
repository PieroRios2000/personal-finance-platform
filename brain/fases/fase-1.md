---
tipo: fase
fase: 1
---

# Fase 1 — Fundación

Un PDF de estado de cuenta (BCP o Scotiabank) se parsea, se reconcilia, se descarta si ya fue
ingerido y se escribe en bronze; dbt construye silver con tests, y el CI valida cada PR. Plan completo
en [tasks/plan.md](../../tasks/plan.md) y tareas en [tasks/todo.md](../../tasks/todo.md).

## Estado

| Bloque | Tareas | Estado |
|---|---|---|
| A — Fundación del repo | T1 guardas (#8) · T2 proyecto Python (#10) · T3a cerebro · T3b CLAUDE.md · T4 CONSTRAINTS · T5 CI de calidad | T1 y T2 hechas; T3a en curso |
| B — Ingesta | T6–T12 | Pendiente |
| C — Lakehouse | T13–T15 | Pendiente |
| D — Transformación | T16, T17, T17b | Pendiente |
| E — Segundo banco y cierre | T18, T19 | Pendiente |

También integrados: [SETUP.md](../../SETUP.md) con la reproducción del entorno (#10) y el plan de
entornos efímeros y CI por impacto (#12).

## Componentes

- [Guardas de seguridad](../componentes/guardas-de-seguridad.md) — construido (T1).
- [Proyecto Python](../componentes/proyecto-python.md) — construido (T2).
- [CI](../componentes/ci.md) — en curso: política de ramas hecha; calidad en T5.

## Decisiones

| ADR | Decisión | Nota |
|---|---|---|
| 0001 | Python 3.12 con uv | [ADR 0001](../decisiones/0001-python-312-con-uv.md) |
| 0002 | DuckDB + delta-rs antes que Spark | [ADR 0002](../decisiones/0002-duckdb-y-delta-rs-antes-que-spark.md) |
| 0003 | S3 local con SeaweedFS | [ADR 0003](../decisiones/0003-s3-local-con-seaweedfs.md) |
| 0004 | Los PDFs reales nunca salen de tu máquina | [ADR 0004](../decisiones/0004-pdfs-reales-no-salen-de-la-maquina.md) |
| 0005 | `Transaction` con `Decimal` y cuenta enmascarada | Se escribe en T6 |
| 0006 | Ubicación del lake por URI | Se escribe en T14 |
| 0007 | Entornos efímeros por PR | Se escribe en T13 |
| 0008 | CI por impacto | Se escribe en T15 |

## Conceptos

- [Arquitectura medallón](../conceptos/medallon.md)
- [Idempotencia](../conceptos/idempotencia.md)
- [Business key](../conceptos/business-key.md)
- [Reconciliación](../conceptos/reconciliacion.md)
- [Dedup por archivo](../conceptos/dedup-por-archivo.md)
