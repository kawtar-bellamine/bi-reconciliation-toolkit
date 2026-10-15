"""Reconciliation dashboard. Run with: streamlit run app/dashboard.py

Reads the files written by experiments/run_all.py; nothing is recomputed here.
"""
import json
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
st.set_page_config(page_title="BI reconciliation toolkit", layout="wide")


@st.cache_data
def load(name):
    p = RES / name
    return json.loads(p.read_text()) if p.suffix == ".json" else pd.read_csv(p)


S = load("summary.json")
PAGES = ["Overview", "Daily operations", "Reconciliation checks", "Sales bridge", "Daily anomalies", "Issue log",
         "KPI dictionary", "Fault tests"]
page = st.sidebar.radio("Page", PAGES)
st.sidebar.caption(f"Source: {S['source_lines']:,} lines, {S['first_date']} to {S['last_date']}, "
                   f"{S['countries']} countries. Amounts in GBP.")

if page == "Overview":
    st.title("Sales reporting, reconciled with its source")
    k = S["kpis"]
    c = st.columns(4)
    c[0].metric("Net product sales", f"{k['net_product_sales']:,.0f}")
    c[1].metric("Orders", f"{k['orders']:,}")
    c[2].metric("Average order value", f"{k['average_order_value']:,.2f}")
    c[3].metric("Cancellation rate", f"{k['cancellation_rate']:.1%}")
    c = st.columns(4)
    c[0].metric("Checks passed", S["checks_pass"])
    c[1].metric("Warnings (source data)", S["checks_warn"])
    c[2].metric("Failures", S["checks_fail"])
    c[3].metric("Sales without customer ID", f"{S['missing_customer_sales_share']:.1%}")
    m = load("naive_vs_reference.csv")
    long = m.melt("month", ["naive_milli", "net_product_sales_milli"], "series", "milli")
    long["GBP"] = long["milli"] / 1000
    long["series"] = long["series"].map({"naive_milli": "sum of all lines",
                                         "net_product_sales_milli": "net product sales (reference)"})
    st.subheader("Monthly sales: quick sum against the reference definition")
    st.altair_chart(alt.Chart(long).mark_line(point=True).encode(
        x="month:N", y=alt.Y("GBP:Q", title="GBP"), color="series:N", tooltip=["month", "series", "GBP"]),
        width="stretch")
    st.caption(f"The last month stops on {S['last_date']}: it is partial, not a fall in sales.")
    km = load("kpi_by_month.csv")
    st.subheader("Net product sales per trading day")
    km["partial"] = km["month"] == km["month"].max()
    st.altair_chart(alt.Chart(km).mark_bar().encode(
        x="month:N", y=alt.Y("net_sales_per_trading_day:Q", title="GBP per trading day"),
        color=alt.Color("partial:N", scale=alt.Scale(domain=[False, True], range=["#1f3b5c", "#c0504d"]),
                        legend=alt.Legend(title="partial month")),
        tooltip=["month", "trading_days", alt.Tooltip("net_sales_per_trading_day:Q", format=",.0f")]),
        width="stretch")

elif page == "Daily operations":
    st.title("Daily operations")
    d = load("daily_kpis.csv")
    d["date"] = pd.to_datetime(d["date"])
    issues = load("issue_log.csv")
    day = st.select_slider("Trading day", options=list(d["date"].dt.date), value=d["date"].dt.date.iloc[-1])
    row = d[d["date"].dt.date == day].iloc[0]
    last = d["date"].max()
    if pd.Timestamp(day) == last:
        st.warning(f"Data stops on {last:%Y-%m-%d}: this is the last day of the extract and may be incomplete.")
    st.caption("Expected = level of the surrounding trading days, adjusted for the weekday (see the anomaly test).")
    c = st.columns(4)
    for col, (k, label, fmt) in zip(c, [("net_product_sales", "Net product sales", "{:,.0f}"),
                                        ("gross_product_sales", "Gross product sales", "{:,.0f}"),
                                        ("orders", "Orders", "{:,.0f}"), ("lines", "Lines", "{:,.0f}")]):
        exp = row[f"{k}_expected"]
        delta = (row[k] - exp) / exp if exp else None
        col.metric(label, fmt.format(row[k]), f"{delta:+.0%} vs expected" if delta is not None else None,
                   delta_color="off")
    flags = [k for k in ["gross_product_sales", "net_product_sales", "lines", "orders", "unidentified_share"]
             if row[f"{k}_flag"]]
    if flags:
        st.error("Flagged by the anomaly test on: " + ", ".join(flags))
    else:
        st.success("No anomaly flagged on this day.")
    st.metric("Share of sales without customer ID", f"{row['unidentified_share']:.1%}")
    st.subheader("Open issues to keep in mind when reading this day")
    st.dataframe(issues[issues["severity"] == "high"][["issue_id", "title", "kpis_affected", "action"]],
                 width="stretch", hide_index=True)

