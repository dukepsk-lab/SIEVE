"""Batch 2 variant definitions (PLAN section 9): H6a H6b (volatility-managed exposure), H3a H8a H8b (events), control E0.

H6 is a position series on valid daily closes C(d) = P(16:00, d), built exactly like H5 / C2 (same `_positions`, same evaluator).
The target at C(d) is min(cap, 0.20 / sigma_hat(d-1)): sigma_hat(d-1) is the annualised std (ddof 1) of the 20 valid daily returns up
to and including d-1, so the one-day lag is built in. The held w only moves to the target when |target - w| >= 0.10; it starts
flat (w = 0) and is reset to 0 while the target is unavailable (warm-up), so the band always refers to the position really held.

Event variants are long-only trades, one per event day d (a day with several events gets one trade; the previous trading day d-1 is
the latest trading day before d, as in PLAN section 2). They use only scheduled = True rows of research/data/events.csv, restricted to
event days inside the market (an event on or after the holdout cut, or before the first bar, is not a candidate). An event day that
is not a trading day of the market, or that has no previous trading day, is skipped as "signal unavailable". A missing P(T) is
skipped, never filled. E0 is the H8a trade on every trading day that has no event row of any kind (scheduled or not).

Events frames are normalised to columns: event (FOMC|CPI|NFP), date (ET calendar day, datetime64[ns]), scheduled (bool).
"""
from pathlib import Path

import numpy as np
import pandas as pd

from .data import Market
from .variants import HM, Result, _positions, _trades

SIGMA_STAR, VOL_WINDOW, BAND = 0.20, 20, 0.10             # frozen constants (PLAN section 9): 20% a year, 20 returns, no-trade band
CAPS = {"H6a": 2.0, "H6b": 1.0}
EVENTS_CSV = Path(__file__).resolve().parent / "data" / "events.csv"
KINDS = {"H3a": ("FOMC",), "H8a": ("FOMC", "CPI", "NFP"), "H8b": ("CPI", "NFP")}
ALL_KINDS = ("FOMC", "CPI", "NFP")


# ------------------------------------------------------------------ H6 volatility-managed exposure
def band_path(target, band: float = BAND) -> np.ndarray:
    """Held weight under a no-trade band: start flat, move to the target only when |target - w| >= band. NaN target: not held."""
    w, out = 0.0, np.full(len(target), np.nan)
    for i, x in enumerate(np.asarray(target, float)):
        if np.isnan(x):
            w = 0.0
            continue
        if abs(x - w) >= band:
            w = x
        out[i] = w
    return out


def _h6(m: Market, name: str, band: float = BAND) -> Result:
    close = m.px(16).dropna()
    r = close / close.shift(1) - 1                                                    # r(d) = C(d) / C(d-1) - 1, valid closes
    sigma = r.rolling(VOL_WINDOW, min_periods=VOL_WINDOW).std(ddof=1) * np.sqrt(252)  # sigma_hat(d), includes day d
    with np.errstate(divide="ignore"):                                                # sigma 0 -> infinite target -> the cap
        target = np.minimum(CAPS[name], SIGMA_STAR / sigma.shift(1).to_numpy())       # one-day lag: sigma_hat(d-1)
    return _positions(name, m, close, pd.Series(band_path(target, band), index=close.index))


def h6a(m: Market) -> Result:
    return _h6(m, "H6a")


def h6b(m: Market) -> Result:
    return _h6(m, "H6b")


# ------------------------------------------------------------------ events file
def _empty_events() -> pd.DataFrame:
    return pd.DataFrame({"event": pd.Series(dtype=object), "date": pd.DatetimeIndex([]).as_unit("ns"), "scheduled": pd.Series(dtype=bool)})


