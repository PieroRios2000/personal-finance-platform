---
tipo: concepto
fase: 1
---

# Reconciliación

Comprobar que los datos cuadran: cada PDF consigo mismo, cada cuenta a lo largo del tiempo y las
cuentas entre sí. Si algo no cuadra, se reporta la diferencia en vez de guardar datos incorrectos.

## Cómo se aplica aquí

La conciliación es integral, en tres niveles:

| Nivel | Qué comprueba | Dónde |
|---|---|---|
| Estado de cuenta | `saldo inicial + Σ montos = saldo final`, y los totales de cargos y abonos cuando el banco los declara | T8 |
| Continuidad | El saldo final de un periodo es el saldo inicial del siguiente, en la misma cuenta; detecta estados de cuenta faltantes | T16 |
| Entre cuentas | Cada transferencia entre cuentas del mismo usuario tiene su contraparte, y no cuenta como gasto ni como ingreso | T18b |

- `ReconciliationError` informa el valor esperado, el obtenido y la diferencia.
- Es la red de seguridad del OCR (T11b): un dígito mal leído en una página escaneada rompe el cuadre.
- Con los PDFs reales, los tests locales (`pytest -m real_pdf`) muestran solo si cuadra y las
  diferencias, nunca los valores extraídos.

Es la versión personal de las metodologías de reconciliación y validación de las migraciones de datos.

## Relacionado

- [Arquitectura medallón](medallon.md) — bronze solo recibe estados de cuenta reconciliados.
- [Usuarios y cuentas](usuarios-y-cuentas.md) — la continuidad y la conciliación entre cuentas necesitan saber de qué cuenta es cada movimiento.
- [ADR 0004: PDFs reales](../decisiones/0004-pdfs-reales-no-salen-de-la-maquina.md) — qué se muestra al probar con PDFs reales.
- [Fase 1](../fases/fase-1.md)
