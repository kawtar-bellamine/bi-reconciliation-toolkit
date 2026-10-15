"""Fault injection: break a clean extract on purpose and measure which family of checks notices.

Each fault reproduces a problem that happens when data moves between systems (a lost day, a load run twice, a
decimal shift, a date format change...). The pipeline then runs on the broken extract, and three families of
checks look at the result:

* ``control totals``: rows and amount per day and country, compared with totals sent by the source system;
* ``reference data``: codes, countries and prices compared with the reference data of the previous clean load, and
  the business calendar (sales on a closed day, or no sales on an expected trading day);
* ``statistics only``: the daily anomaly test, plus the share of sales without a customer ID by country and month
  (flagged when it is 30 points above that country's median month). These need nothing but the report itself.

Faults that target a country pick one of the ten largest countries after the United Kingdom, so that the fault
touches enough lines to matter.

A fault counts as detected by a family when that family reports something it did not report on the clean data.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .anomaly import daily_kpis, flagged_days, robust_scores
from .bronze import control_totals
from .gold import build_gold
from .reconcile import control_total_check
from .silver import build_silver

FAMILIES = ["control totals", "reference data", "statistics only"]


def _days(b):
    return np.sort(b["invoice_ts"].dt.normalize().unique())


def _months(b):
    return np.sort(b["invoice_ts"].dt.to_period("M").astype(str).unique())


def missing_day(b, rng):
    day = rng.choice(_days(b))
    return b[b["invoice_ts"].dt.normalize() != day], f"all lines of {pd.Timestamp(day):%Y-%m-%d} lost"


def double_load(b, rng):
    day = rng.choice(_days(b))
    extra = b[b["invoice_ts"].dt.normalize() == day].copy()
    extra["row_id"] = np.arange(len(extra)) + b["row_id"].max() + 1
    return pd.concat([b, extra], ignore_index=True), f"{pd.Timestamp(day):%Y-%m-%d} loaded twice"


def truncated_extract(b, rng):
    frac = rng.uniform(0.002, 0.02)
    n = int(len(b) * (1 - frac))
    return b.iloc[:n], f"last {frac:.1%} of the file cut off"


def _country(b, rng):
    vc = b["country"].value_counts()
    return rng.choice(vc.drop("United Kingdom").index[:10].to_numpy())


def decimal_shift(b, rng):
    ctry = _country(b, rng)
    month = rng.choice(_months(b[b["country"] == ctry]))
    m = (b["country"] == ctry) & (b["invoice_ts"].dt.to_period("M").astype(str) == month)
    out = b.copy()
    out.loc[m, "unit_price_milli"] *= 100
    out["amount_milli"] = out["quantity"] * out["unit_price_milli"]
    return out, f"prices of {ctry} in {month} loaded in pence instead of pounds ({int(m.sum())} lines)"


def date_format_swap(b, rng):
    month = rng.choice(_months(b)[:-1])
    ts = b["invoice_ts"]
    m = (ts.dt.to_period("M").astype(str) == month) & (ts.dt.day <= 12) & (ts.dt.day != ts.dt.month)
    out = b.copy()
    sw = ts[m]
    out.loc[m, "invoice_ts"] = pd.to_datetime(pd.DataFrame({
        "year": sw.dt.year, "month": sw.dt.day, "day": sw.dt.month, "hour": sw.dt.hour, "minute": sw.dt.minute}))
    return out, f"day and month swapped for days 1 to 12 of {month} ({int(m.sum())} lines)"


def new_product_codes(b, rng):
    day = rng.choice(_days(b))
    m = b["invoice_ts"].dt.normalize() == day
    out = b.copy()
    out.loc[m, "stock_code"] = out.loc[m, "stock_code"] + "-01"
    return out, f"product codes of {pd.Timestamp(day):%Y-%m-%d} arrive in a new format"


def customer_join_lost(b, rng):
    ctry = _country(b, rng)
    month = rng.choice(_months(b[b["country"] == ctry]))
    m = (b["country"] == ctry) & (b["invoice_ts"].dt.to_period("M").astype(str) == month)
    out = b.copy()
    out.loc[m, "customer_id"] = pd.NA
    return out, f"customer IDs of {ctry} in {month} lost ({int(m.sum())} lines)"


def country_relabel(b, rng):
    ctry = _country(b, rng)
    month = rng.choice(_months(b[b["country"] == ctry]))
    m = (b["country"] == ctry) & (b["invoice_ts"].dt.to_period("M").astype(str) >= month)
    out = b.copy()
    out.loc[m, "country"] = ctry.upper() + " (NEW)"
    return out, f"{ctry} renamed from {month} on ({int(m.sum())} lines)"


FAULTS = {f.__name__: f for f in [missing_day, double_load, truncated_extract, decimal_shift, date_format_swap,
                                  new_product_codes, customer_join_lost, country_relabel]}


@dataclass
class Reference:
    controls: pd.DataFrame
    product_codes: set
    countries: set
    median_price: pd.Series
    closed_days: set
    trading_days: set
    baseline: dict

    @classmethod
    def from_clean(cls, bronze: pd.DataFrame) -> Reference:
        silver = build_silver(bronze)
        gold = build_gold(silver)
        sale = silver[silver["line_type"] == "product_sale"]
        cal = gold["dim_date"]
        ref = cls(control_totals(bronze), set(bronze["stock_code"]), set(bronze["country"]),
                  sale.groupby("stock_code")["unit_price_milli"].median(),
                  set(cal.loc[~cal["expected_trading_day"], "date"]), set(cal.loc[cal["expected_trading_day"], "date"]),
                  {})
        ref.baseline = family_findings(gold, silver, ref)
        return ref


def unidentified_jumps(silver: pd.DataFrame, jump: float = 0.30, min_lines: int = 20) -> list[tuple]:
    """Country-months where the share of sales without a customer ID is ``jump`` above the country's median."""
    sale = silver[silver["line_type"] == "product_sale"]
    g = sale.assign(u=sale["amount_milli"].where(sale["customer_missing"], 0)).groupby(["country", "month"]).agg(
        u=("u", "sum"), a=("amount_milli", "sum"), n=("row_id", "size")).reset_index()
    g["share"] = g["u"] / g["a"]
    g["median"] = g.groupby("country")["share"].transform("median")
    hit = g[(g["n"] >= min_lines) & (g["share"] > g["median"] + jump)]
    return list(zip(hit["month"], hit["country"]))


