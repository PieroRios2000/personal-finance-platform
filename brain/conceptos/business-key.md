---
tipo: concepto
fase: 1
---

# Business key

Identificador de una transacción construido con sus propios datos, no con un id generado, para
reconocer el mismo movimiento aunque llegue en otro PDF.

## Cómo se aplica aquí

`fecha + monto + descripción normalizada + cuenta`.

La descripción se normaliza (sin espacios sobrantes, en mayúsculas, sin códigos de relleno) con
`normalize_description()` (T6), para que la clave sea estable entre reportes. En la Fase 2, silver usa
esta clave para hacer MERGE en Delta: si la clave ya existe, no se inserta otra vez.

## Pregunta abierta

Dos compras legítimas iguales el mismo día (mismo comercio y mismo monto) producirían la misma clave y
se fusionarían en una. Se resuelve al diseñar el MERGE en la Fase 2; una opción es añadir el número de
ocurrencia dentro del mismo PDF.

## Relacionado

- [Idempotencia](idempotencia.md) — la business key es su segundo nivel.
- [Dedup por archivo](dedup-por-archivo.md) — el nivel anterior, que no ve PDFs regenerados.
- [Arquitectura medallón](medallon.md) — el MERGE ocurre en silver.
- [Fase 1](../fases/fase-1.md)
