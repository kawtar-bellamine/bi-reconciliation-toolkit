"""Rebuild every result, figure and Power BI file from the source extract.

    python experiments/run_all.py            # full run, fault benchmark with 10 seeds per fault
    python experiments/run_all.py --seeds 2  # quicker
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bitk import faults  # noqa: E402
from bitk.anomaly import SERIES  # noqa: E402
from bitk.escalation import window_label, write_notes  # noqa: E402
from bitk.kpi import _base_measures, _with_labels  # noqa: E402
from bitk.pipeline import run  # noqa: E402

RES, PBI = ROOT / "results", ROOT / "powerbi"


def gbp(milli) -> float:
    return round(float(milli) / 1000, 2)


def main(seeds: int) -> None:
    RES.mkdir(exist_ok=True)
    PBI.mkdir(exist_ok=True)
    r = run()
    g = r["gold"]

    r["checks"].to_csv(RES / "checks.csv", index=False)
    r["issues"].to_csv(RES / "issue_log.csv", index=False)
    write_notes(r["issues"], r["checks"], r["samples"], RES / "escalations", window_label(r["silver"]))
    lt = r["line_types"].copy()
    lt["amount_gbp"] = lt["amount_milli"] / 1000
    lt.to_csv(RES / "line_types.csv", index=False)
    r["kpi_dictionary"].to_csv(ROOT / "kpi" / "kpi_dictionary.csv", index=False)

    mc = r["kpi_by_month_country"].copy()
    money = ["gross_product_sales", "product_cancellations", "net_product_sales", "shipping_income",
             "unidentified_sales"]
    for c in money:
        mc[c] = mc[c] / 1000
    mc.to_csv(RES / "kpi_by_month_country.csv", index=False)
    month = _base_measures(_with_labels(g), ["month"])
    for c in money:
        month[c] = month[c] / 1000
    cal = g["dim_date"]
    month = month.merge(cal.groupby("month").agg(trading_days=("has_sales", "sum")).reset_index(), on="month")
    month["net_sales_per_trading_day"] = (month["net_product_sales"] / month["trading_days"]).round(2)
    month.to_csv(RES / "kpi_by_month.csv", index=False)

    t = r["kpi_totals"]
    totals = {k: (gbp(v) if k in money else v) for k, v in t.items()}
    totals["average_order_value"] = round(t["average_order_value"] / 1000, 2)
    totals["cancellation_rate"] = round(t["cancellation_rate"], 4)
    pd.DataFrame([{"kpi_id": k, "value": v} for k, v in totals.items()]).to_csv(RES / "kpi_reference.csv", index=False)

    di = r["dual_implementation"]
    pd.DataFrame([{"cells": len(di), "cells_matching": int(di["matches"].sum()),
                   "max_abs_difference": float(di.filter(like="_diff").abs().max().max())}]).to_csv(
        RES / "dual_implementation_summary.csv", index=False)
    br = r["bridge"]
    br.to_csv(RES / "sales_bridge.csv", index=False)
    nv = r["naive_vs_reference"]
    nv.to_csv(RES / "naive_vs_reference.csv", index=False)
    an = r["anomalies"]
    keep = ["date", "weekday", "flagged_on", "largest_invoice"] + [f"{c}_z" for c in SERIES] + \
           ["gross_product_sales", "net_product_sales", "lines", "orders"]
    an[keep].to_csv(RES / "daily_anomalies.csv", index=False)
    r["daily_scores"].to_csv(RES / "daily_kpis.csv", index=False)

    # Power BI kit
    for name, df in g.items():
        if name == "fact_sales_line":
            df.drop(columns=["amount_milli"]).to_parquet(PBI / f"{name}.parquet", index=False)
        else:
            df.to_csv(PBI / f"{name}.csv", index=False)

    # fault benchmark
    bench = faults.benchmark(r["bronze"], seeds=seeds)
    bench.to_csv(RES / "fault_benchmark.csv", index=False)
    fam = faults.FAMILIES + ["any family"]
    summary = bench.groupby("fault", sort=False)[fam].mean().reset_index()
    summary.to_csv(RES / "fault_summary.csv", index=False)

    s = r["silver"]
    sale = s["line_type"] == "product_sale"
    cm = r["cancellations"]
    sd = cm[cm["same_day"]].nsmallest(2, "amount_milli")
    q = r["checks"].set_index("check_id")
    facts = {
        "source_lines": len(s), "source_total_gbp": gbp(s["amount_milli"].sum()),
        "first_date": str(s["date"].min().date()), "last_date": str(s["date"].max().date()),
        "countries": int(s["country"].nunique()), "products": int(s["stock_code"].nunique()),
        "line_types": {row.line_type: {"lines": int(row.lines), "gbp": gbp(row.amount_milli)}
                       for row in lt.itertuples()},
        "kpis": totals,
        "checks_pass": int((r["checks"]["status"] == "pass").sum()),
        "checks_warn": int((r["checks"]["status"] == "warn").sum()),
        "checks_fail": int((r["checks"]["status"] == "fail").sum()),
        "dual_cells": len(di), "dual_matching": int(di["matches"].sum()),
        "control_cells": len(r["control_totals"]),
        "missing_customer_lines": int(s["customer_missing"].sum()),
        "missing_customer_sales_share": round(float(s.loc[sale & s["customer_missing"], "amount_milli"].sum()
                                                    / s.loc[sale, "amount_milli"].sum()), 4),
        "same_day_cancellations": [{"sale": a, "cancel": b, "gbp": gbp(-v), "minutes": int(m)}
                                   for a, b, v, m in zip(sd["sale_invoice"], sd["invoice_no"], sd["amount_milli"],
                                                         (sd["invoice_ts"] - sd["sale_ts"]).dt.total_seconds() / 60)],
        "anomaly_days": len(an), "trading_days": len(r["daily_scores"]),
        "gross_only_anomalies": an.loc[an["gross_product_sales_flag"] & ~an["net_product_sales_flag"], "date"]
        .dt.strftime("%Y-%m-%d").tolist(),
        "issues": r["issues"]["severity"].value_counts().to_dict(),
        "fault_runs": len(bench), "seeds_per_fault": seeds,
        "fault_detected_any": float(bench["any family"].mean()),
        "fault_detection": {f: float(bench[f].mean()) for f in fam},
        "q_observed": q["observed"].to_dict(),
    }
    (RES / "summary.json").write_text(json.dumps(facts, indent=2, default=str))
    print(json.dumps(facts, indent=2, default=str))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=10)
    main(ap.parse_args().seeds)
