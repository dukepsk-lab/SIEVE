"""Frozen variant definitions (PLAN section 3): H1a H1b H2a H2b H4a H4b H5a H5b plus controls C1 and C2.

Every builder takes a Market and returns a Result for ALL trading days of the market; stage windows are applied by the
evaluator. Trade variants give a trade list (variant, entry_et, exit_et, direction, entry_px, exit_px) and a skip list
(variant, date, reason). A day with no signal (sign 0, |z| below the threshold, momentum disagreement) is not a trade and not a
skip. Skip reasons are checked in this order: next day not a trading day, signal unavailable, missing entry price,
missing exit price. A skip is never filled.

Position variants (H5a, H5b, C2) work on the sequence of trading days with a valid close C(d) = P(16:00, d): the position
entered at C(d) is held to the next valid close. `pos` is indexed by those days with columns pos, close, next_close, next_day.

No lookahead: a signal only uses prices stamped before the entry time (H2, H4) or the previous valid close (H5, one-day lag).
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data import Market

R_ENTRY, R_EXIT = "missing entry price", "missing exit price"
R_SIGNAL = "signal unavailable (warm-up or missing input)"
R_NEXT = "next day not a trading day"
SKIP_REASONS = [R_NEXT, R_SIGNAL, R_ENTRY, R_EXIT]
TRADE_COLS = ["variant", "entry_et", "exit_et", "direction", "entry_px", "exit_px"]
HM = lambda h, m=0: pd.Timedelta(hours=h, minutes=m)
DAY = pd.Timedelta(days=1)


@dataclass
class Result:
    variant: str
    trades: pd.DataFrame
    skips: pd.DataFrame
    pos: pd.DataFrame | None = None


def _trades(name: str, days: pd.DatetimeIndex, direction, t_in, t_out, p_in, p_out, blocked=None) -> Result:
    """One candidate per day in `days`. direction: +-1, 0 (no trade) or NaN (signal unavailable)."""
    n = len(days)
    direction = np.broadcast_to(np.asarray(direction, float), n)
    blocked = np.zeros(n, bool) if blocked is None else np.asarray(blocked, bool)
    reason = np.select([blocked, np.isnan(direction), direction == 0, np.isnan(p_in), np.isnan(p_out)],
                       [R_NEXT, R_SIGNAL, "none", R_ENTRY, R_EXIT], default="trade")
    tr = pd.DataFrame({"variant": name, "entry_et": t_in, "exit_et": t_out, "direction": direction,
                       "entry_px": p_in, "exit_px": p_out})[reason == "trade"]
    sk = pd.DataFrame({"variant": name, "date": days, "reason": reason})
    return Result(name, tr.reset_index(drop=True), sk[sk["reason"].isin(SKIP_REASONS)].reset_index(drop=True))


# ------------------------------------------------------------------ H1 overnight and controls
def _long(m: Market, name: str, days, t_in, t_out, blocked=None) -> Result:
    return _trades(name, days, 1.0, t_in, t_out, m.price(t_in), m.price(t_out), blocked)


def h1a(m: Market) -> Result:
    """Long 16:00 d -> 09:30 d+1, Monday-Thursday; skipped unless d+1 (next calendar day) is a trading day."""
    d = m.days[m.days.dayofweek <= 3]
    return _long(m, "H1a", d, d + HM(16), d + DAY + HM(9, 30), blocked=~(d + DAY).isin(m.days))


def h1b(m: Market) -> Result:
    """Long 16:00 Friday -> 09:30 Monday; skipped unless that Monday is a trading day."""
    d = m.days[m.days.dayofweek == 4]
    return _long(m, "H1b", d, d + HM(16), d + 3 * DAY + HM(9, 30), blocked=~(d + 3 * DAY).isin(m.days))


def c1(m: Market) -> Result:
    """Control: long 09:30 -> 16:00 every trading day (the intraday half)."""
    d = m.days
    return _long(m, "C1", d, d + HM(9, 30), d + HM(16))


# ------------------------------------------------------------------ H2 intraday momentum
def _h2(m: Market, name: str, both: bool) -> Result:
    r1 = (m.px(10) / m.px(16).shift(1) - 1).to_numpy()                 # previous 16:00 -> 10:00
    r2 = (m.px(15, 30) / m.px(15) - 1).to_numpy()                      # 15:00 -> 15:30
    s1, s2 = np.sign(r1), np.sign(r2)
    direction = np.where(np.isnan(r1) | np.isnan(r2), np.nan, np.where(s1 == s2, s1, 0.0)) if both else s1
    d = m.days
    t_in, t_out = d + HM(15, 31), d + HM(16)
    return _trades(name, d, direction, t_in, t_out, m.price(t_in), m.price(t_out))


def h2a(m: Market) -> Result:
    return _h2(m, "H2a", both=False)


def h2b(m: Market) -> Result:
    return _h2(m, "H2b", both=True)


# ------------------------------------------------------------------ H4 opening-gap reaction
def _h4(m: Market, name: str, thr: float) -> Result:
    """g = P(09:30) / previous P(16:00) - 1; sigma_g = std of g over the previous 60 trading days (>= 40 valid), excluding d."""
    g = m.px(9, 30) / m.px(16).shift(1) - 1
    sd = g.shift(1).rolling(60, min_periods=40).std()
    z = (g / sd.where(sd > 0)).to_numpy()
    direction = np.where(np.isnan(z), np.nan, np.where(np.abs(z) >= thr, -np.sign(z), 0.0))   # fade the gap
    d = m.days
    t_in, t_out = d + HM(9, 35), d + HM(16)
    return _trades(name, d, direction, t_in, t_out, m.price(t_in), m.price(t_out))


def h4a(m: Market) -> Result:
    return _h4(m, "H4a", 1.0)


def h4b(m: Market) -> Result:
    return _h4(m, "H4b", 1.5)


# ------------------------------------------------------------------ position series: H5 and C2
def _positions(name: str, m: Market, close: pd.Series, pos: pd.Series) -> Result:
    """close: valid closes by day; pos: position entered at that close (NaN = signal unavailable)."""
    p = pd.DataFrame({"pos": pos.reindex(close.index), "close": close, "next_close": close.shift(-1),
                      "next_day": close.index.to_series().shift(-1)})
    reason = pd.Series(R_ENTRY, index=m.days)                                         # C(d) missing unless d is a valid day
    reason[p.index] = np.where(p["pos"].isna(), R_SIGNAL, np.where(p["next_close"].isna(), R_EXIT, "ok"))
    sk = pd.DataFrame({"variant": name, "date": m.days, "reason": reason.to_numpy()})
    return Result(name, pd.DataFrame(columns=TRADE_COLS), sk[sk["reason"].isin(SKIP_REASONS)].reset_index(drop=True), p)


def _h5(m: Market, name: str, to_pos) -> Result:
    close = m.px(16).dropna()
    mom = close / close.shift(60) - 1                                                 # C(d) / C(d-60), 60 valid closes back
    sig = mom.shift(1)                                                                # one-day lag: held at C(d) = f(m(d-1))
    return _positions(name, m, close, pd.Series(np.where(sig.isna(), np.nan, to_pos(sig)), index=close.index))


def h5a(m: Market) -> Result:
    return _h5(m, "H5a", np.sign)


def h5b(m: Market) -> Result:
    return _h5(m, "H5b", lambda s: (s > 0).astype(float))


def c2(m: Market) -> Result:
    """Control: buy and hold, long from the first window close to the last (one round trip, no signal)."""
    close = m.px(16).dropna()
    return _positions("C2", m, close, pd.Series(1.0, index=close.index))


CANDIDATES = {"H1a": h1a, "H1b": h1b, "H2a": h2a, "H2b": h2b, "H4a": h4a, "H4b": h4b, "H5a": h5a, "H5b": h5b}
CONTROLS = {"C1": c1, "C2": c2}
