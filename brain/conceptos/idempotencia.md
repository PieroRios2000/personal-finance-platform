---
tipo: concepto
fase: 1
---

# Idempotencia

Una operación es idempotente si ejecutarla dos veces deja el mismo resultado que ejecutarla una.
Aquí significa que **subir el mismo estado de cuenta dos veces no duplica movimientos**.

## Cómo se aplica aquí

Se protege en dos niveles, porque cada uno cubre lo que el otro no ve:

| Nivel | Detecta | Cómo | Dónde |
|---|---|---|---|
| Archivo | El mismo PDF subido otra vez | Hash SHA-256 del contenido | [Dedup por archivo](dedup-por-archivo.md) (T7, T14) |
| Transacción | El mismo movimiento en dos PDFs distintos (el de enero y uno de "últimos 60 días") | [Business key](business-key.md) + MERGE en silver | Fase 2 |

La verificación de T14 lo prueba directamente: ingerir dos veces el mismo PDF agrega 0 filas.

## Relacionado

- [Dedup por archivo](dedup-por-archivo.md) — el primer nivel.
- [Business key](business-key.md) — el segundo nivel.
- [Arquitectura medallón](medallon.md) — reprocesar una capa también debe ser idempotente.
- [Fase 1](../fases/fase-1.md)
