"""Silver layer: bronze plus one line type per line and the flags the checks need. Nothing is removed."""
from __future__ import annotations

import pandas as pd

from .rules import classify


def build_silver(bronze: pd.DataFrame) -> pd.DataFrame:
    s = bronze.copy()
    s["line_type"] = classify(bronze)
    s["date"] = s["invoice_ts"].dt.normalize()
    s["month"] = s["invoice_ts"].dt.to_period("M").astype(str)
    s["customer_missing"] = s["customer_id"].isna()
    s["description_missing"] = s["description"].isna()
    return s
