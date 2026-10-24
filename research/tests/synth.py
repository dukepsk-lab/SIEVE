"""Small synthetic markets for the unit tests (ET-stamped bars, no clock or files needed)."""
import numpy as np
import pandas as pd

from research.data import Market

CASH = range(9 * 60 + 30, 16 * 60 + 1)          # 09:30 .. 16:00 inclusive, one bar per minute


def stamps(days, minutes) -> pd.DatetimeIndex:
    return pd.DatetimeIndex([pd.Timestamp(d) + pd.Timedelta(minutes=m) for d in days for m in minutes]).as_unit("ns")


def random_market(days, seed: int = 0, minutes=CASH) -> Market:
    """Random-walk bars on the given weekdays."""
    rng = np.random.default_rng(seed)
    idx = stamps(days, minutes)
    o = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 3e-4, len(idx)))), index=idx)
    return Market(o, o * (1 + rng.normal(0, 1e-4, len(idx))))


def close_only_market(days, closes) -> Market:
    """One bar per day, stamped 16:00, with open = close = the given value."""
    s = pd.Series(np.asarray(closes, float), index=stamps(days, [16 * 60]))
    return Market(s, s.copy())


def perturb(m: Market, t0, seed: int = 1) -> Market:
    """Same market with every bar stamped at or after t0 multiplied by random noise (+-5%)."""
    rng = np.random.default_rng(seed)
    o, c = m.P
    f = pd.Series(np.where(o.index >= pd.Timestamp(t0), np.exp(rng.normal(0, 0.05, len(o))), 1.0), index=o.index)
    return Market(o * f, c * f)
