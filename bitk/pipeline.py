"""One call that runs the whole audit on the source extract and returns every table."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .anomaly import SERIES, daily_kpis, explain_day, robust_scores
from .bridge import naive_vs_reference, sales_bridge
from .bronze import RAW, load_bronze
from .gold import build_gold
from .kpi import KPI_DICTIONARY, SQL_LINE_TYPES, by_month_country_pandas, run_sql, totals_pandas
from .quality import quality_checks
from .reconcile import structural_checks
from .silver import build_silver


def run(path: str | Path = RAW) -> dict:
    bronze = load_bronze(path)
    silver = build_silver(bronze)
    gold = build_gold(silver)
    fact = gold["fact_sales_line"]
    checks, tables = structural_checks(bronze, gold)
    qchecks, issues, qtables = quality_checks(silver, gold)

    line_types = (fact.groupby("line_type").agg(lines=("row_id", "size"), amount_milli=("amount_milli", "sum"))
                  .reset_index())
    sql_types = run_sql(bronze, SQL_LINE_TYPES).astype({"rows": "int64", "amount_milli": "int64"})
    line_types = line_types.merge(sql_types.rename(columns={"lines": "lines_sql", "rows": "lines_sql",
                                                            "amount_milli": "amount_milli_sql"}),
                                  on="line_type", how="outer")

    scores = robust_scores(daily_kpis(fact))
    flag_cols = [f"{c}_flag" for c in SERIES]
    flagged = scores[scores[flag_cols].any(axis=1)].copy()
    flagged["flagged_on"] = flagged[flag_cols].apply(lambda r: ", ".join(c[:-5] for c in flag_cols if r[c]), axis=1)
    expl = []
    for dk in flagged["date_key"]:
        top = explain_day(fact, dk, 1)
        expl.append(f"invoice {top.iloc[0]['invoice_no']}: {top.iloc[0]['amount_gbp']:,.2f} GBP" if len(top) else "")
    flagged["largest_invoice"] = expl

    return {
        "bronze": bronze, "silver": silver, "gold": gold,
        "checks": pd.DataFrame([c.row() for c in checks + qchecks]),
        "issues": pd.DataFrame(issues),
        "line_types": line_types,
        "kpi_dictionary": pd.DataFrame(KPI_DICTIONARY),
        "kpi_totals": totals_pandas(gold),
        "kpi_by_month_country": by_month_country_pandas(gold),
        "dual_implementation": tables["dual_implementation"],
        "control_totals": tables["control_totals"],
        "bridge": sales_bridge(fact),
        "naive_vs_reference": naive_vs_reference(fact, gold["dim_date"]),
        "daily_scores": scores,
        "anomalies": flagged,
        "cancellations": qtables["cancellations"],
        "samples": qtables["samples"],
    }
