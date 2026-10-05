"""Task 1: history coverage (bars and ticks), M1 gaps against an inferred session schedule, usable history.

The trading schedule is inferred from the data itself in New York wall-clock time (exchange hours are fixed in ET
while the server clock moves, see task 4): for every (year, weekday, minute-of-day) the share of open days that
have an M1 bar; minutes present on >= 50% of open days are "expected". A gap is a run of expected minutes with no bar.
"""
import json
import logging
from datetime import datetime, timedelta

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

from . import config as C
from . import mt5io as io

log = logging.getLogger("audit")
EXPECTED_SHARE = 0.5
MIN_BARS_OPEN_DAY = 30
DST_LAG_DAYS = 21          # the broker sets its session in server time and has moved it up to ~9 days late after a DST change
KIND_CLOSURE, KIND_DST, KIND_EARLY, KIND_OTHER = ("closure >=10h (holiday or outage)", "session shift after a DST change",
                                                  "early close (runs to the daily break)", "other")


# ------------------------------------------------------------------ earliest tick (binary search)
def find_first_tick(sym: str, first_bar_day: datetime, now: datetime) -> dict:
    """Binary search over days for the first week containing ticks, cross-checked with copy_ticks_from."""
    f = C.CACHE / "ticks" / "first_tick.json"
    if f.exists():
        return json.loads(f.read_text())

    def has_ticks(day):
        arr = io._call(lambda: mt5.copy_ticks_range(sym, io.lab(day), io.lab(day + timedelta(days=7)), mt5.COPY_TICKS_ALL),
                       f"tick probe {day:%Y-%m-%d}")
        return len(arr) > 0

    lo = datetime(first_bar_day.year, first_bar_day.month, first_bar_day.day) - timedelta(days=1)
    hi = datetime(now.year, now.month, now.day) - timedelta(days=14)
    if not has_ticks(hi):
        return {"first_tick": None, "note": "no ticks found in the last weeks"}
    probes = 0
    while (hi - lo).days > 1:
        mid = lo + (hi - lo) / 2
        mid = datetime(mid.year, mid.month, mid.day)
        probes += 1
        hi, lo = (mid, lo) if has_ticks(mid) else (hi, mid)
    first = io.first_tick_after(sym, hi)
    direct = io.first_tick_after(sym, lo)
    out = {"first_tick": str(first), "first_tick_direct_copy_ticks_from": str(direct), "probes": probes}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out))
    return out


# ------------------------------------------------------------------ bars
def bars_before(sym: str, tf: str, first_ts: int) -> int:
    """Cross-check with a different API call: ask for 5 bars ending one year before the 'first' bar and count the ones that are
    strictly earlier. (MT5 answers with the first available bar itself, which is counted as 0 here.)"""
    d = datetime.fromtimestamp(first_ts, io.UTC).replace(tzinfo=None) - timedelta(days=365)
    arr = io._call(lambda: mt5.copy_rates_from(sym, io.TF[tf], io.lab(d), 5), f"bars before {tf}")
    return int(sum(1 for t in arr["time"] if int(t) < first_ts)) if len(arr) else 0


def tf_extent(sym: str, data: dict) -> pd.DataFrame:
    rows = []
    for tf, df in data.items():
        first, last = int(df["time"].iloc[0]), int(df["time"].iloc[-1])
        rows.append({"timeframe": tf, "bars": len(df), "first_bar_server": pd.to_datetime(first, unit="s"),
                     "last_bar_server": pd.to_datetime(last, unit="s"), "earlier_bars_found (copy_rates_from, 1y before)": bars_before(sym, tf, first),
                     "years": round((last - first) / 86400 / 365.25, 2)})
    return pd.DataFrame(rows)