def family_findings(gold: dict, silver: pd.DataFrame, ref: Reference) -> dict[str, set]:
    chk, _ = control_total_check(gold, ref.controls)
    sale = silver[silver["line_type"] == "product_sale"]
    med = sale["stock_code"].map(ref.median_price)
    price = sale[med.notna() & (sale["unit_price_milli"] > 20 * med) & (sale["unit_price_milli"] > 10_000)]
    refdata = ({("unknown code", c) for c in set(silver["stock_code"]) - ref.product_codes}
               | {("unknown country", c) for c in set(silver["country"]) - ref.countries}
               | {("price", r.invoice_no, r.stock_code) for r in price.itertuples()}
               | {("closed day", d) for d in set(silver["date"]) & ref.closed_days}
               | {("no sales", d) for d in ref.trading_days - set(silver["date"])})
    stats = flagged_days(robust_scores(daily_kpis(gold["fact_sales_line"])))
    stats |= {("unidentified share", m, c) for m, c in unidentified_jumps(silver)}
    return {"control totals": set(chk.failing), "reference data": refdata, "statistics only": stats}


def run_fault(bronze: pd.DataFrame, ref: Reference, fault: str, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    broken, what = FAULTS[fault](bronze, rng)
    silver = build_silver(broken)
    found = family_findings(build_gold(silver), silver, ref)
    row = {"fault": fault, "seed": seed, "description": what}
    for fam in FAMILIES:
        row[fam] = bool(found[fam] - ref.baseline[fam])
    row["any family"] = any(row[f] for f in FAMILIES)
    return row


def benchmark(bronze: pd.DataFrame, seeds: int = 10, faults=None, ref: Reference | None = None) -> pd.DataFrame:
    ref = ref or Reference.from_clean(bronze)
    rows = [run_fault(bronze, ref, f, 1000 * i + s) for i, f in enumerate(faults or FAULTS) for s in range(seeds)]
    return pd.DataFrame(rows)
