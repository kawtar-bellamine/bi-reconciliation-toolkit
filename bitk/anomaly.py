"""Anomaly detection on daily KPIs, robust to the outliers it is looking for.

The test is run on history (an audit), so it can look at both sides of each day:

1. values go on a signed log scale, so that a doubling counts the same in March and in November;
2. the level is the median of the 15 surrounding trading days, which follows the seasonal growth;
3. the weekday effect is the median gap to that level for each weekday (Sundays are smaller, for example);
4. what is left is scaled by its median absolute deviation (MAD, times 1.4826, at least 0.02), and a day is
   flagged when the score is above 3.5 in absolute value.

Medians and MAD are used everywhere because a mean and a standard deviation would be pulled by the very days the
test is meant to find.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

LEVEL_WINDOW, THRESHOLD = 15, 3.5
MIN_SCALE = 0.02  # on the log scale, about 2%: a perfectly regular series should not flag tiny wiggles
SERIES = ["gross_product_sales", "net_product_sales", "lines", "orders", "unidentified_share"]


def daily_kpis(fact: pd.DataFrame) -> pd.DataFrame:
    sale = fact["line_type"] == "product_sale"
    ref = fact["line_type"].isin(["product_sale", "product_cancellation"])
    f = fact.assign(g=fact["amount_milli"].where(sale, 0) / 1000, n=fact["amount_milli"].where(ref, 0) / 1000,
                    o=fact["invoice_no"].where(sale),
                    u=(fact["amount_milli"].where(sale & (fact["customer_key"] < 0), 0) / 1000))
    d = f.groupby("date_key").agg(gross_product_sales=("g", "sum"), net_product_sales=("n", "sum"),
                                  lines=("row_id", "size"), orders=("o", "nunique"),
                                  unidentified=("u", "sum")).reset_index()
    gross = d["gross_product_sales"].where(d["gross_product_sales"] > 0)
    d["unidentified_share"] = (d["unidentified"] / gross).fillna(0)
    d = d.drop(columns="unidentified")
    d["date"] = pd.to_datetime(d["date_key"].astype(str))
    d["weekday"] = d["date"].dt.dayofweek
    return d


def _slog(x):
    return np.sign(x) * np.log1p(np.abs(x))


def robust_scores(daily: pd.DataFrame, series: list[str] = SERIES) -> pd.DataFrame:
    out = daily.sort_values("date", ignore_index=True).copy()
    for col in series:
        y = pd.Series(_slog(out[col].to_numpy(dtype=float)))
        level = y.rolling(LEVEL_WINDOW, center=True, min_periods=5).median()
        resid = y - level
        wd = resid.groupby(out["weekday"]).transform("median")
        r = resid - wd
        mad = max(1.4826 * np.nanmedian(np.abs(r - np.nanmedian(r))), MIN_SCALE)
        out[f"{col}_expected"] = np.sign(level + wd) * np.expm1(np.abs(level + wd))
        out[f"{col}_z"] = r / mad
        out[f"{col}_flag"] = out[f"{col}_z"].abs() > THRESHOLD
    return out


def flagged_days(scores: pd.DataFrame, series: list[str] = SERIES) -> set:
    flags = np.zeros(len(scores), dtype=bool)
    for col in series:
        flags |= scores[f"{col}_flag"].to_numpy()
    return set(scores.loc[flags, "date_key"])


def explain_day(fact: pd.DataFrame, date_key: int, n: int = 3) -> pd.DataFrame:
    """The invoices that move the day the most (absolute amount on product lines)."""
    f = fact[(fact["date_key"] == date_key) & fact["line_type"].isin(["product_sale", "product_cancellation"])]
    inv = f.groupby("invoice_no").agg(amount_gbp=("amount_gbp", "sum"), lines=("row_id", "size"),
                                     customer_key=("customer_key", "first"))
    return inv.reindex(inv["amount_gbp"].abs().sort_values(ascending=False).index).head(n).reset_index()
