---
tipo: concepto
fase: 1
---

# Reconciliación

Comprobar que lo extraído de un PDF cuadra con lo que el propio PDF declara. Si no cuadra, el parser
falla y reporta la diferencia, en vez de guardar datos incorrectos.

## Cómo se aplica aquí

- `saldo inicial + Σ montos = saldo final`, y los totales de cargos y abonos cuando el banco los
  declara (T8).
- `ReconciliationError` informa el valor esperado, el obtenido y la diferencia.
- Es la red de seguridad del OCR (T11b): un dígito mal leído en una página escaneada rompe el cuadre.
- Con los PDFs reales, los tests locales (`pytest -m real_pdf`) muestran solo si cuadra y las
  diferencias, nunca los valores extraídos.

Es la versión personal de las metodologías de reconciliación y validación de las migraciones de datos.

## Relacionado

- [Arquitectura medallón](medallon.md) — bronze solo recibe estados de cuenta reconciliados.
- [ADR 0004: PDFs reales](../decisiones/0004-pdfs-reales-no-salen-de-la-maquina.md) — qué se muestra al probar con PDFs reales.
- [Fase 1](../fases/fase-1.md)