def parse_events(raw: pd.DataFrame) -> pd.DataFrame:
    """Normalise raw events.csv columns (event, date_et, time_et, scheduled, ...). Strict: unknown event or scheduled values raise."""
    if raw is None or raw.empty:
        return _empty_events()
    missing = {"event", "date_et", "scheduled"} - set(raw.columns)
    if missing:
        raise ValueError(f"events file lacks columns {sorted(missing)}")
    event = raw["event"].astype(str).str.strip().str.upper()
    sched = raw["scheduled"].astype(str).str.strip().str.lower()
    if not event.isin(ALL_KINDS).all():
        raise ValueError(f"unknown event kinds {sorted(set(event) - set(ALL_KINDS))}; expected {ALL_KINDS}")
    if not sched.isin(["true", "false", "1", "0", "yes", "no", ""]).all():
        raise ValueError(f"unrecognised scheduled values {sorted(set(sched) - {'true', 'false', '1', '0', 'yes', 'no', ''})}")
    date = pd.DatetimeIndex(pd.to_datetime(raw["date_et"].astype(str).str.strip(), format="ISO8601")).normalize().as_unit("ns")
    return pd.DataFrame({"event": event.to_numpy(), "date": date, "scheduled": sched.isin(["true", "1", "yes"]).to_numpy()})


def read_events(path: Path = EVENTS_CSV) -> pd.DataFrame:
    """The normalised events frame; a missing or empty file gives an empty frame (the event variants are then PENDING)."""
    try:
        raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return _empty_events()
    return parse_events(raw)


def event_days(ev: pd.DataFrame, m: Market, kinds=ALL_KINDS, scheduled: bool | None = True) -> pd.DatetimeIndex:
    """Distinct event dates of the given kinds inside the market's date range. scheduled=None keeps scheduled and unscheduled rows."""
    sel = ev["event"].isin(kinds)
    if scheduled is not None:
        sel &= ev["scheduled"] == scheduled
    d = pd.DatetimeIndex(ev.loc[sel, "date"]).as_unit("ns").unique().sort_values()
    return d[(d >= m.days[0]) & (d <= m.days[-1])]


# ------------------------------------------------------------------ event trades
def _prev_day(m: Market, d: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Previous trading day of each d; NaT when d is not a trading day of the market or is its first day."""
    return pd.DatetimeIndex(pd.Series(m.days[:-1], index=m.days[1:]).reindex(d))


def _event_trades(m: Market, name: str, d: pd.DatetimeIndex, t_in: pd.Timedelta, t_out: pd.Timedelta) -> Result:
    """Long P(prev day + t_in) -> P(d + t_out) for each day in d (booked on the entry day by the evaluator)."""
    prev = _prev_day(m, d)
    direction = np.where(prev.isna(), np.nan, 1.0)                                    # NaN: no d-1 -> "signal unavailable"
    start = prev.where(prev.notna(), d) + t_in                                        # placeholder time when d-1 is missing
    end = d + t_out
    return _trades(name, d, direction, start, end, m.price(start), m.price(end))


def h3a(m: Market, ev: pd.DataFrame) -> Result:
    """Pre-FOMC drift: long 14:00 d-1 -> 13:55 d for scheduled FOMC days d."""
    return _event_trades(m, "H3a", event_days(ev, m, KINDS["H3a"]), HM(14), HM(13, 55))


def h8a(m: Market, ev: pd.DataFrame) -> Result:
    """Announcement-day premium: long 16:00 d-1 -> 16:00 d for the union of scheduled FOMC, CPI and NFP days (one trade per day)."""
    return _event_trades(m, "H8a", event_days(ev, m, KINDS["H8a"]), HM(16), HM(16))


def h8b(m: Market, ev: pd.DataFrame) -> Result:
    """08:30 releases, overnight capture: long 16:00 d-1 -> 09:30 d for scheduled CPI and NFP days."""
    return _event_trades(m, "H8b", event_days(ev, m, KINDS["H8b"]), HM(16), HM(9, 30))


def e0(m: Market, ev: pd.DataFrame) -> Result:
    """Control (report only): the H8a trade on every trading day with no event row of any kind in the file."""
    return _event_trades(m, "E0", m.days[~m.days.isin(event_days(ev, m, ALL_KINDS, scheduled=None))], HM(16), HM(16))


EVENT_BUILDERS = {"H3a": h3a, "H8a": h8a, "H8b": h8b, "E0": e0}
