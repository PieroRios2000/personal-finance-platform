# Monthly routine: new statements to a better category model

Run it once a month, after the month's statements arrive. Every command is a `make` target
and reads `PFP_USER` from your `.env` (or pass `PFP_USER=piero`). Counts and scores only are
printed; no description ever is (ADR 0004). The model trains on **your** labels and is applied
to **your** movements only (ADR 0047).

When movements show up: `gold.rpt_movements` keeps only movements dated before
`first_day_of_current_month` (a partial month never mixes with complete ones). Movements dated
in October appear on the first day of the next month (2026-11-01); September's are visible
already. Statements you ingest in October still land in bronze and get proposals straight away,
the dashboard just waits for the month to close.

## 1. Ingest and propose

```bash
make ingest              # PDFs in your inbox -> bronze, then a proposal for every new description
make build               # silver and gold: the dashboard shows the proposals (not confirmed)
```

Statements uploaded through the portal take the same path: `make ingest-uploads` runs
`pfp ingest` for each accepted request (`pfp backfill` does too). Each ends with
`Categorias: N new description(s) predicted`, or nothing printed when there is no model for
that user.

## 2. Label what is new

```bash
make export-category-labels    # an Excel with one row per (bank, description), guess prefilled
# edit the 'category' column, save, then:
make import-category-labels WORKBOOK=~/finance-data/manual/categorias-transacciones.xlsx
make build
```

## 3. Retrain, re-propose, check drift

```bash
make train-category-model      # macro-F1 against the rules baseline, saves the model for you
make categorize-new-movements  # re-propose with the new model, without a full re-ingest
make build
make monitor-category-drift    # has the data changed shape? a prompt, not a verdict
```

Training pins the saved model to the user it was trained for. Run it again after any
re-labelling. Record the new macro-F1 (reviewed labels, folds) in `docs/operations-log.md`.

## 4. Plan and forecast

```bash
make export-plan          # the workbook with your fixed charges and the goal in dollars
# edit ~/finance-data/plan/plan-de-ahorro.xlsx (Meta sheet: usd_to_pen, goal, emergency account), save, then:
make import-plan          # validates everything, nothing is written if a field is wrong
make build
make forecast             # per-category spend for the next 36 months, the goal projection
```

Only the first two steps change from month to month when you edit the plan: if it did not
change, `make build` then `make forecast` is enough. Open the **Forecast & goal** section of
the dashboard. **Forecast: realized vs expected** shows rows marked `backtest` on the first run
(the model's one-month-ahead forecast of months that already closed); from the second month on
it adds rows marked `realized`, last month's forecast against what happened (a ratio near 1 is
as good as the backtest, red above 2). The interval (p10 to p90) is blank past 12 months: the
backtest cannot measure it there.

To try another goal, exchange rate, emergency months or forecast horizon, type it in the filter
bar (*Goal (US$)*, *Exchange rate (PEN per US$)*, *Emergency months*, *Forecast horizon
(months)*) and press *Apply filters*; no `make forecast` is needed, and an empty filter means the
value of the `Meta` sheet. Where each table lives is in `docs/where-to-look.md`.
