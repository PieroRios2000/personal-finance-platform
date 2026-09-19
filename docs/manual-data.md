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
| `monto` | Signed (negative when money goes out) or unsigned: an unsigned amount whose balance went down is read as a withdrawal |
| `moneda` | `PEN` or `USD` |
| `saldo_final` | The account's balance after that movement |

Every row's balance must equal the previous row's balance plus or minus its amount; if it does not, the import stops and names the row (never the values). **A month with no movements** still needs one row: `descripcion` = `cierre de mes`, `monto` = 0
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

## Loading it

```bash
uv run pfp import-manual ~/finance-data/manual/finanzas-manual.xlsx   # needs .env (PFP_USER, PFP_ACCOUNT_KEY, LAKEHOUSE_URI)
```

The `Ahorros` sheet is loaded into bronze; then run the pipeline as usual (`dbt build`). It is safe
to run again and again: each account-month is **replaced**, not added, so you can keep adding rows
to the same workbook and reload it, and correct an old row and reload. If any row does not
reconcile the import stops and writes nothing, naming the row (never the values). The `Inversiones`
sheet is not loaded yet.

## How it was designed

The importer was built from the template's structure and checked against a real workbook by
counting (rows, months, problems), never by printing values. When something needs adjusting, the
**masked** description below is what you review and share, the same loop the PDF parsers went
through:

```bash
uv run python -m scripts.inspect_manual_excel ~/finance-data/manual/finanzas-manual.xlsx \
    > ~/finance-data/masked-dumps/manual-excel.masked.txt
```

It prints structure and counts only: text as shapes (`X` letters, `9` digits), no number or date
at all, no account or fund name, how many rows follow the previous balance, how many months each
group covers and how many have a valuation. Read it yourself before sharing it.