def _period(idx: pd.DatetimeIndex) -> np.ndarray:
    return ((idx.year - 2000) * 4 + (idx.month - 1) // 3).to_numpy()


def _schedule(et: pd.DatetimeIndex):
    """Presence share per (calendar quarter, weekday, minute-of-day) -> boolean schedule (quarters, because the broker
    changed its session times a few times). Returns (first_period, schedule[periods,7,1440], open_days, bars_per_day)."""
    pi = _period(et)
    p0 = pi.min()
    wd, mod = et.dayofweek.to_numpy(), (et.hour * 60 + et.minute).to_numpy()
    date = et.normalize()
    per_day = pd.Series(1, index=date).groupby(level=0).size()
    open_days = per_day[per_day >= MIN_BARS_OPEN_DAY]
    keep = np.isin(date.asi8, open_days.index.asi8)
    n_p = pi.max() - p0 + 1
    cnt = np.zeros((n_p, 7, 1440))
    np.add.at(cnt, (pi[keep] - p0, wd[keep], mod[keep]), 1)
    n_open = np.zeros((n_p, 7))
    np.add.at(n_open, (_period(open_days.index) - p0, open_days.index.dayofweek), 1)
    share = cnt / np.maximum(n_open[:, :, None], 1)
    return p0, share >= EXPECTED_SHARE, open_days, per_day


def schedule_history(sched: np.ndarray, p0: int, n_open: np.ndarray) -> pd.DataFrame:
    """Per calendar quarter (>= 10 open days): the daily break (ET), from the Tuesday schedule."""
    rows = []
    for i in range(sched.shape[0]):
        m = sched[i, 1]
        if not m.any() or n_open[i] < 10:
            continue
        d = np.diff(np.r_[0, m.astype(np.int8), 0])
        seg = list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1) - 1))
        brk = [f"{hhmm(seg[k][1] + 1)}-{hhmm(seg[k + 1][0] - 1)}" for k in range(len(seg) - 1)]
        rows.append({"quarter": f"{2000 + (p0 + i) // 4}Q{(p0 + i) % 4 + 1}", "daily break (ET, expected-minute gap)": ", ".join(brk) or "none"})
    t = pd.DataFrame(rows)
    # collapse identical consecutive quarters
    t["grp"] = (t["daily break (ET, expected-minute gap)"] != t["daily break (ET, expected-minute gap)"].shift()).cumsum()
    return t.groupby("grp").agg(**{"from": ("quarter", "first"), "to": ("quarter", "last"),
                                   "daily break (ET, expected-minute gap)": ("daily break (ET, expected-minute gap)", "first")}).reset_index(drop=True)


def hhmm(m) -> str:
    return f"{int(m) // 60:02d}:{int(m) % 60:02d}"


def dst_change_days(first: pd.Timestamp, last: pd.Timestamp) -> pd.DatetimeIndex:
    """Calendar days on which New York or London changed its UTC offset, from the tz database (no hand-entered dates)."""
    days = pd.date_range(pd.Timestamp(first).normalize() - pd.Timedelta(days=1), pd.Timestamp(last).normalize() + pd.Timedelta(days=1), freq="D")
    noon = pd.DatetimeIndex(days + pd.Timedelta(hours=12)).as_unit("ns")
    changed = np.zeros(len(days), dtype=bool)
    for zone in (C.ET, "Europe/London"):
        off = (noon.tz_localize("UTC").tz_convert(zone).tz_localize(None) - noon).to_numpy()
        changed[1:] |= off[1:] != off[:-1]
    return days[changed]


def classify_gaps(gaps: pd.DataFrame, dst_days: pd.DatetimeIndex) -> np.ndarray:
    """Kind of each gap (columns start_et, end_et, minutes_missing).
    - closure: >= 10 h missing (holiday or outage)
    - session shift after a DST change: 50-70 min missing, running up to the daily break, within DST_LAG_DAYS after a
      US or EU DST change; the broker ended its session one hour early because its server-time schedule moved late
    - early close: >= 60 min missing, running up to the daily break (mostly US holidays, some broker schedule changes)
    - other: an intraday data gap"""
    end_mod = (gaps["end_et"].dt.hour * 60 + gaps["end_et"].dt.minute).to_numpy()
    n_miss = gaps["minutes_missing"].to_numpy()
    to_break = (end_mod >= 15 * 60 + 55) & (end_mod <= 17 * 60)
    day = gaps["start_et"].dt.normalize().to_numpy()
    k = np.searchsorted(dst_days.to_numpy(), day, side="right") - 1         # most recent DST change on or before the gap day
    since = np.where(k >= 0, (day - dst_days.to_numpy()[np.clip(k, 0, None)]) / np.timedelta64(1, "D"), np.inf)
    dst_shift = to_break & (n_miss >= 50) & (n_miss <= 70) & (since <= DST_LAG_DAYS)
    return np.select([n_miss >= 600, dst_shift, to_break & (n_miss >= 60)], [KIND_CLOSURE, KIND_DST, KIND_EARLY], KIND_OTHER)


