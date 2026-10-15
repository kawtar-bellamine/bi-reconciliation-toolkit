"""Integration tests on the real extract (about 20 seconds)."""
import json
from pathlib import Path

import pytest

from bitk import faults
from bitk.bronze import RAW, sha256

SUMMARY = Path(__file__).resolve().parent.parent / "results" / "summary.json"


def test_source_file_is_the_expected_one():
    assert sha256(RAW) == "d686c7ec387fdc64fde3a5b6f1c31d43751735f4053f34c92e677beacf5e0664"


def test_every_structural_check_passes(real_run):
    c = real_run["checks"]
    structural = c[c["family"] != "source data quality"]
    assert (structural["status"] == "pass").all(), structural[structural["status"] != "pass"]


def test_results_in_the_repository_are_current(real_run):
    s = json.loads(SUMMARY.read_text())
    assert s["source_lines"] == len(real_run["silver"]) == 541909
    assert s["kpis"]["net_product_sales"] == round(real_run["kpi_totals"]["net_product_sales"] / 1000, 2)
    assert s["dual_matching"] == s["dual_cells"]


def test_partial_last_month_is_reported(real_run):
    q = real_run["checks"].set_index("check_id")
    assert q.loc["Q11", "status"] == "warn" and "2011-12-09" in q.loc["Q11", "observed"]


@pytest.mark.parametrize("fault,family", [("missing_day", "control totals"),
                                          ("new_product_codes", "reference data"),
                                          ("customer_join_lost", "statistics only")])
def test_injected_fault_is_caught(real_run, fault, family):
    ref = faults.Reference.from_clean(real_run["bronze"])
    row = faults.run_fault(real_run["bronze"], ref, fault, seed=0)
    assert row[family], row


def test_daily_figures_add_up_to_months(real_run):
    d = real_run["daily_scores"]
    month = d.groupby(d["date"].dt.to_period("M").astype(str))["net_product_sales"].sum()
    ref = real_run["kpi_by_month_country"].groupby("month")["net_product_sales"].sum() / 1000
    assert (month - ref).abs().max() < 0.01


def test_cancelled_order_flags_gross_not_net(real_run):
    a = real_run["anomalies"].set_index("date_key")
    assert a.loc[20110118, "gross_product_sales_flag"] and not a.loc[20110118, "net_product_sales_flag"]


def test_every_issue_gets_an_escalation_note(real_run, tmp_path):
    from bitk.escalation import window_label, write_notes
    paths = write_notes(real_run["issues"], real_run["checks"], real_run["samples"], tmp_path,
                        window_label(real_run["silver"]))
    assert len(paths) == len(real_run["issues"])
    text = (tmp_path / "DQ-03.md").read_text()
    assert "581483" in text and "## Evidence" in text
    assert (tmp_path / "README.md").exists()
