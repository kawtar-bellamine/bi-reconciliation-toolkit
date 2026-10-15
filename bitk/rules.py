"""Line classification: every source line gets exactly one ``line_type``, nothing is dropped.

The rules are applied in this order, and the first one that matches wins:

1. ``bad_debt_adjustment``: invoice numbers starting with ``A`` (accounting entries, not sales).
2. ``probable_duplicate``: a line identical in every column to an earlier line. Kept, tagged and logged, because
   only the source owner can say whether the same item was really scanned twice.
3. Service codes (case-insensitive), whatever the invoice type: ``shipping``, ``fees_and_charges``,
   ``manual_and_discount``, ``gift_voucher``.
4. ``product_cancellation``: invoice numbers starting with ``C``.
5. ``stock_adjustment``: lines at a zero price (damaged, found, thrown away...). They move quantities, not money.
6. ``product_sale``: positive quantity and positive price.
7. ``unclassified``: anything else. It should stay empty; a check fails if it does not.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

SERVICE_CODES = {
    "POST": "shipping", "DOT": "shipping", "C2": "shipping",
    "AMAZONFEE": "fees_and_charges", "BANK CHARGES": "fees_and_charges", "CRUK": "fees_and_charges",
    "M": "manual_and_discount", "D": "manual_and_discount", "S": "manual_and_discount",
}
GIFT_VOUCHER = re.compile(r"^GIFT_\d{4}_\d+$")
LINE_TYPES = ["product_sale", "product_cancellation", "stock_adjustment", "shipping", "fees_and_charges",
              "manual_and_discount", "gift_voucher", "bad_debt_adjustment", "probable_duplicate", "unclassified"]
SALES_TYPES = ("product_sale", "product_cancellation")


def service_category(stock_code: pd.Series) -> pd.Series:
    up = stock_code.str.upper()
    cat = up.map(SERVICE_CODES)
    return cat.mask(up.str.match(GIFT_VOUCHER.pattern), "gift_voucher")


def classify(bronze: pd.DataFrame) -> pd.Series:
    inv = bronze["invoice_no"]
    raw_cols = ["invoice_no", "stock_code", "description", "quantity", "invoice_ts", "unit_price_milli",
                "customer_id", "country"]
    dup = bronze.duplicated(subset=raw_cols, keep="first").to_numpy()
    service = service_category(bronze["stock_code"])
    conditions = [
        inv.str.startswith("A").to_numpy(),
        dup,
        service.notna().to_numpy(),
        inv.str.startswith("C").to_numpy(),
        (bronze["unit_price_milli"] == 0).to_numpy(),
        ((bronze["quantity"] > 0) & (bronze["unit_price_milli"] > 0)).to_numpy(),
    ]
    choices = ["bad_debt_adjustment", "probable_duplicate", "SERVICE", "product_cancellation", "stock_adjustment",
               "product_sale"]
    out = pd.Series(np.select(conditions, choices, default="unclassified"), index=bronze.index)
    return out.mask(out == "SERVICE", service)
