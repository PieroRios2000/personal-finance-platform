---
tipo: componente
fase: 1
estado: construido
tarea: T9
---

# Inspector de layout enmascarado

Muestra dónde está cada texto de un PDF de estado de cuenta con los dígitos como `9` y el
texto como `X`, para diseñar parsers y fixtures sintéticos sin que ningún dato personal salga
de tu máquina.

## Piezas

| Pieza | Qué hace |
|---|---|
| [`scripts/inspect_pdf_layout.py`](../../scripts/inspect_pdf_layout.py) | Abre el PDF con pikepdf (tolera bytes antes de `%PDF-`, como el `$BOP$` de BCP, y lo descifra), lee las palabras con posiciones con pdfplumber, las agrupa en líneas e imprime cada una enmascarada. No imprime la ruta ni los metadatos del archivo |
| `HEADERS` (en el mismo script) | Lista corta de encabezados genéricos (FECHA, CARGO, SALDO…) que se muestran tal cual; todo lo demás se enmascara. Nunca lleva nombres propios |
| [`tests/test_inspect_pdf_layout.py`](../../tests/test_inspect_pdf_layout.py) | PDFs sintéticos generados con fpdf2 en `tmp_path`: prefijo de bytes, cifrado, página solo imagen y un test de privacidad |

## Cómo se usa y cómo se verifica

```bash
uv run --env-file .env scripts/inspect_pdf_layout.py ~/finance-data/raw/<usuario>/<archivo>.pdf \
    --password-env BCP_PDF_PASSWORD
```

Salida sobre un PDF sintético:

```text
Cifrado: sí
Páginas: 2
Páginas sin capa de texto (escaneadas): 2

== Página 1 · 595x842 pt ==
y=103 | x=40-71 FECHA | x=150-213 DESCRIPCIÓN | x=380-419 CARGOS | x=520-551 SALDO
y=118 | x=40-63 99/99 | x=150-189 XXXXXX | x=191-221 XXXXX | x=385-420 9,999.99
```

- `y` es el borde superior de la línea y `x=inicio-fin` los bordes de cada palabra, en puntos:
  los montos alineados a la derecha comparten el `fin`.
- La contraseña nunca va en la línea de comandos: `--password-env` recibe el nombre de la
  variable y `uv run --env-file .env` la carga, sin librerías extra.
- Se sigue viendo la forma (largo de cada palabra, puntuación y posiciones): revisa la salida
  antes de compartirla.
- Verificación: `uv run pytest tests/test_inspect_pdf_layout.py`. Sobre PDFs reales solo lo
  corre el dueño.

## Relacionado

- [ADR 0004: PDFs reales](../decisiones/0004-pdfs-reales-no-salen-de-la-maquina.md) — la decisión que este inspector hace posible.
- [Guardas de seguridad](../componentes/guardas-de-seguridad.md) — impiden que un PDF llegue a Git.
- [Fase 1](../fases/fase-1.md)
