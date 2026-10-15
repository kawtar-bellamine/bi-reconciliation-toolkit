import pandas as pd
import pytest
from conftest import source_frame

from bitk.bridge import sales_bridge
from bitk.bronze import from_source_frame
from bitk.gold import build_gold
from bitk.kpi import MEASURES, by_month_country_pandas, by_month_country_sql, totals_pandas
from bitk.reconcile import compare, structural_checks
from bitk.rules import classify
from bitk.silver import build_silver


def test_amounts_are_exact_integers(small_bronze):
    assert small_bronze["amount_milli"].dtype == "int64"
    assert small_bronze.loc[0, "amount_milli"] == 6 * 2550


def test_four_decimal_price_is_refused():
    df = source_frame()
    df.loc[0, "UnitPrice"] = 2.5555
    with pytest.raises(ValueError):
        from_source_frame(df)


def test_classification_order(small_bronze):
    t = classify(small_bronze).tolist()
    assert t == ["product_sale", "product_sale", "probable_duplicate", "shipping", "product_sale",
                 "product_cancellation", "shipping", "stock_adjustment", "stock_adjustment", "bad_debt_adjustment",
                 "fees_and_charges", "gift_voucher", "manual_and_discount", "product_sale"]


def test_gold_keeps_every_line_and_unknown_customer(small_bronze):
    g = build_gold(build_silver(small_bronze))
    f = g["fact_sales_line"]
    assert len(f) == len(small_bronze)
    assert f["amount_milli"].sum() == small_bronze["amount_milli"].sum()
    assert -1 in set(g["dim_customer"]["customer_key"])
    # most frequent description wins, the count of descriptions is kept
    p = g["dim_product"].set_index("stock_code")
    assert p.loc["85123A", "n_descriptions"] == 2


def test_pandas_and_sql_kpis_agree(small_bronze):
    g = build_gold(build_silver(small_bronze))
    a, b = by_month_country_pandas(g), by_month_country_sql(small_bronze)
    cmp = compare(a, b, ["month", "country"], MEASURES)
    assert cmp["matches"].all()
    t = totals_pandas(g)
    assert t["gross_product_sales"] == 6 * 2550 + 6 * 3390 + 12 * 1850 + 2 * 2950
    assert t["product_cancellations"] == -2 * 1850
    assert t["orders"] == 3 and t["active_customers"] == 1
    assert t["unidentified_sales"] == 12 * 1850


def test_bridge_closes(small_bronze):
    f = build_gold(build_silver(small_bronze))["fact_sales_line"]
    br = sales_bridge(f).set_index("step")
    total = br.loc["All lines in the source extract", "amount_milli"]
    removed = br.loc[br["kind"] == "remove", "amount_milli"].sum()
    assert total + removed == br.loc["Net product sales (reference KPI)", "amount_milli"]


def test_structural_checks_pass_then_fail_on_a_lost_line(small_bronze):
    g = build_gold(build_silver(small_bronze))
    checks, _ = structural_checks(small_bronze, g)
    assert all(c.status == "pass" for c in checks)
    broken = small_bronze.drop(index=4).reset_index(drop=True)
    gb = build_gold(build_silver(broken))
    from bitk.bronze import control_totals
    checks, _ = structural_checks(broken, gb, controls=control_totals(small_bronze))
    status = {c.check_id: c.status for c in checks}
    assert status["R1"] == "fail"
    assert status["R5"] == "pass"  # both implementations agree on the broken data; only control totals see it


def test_compare_reports_one_sided_keys():
    a = pd.DataFrame({"k": ["x", "y"], "v": [1, 2]})
    b = pd.DataFrame({"k": ["x", "z"], "v": [1, 5]})
    cmp = compare(a, b, ["k"], ["v"], names=("old", "new")).set_index("k")
    assert cmp.loc["x", "matches"] and not cmp.loc["y", "matches"]
    assert cmp.loc["y", "presence"] == "old only" and cmp.loc["z", "v_diff"] == -5


def test_cli_exit_code(tmp_path):
    from bitk.__main__ import main
    pd.DataFrame({"m": ["a", "b"], "v": [1.0, 2.0]}).to_csv(tmp_path / "l.csv", index=False)
    pd.DataFrame({"m": ["a", "b"], "v": [1.0, 2.004]}).to_csv(tmp_path / "r.csv", index=False)
    args = [str(tmp_path / "l.csv"), str(tmp_path / "r.csv"), "--keys", "m", "--measures", "v"]
    assert main(args) == 1
    assert main(args + ["--tolerance", "0.005"]) == 0


def test_codes_without_description_get_a_placeholder():
    rows = [("536370", "99999", None, -5, "2010-12-03 12:00", 0.0, None, "United Kingdom"),
            ("536371", "22633", "HAND WARMER", 2, "2010-12-03 12:00", 1.85, 12583, "France")]
    from bitk.gold import NO_DESCRIPTION
    g = build_gold(build_silver(from_source_frame(source_frame(rows))))
    p = g["dim_product"].set_index("stock_code")
    assert p.loc["99999", "description"] == NO_DESCRIPTION and p.loc["99999", "n_descriptions"] == 0