elif page == "Reconciliation checks":
    st.title("Checks")
    c = load("checks.csv")
    fam = st.multiselect("Family", sorted(c["family"].unique()), default=sorted(c["family"].unique()))
    st.dataframe(c[c["family"].isin(fam)][["check_id", "family", "name", "status", "observed", "expected",
                                           "detail", "n_failing"]], width="stretch", hide_index=True)
    st.subheader("KPIs by month and country (pipeline, checked against SQL)")
    mc = load("kpi_by_month_country.csv")
    country = st.selectbox("Country", ["All"] + sorted(mc["country"].unique()))
    st.dataframe(mc if country == "All" else mc[mc["country"] == country], width="stretch",
                 hide_index=True)

elif page == "Sales bridge":
    st.title("From the source total to net product sales")
    b = load("sales_bridge.csv")
    w = b[b["kind"] != "detail"].copy()
    run, starts, ends = 0.0, [], []
    for kind, amt in zip(w["kind"], w["amount_gbp"]):
        start = 9e6 if kind == "total" else run
        end = amt if kind == "total" else run + amt
        starts.append(start)
        ends.append(end)
        run = end
    w["start"], w["end"] = starts, ends
    w["effect"] = np.where(w["kind"] == "total", "total", np.where(w["amount_gbp"] < 0, "lowers", "raises"))
    w["label"] = w["step"].str.replace("less ", "", regex=False).str.replace(" (reference KPI)", "", regex=False)
    w["order"] = range(len(w))
    st.altair_chart(alt.Chart(w).mark_bar().encode(
        x=alt.X("label:N", sort=alt.SortField("order"), title=None,
                axis=alt.Axis(labelAngle=-30, labelLimit=260, labelOverlap=False)),
        y=alt.Y("start:Q", title="GBP (axis starts at 9 million)", scale=alt.Scale(domain=[9e6, 10e6])), y2="end:Q",
        color=alt.Color("effect:N", scale=alt.Scale(domain=["total", "lowers", "raises"],
                                                    range=["#1f3b5c", "#c0504d", "#4f8a5b"])),
        tooltip=["step", "lines", alt.Tooltip("amount_gbp:Q", format=",.2f")]).properties(height=420),
        width="stretch")
    st.dataframe(b[["step", "lines", "amount_gbp"]], width="stretch", hide_index=True)

elif page == "Daily anomalies":
    st.title("Days that do not look like their neighbours")
    d = load("daily_kpis.csv")
    d["date"] = pd.to_datetime(d["date"])
    series = st.selectbox("KPI", ["gross_product_sales", "net_product_sales", "lines", "orders",
                                  "unidentified_share"])
    base = alt.Chart(d).encode(x="date:T")
    line = base.mark_line(opacity=0.6).encode(y=alt.Y(f"{series}:Q"))
    pts = base.transform_filter(f"datum.{series}_flag").mark_point(color="#c0504d", size=70, filled=True).encode(
        y=f"{series}:Q", tooltip=["date:T", f"{series}:Q", alt.Tooltip(f"{series}_z:Q", format=".1f")])
    st.altair_chart((line + pts).properties(height=380), width="stretch")
    st.dataframe(load("daily_anomalies.csv"), width="stretch", hide_index=True)

elif page == "Issue log":
    st.title("Issue log")
    i = load("issue_log.csv")
    sev = st.multiselect("Severity", ["high", "medium", "low"], default=["high", "medium", "low"])
    st.dataframe(i[i["severity"].isin(sev)], width="stretch", hide_index=True)
    st.caption("Counts and values are measured. Causes are hypotheses to confirm with the owner named.")

elif page == "KPI dictionary":
    st.title("KPI dictionary")
    st.dataframe(pd.read_csv(ROOT / "kpi" / "kpi_dictionary.csv"), width="stretch", hide_index=True)
    st.dataframe(load("kpi_reference.csv"), width="stretch", hide_index=True)

else:
    st.title("Fault injection: which checks notice what")
    f = load("fault_summary.csv").set_index("fault")
    long = f.reset_index().melt("fault", var_name="family", value_name="detected")
    st.altair_chart(alt.Chart(long).mark_rect().encode(
        x=alt.X("family:N", sort=None), y=alt.Y("fault:N", sort=None),
        color=alt.Color("detected:Q", scale=alt.Scale(domain=[0, 1], scheme="blues")),
        tooltip=["fault", "family", alt.Tooltip("detected:Q", format=".0%")]).properties(height=320),
        width="stretch")
    st.dataframe(load("fault_benchmark.csv"), width="stretch", hide_index=True)
