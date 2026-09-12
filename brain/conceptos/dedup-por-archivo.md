---
tipo: concepto
fase: 1
---

# Deduplicación por archivo

Reconocer un PDF ya ingerido por su contenido, no por su nombre.

## Cómo se aplica aquí

- `file_sha256(path)` calcula el SHA-256 del contenido con `hashlib.file_digest` (T7).
- `bronze/ingested_files` registra cada par (usuario, hash) ingerido, y `pfp ingest` salta un archivo
  que ese usuario ya ingirió (T14). El nombre del archivo no se guarda: puede contener números de cuenta.
- En la bandeja de entrada (T12b), un archivo repetido se mueve a `_duplicados/` en vez de archivarse otra vez.
- El mismo PDF con otro nombre tiene el mismo hash, así que también se salta.

## Límite

Si el banco vuelve a generar el PDF (por ejemplo, con otra fecha de emisión), los bytes cambian y el
hash también, aunque los movimientos sean los mismos. Ese caso lo cubre el segundo nivel: la
[business key](business-key.md).

## Relacionado

- [Idempotencia](idempotencia.md) — este es su primer nivel.
- [Business key](business-key.md) — el nivel que cubre los PDFs regenerados.
- [Arquitectura medallón](medallon.md) — el registro de archivos vive en bronze.
- [Fase 1](../fases/fase-1.md)
