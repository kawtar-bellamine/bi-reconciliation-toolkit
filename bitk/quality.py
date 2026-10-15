"""Source data quality: what is wrong or ambiguous in the source, measured, with its effect on the KPIs.

Each finding becomes a row of the issue log. Causes are hypotheses for the source owner to confirm; the counts
and values are measured.
"""
from __future__ import annotations

import pandas as pd

from .reconcile import Check

NON_COUNTRIES = ("Unspecified", "European Community")
LINE_COLS = ["row_id", "invoice_no", "invoice_ts", "stock_code", "description", "quantity", "unit_price_milli",
             "customer_id", "country", "line_type", "amount_milli"]


def _gbp(milli) -> float:
    return round(float(milli) / 1000, 2)


def matched_cancellations(silver: pd.DataFrame) -> pd.DataFrame:
    """For each product cancellation with a customer ID, the latest earlier sale of the same product to the same
    customer with the same quantity, if any."""
    c = silver[(silver["line_type"] == "product_cancellation") & ~silver["customer_missing"]]
    s = silver[(silver["line_type"] == "product_sale") & ~silver["customer_missing"]]
    c = c[["row_id", "invoice_no", "customer_id", "stock_code", "quantity", "invoice_ts", "amount_milli"]].copy()
    c["abs_qty"] = -c["quantity"]
    s = s[["customer_id", "stock_code", "quantity", "invoice_ts", "invoice_no"]].rename(
        columns={"quantity": "abs_qty", "invoice_ts": "sale_ts", "invoice_no": "sale_invoice"})
    m = c.merge(s, on=["customer_id", "stock_code", "abs_qty"], how="left")
    m = m[m["sale_ts"].isna() | (m["sale_ts"] <= m["invoice_ts"])]
    m = m.sort_values("sale_ts").groupby("row_id", as_index=False).last()
    any_earlier = (silver.loc[(silver["line_type"] == "product_sale") & ~silver["customer_missing"],
                              ["customer_id", "stock_code", "invoice_ts"]]
                   .rename(columns={"invoice_ts": "t"}))
    e = c.merge(any_earlier, on=["customer_id", "stock_code"], how="left")
    e = e.assign(ok=e["t"].notna() & (e["t"] <= e["invoice_ts"])).groupby("row_id")["ok"].any()
    m = c[["row_id"]].merge(m.drop(columns=[x for x in c.columns if x != "row_id"]), on="row_id", how="left") \
        .merge(c, on="row_id")
    m["has_earlier_sale_any_qty"] = m["row_id"].map(e).fillna(False).astype(bool)
    m["same_day"] = m["sale_ts"].notna() & (m["sale_ts"].dt.normalize() == m["invoice_ts"].dt.normalize())
    return m


