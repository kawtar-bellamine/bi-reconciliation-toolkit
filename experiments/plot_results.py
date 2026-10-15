"""Figures for the README, from the files in results/."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RES, FIG = ROOT / "results", ROOT / "results" / "figures"
NAVY, RED, GREY, GREEN = "#1f3b5c", "#c0504d", "#9aa5b1", "#4f8a5b"
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})


def bridge():
    b = pd.read_csv(RES / "sales_bridge.csv")
    w = b[b["kind"] != "detail"].reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(10, 4.8))
    run = 0.0
    for i, r in w.iterrows():
        v = r["amount_gbp"] / 1e6
        if r["kind"] == "total":
            ax.bar(i, v, color=NAVY)
            run = v
            ax.text(i, v + 0.08, f"{v:,.3f} M", ha="center", fontsize=9)
        else:
            ax.bar(i, v, bottom=run, color=RED if v < 0 else GREEN)
            ax.text(i, max(run, run + v) + 0.08, f"{v * 1000:+,.1f} k", ha="center", fontsize=8)
            run += v
    labels = [s.replace("less ", "").replace(" (reference KPI)", "").replace(", ", ",\n") for s in w["step"]]
    ax.set_xticks(range(len(w)), labels, rotation=30, ha="right", fontsize=8)
    ax.set_ylim(9.0, 10.3)
    ax.set_ylabel("million GBP (axis starts at 9)")
    ax.set_title("From the total of every source line to net product sales")
    fig.tight_layout()
    fig.savefig(FIG / "fig1_sales_bridge.png", dpi=150)


def monthly():
    m = pd.read_csv(RES / "kpi_by_month.csv")
    n = pd.read_csv(RES / "naive_vs_reference.csv")
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    x = np.arange(len(m))
    ax[0].plot(x, n["naive_milli"] / 1e9, "o-", color=GREY, label="sum of all lines")
    ax[0].plot(x, m["net_product_sales"] / 1e6, "o-", color=NAVY, label="net product sales")
    ax[0].set_title("Monthly total: the last month looks like a collapse")
    ax[0].set_ylabel("million GBP")
    ax[0].legend(frameon=False)
    ax[1].bar(x, m["net_sales_per_trading_day"] / 1e3, color=[NAVY] * (len(m) - 1) + [RED])
    ax[1].set_title("Per trading day: the last month is in line")
    ax[1].set_ylabel("thousand GBP per trading day")
    for a in ax:
        a.set_xticks(x, m["month"], rotation=45, ha="right", fontsize=8)
    ax[1].text(len(m) - 1, m["net_sales_per_trading_day"].iloc[-1] / 1e3 + 1,
               f"{int(m['trading_days'].iloc[-1])} days", ha="center", fontsize=8, color=RED)
    fig.tight_layout()
    fig.savefig(FIG / "fig2_partial_month.png", dpi=150)


def anomalies():
    d = pd.read_csv(RES / "daily_kpis.csv", parse_dates=["date"])
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(d["date"], d["gross_product_sales"] / 1e3, color=GREY, lw=1, label="gross product sales")
    ax.plot(d["date"], d["net_product_sales"] / 1e3, color=NAVY, lw=1, label="net product sales")
    g = d[d["gross_product_sales_flag"] & ~d["net_product_sales_flag"]]
    ax.scatter(g["date"], g["gross_product_sales"] / 1e3, color=RED, zorder=3,
               label="flagged on gross only (order cancelled the same day)")
    f = d[d["net_product_sales_flag"]]
    ax.scatter(f["date"], f["net_product_sales"] / 1e3, facecolor="none", edgecolor=NAVY, zorder=3,
               label="flagged on net sales")
    ax.set_ylabel("thousand GBP")
    ax.set_title("Daily sales and the days the robust test flags")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig(FIG / "fig3_daily_anomalies.png", dpi=150)


def faults():
    f = pd.read_csv(RES / "fault_summary.csv").set_index("fault")
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    im = ax.imshow(f.to_numpy(), cmap="Blues", vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(f.shape[1]), f.columns, rotation=20, ha="right")
    ax.set_yticks(range(f.shape[0]), [i.replace("_", " ") for i in f.index])
    for i in range(f.shape[0]):
        for j in range(f.shape[1]):
            v = f.iat[i, j]
            ax.text(j, i, f"{v:.0%}", ha="center", va="center", color="white" if v > 0.6 else "black", fontsize=9)
    ax.set_title("Share of injected faults each family of checks detects")
    fig.colorbar(im, ax=ax, fraction=0.03)
    fig.tight_layout()
    fig.savefig(FIG / "fig4_fault_detection.png", dpi=150)


if __name__ == "__main__":
    FIG.mkdir(parents=True, exist_ok=True)
    bridge(), monthly(), anomalies(), faults()
