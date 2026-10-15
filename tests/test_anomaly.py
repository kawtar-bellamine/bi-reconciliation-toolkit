import numpy as np
import pandas as pd

from bitk.anomaly import robust_scores


def _daily(values):
    dates = pd.bdate_range("2011-01-03", periods=len(values))
    return pd.DataFrame({"date_key": dates.strftime("%Y%m%d").astype(int), "date": dates,
                         "weekday": dates.dayofweek, "x": values})


def test_spike_flagged_and_steady_days_not():
    rng = np.random.default_rng(0)
    v = 1000 * (1 + 0.05 * rng.standard_normal(120))
    v[60] *= 3
    s = robust_scores(_daily(v), ["x"])
    assert s.loc[60, "x_flag"]
    assert s["x_flag"].sum() <= 3


def test_growth_alone_is_not_an_anomaly():
    v = np.linspace(1000, 3000, 150)
    s = robust_scores(_daily(v), ["x"])
    assert not s["x_flag"].any()
