"""Sales bridge: from the total of every line in the extract to the reference sales figure, one step per line type.

This is the answer to the most common question a BI team gets: "why is your number not the one in the source?"
"""
from __future__ import annotations

import pandas as pd

STEPS = [
    ("bad_debt_adjustment", "Bad debt adjustments"),
    ("probable_duplicate", "Probable duplicate lines"),
    ("shipping", "Shipping and carriage"),
    ("fees_and_charges", "Marketplace fees, bank charges, commissions"),
    ("manual_and_discount", "Manual entries, discounts, samples"),
    ("gift_voucher", "Gift vouchers"),
    ("stock_adjustment", "Zero-price stock movements"),
]


def sales_bridge(fact: pd.DataFrame) -> pd.DataFrame:
    by = fact.groupby("line_type").agg(lines=("amount_milli", "size"), amount_milli=("amount_milli", "sum"))
    get = lambda t, c="amount_milli": int(by[c].get(t, 0))  # noqa: E731
    total = int(fact["amount_milli"].sum())
    rows = [{"step": "All lines in the source extract", "kind": "total", "lines": len(fact), "amount_milli": total}]
    for t, label in STEPS:
        rows.append({"step": f"less {label.lower()}", "kind": "remove", "lines": get(t, "lines"),
                     "amount_milli": -get(t)})
    net = total - sum(get(t) for t, _ in STEPS)
    rows.append({"step": "Net product sales (reference KPI)", "kind": "total",
                 "lines": get("product_sale", "lines") + get("product_cancellation", "lines"), "amount_milli": net})
    rows.append({"step": "of which gross product sales", "kind": "detail", "lines": get("product_sale", "lines"),
                 "amount_milli": get("product_sale")})
    rows.append({"step": "of which product cancellations", "kind": "detail",
                 "lines": get("product_cancellation", "lines"), "amount_milli": get("product_cancellation")})
    out = pd.DataFrame(rows)
    out["amount_gbp"] = out["amount_milli"] / 1000
    if net != get("product_sale") + get("product_cancellation") or get("unclassified", "lines"):
        raise AssertionError("the bridge does not close")
    return out


def naive_vs_reference(fact: pd.DataFrame, dim_date: pd.DataFrame) -> pd.DataFrame:
    """Monthly 'sum of everything' (what a quick report shows) against net product sales, and the gap."""
    month = fact["date_key"].map(dim_date.set_index("date_key")["month"])
    f = fact.assign(month=month)
    ref = f["line_type"].isin(["product_sale", "product_cancellation"])
    out = f.groupby("month").agg(naive_milli=("amount_milli", "sum")).join(
        f[ref].groupby("month").agg(net_product_sales_milli=("amount_milli", "sum"))).join(
        f[f["line_type"] == "product_sale"].groupby("month").agg(gross_product_sales_milli=("amount_milli", "sum")))
    out["gap_milli"] = out["naive_milli"] - out["net_product_sales_milli"]
    out["gap_pct"] = out["gap_milli"] / out["net_product_sales_milli"]
    return out.reset_index()
