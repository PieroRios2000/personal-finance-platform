---
tipo: decision
fase: 1
estado: aceptada
fecha: 2026-09-12
---

# ADR 0002: DuckDB + delta-rs antes que Spark

## Contexto

PROJECT.md propone PySpark, DuckDB y Polars. En la Fase 1 el volumen es el de estados de cuenta
personales (miles de filas), WSL tiene 7 GB de RAM, y lo que el proyecto necesita del lake es el
formato Delta: transacciones ACID y MERGE para deduplicar.

## Decisión

- Escritura en Delta Lake con **delta-rs** (librería `deltalake`), sin JVM.
- Lectura y transformación con **DuckDB**: dbt-duckdb lee Delta desde el S3 local.
- Spark entra cuando haya un motivo medible (volumen o demostración), sobre las mismas tablas Delta.

## Alternativas consideradas

- **PySpark + delta-spark**: requiere JVM y bastante memoria; sobredimensionado para miles de filas
  en una laptop.
- **Polars**: sería un tercer motor para el mismo trabajo, sin nada que DuckDB no cubra aquí.
- **Parquet sueltos**: sin transacciones ni MERGE, la deduplicación por business key sería frágil.

## Consecuencias

- Stack liviano y rápido en local y en el CI.
- Como el formato es Delta, sumar Spark después no obliga a migrar datos.
- delta-rs sobre S3 no tiene locking entre escritores: en la Fase 1 hay un solo escritor; se
  documenta en el ADR 0006 (T14) y se revisa en la Fase 2 con Dagster.
- Leer Delta en el S3 local desde DuckDB exige configurar endpoint, path-style y SSL: T16 empieza con
  una prueba mínima antes de modelar.

## Relacionado

- [Arquitectura medallón](../conceptos/medallon.md) — las capas que se guardan en Delta.
- [Business key](../conceptos/business-key.md) — la deduplicación que necesita MERGE.
- [ADR 0003: SeaweedFS](0003-s3-local-con-seaweedfs.md) — dónde viven las tablas.
- [Fase 1](../fases/fase-1.md)
