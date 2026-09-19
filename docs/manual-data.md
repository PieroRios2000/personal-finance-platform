# Data the banks won't export: the manual Excel

Banco Ripley does not let you download statements, and the investments (Tyba funds, Flip) have
none the platform can read. Both go in **one Excel workbook that you fill in month by month**.
Like the PDFs, it stays on your machine: never in the repository, never pasted into a chat
([ADR 0004](../brain/decisions/0004-real-pdfs-never-leave-your-machine.md)).

## Get the template

```bash
uv run python -m scripts.make_manual_templates
```

This writes `~/finance-data/manual/plantilla-finanzas-manual.xlsx` (from Windows:
`\\wsl.localhost\Ubuntu\home\<you>\finance-data\manual\`). **Copy it as
`finanzas-manual.xlsx` in the same folder and fill in the copy.** The script never writes that
name, so it cannot overwrite your data. Every example row says `EJEMPLO`: delete them.

## The sheets

Numbers and dates must be Excel numbers and dates, not text. One movement per row. Do not type
names, account numbers or other personal data in any cell.

### `Ahorros` — savings accounts (Banco Ripley, others later)

| Column | What goes in it |
|---|---|
| `cuenta` | The account's name, always written the same way |
| `fecha` | Date of the movement |
| `descripcion` | Short text (deposit, interest, ...) |
| `monto` | Signed: positive when money comes in, negative when it goes out |
| `moneda` | `PEN` or `USD` |
| `saldo_final` | The account's balance after that movement |

**A month with no movements** still needs one row: `descripcion` = `cierre de mes`, `monto` = 0
and the balance at month end. That is how the platform knows the month exists and how it closed
(months are checked one statement per account and month, like the PDFs). A row with amount 0 is a
balance marker, not a transaction.

### `Inversiones` — funds and platforms

| Column | What goes in it |
|---|---|
| `lugar` | `Tyba fondo 1`, `Tyba fondo 2`, `Tyba fondo 3` or `Flip`, always written the same way |
| `fecha` | Date of the movement or of the valuation |
| `tipo` | `aporte` (you put money in), `retiro` (you took money out) or `valorizacion` |
| `monto` | Always positive; 0 in a `valorizacion` |
| `moneda` | `PEN` or `USD`, row by row |
| `saldo_final` | The investment's total balance after that row |
| `nota` | Optional, no personal data |

**`valorizacion`**: one row per investment at the end of every month, even if you moved nothing,
with amount 0 and that day's balance. Without it a month has no valuation and its return cannot
be computed: the return is what changes the balance without you putting in or taking out anything.
If a fund charges a fee or there are taxes, say so: a `comision` column would be added.

## What it is used for

- **Ripley savings** join the accounts the platform tracks (liquid savings, which count toward the
  savings goal, [ADR 0025](../brain/decisions/0025-savings-goal-projection-counts-liquid-savings-only.md)).
- **Investments** are tracked separately to see each fund's return month by month. They are not
  part of the savings goal ([ADR 0027](../brain/decisions/0027-manual-excel-for-ripley-savings-and-investment-tracking.md)).

The importer that reads the workbook is not built yet. Its design starts from a **masked** layout
dump of your real file (digits as `9`, text as `X`) that you review before anyone reads it, the
same loop the PDF parsers went through.
