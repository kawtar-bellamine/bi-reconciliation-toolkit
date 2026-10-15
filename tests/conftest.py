import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bitk.bronze import from_source_frame  # noqa: E402

ROWS = [
    # InvoiceNo, StockCode, Description, Quantity, InvoiceDate, UnitPrice, CustomerID, Country
    ("536365", "85123A", "WHITE HANGING HEART", 6, "2010-12-01 08:26", 2.55, 17850, "United Kingdom"),
    ("536365", "71053", "WHITE METAL LANTERN", 6, "2010-12-01 08:26", 3.39, 17850, "United Kingdom"),
    ("536365", "71053", "WHITE METAL LANTERN", 6, "2010-12-01 08:26", 3.39, 17850, "United Kingdom"),  # duplicate
    ("536366", "POST", "POSTAGE", 1, "2010-12-01 09:00", 18.00, 12583, "France"),
    ("536367", "22633", "HAND WARMER", 12, "2010-12-02 10:00", 1.85, None, "France"),
    ("C536368", "22633", "HAND WARMER", -2, "2010-12-03 11:00", 1.85, 12583, "France"),
    ("C536369", "POST", "POSTAGE", -1, "2010-12-03 11:05", 18.00, 12583, "France"),
    ("536370", "22139", None, 50, "2010-12-03 12:00", 0.0, None, "United Kingdom"),  # stock movement
    ("536371", "22139", "damaged", -20, "2011-01-04 12:00", 0.0, None, "United Kingdom"),
    ("A563185", "B", "Adjust bad debt", 1, "2011-01-04 14:00", 11062.06, None, "United Kingdom"),
    ("536372", "AMAZONFEE", "AMAZON FEE", 1, "2011-01-05 09:00", 135.0, None, "United Kingdom"),
    ("536373", "gift_0001_20", "Gift Voucher 20", 1, "2011-01-05 09:30", 17.02, None, "United Kingdom"),
    ("536374", "m", "Manual", 1, "2011-01-05 10:00", 2.55, 14096, "United Kingdom"),
    ("536375", "85123A", "CREAM HANGING HEART", 2, "2011-01-06 10:00", 2.95, 17850, "United Kingdom"),
]


def source_frame(rows=ROWS) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["InvoiceNo", "StockCode", "Description", "Quantity", "InvoiceDate",
                                     "UnitPrice", "CustomerID", "Country"])
    df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"])
    df["Quantity"] = df["Quantity"].astype(float)
    df["CustomerID"] = df["CustomerID"].astype(float)
    return df


@pytest.fixture
def small_bronze():
    return from_source_frame(source_frame())


@pytest.fixture(scope="session")
def real_run():
    from bitk.pipeline import run
    return run()
