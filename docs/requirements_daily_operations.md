# Requirement sheet: daily operations view

An example of how a user request is turned into a requirement that can be built and tested. The request below
is illustrative: it was written for this project and does not come from real users. The KPIs, checks and data
are those of this repository, and the result is the *Daily operations* page of the dashboard.

## Request, in the user's words

"Each morning I want to see how yesterday went compared with a normal day, and to know if I can trust the
figures before I send them on."

## What the page must answer

| Question | Answer on the page |
|---|---|
| How did the day go? | Net product sales, gross product sales, orders and lines for the day |
| Compared with what? | Expected value for that day: level of the surrounding trading days, adjusted for the weekday |
| Is anything unusual? | Anomaly flags (robust test, threshold 3.5) |
| Can I trust it? | Warning when the day is the last day of the extract; open high-severity issues listed |

## KPIs

All from the KPI dictionary (`kpi/kpi_dictionary.csv`): `net_product_sales`, `gross_product_sales`, `orders`,
plus line count and share of sales without a customer ID.

## Constraints

- No trading on Saturdays and bank holidays: the day selector only offers trading days.
- The last day of the extract can be partial: it is labelled.
- Gross sales can include orders cancelled the same day: net sales is the headline figure.

## Acceptance tests

1. The day's net product sales equal the value in `results/daily_kpis.csv` for that date.
2. The sum over a month equals `net_product_sales` in `results/kpi_by_month.csv`.
3. Choosing 9 December 2011 shows the partial-day warning.
4. Choosing 18 January 2011 shows a flag on gross sales and none on net sales (an order cancelled 16 minutes
   after it was placed).
