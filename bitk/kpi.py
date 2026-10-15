"""KPI dictionary: one written definition per KPI, implemented twice.

``by_month_country_pandas`` computes the KPIs from the gold star schema. ``by_month_country_sql`` computes them
again, in SQL, straight from the bronze extract, with its own classification. The two implementations share no
code, so when they agree to the thousandth of a pound, the definition is implemented consistently; when they do
not, one of them is wrong. ``powerbi/measures.dax`` is the third implementation, for the Power BI model.
"""
from __future__ import annotations

import duckdb
import pandas as pd

KPI_DICTIONARY = [
    {"kpi_id": "gross_product_sales", "name": "Gross product sales", "unit": "GBP",
     "definition": "Value of product lines sold: positive quantity at a positive price.",
     "includes": "line_type = product_sale",
     "excludes": "cancellations, shipping, fees, manual entries, discounts, gift vouchers, bad debt adjustments, "
                 "zero-price stock movements, probable duplicates",
     "additive": "yes"},
    {"kpi_id": "product_cancellations", "name": "Product cancellations", "unit": "GBP",
     "definition": "Value of cancelled product lines (invoice numbers starting with C), booked on the cancellation "
                   "date, negative by convention.",
     "includes": "line_type = product_cancellation", "excludes": "cancelled shipping and fees", "additive": "yes"},
    {"kpi_id": "net_product_sales", "name": "Net product sales", "unit": "GBP",
     "definition": "Gross product sales plus product cancellations. The reference sales figure.",
     "includes": "line_type in (product_sale, product_cancellation)", "excludes": "as above", "additive": "yes"},
    {"kpi_id": "shipping_income", "name": "Shipping income", "unit": "GBP",
     "definition": "Postage and carriage charged to customers, net of their cancellations.",
     "includes": "line_type = shipping (codes POST, DOT, C2)", "excludes": "", "additive": "yes"},
    {"kpi_id": "orders", "name": "Orders", "unit": "count",
     "definition": "Distinct invoices with at least one product sale line.",
     "includes": "invoices with a product_sale line", "excludes": "cancellation invoices, service-only invoices",
     "additive": "no (distinct count)"},
    {"kpi_id": "units_sold", "name": "Units sold", "unit": "units",
     "definition": "Quantity on product sale lines.", "includes": "line_type = product_sale",
     "excludes": "stock adjustments, cancellations", "additive": "yes"},
    {"kpi_id": "active_customers", "name": "Active customers", "unit": "count",
     "definition": "Distinct identified customers with at least one product sale line.",
     "includes": "product_sale lines with a customer ID", "excludes": "lines without a customer ID",
     "additive": "no (distinct count)"},
    {"kpi_id": "unidentified_sales", "name": "Sales without a customer ID", "unit": "GBP",
     "definition": "Gross product sales on lines without a customer ID. Reported, not excluded: these sales are "
                   "real, but no customer KPI can use them.",
     "includes": "line_type = product_sale and customer ID missing", "excludes": "", "additive": "yes"},
    {"kpi_id": "average_order_value", "name": "Average order value", "unit": "GBP",
     "definition": "Gross product sales divided by orders.", "includes": "", "excludes": "",
     "additive": "no (ratio)"},
    {"kpi_id": "cancellation_rate", "name": "Cancellation rate", "unit": "%",
     "definition": "Product cancellations (absolute value) divided by gross product sales.", "includes": "",
     "excludes": "", "additive": "no (ratio)"},
]
MEASURES = ["gross_product_sales", "product_cancellations", "net_product_sales", "shipping_income", "orders",
            "units_sold", "active_customers", "unidentified_sales"]
KEYS = ["month", "country"]


