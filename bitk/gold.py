"""Gold layer: a star schema that Power BI (or any SQL engine) can read.

One fact table at source-line grain keeps every line with its ``line_type``, so the fact always adds up to the
source, and each KPI is a filter on that column (see ``kpi.py``).
"""
from __future__ import annotations

import pandas as pd

from .calendar import build_calendar
from .rules import service_category

UNKNOWN_CUSTOMER = -1
NO_DESCRIPTION = "(no description in source)"


def _mode_by(df: pd.DataFrame, key: str, col: str) -> pd.Series:
    """Most frequent non-null ``col`` per ``key`` (ties: first in sort order), vectorised."""
    c = df.dropna(subset=[col]).groupby([key, col], observed=True).size().rename("n").reset_index()
    c = c.sort_values([key, "n", col], ascending=[True, False, True], kind="stable")
    return c.drop_duplicates(key).set_index(key)[col]


def date_key(ts: pd.Series) -> pd.Series:
    return (ts.dt.year * 10000 + ts.dt.month * 100 + ts.dt.day).astype("int64")


def build_gold(silver: pd.DataFrame) -> dict[str, pd.DataFrame]:
    s = silver
    # products: one row per stock code, most frequent description
    prod = (s.groupby("stock_code")
            .agg(n_descriptions=("description", "nunique"), first_sold=("date", "min"), last_sold=("date", "max"))
            .reset_index().sort_values("stock_code", kind="stable"))
    prod.insert(1, "description", prod["stock_code"].map(_mode_by(s, "stock_code", "description"))
                .fillna(NO_DESCRIPTION))
    cat = service_category(prod["stock_code"])
    prod["product_group"] = cat.fillna("product")
    prod.insert(0, "product_key", range(1, len(prod) + 1))

    known = s.dropna(subset=["customer_id"])
    cust = (known.groupby("customer_id").agg(n_countries=("country", "nunique"))
            .reset_index().rename(columns={"customer_id": "customer_key"}))
    cust.insert(1, "main_country", cust["customer_key"].map(_mode_by(known, "customer_id", "country")))
    cust["customer_key"] = cust["customer_key"].astype("int64")
    cust = pd.concat([pd.DataFrame({"customer_key": [UNKNOWN_CUSTOMER], "main_country": ["(unknown)"],
                                    "n_countries": [0]}), cust], ignore_index=True)
    cust["is_identified"] = cust["customer_key"] != UNKNOWN_CUSTOMER

    ctry = pd.DataFrame({"country": sorted(s["country"].unique())})
    ctry.insert(0, "country_key", range(1, len(ctry) + 1))

    cal = build_calendar(s["date"].min(), s["date"].max(), s["date"].unique())

    fact = pd.DataFrame({
        "row_id": s["row_id"],
        "date_key": date_key(s["date"]),
        "invoice_no": s["invoice_no"],
        "product_key": s["stock_code"].map(prod.set_index("stock_code")["product_key"]).astype("int64"),
        "customer_key": s["customer_id"].fillna(UNKNOWN_CUSTOMER).astype("int64"),
        "country_key": s["country"].map(ctry.set_index("country")["country_key"]).astype("int64"),
        "line_type": s["line_type"],
        "quantity": s["quantity"],
        "amount_milli": s["amount_milli"],
    })
    fact["amount_gbp"] = fact["amount_milli"] / 1000
    return {"fact_sales_line": fact, "dim_product": prod, "dim_customer": cust, "dim_country": ctry, "dim_date": cal}
