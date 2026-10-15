"""Business calendar. The shop does not trade on Saturdays, so a missing Saturday is not a gap.

Bank holidays in England and Wales over the data window, from the UK government list (gov.uk/bank-holidays).
"""
from __future__ import annotations

import pandas as pd

BANK_HOLIDAYS = {
    "2010-12-27": "Christmas Day (substitute day)",
    "2010-12-28": "Boxing Day (substitute day)",
    "2011-01-03": "New Year's Day (substitute day)",
    "2011-04-22": "Good Friday",
    "2011-04-25": "Easter Monday",
    "2011-04-29": "Royal wedding",
    "2011-05-02": "Early May bank holiday",
    "2011-05-30": "Spring bank holiday",
    "2011-08-29": "Summer bank holiday",
}
NON_TRADING_WEEKDAY = 5  # Saturday


def build_calendar(first: pd.Timestamp, last: pd.Timestamp, trading_dates) -> pd.DataFrame:
    dates = pd.date_range(first.normalize(), last.normalize(), freq="D")
    traded = set(pd.to_datetime(list(trading_dates)).normalize())
    hol = {pd.Timestamp(k): v for k, v in BANK_HOLIDAYS.items()}
    cal = pd.DataFrame({"date": dates})
    cal["date_key"] = (cal["date"].dt.year * 10000 + cal["date"].dt.month * 100 + cal["date"].dt.day).astype("int64")
    cal["year"] = cal["date"].dt.year
    cal["month"] = cal["date"].dt.to_period("M").astype(str)
    cal["weekday"] = cal["date"].dt.day_name()
    cal["has_sales"] = cal["date"].isin(traded)
    cal["bank_holiday"] = cal["date"].map(hol).fillna("")
    cal["expected_trading_day"] = (cal["date"].dt.dayofweek != NON_TRADING_WEEKDAY) & (cal["bank_holiday"] == "")
    return cal[["date_key", "date", "year", "month", "weekday", "has_sales", "expected_trading_day", "bank_holiday"]]