def gap_analysis(m1: pd.DataFrame, clock) -> dict:
    server = pd.DatetimeIndex(pd.to_datetime(m1["time"], unit="s")).as_unit("ns")
    et = clock.to_et(server)
    p0, sched, open_days, per_day = _schedule(et)

    start = et.min().floor("min")
    k = ((et.asi8 - start.value) // 60_000_000_000).astype(np.int64)
    grid = pd.date_range(start, periods=int(k.max()) + 1, freq="min")
    present = np.zeros(len(grid), dtype=bool)
    present[k] = True
    gy, gw, gm = _period(grid) - p0, grid.dayofweek.to_numpy(), (grid.hour * 60 + grid.minute).to_numpy()
    expected = sched[gy, gw, gm]
    missing = expected & ~present

    edge = np.diff(np.r_[0, missing.astype(np.int8), 0])
    s, e = np.flatnonzero(edge == 1), np.flatnonzero(edge == -1)
    gaps = pd.DataFrame({"start_et": grid[s], "minutes_missing": e - s})
    gaps["end_et"] = grid[e - 1]
    gaps["year"] = gaps["start_et"].dt.year
    gaps["kind"] = classify_gaps(gaps, dst_change_days(start, et.max()))
    scheduled = gaps["kind"] != KIND_OTHER
    srv = clock.et_to_server(pd.DatetimeIndex(gaps["start_et"]))
    gaps["start_server"] = srv

    cat = pd.DataFrame({"year": gaps["year"],
                        ">1 min": gaps["minutes_missing"] >= 1, ">5 min": gaps["minutes_missing"] >= 5, ">60 min": gaps["minutes_missing"] >= 60}) \
        .groupby("year").sum().astype(int)
    cat[">60 min, excluding closures, early closes and DST session shifts"] = (gaps["kind"].eq(KIND_OTHER) & (gaps["minutes_missing"] >= 60)).groupby(gaps["year"]).sum().astype(int)
    cat.loc["all"] = cat.sum()
    gaps_other = gaps[gaps["kind"] == KIND_OTHER].nlargest(20, "minutes_missing")
    # tradability calendar: days on which the CFD stopped quoting before the regular daily break
    s = gaps[gaps["kind"].isin([KIND_DST, KIND_EARLY])]
    shortened = pd.DataFrame({"date_et": s["start_et"].dt.strftime("%Y-%m-%d"), "weekday": s["start_et"].dt.day_name().str[:3],
                              "no_quotes_from_et": s["start_et"].dt.strftime("%H:%M"), "regular_break_from_et": (s["end_et"] + pd.Timedelta(minutes=1)).dt.strftime("%H:%M"),
                              "minutes_lost": s["minutes_missing"], "kind": s["kind"], "no_quotes_from_server": s["start_server"].dt.strftime("%Y-%m-%d %H:%M")})

    # bars per day vs expected active-session minutes
    exp_per_day = pd.Series(sched.sum(axis=2)[(_period(open_days.index) - p0), open_days.index.dayofweek], index=open_days.index)
    cover = pd.DataFrame({"bars": per_day.reindex(open_days.index), "expected": exp_per_day})
    cover["ratio"] = cover["bars"] / cover["expected"]
    by_year = cover.groupby(cover.index.year).agg(open_days=("bars", "size"), mean_bars=("bars", "mean"), mean_expected=("expected", "mean"),
                                                  mean_ratio=("ratio", "mean"), days_below_95pct=("ratio", lambda r: int((r < 0.95).sum())))
    by_year.index.name = "year"
    by_year["mean_bars"], by_year["mean_expected"] = by_year["mean_bars"].round(0), by_year["mean_expected"].round(0)
    by_year["mean_ratio"] = (by_year["mean_ratio"] * 100).round(2)

    # human-readable session schedule of the latest year (ET): first/last expected minute per weekday segment
    n_open_p = np.bincount(_period(open_days.index) - p0, minlength=sched.shape[0])
    ylast = int(np.flatnonzero(n_open_p >= 30)[-1])               # latest quarter with enough days to infer a schedule
    sched_rows = []
    for wd in range(7):
        m = sched[ylast, wd]
        if not m.any():
            continue
        d = np.diff(np.r_[0, m.astype(np.int8), 0])
        for a, b in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)):
            sched_rows.append({"weekday_ET": "Mon Tue Wed Thu Fri Sat Sun".split()[wd],
                               "from_ET": f"{a // 60:02d}:{a % 60:02d}", "to_ET": f"{(b - 1) // 60:02d}:{(b - 1) % 60:02d}",
                               "minutes": int(b - a)})
    outside = int((~sched[_period(et) - p0, et.dayofweek.to_numpy(), (et.hour * 60 + et.minute).to_numpy()]).sum())
    return {"gaps": gaps, "gap_counts": cat, "top20": gaps.nlargest(20, "minutes_missing"), "top_other": gaps_other, "holiday_gaps": int(scheduled.sum()),
            "shortened": shortened.reset_index(drop=True), "kind_counts": gaps["kind"].value_counts(),
            "coverage_by_year": by_year, "schedule_latest_year": pd.DataFrame(sched_rows), "schedule_period": f"{2000 + (p0 + ylast) // 4}Q{(p0 + ylast) % 4 + 1}",
            "schedule_history": schedule_history(sched, p0, n_open_p), "bars_outside_schedule": outside, "expected_minutes_total": int(expected.sum()), "missing_minutes_total": int(missing.sum())}


