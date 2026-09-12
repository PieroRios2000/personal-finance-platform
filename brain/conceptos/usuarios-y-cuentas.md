---
tipo: concepto
fase: 1
---

# Usuarios y cuentas

Cada movimiento pertenece a un usuario y a una cuenta. Una instalación sirve a varias personas, y cada
una puede tener varias cuentas, incluso en el mismo banco.

## Cómo se aplica aquí

- **Usuario (`user_id`)**: viene del contexto de la ingesta (`pfp ingest --user`, por defecto
  `PFP_USER`), no del PDF. El lake se particiona por `user_id`, así que borrar los datos de alguien es
  borrar su partición.
- **Bandeja y archivo (T12b)**: los PDFs se dejan con cualquier nombre en `~/finance-data/inbox/<usuario>/`
  y se archivan en `raw/<usuario>/<banco>/<últimos4>-<id6>/<inicio>_<fin>.pdf`. Tres `EECC.pdf` de
  cuentas distintas terminan en tres carpetas; uno repetido, en `_duplicados/`; uno ilegible, en
  `_por_clasificar/`, con un reporte. Nunca se borra un archivo.
- **Cuenta (`account_id`)**: HMAC-SHA256 del banco y el número completo, con la clave
  `PFP_ACCOUNT_KEY` de `.env`. Es único por cuenta y no revela el número; para mostrar se guardan los
  últimos 4 dígitos. Un hash sin clave no serviría: los números de cuenta posibles son pocos y se
  revierten probándolos todos.
- **El contenido manda**: banco, cuenta y periodo se leen del PDF. El nombre del archivo no importa y
  nunca se guarda, porque puede incluir números de cuenta.

## Pregunta abierta

Una cuenta mancomunada (dos usuarios, la misma cuenta) quedaría duplicada, una copia por usuario. Se
decide si aparece el caso.

## Relacionado

- [Reconciliación](reconciliacion.md) — la continuidad y la conciliación entre cuentas dependen de saber de qué cuenta es cada movimiento.
- [Business key](business-key.md) — la clave incluye la cuenta.
- [Dedup por archivo](dedup-por-archivo.md) — el registro de archivos es por usuario.
- [ADR 0004: PDFs reales](../decisiones/0004-pdfs-reales-no-salen-de-la-maquina.md) — el número completo nunca sale de la memoria del parseo.
- [Fase 1](../fases/fase-1.md)
