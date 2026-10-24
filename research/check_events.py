"""Sanity check of research/data/events.csv against the USTEC M1 bars: an event minute should show a range spike.

For every event dated before 2026-01-01 (ET):
    event_range = max(high - low) over the event minute and the next 2 minutes          (3 bars)
    base_median = median(high - low) over the 30 minutes ending 15 minutes before the event  (bars stamped in [t-45m, t-15m))
    ratio       = event_range / base_median
Rows with ratio < 2.0, or with missing / thin bars, are flagged for review.

This checks the DATES, it is not a strategy test: no returns or trading statistics are computed. Only bars stamped before
2026-01-01 ET are loaded (the 2026 holdout is never read into the comparison).

Run from anywhere:  python research/check_events.py
Reads : research/data/events.csv, audit/cache/rates/USTEC/M1/*.parquet, audit/out/server_clock.json
Writes: research/data/events_check.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from audit.tz import ServerClock  # noqa: E402

M1_DIR = ROOT / "audit" / "cache" / "rates" / "USTEC" / "M1"
CLOCK_JSON = ROOT / "audit" / "out" / "server_clock.json"
EVENTS = ROOT / "research" / "data" / "events.csv"
OUT = ROOT / "research" / "data" / "events_check.csv"

CUTOFF = pd.Timestamp("2026-01-01")        # ET; bars and events from here on are the locked holdout
RATIO_FLAG = 2.0
MIN_EVENT_BARS = 3                         # event minute + next 2 minutes
MIN_BASE_BARS = 20                         # of 30 baseline minutes; fewer than this = thin baseline (flagged)
EVENT_MIN, BASE_START_MIN, BASE_END_MIN = 3, 45, 15


def load_m1_et() -> pd.DataFrame:
    """M1 bars (before the cutoff) indexed by New York wall-clock minute. `time` is the broker server wall clock."""
    frames = []
    for f in sorted(M1_DIR.glob("*.parquet")):
        d = pd.read_parquet(f, columns=["time", "high", "low"])
        if len(d):
            frames.append(d)
    m1 = pd.concat(frames, ignore_index=True).sort_values("time").drop_duplicates("time")
    clock = ServerClock.load(CLOCK_JSON)
    et = clock.to_et(pd.DatetimeIndex(pd.to_datetime(m1["time"], unit="s")).as_unit("ns"))
    out = pd.DataFrame({"et": et, "rng": (m1["high"] - m1["low"]).to_numpy()})
    out = out[out["et"] < CUTOFF].sort_values("et").drop_duplicates("et").reset_index(drop=True)
    return out


def check(events: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    t_bar = bars["et"].to_numpy("datetime64[ns]")
    rng = bars["rng"].to_numpy()
    rows = []
    for e in events.itertuples(index=False):
        t = np.datetime64(pd.Timestamp(f"{e.date_et} {e.time_et}"), "ns")
        m = np.timedelta64(1, "m")
        i0, i1 = np.searchsorted(t_bar, [t, t + EVENT_MIN * m])
        j0, j1 = np.searchsorted(t_bar, [t - BASE_START_MIN * m, t - BASE_END_MIN * m])
        ev, base = rng[i0:i1], rng[j0:j1]
        ev_range = float(ev.max()) if len(ev) else np.nan
        base_med = float(np.median(base)) if len(base) else np.nan
        ratio = ev_range / base_med if len(ev) and len(base) and base_med > 0 else np.nan
        reasons = []
        if len(ev) == 0 or len(base) == 0:
            reasons.append("missing_bars")
        elif base_med <= 0:
            reasons.append("zero_baseline")
        else:
            if len(ev) < MIN_EVENT_BARS or len(base) < MIN_BASE_BARS:
                reasons.append("thin_bars")
            if ratio < RATIO_FLAG:
                reasons.append("ratio<2")
        rows.append(dict(event=e.event, date_et=e.date_et, time_et=e.time_et, scheduled=e.scheduled,
                         ratio=ratio, bars_found=len(ev) + len(base), n_event_bars=len(ev), n_base_bars=len(base),
                         event_range=ev_range, base_median=base_med,
                         flag=bool(reasons), flag_reason=";".join(reasons)))
    return pd.DataFrame(rows)


def main() -> None:
    ev = pd.read_csv(EVENTS, dtype={"time_et": str})
    ev = ev[pd.to_datetime(ev["date_et"]) < CUTOFF].reset_index(drop=True)
    bars = load_m1_et()
    print(f"events checked: {len(ev)}   M1 bars (before {CUTOFF.date()} ET): {len(bars)}   "
          f"first bar ET {bars['et'].iloc[0]}   last bar ET {bars['et'].iloc[-1]}")
    res = check(ev, bars)
    res.to_csv(OUT, index=False, float_format="%.6g")
    print("wrote research/data/events_check.csv")

    def summ(g: pd.DataFrame) -> pd.Series:
        return pd.Series({"n": len(g), "median_ratio": g["ratio"].median(), "n_flagged": int(g["flag"].sum()),
                          "n_ratio_lt_2": int(g["flag_reason"].str.contains("ratio<2").sum()),
                          "n_missing_or_thin": int(g["flag_reason"].str.contains("missing|thin|zero").sum())})
    print("\nBy event type")
    print(res.groupby("event").apply(summ, include_groups=False).to_string(float_format=lambda x: f"{x:.2f}"))
    print("\nBy event type and scheduled")
    print(res.groupby(["event", "scheduled"]).apply(summ, include_groups=False).to_string(float_format=lambda x: f"{x:.2f}"))
    fl = res[res["flag"]]
    print(f"\nFlagged rows ({len(fl)}):")
    if len(fl):
        print(fl[["event", "date_et", "time_et", "scheduled", "ratio", "n_event_bars", "n_base_bars", "flag_reason"]]
              .to_string(index=False, float_format=lambda x: f"{x:.2f}"))


if __name__ == "__main__":
    main()
