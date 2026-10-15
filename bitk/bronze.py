"""Bronze layer: the source extract, typed but otherwise untouched.

Prices in the source have at most three decimals, so amounts are stored as integers in thousandths of a pound
(``amount_milli``). Totals can then be compared exactly, with no floating-point tolerance.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path(__file__).resolve().parent.parent / "data" / "raw" / "onlineretail.rda"
RAW_SHA256 = "d686c7ec387fdc64fde3a5b6f1c31d43751735f4053f34c92e677beacf5e0664"
COLUMNS = ["row_id", "invoice_no", "stock_code", "description", "quantity", "invoice_ts", "unit_price_milli",
           "customer_id", "country", "amount_milli"]


def sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def from_source_frame(src: pd.DataFrame) -> pd.DataFrame:
    """Type the columns of the source extract (UCI Online Retail names) without changing any value."""
    price = src["UnitPrice"].to_numpy(dtype=float) * 1000
    milli = np.round(price)
    if np.abs(price - milli).max() > 1e-6:
        raise ValueError("a unit price has more than three decimals; amounts would not be exact")
    qty = src["Quantity"].to_numpy(dtype=float)
    if np.any(qty % 1):
        raise ValueError("non-integer quantity in the source")
    out = pd.DataFrame({
        "row_id": np.arange(len(src), dtype=np.int64),
        "invoice_no": src["InvoiceNo"].astype(str).to_numpy(),
        "stock_code": src["StockCode"].astype(str).to_numpy(),
        "description": src["Description"].astype("string").to_numpy(),
        "quantity": qty.astype(np.int64),
        "invoice_ts": pd.to_datetime(src["InvoiceDate"]).astype("datetime64[ns]").to_numpy(),
        "unit_price_milli": milli.astype(np.int64),
        "customer_id": pd.array(src["CustomerID"].to_numpy(), dtype="Int64"),
        "country": src["Country"].astype(str).to_numpy(),
    })
    out["amount_milli"] = out["quantity"] * out["unit_price_milli"]
    return out[COLUMNS]


def load_bronze(path: str | Path = RAW, check_hash: bool = True) -> pd.DataFrame:
    import pyreadr

    path = Path(path)
    if check_hash and sha256(path) != RAW_SHA256:
        raise ValueError(f"{path} is not the expected source file (SHA-256 differs)")
    frames = pyreadr.read_r(str(path))
    return from_source_frame(next(iter(frames.values())))


def control_totals(bronze: pd.DataFrame) -> pd.DataFrame:
    """What the source system would send alongside the extract: rows and amount per day and country."""
    d = bronze.assign(date=bronze["invoice_ts"].dt.normalize())
    return (d.groupby(["date", "country"], as_index=False)
            .agg(rows=("row_id", "size"), amount_milli=("amount_milli", "sum")))