def quality_checks(silver: pd.DataFrame, gold: dict) -> tuple[list[Check], list[dict], dict]:
    s = silver
    sale = s["line_type"] == "product_sale"
    gross = int(s.loc[sale, "amount_milli"].sum())
    checks, issues, tables = [], [], {}
    samples = tables["samples"] = {}

    def add(cid, name, status, observed, issue=None, failing=None, detail=""):
        checks.append(Check(cid, "source data quality", name, status, observed, "", detail, failing or []))
        if issue:
            v = issue.get("value_gbp")
            share = abs(v) / (gross / 1000) if v is not None and gross else 0
            sev = issue.pop("severity", None) or ("high" if share >= 0.01 else "medium" if share >= 0.001 else "low")
            issues.append({"issue_id": f"DQ-{len(issues) + 1:02d}", "check_id": cid, "title": name,
                           "severity": sev, "status": "open", **issue,
                           "share_of_gross_sales": round(share, 4) if v is not None else None})

    # customer ID
    miss = s["customer_missing"]
    v = int(s.loc[sale & miss, "amount_milli"].sum())
    add("Q1", "Lines without a customer ID", "warn",
        f"{int(miss.sum()):,} lines ({miss.mean():.1%}); {v / gross:.1%} of gross product sales",
        {"lines": int(miss.sum()), "value_gbp": _gbp(v), "kpis_affected": "active_customers, any per-customer KPI",
         "likely_cause": "guest checkouts or orders keyed without an account",
         "action": "keep in sales totals under an 'unknown customer' member; ask the source owner whether an "
                   "account can be recovered", "owner": "source system owner"})

    samples["Q1"] = s.loc[sale & miss, LINE_COLS].nlargest(5, "amount_milli")
    dup = s["line_type"] == "probable_duplicate"
    v = int(s.loc[dup, "amount_milli"].sum())
    add("Q2", "Probable duplicate lines (identical in every column)", "warn",
        f"{int(dup.sum()):,} lines on {s.loc[dup, 'invoice_no'].nunique():,} invoices, {_gbp(v):,.2f} GBP",
        {"lines": int(dup.sum()), "value_gbp": _gbp(v), "kpis_affected": "gross and net product sales, units",
         "likely_cause": "the same item scanned twice on one invoice, or a duplicated extract row",
         "action": "excluded from the reference KPIs; confirm with the source owner on a sample of invoices",
         "owner": "source system owner"})

    first_dup = s.loc[dup, LINE_COLS].head(3)
    samples["Q2"] = pd.concat([s.loc[(s["invoice_no"] == r.invoice_no) & (s["stock_code"] == r.stock_code)
                                     & (s["invoice_ts"] == r.invoice_ts), LINE_COLS] for r in first_dup.itertuples()])
    mc = matched_cancellations(s)
    tables["cancellations"] = mc
    sd = mc[mc["same_day"]]
    top = sd.nsmallest(3, "amount_milli")
    add("Q3", "Orders cancelled the same day they were placed", "warn",
        f"{len(sd):,} cancellation lines, {_gbp(-sd['amount_milli'].sum()):,.2f} GBP of gross sales cancelled",
        {"lines": len(sd), "value_gbp": _gbp(-sd["amount_milli"].sum()),
         "kpis_affected": "gross product sales, average order value (net sales unaffected)",
         "likely_cause": "order entry mistakes corrected by a cancellation invoice",
         "action": "report net product sales as the reference; show gross only next to it",
         "owner": "BI team"},
        detail="largest: " + "; ".join(f"invoice {r.sale_invoice} cancelled by {r.invoice_no}, "
                                       f"{_gbp(-r.amount_milli):,.2f} GBP" for r in top.itertuples()))
    pair_cols = ["sale_invoice", "sale_ts", "invoice_no", "invoice_ts", "customer_id", "stock_code", "abs_qty",
                 "amount_milli"]
    samples["Q3"] = sd.nsmallest(5, "amount_milli")[pair_cols]
    orphan = mc[~mc["has_earlier_sale_any_qty"]]
    samples["Q4"] = orphan.nsmallest(5, "amount_milli")[["invoice_no", "invoice_ts", "customer_id", "stock_code",
                                                         "abs_qty", "amount_milli"]]
    first_month = s["month"].min()
    n_first = int((orphan["invoice_ts"].dt.to_period("M").astype(str) == first_month).sum())
    add("Q4", "Cancellations with no earlier sale of that product to that customer in the data", "warn",
        f"{len(orphan):,} of {len(mc):,} lines with a customer ID; {n_first:,} of them in {first_month}",
        {"lines": len(orphan), "value_gbp": _gbp(orphan["amount_milli"].sum()),
         "kpis_affected": "net product sales of the first months",
         "likely_cause": "the original sale happened before the start of the extract",
         "action": "do not read the first months' net sales as a trend; extend the extract back if possible",
         "owner": "BI team"})

    nd = gold["dim_product"]
    multi = nd[nd["n_descriptions"] > 1]
    add("Q5", "Product codes with more than one description", "warn",
        f"{len(multi):,} of {len(nd):,} codes", {"lines": None, "value_gbp": None, "severity": "medium",
        "kpis_affected": "product-level reports (a product can appear under two names)",
        "likely_cause": "descriptions edited over time, or used as free-text notes (damaged, found...)",
        "action": "report on the code; the dimension keeps the most frequent description",
        "owner": "master data owner"}, multi["stock_code"].tolist())

    samples["Q5"] = multi.nlargest(5, "n_descriptions")[["stock_code", "description", "n_descriptions"]]
    cust = gold["dim_customer"]
    mcust = cust[cust["n_countries"] > 1]
    add("Q6", "Customers recorded in more than one country", "warn", f"{len(mcust)} customers",
        {"lines": None, "value_gbp": None, "severity": "low",
         "kpis_affected": "customers by country (a customer counted in two countries)",
         "likely_cause": "address changes or several delivery addresses",
         "action": "country comes from the invoice in sales reports; the customer dimension keeps the main one",
         "owner": "master data owner"}, mcust["customer_key"].tolist())

    samples["Q6"] = mcust[["customer_key", "main_country", "n_countries"]].head(5)
    ts = s.groupby("invoice_no")["invoice_ts"].nunique()
    multi_ts = ts[ts > 1].index.tolist()
    add("Q7", "Invoices with lines at different timestamps", "warn", f"{len(multi_ts)} invoices",
        {"lines": int(s["invoice_no"].isin(multi_ts).sum()), "value_gbp": None, "severity": "low",
         "kpis_affected": "none at month level; an invoice can split across two days in daily reports",
         "likely_cause": "an invoice entered across a minute boundary", "action": "none needed for monthly KPIs",
         "owner": "BI team"}, multi_ts)

    samples["Q7"] = (s[s["invoice_no"].isin(multi_ts[:2])].groupby(["invoice_no", "invoice_ts"])
                     .agg(lines=("row_id", "size")).reset_index())
    adj = s[s["line_type"] == "stock_adjustment"]
    samples["Q8"] = adj.nsmallest(5, "quantity")[LINE_COLS]
    add("Q8", "Zero-price stock movements in the sales table", "warn",
        f"{len(adj):,} lines, {int(adj.loc[adj['quantity'] > 0, 'quantity'].sum()):,} units in and "
        f"{int(-adj.loc[adj['quantity'] < 0, 'quantity'].sum()):,} units out, 0 GBP",
        {"lines": len(adj), "value_gbp": 0.0, "severity": "medium",
         "kpis_affected": "units sold if counted naively",
         "likely_cause": "inventory corrections (damaged, found, thrown away) recorded as invoice lines",
         "action": "excluded from units sold; worth a separate inventory report", "owner": "BI team"})

    nc = s[s["country"].isin(NON_COUNTRIES)]
    samples["Q9"] = nc.groupby(["country", "line_type"]).agg(lines=("row_id", "size")).reset_index()
    add("Q9", "Country values that are not countries", "warn",
        f"{len(nc):,} lines ({', '.join(NON_COUNTRIES)}), "
        f"{_gbp(nc.loc[nc['line_type'] == 'product_sale', 'amount_milli'].sum()):,.2f} GBP of sales",
        {"lines": len(nc), "value_gbp": _gbp(nc.loc[nc["line_type"] == "product_sale", "amount_milli"].sum()),
         "kpis_affected": "sales by country", "likely_cause": "default or regional values in the order form",
         "action": "keep as their own members; ask the source owner for the delivery country",
         "owner": "source system owner"})

    cal = gold["dim_date"]
    gaps = cal[cal["expected_trading_day"] & ~cal["has_sales"]]
    hol_sales = cal[(cal["bank_holiday"] != "") & cal["has_sales"]]
    samples["Q10"] = gaps[["date", "weekday"]]
    add("Q10", "Expected trading days with no sales (Saturdays and bank holidays excluded)",
        "warn" if len(gaps) else "pass",
        f"{len(gaps)} days; {len(hol_sales)} bank holidays with sales",
        {"lines": None, "value_gbp": None, "severity": "low",
         "kpis_affected": "daily and weekly reports",
         "likely_cause": "closure days outside the bank holiday list: "
                         + ", ".join(gaps["date"].dt.strftime("%d %b %Y")),
         "action": "add closure days to the business calendar so they are not flagged",
         "owner": "BI team"} if len(gaps) else None, gaps["date"].dt.strftime("%Y-%m-%d").tolist())

    last_month = cal["month"].max()
    lm = cal[cal["month"] == last_month]
    full = cal.groupby("month")["has_sales"].sum()
    typical = int(full.drop(last_month).median())
    samples["Q11"] = full.rename("trading_days").reset_index().tail(4)
    add("Q11", "Last month is incomplete", "warn" if lm["date"].max().day < lm["date"].max().days_in_month else "pass",
        f"{last_month}: data until {lm['date'].max():%Y-%m-%d}, {int(lm['has_sales'].sum())} trading days "
        f"against a median of {typical}",
        {"lines": int((s["month"] == last_month).sum()), "value_gbp": None, "severity": "high",
         "kpis_affected": "every monthly KPI and month-on-month change",
         "likely_cause": "the extract stops on the day it was taken",
         "action": "label the month as partial, or compare per trading day", "owner": "BI team"})

    ps = s[sale]
    med = ps.groupby("stock_code")["unit_price_milli"].transform("median")
    out = ps[(ps["unit_price_milli"] > 20 * med) & (ps["unit_price_milli"] > 10_000)]
    add("Q12", "Sale prices over 20 times the product's median price (and over 10 GBP)",
        "warn" if len(out) else "pass",
        f"{len(out)} lines, {_gbp(out['amount_milli'].sum()):,.2f} GBP; {int(out['customer_missing'].sum())} of "
        "them without a customer ID",
        {"lines": len(out), "value_gbp": _gbp(out["amount_milli"].sum()),
         "kpis_affected": "sales of the products concerned",
         "likely_cause": "keying errors, or a different price list for orders without a customer ID",
         "action": "review the lines with the sales team", "owner": "sales operations"} if len(out) else None,
        out["row_id"].tolist())
    tables["price_outliers"] = out
    samples["Q12"] = out.assign(median_price_milli=med[out.index]).nlargest(5, "amount_milli")[
        LINE_COLS + ["median_price_milli"]]

    nodesc = nd[nd["n_descriptions"] == 0]
    lines_nd = s[s["stock_code"].isin(nodesc["stock_code"])]
    add("Q13", "Product codes that never have a description", "warn" if len(nodesc) else "pass",
        f"{len(nodesc)} codes, seen on {len(lines_nd)} lines, all of them "
        f"{', '.join(sorted(lines_nd['line_type'].unique()))}",
        {"lines": len(lines_nd), "value_gbp": _gbp(lines_nd["amount_milli"].sum()), "severity": "low",
         "kpis_affected": "none (no money on these lines); product lists show a placeholder name",
         "likely_cause": "stock corrections keyed on codes that were never set up in the catalogue",
         "action": "the product dimension shows '(no description in source)'; ask master data whether the codes "
                   "should exist", "owner": "master data owner"} if len(nodesc) else None,
        nodesc["stock_code"].tolist())
    samples["Q13"] = lines_nd[LINE_COLS].head(5)
    return checks, issues, tables
