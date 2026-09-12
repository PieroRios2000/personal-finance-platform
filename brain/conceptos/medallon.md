---
tipo: concepto
fase: 1
---

# Arquitectura medallón

Organizar el lake en capas de calidad creciente, donde cada capa se construye solo a partir de la
anterior. Así un error se corrige reprocesando desde la capa de abajo, sin volver a leer los PDFs.

| Capa | Qué contiene en este proyecto | Quién la escribe | Fase |
|---|---|---|---|
| **Bronze** | Transacciones tal como salen del parser, más el registro de archivos ingeridos. Solo se agrega (append-only) | `lakehouse/` con delta-rs | 1 |
| **Silver** | Transacciones limpias: tipos, descripción normalizada, moneda y cuenta, sin duplicados | dbt | 1 (dedup por MERGE en la 2) |
| **Gold** | Modelo estrella para análisis: `fact_transacciones` + dimensiones | dbt | 2 |

## Cómo se aplica aquí

Bronze guarda la versión "cruda pero validada": solo recibe estados de cuenta que pasaron la
[reconciliación](reconciliacion.md). Si mañana cambia una regla de normalización, silver se
reconstruye desde bronze sin tocar los PDFs, que además nunca salen de tu máquina.

## Relacionado

- [Idempotencia](idempotencia.md) — reprocesar una capa no debe duplicar datos.
- [Business key](business-key.md) — cómo silver reconoce la misma transacción en dos PDFs.
- [ADR 0002: DuckDB + delta-rs](../decisiones/0002-duckdb-y-delta-rs-antes-que-spark.md) — el formato Delta de las capas.
- [ADR 0004: PDFs reales](../decisiones/0004-pdfs-reales-no-salen-de-la-maquina.md) — por qué no se relee el PDF original.
- [Fase 1](../fases/fase-1.md)
