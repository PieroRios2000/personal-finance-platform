---
tipo: decision
fase: 1
estado: aceptada
fecha: 2026-09-12
---

# ADR 0003: S3 local con SeaweedFS en vez de MinIO

## Contexto

El lake necesita un almacenamiento compatible con S3 en local, para trabajar igual que con un object
store en la nube. PROJECT.md proponía MinIO, pero MinIO Community dejó de publicar imágenes en octubre
de 2025, pasó a mantenimiento en diciembre de 2025 y su repositorio quedó archivado en 2026: ya no
recibe parches de seguridad.

## Decisión

SeaweedFS con su gateway S3 (licencia Apache 2.0), levantado con docker compose. La configuración
final (tag de la imagen, credenciales y bucket) se fija en T13, que actualiza este ADR.

## Alternativas consideradas

- **Seguir con MinIO Community**: la última imagen quedaría sin parches de seguridad.
- **Carpeta local sin S3**: se pierde la paridad con un object store y la configuración de endpoint
  que el pipeline necesitará en la nube.
- **Ceph (RADOS Gateway)**: completo, pero pesado para una laptop.

## Consecuencias

- El pipeline habla S3 estándar: cambiar de servidor (SeaweedFS, otro S3 local o la nube en la Fase 4)
  es cambiar el endpoint y las credenciales en `.env`.
- El mismo compose sirve para los entornos efímeros por PR, en local y en el CI (ADR 0007, T13).

## Relacionado

- [ADR 0002: DuckDB + delta-rs](0002-duckdb-y-delta-rs-antes-que-spark.md) — qué se guarda aquí.
- [Arquitectura medallón](../conceptos/medallon.md)
- [Fase 1](../fases/fase-1.md)