# ------------------------------------------------------------------ ticks
def tick_coverage(counters: pd.DataFrame) -> dict:
    c = counters.copy()
    c["day"] = pd.to_datetime(c["day"])
    for col in ["n_ticks", "n_valid", "n_last_nonzero", "n_volume_nonzero", "n_volume_real_nonzero", "n_nonpositive_price"]:
        c[col] = pd.to_numeric(c[col], errors="coerce").fillna(0)
    active = c[c["n_ticks"] > 0]
    monthly = active.groupby(active["day"].dt.to_period("M")).agg(days=("n_ticks", "size"), ticks_total=("n_ticks", "sum"),
                                                                  ticks_per_day_mean=("n_ticks", "mean"), ticks_per_day_min=("n_ticks", "min"),
                                                                  ticks_per_day_max=("n_ticks", "max")).round(0).astype(int)
    flags = {}
    for d in c["flags"].dropna():
        for k, v in d.items():
            flags[int(k)] = flags.get(int(k), 0) + int(v)
    flag_df = pd.DataFrame({"flags": list(flags), "ticks": list(flags.values())}).sort_values("ticks", ascending=False)
    flag_df["decoded"] = flag_df["flags"].map(decode_flags)
    flag_df["share_pct"] = (100 * flag_df["ticks"] / flag_df["ticks"].sum()).round(3)
    # flag values by year, to show feed changes
    fy = []
    for _, r in c.dropna(subset=["flags"]).iterrows():
        for k, v in r["flags"].items():
            fy.append((r["day"].year, int(k), int(v)))
    flags_by_year = pd.DataFrame(fy, columns=["year", "flags", "n"]).groupby(["year", "flags"])["n"].sum().unstack(fill_value=0)
    monthly.index.name = "month"
    tot = int(active["n_ticks"].sum())
    return {"monthly": monthly, "days_with_ticks": int(len(active)), "days_checked": int(len(c)), "ticks_total": tot,
            "bid_ask_both_positive_pct": round(100 * float(active["n_valid"].sum()) / tot, 4),
            "last_nonzero": int(active["n_last_nonzero"].sum()), "volume_nonzero": int(active["n_volume_nonzero"].sum()),
            "volume_real_nonzero": int(active["n_volume_real_nonzero"].sum()), "flags": flag_df, "flags_by_year": flags_by_year,
            "first_day": active["day"].min(), "last_day": active["day"].max()}


def decode_flags(v: int) -> str:
    names = {2: "BID", 4: "ASK", 8: "LAST", 16: "VOLUME", 32: "BUY", 64: "SELL"}
    known = [n for b, n in names.items() if v & b]
    rest = v & ~sum(names)
    return "+".join(known) + (f" +undocumented bits {rest}" if rest else "")


def usable_history(m1: pd.DataFrame, tick_first: pd.Timestamp, tick_last: pd.Timestamp) -> pd.DataFrame:
    m1_years = (m1["time"].iloc[-1] - m1["time"].iloc[0]) / 86400 / 365.25
    tk_years = (tick_last - tick_first).days / 365.25
    return pd.DataFrame([{"source": "M1 bars", "years": round(m1_years, 2), "min_detectable_sharpe_t3": round(3 / np.sqrt(m1_years), 2)},
                         {"source": "ticks", "years": round(tk_years, 2), "min_detectable_sharpe_t3": round(3 / np.sqrt(tk_years), 2)}])
