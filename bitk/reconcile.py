"""Reconciliation: compare two versions of the same figures and report every difference.

``compare`` is the generic tool (source vs report, old platform vs new platform, SQL vs DAX...).
``structural_checks`` runs the checks that must always pass between the source extract and the gold layer.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import pandas as pd

from .bronze import control_totals
from .kpi import KEYS, MEASURES, by_month_country_pandas, by_month_country_sql


@dataclass
class Check:
    check_id: str
    family: str
    name: str
    status: str  # pass, warn, fail
    observed: str
    expected: str = ""
    detail: str = ""
    failing: list = field(default_factory=list)  # items that fail (days, keys...), for drill-down

    def row(self) -> dict:
        d = asdict(self)
        d["n_failing"] = len(d.pop("failing"))
        return d


def compare(left: pd.DataFrame, right: pd.DataFrame, keys: list[str], measures: list[str],
            tolerance: float = 0, names=("left", "right")) -> pd.DataFrame:
    """Full outer join on ``keys``; one row per key with both values and the difference for each measure.

    A key present on one side only shows as a difference against zero, and ``presence`` says which side has it.
    """
    m = left[keys + measures].merge(right[keys + measures], on=keys, how="outer", suffixes=("_l", "_r"),
                                    indicator="presence")
    m["presence"] = m["presence"].map({"both": "both", "left_only": f"{names[0]} only",
                                       "right_only": f"{names[1]} only"})
    ok = pd.Series(True, index=m.index)
    for c in measures:
        lv, rv = m[f"{c}_l"].fillna(0), m[f"{c}_r"].fillna(0)
        m[f"{c}_diff"] = lv - rv
        ok &= (m[f"{c}_diff"].abs() <= tolerance)
    m["matches"] = ok & (m["presence"] == "both")
    return m.sort_values(keys, ignore_index=True)


def control_total_check(gold: dict, controls: pd.DataFrame) -> tuple[Check, pd.DataFrame]:
    f = gold["fact_sales_line"]
    cal = gold["dim_date"].set_index("date_key")["date"]
    ctry = gold["dim_country"].set_index("country_key")["country"]
    rep = (f.assign(date=f["date_key"].map(cal), country=f["country_key"].map(ctry))
           .groupby(["date", "country"], as_index=False).agg(rows=("row_id", "size"),
                                                              amount_milli=("amount_milli", "sum")))
    cmp = compare(controls, rep, ["date", "country"], ["rows", "amount_milli"], names=("source", "report"))
    bad = cmp[~cmp["matches"]]
    days = sorted(pd.to_datetime(bad["date"]).dt.strftime("%Y-%m-%d").unique())
    chk = Check("R1", "control totals", "Rows and amount per day and country match the source control totals",
                "pass" if bad.empty else "fail", f"{len(bad)} of {len(cmp)} day-country cells differ",
                "0 differences", f"{len(days)} days affected" if days else "", days)
    return chk, cmp


def structural_checks(bronze: pd.DataFrame, gold: dict,
                      controls: pd.DataFrame | None = None) -> tuple[list[Check], dict]:
    """Checks between the source extract and the gold layer. ``controls`` defaults to the totals of ``bronze``."""
    f = gold["fact_sales_line"]
    out, tables = [], {}
    controls = control_totals(bronze) if controls is None else controls
    chk, tables["control_totals"] = control_total_check(gold, controls)
    out.append(chk)

    n_src, n_fact = len(bronze), len(f)
    a_src, a_fact = int(bronze["amount_milli"].sum()), int(f["amount_milli"].sum())
    out.append(Check("R2", "conservation", "Every source line is in the fact table, once",
                     "pass" if n_src == n_fact and f["row_id"].is_unique else "fail",
                     f"{n_fact:,} fact lines, {f['row_id'].nunique():,} distinct", f"{n_src:,} source lines"))
    out.append(Check("R3", "conservation", "The fact table adds up to the source, to the thousandth of a pound",
                     "pass" if a_src == a_fact else "fail", f"{a_fact / 1000:,.3f} GBP", f"{a_src / 1000:,.3f} GBP"))
    unc = f[f["line_type"] == "unclassified"]
    out.append(Check("R4", "classification", "Every line has a known line type", "pass" if unc.empty else "fail",
                     f"{len(unc)} unclassified lines", "0", "", unc["row_id"].tolist()))

    for dim, key in [("dim_product", "product_key"), ("dim_customer", "customer_key"),
                     ("dim_country", "country_key"), ("dim_date", "date_key")]:
        d = gold[dim]
        orphans = f.loc[~f[key].isin(d[key]), key].unique().tolist()
        dup = int(d[key].duplicated().sum())
        out.append(Check(f"K-{dim}", "keys", f"Fact keys all exist in {dim}, and its keys are unique",
                         "pass" if not orphans and not dup else "fail",
                         f"{len(orphans)} orphan keys, {dup} duplicate keys", "0 and 0", "", orphans))

    pdx, sql = by_month_country_pandas(gold), by_month_country_sql(bronze)
    cmp = compare(pdx, sql, KEYS, MEASURES, names=("pipeline", "sql"))
    tables["dual_implementation"] = cmp
    bad = cmp[~cmp["matches"]]
    out.append(Check("R5", "dual implementation", "KPIs by month and country: pipeline and independent SQL agree",
                     "pass" if bad.empty else "fail", f"{len(bad)} of {len(cmp)} cells differ, "
                     f"{len(MEASURES)} measures each", "0 differences", "",
                     (bad["month"] + " " + bad["country"]).tolist()))
    return out, tables
