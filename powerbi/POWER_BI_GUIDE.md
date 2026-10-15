# Loading the model in Power BI Desktop

The files in this folder are written by `python experiments/run_all.py`. They hold the gold layer: one fact
table at source-line grain and four dimensions.

| File | Rows | Key |
|---|---|---|
| `fact_sales_line.parquet` | one per source line | `row_id` |
| `dim_date.csv` | one per calendar day, Saturdays included | `date_key` |
| `dim_product.csv` | one per stock code | `product_key` |
| `dim_customer.csv` | one per customer, plus `-1` for lines without a customer ID | `customer_key` |
| `dim_country.csv` | one per country value | `country_key` |

## Steps

1. **Get data > Parquet** for the fact table, **Get data > Text/CSV** for each dimension. Check the types in
   Power Query: `amount_gbp` as Decimal number, keys as Whole number, `dim_date[date]` as Date,
   `has_sales` and `expected_trading_day` as True/False (the *Trading Days* measure filters on `has_sales`).
2. **Relationships** (Model view), all many-to-one, single direction, from the fact to each dimension:
   `date_key`, `product_key`, `customer_key`, `country_key`.
3. **Mark `dim_date` as the date table** on its `date` column.
4. **Measures:** create the measures of `measures.dax` in the fact table (one *New measure* per block).
5. **Check the model before building pages.** Put *Net Product Sales*, *Orders* and *Active Customers* in a
   table visual by `dim_date[month]` and compare with `results/kpi_by_month.csv`; the totals are in
   `results/kpi_reference.csv`. To automate it, load `kpi_reference.csv` as a table named `kpi_reference` and
   use the *Check Net Product Sales* measure in a card.

## Suggested pages

* **Overview:** net product sales by month with the *Month Is Partial* label, orders, average order value.
* **Daily operations:** each day against what a normal day would look like, as specified in
  [`docs/requirements_daily_operations.md`](../docs/requirements_daily_operations.md).
* **Sales bridge:** a waterfall visual on `results/sales_bridge.csv`, from all source lines to net product sales.
* **Data quality:** `results/issue_log.csv` as a table, sorted by severity and value.

## Performance notes

The fact table has one row per source line (about 540,000) and only integer keys, short codes and numbers, which
Power BI compresses well. Measures filter on `line_type` instead of using calculated columns, and the
relationships are single-direction from the fact to each dimension. If a page becomes slow, the Performance
analyzer shows whether time goes to the DAX query or to the visual (see [`docs/support_runbook.md`](../docs/support_runbook.md)).

## What has and has not been tested

The SQL and Python implementations of the KPIs are compared in CI (they agree on every month and country).
The DAX was written to follow the same definitions but has not been run in this repository, because Power BI
Desktop does not run on the Linux CI machines. Step 5 is there for that reason.

The bronze, silver and gold folders follow the usual lakehouse layering (the "medallion" pattern used in
Microsoft Fabric and Databricks). The SQL in `bitk/kpi.py` is standard apart from `strftime` and
`regexp_full_match`, which would need their equivalents on another engine.
