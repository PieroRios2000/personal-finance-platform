---
tipo: decision
fase: 1
estado: aceptada
fecha: 2026-09-12
---

# ADR 0004: Los PDFs reales nunca salen de tu máquina

## Contexto

Los estados de cuenta de BCP y Scotiabank tienen datos personales y financieros: nombre, números de
cuenta, saldos y cada movimiento. Hay dos vías por las que podrían salir de la máquina: Git (el repo
es público) y el asistente de IA, porque todo lo que lee se envía a su API. Además, el CI corre en
máquinas de GitHub.

## Decisión

- Los PDFs viven en `~/finance-data/` (bandeja `inbox/<usuario>/` y archivo `raw/<usuario>/`, desde el
  ADR 0009), fuera del repo y con permisos solo para su dueño;
  la contraseña, en `.env`.
- Git no puede recibirlos: `.gitignore` y el hook `forbid-data-files`.
- El CI usa PDFs sintéticos generados en los tests (T10), nunca PDFs reales.
- Los parsers se diseñan con un volcado de layout enmascarado (T9) que el dueño revisa antes de
  compartirlo; el asistente no lee PDFs reales sin enmascarar (reconfirmado el 2026-09-12).
- Las pruebas con PDFs reales (`pytest -m real_pdf`, `make poc`) corren solo en local y muestran
  pass/fail y diferencias de reconciliación, nunca valores extraídos.

## Alternativas consideradas

- **Subir PDFs anonimizados al repo**: anonimizar un PDF es fácil de hacer mal, y un binario en Git
  no se borra de la historia.
- **Que el asistente lea los PDFs reales**: más rápido para diseñar parsers, pero expone todo el
  contenido; descartado por el dueño.
- **PDFs cifrados en el repo**: agrega gestión de claves y el contenido sigue saliendo de la máquina.

## Consecuencias

- Los fixtures sintéticos tienen que imitar bien el layout real; si se desvían, lo detectan los
  tests `real_pdf` locales y la reconciliación.
- Los entornos efímeros del CI solo usan datos sintéticos (ADR 0007); con datos reales, solo
  `make poc` en local.
- Diseñar un parser toma un paso más: correr el inspector y revisar su salida.

## Relacionado

- [Guardas de seguridad](../componentes/guardas-de-seguridad.md) — cómo se impide que lleguen a Git.
- [Reconciliación](../conceptos/reconciliacion.md) — lo único que se muestra al probar con PDFs reales.
- [Fase 1](../fases/fase-1.md)