def _base_measures(f: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    sale = f["line_type"] == "product_sale"
    canc = f["line_type"] == "product_cancellation"
    f = f.assign(
        gross_product_sales=f["amount_milli"].where(sale, 0),
        product_cancellations=f["amount_milli"].where(canc, 0),
        shipping_income=f["amount_milli"].where(f["line_type"] == "shipping", 0),
        units_sold=f["quantity"].where(sale, 0),
        unidentified_sales=f["amount_milli"].where(sale & (f["customer_key"] < 0), 0),
        _order=f["invoice_no"].where(sale),
        _customer=f["customer_key"].where(sale & (f["customer_key"] >= 0)),
    )
    g = f.groupby(by, as_index=False) if by else f.assign(_all=1).groupby("_all", as_index=False)
    out = g.agg(gross_product_sales=("gross_product_sales", "sum"),
                product_cancellations=("product_cancellations", "sum"),
                shipping_income=("shipping_income", "sum"), units_sold=("units_sold", "sum"),
                unidentified_sales=("unidentified_sales", "sum"),
                orders=("_order", "nunique"), active_customers=("_customer", "nunique"))
    out["net_product_sales"] = out["gross_product_sales"] + out["product_cancellations"]
    return out.drop(columns=["_all"], errors="ignore")[by + MEASURES]


def _with_labels(gold: dict) -> pd.DataFrame:
    f = gold["fact_sales_line"]
    cal = gold["dim_date"].set_index("date_key")["month"]
    ctry = gold["dim_country"].set_index("country_key")["country"]
    return f.assign(month=f["date_key"].map(cal), country=f["country_key"].map(ctry))


def by_month_country_pandas(gold: dict) -> pd.DataFrame:
    return _base_measures(_with_labels(gold), KEYS).sort_values(KEYS, ignore_index=True)


def totals_pandas(gold: dict) -> dict:
    t = _base_measures(_with_labels(gold), []).iloc[0].to_dict()
    t["average_order_value"] = t["gross_product_sales"] / t["orders"] if t["orders"] else float("nan")
    gross = t["gross_product_sales"]
    t["cancellation_rate"] = -t["product_cancellations"] / gross if gross else float("nan")
    return t


SQL_CLASSIFY = """
WITH numbered AS (
    SELECT *, ROW_NUMBER() OVER (
        PARTITION BY invoice_no, stock_code, description, quantity, invoice_ts, unit_price_milli, customer_id, country
        ORDER BY row_id) AS copy_no
    FROM bronze
), typed AS (
    SELECT *, CASE
        WHEN invoice_no LIKE 'A%' THEN 'bad_debt_adjustment'
        WHEN copy_no > 1 THEN 'probable_duplicate'
        WHEN upper(stock_code) IN ('POST', 'DOT', 'C2') THEN 'shipping'
        WHEN upper(stock_code) IN ('AMAZONFEE', 'BANK CHARGES', 'CRUK') THEN 'fees_and_charges'
        WHEN upper(stock_code) IN ('M', 'D', 'S') THEN 'manual_and_discount'
        WHEN regexp_full_match(upper(stock_code), 'GIFT_[0-9]{4}_[0-9]+') THEN 'gift_voucher'
        WHEN invoice_no LIKE 'C%' THEN 'product_cancellation'
        WHEN unit_price_milli = 0 THEN 'stock_adjustment'
        WHEN quantity > 0 AND unit_price_milli > 0 THEN 'product_sale'
        ELSE 'unclassified' END AS line_type
    FROM numbered
)
"""

SQL_MONTH_COUNTRY = SQL_CLASSIFY + """
SELECT strftime(invoice_ts, '%Y-%m') AS month, country,
    SUM(CASE WHEN line_type = 'product_sale' THEN amount_milli ELSE 0 END) AS gross_product_sales,
    SUM(CASE WHEN line_type = 'product_cancellation' THEN amount_milli ELSE 0 END) AS product_cancellations,
    SUM(CASE WHEN line_type IN ('product_sale', 'product_cancellation') THEN amount_milli ELSE 0 END)
        AS net_product_sales,
    SUM(CASE WHEN line_type = 'shipping' THEN amount_milli ELSE 0 END) AS shipping_income,
    COUNT(DISTINCT CASE WHEN line_type = 'product_sale' THEN invoice_no END) AS orders,
    SUM(CASE WHEN line_type = 'product_sale' THEN quantity ELSE 0 END) AS units_sold,
    COUNT(DISTINCT CASE WHEN line_type = 'product_sale' THEN customer_id END) AS active_customers,
    SUM(CASE WHEN line_type = 'product_sale' AND customer_id IS NULL THEN amount_milli ELSE 0 END)
        AS unidentified_sales
FROM typed
GROUP BY ALL
ORDER BY month, country
"""

SQL_LINE_TYPES = SQL_CLASSIFY + """
SELECT line_type, COUNT(*) AS rows, SUM(amount_milli) AS amount_milli FROM typed GROUP BY ALL ORDER BY line_type
"""


def run_sql(bronze: pd.DataFrame, sql: str) -> pd.DataFrame:
    con = duckdb.connect()
    con.register("bronze", bronze.assign(customer_id=bronze["customer_id"].astype("float64")))
    try:
        return con.execute(sql).df()
    finally:
        con.close()


def by_month_country_sql(bronze: pd.DataFrame) -> pd.DataFrame:
    out = run_sql(bronze, SQL_MONTH_COUNTRY)
    for m in MEASURES:
        out[m] = out[m].astype("int64")
    return out[KEYS + MEASURES].sort_values(KEYS, ignore_index=True)
