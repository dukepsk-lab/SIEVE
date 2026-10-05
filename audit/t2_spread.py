"""Task 2: spread audit.

Primary measure: per-minute time-weighted spread under LOCF from ticks (digest columns s_min / s_med / s_max / s_mean).
Tick-weighted statistics (from the histograms) are shown only as a comparison. All spreads are in index points
(price units) = points * `point`. `s_med` is the headline per-minute value; `s_max` the worst tick inside the minute.
Because the broker re-prices its spread in steps (see regimes), levels are only comparable inside a regime; ratios
to the day's own median remove the level and are used for spike behaviour across the whole sample.
"""
import logging
import warnings

import numpy as np
import pandas as pd

from . import config as C

log = logging.getLogger("audit")
Q = [0.5, 0.9, 0.99]
REL = np.arange(-15, 31)            # event window, minutes relative to the release


def hhmm(minutes) -> str:
    return f"{int(minutes) // 60:02d}:{int(minutes) % 60:02d}"


def bucket_label(b: int) -> str:
    return f"{hhmm(b * 30)}-{hhmm(b * 30 + 29)}"


# ------------------------------------------------------------------ prepare
def prepare(mins: pd.DataFrame, clock, point: float) -> pd.DataFrame:
    mm = mins.copy()
    srv = pd.DatetimeIndex(pd.to_datetime(mm["m"] * 60, unit="s")).as_unit("ns")
    et = clock.to_et(srv)
    mm["srv"], mm["et"] = srv, et
    mm["date"] = et.normalize()
    mm["mod_et"] = et.hour * 60 + et.minute
    mm["mod_srv"] = srv.hour * 60 + srv.minute
    for c in ("s_min", "s_med", "s_max", "s_mean", "s_last"):
        mm[c + "_pt"] = mm[c] * point
    base = mm.groupby("date")["s_med_pt"].transform("median")
    mm["base"] = base
    mm["r_med"], mm["r_max"] = mm["s_med_pt"] / base, mm["s_max_pt"] / base
    return mm


# ------------------------------------------------------------------ regimes (2d)
def regime_table(mm: pd.DataFrame, rel: float = 0.04, streak: int = 5) -> tuple[pd.DataFrame, pd.Timestamp]:
    """Piecewise-constant levels of the daily modal per-minute spread. A new regime starts when `streak` consecutive
    days all deviate from the running reference by >= `rel`."""
    dm = mm.groupby("date")["s_med_pt"].agg(lambda x: x.round(4).mode().iloc[0])
    lv, idx = dm.to_numpy(float), dm.index
    starts, ref, i = [0], np.median(lv[:streak]), streak
    while i < len(lv):
        w = lv[i:i + streak]
        if len(w) == streak and (np.abs(w / ref - 1) >= rel).all():
            starts.append(i)
            ref = np.median(w)
            i += streak
        else:
            i += 1
    rows = []
    for j, s in enumerate(starts):
        e = starts[j + 1] - 1 if j + 1 < len(starts) else len(lv) - 1
        d0, d1 = idx[s], idx[e]
        sel = mm[(mm["date"] >= d0) & (mm["date"] <= d1)]
        v = sel["s_med_pt"].round(4)
        rows.append({"start": d0.date(), "end": d1.date(), "days": e - s + 1, "level_pts": round(float(np.median(lv[s:e + 1])), 2),
                     "minutes": len(sel), "pct_minutes_at_modal_value": round(100 * float((v == v.mode().iloc[0]).mean()), 1),
                     "p50": sel["s_med_pt"].quantile(.5), "p99": sel["s_med_pt"].quantile(.99),
                     "p99.9": sel["s_med_pt"].quantile(.999), "max_tick": sel["s_max_pt"].max()})
    t = pd.DataFrame(rows)
    t[["p50", "p99", "p99.9", "max_tick"]] = t[["p50", "p99", "p99.9", "max_tick"]].round(2)
    return t, pd.Timestamp(t["start"].iloc[-1])


# ------------------------------------------------------------------ 2a buckets
def _wq(s: np.ndarray, n: np.ndarray, qs) -> list[float]:
    o = np.argsort(s)
    s, cum = s[o], np.cumsum(n[o])
    return [float(s[min(np.searchsorted(cum, q * cum[-1]), len(s) - 1)]) for q in qs]


def tick_weighted(hist: pd.DataFrame, clock, point: float, since: pd.Timestamp | None, et: bool) -> pd.DataFrame:
    """Tick-weighted p50/p99 per 30-min bucket from per-day histograms (comparison only)."""
    h = hist.copy()
    h["day"] = pd.to_datetime(h["day"])
    if since is not None:
        h = h[h["day"] >= since]
    b = h["bucket"].to_numpy()
    if et:
        noon = pd.DatetimeIndex(h["day"].unique()) + pd.Timedelta(hours=12)
        shift = pd.Series(((clock.to_et(noon) - noon) / pd.Timedelta(minutes=1)).to_numpy().astype(int), index=noon.normalize())
        b = ((b * 30 + h["day"].map(shift).to_numpy()) % 1440) // 30
    h["b"] = b
    rows = {}
    for k, g in h.groupby("b"):
        t = g.groupby("s")["n"].sum()
        p50, p99 = _wq(t.index.to_numpy(float), t.to_numpy(float), [.5, .99])
        rows[int(k)] = {"tick_N": int(t.sum()), "tick_p50": round(p50 * point, 2), "tick_p99": round(p99 * point, 2)}
    return pd.DataFrame.from_dict(rows, orient="index")


def bucket_table(mm: pd.DataFrame, col_b: str, since: pd.Timestamp | None, tw: pd.DataFrame | None) -> pd.DataFrame:
    d = mm if since is None else mm[mm["date"] >= since]
    g = d.groupby(col_b)
    t = pd.DataFrame({"N_min": g.size(), "p50": g["s_med_pt"].quantile(.5), "p90": g["s_med_pt"].quantile(.9),
                      "p99": g["s_med_pt"].quantile(.99), "max_tick": g["s_max_pt"].max(), "mean": g["s_mean_pt"].mean()}).round(3)
    if tw is not None:
        t = t.join(tw)
    t.insert(0, "bucket", [bucket_label(b) for b in t.index])
    return t


# ------------------------------------------------------------------ 2b rollover
def _anchor_rel(mm: pd.DataFrame, mode: str) -> pd.DataFrame:
    """Rows within +-30 min of the daily anchor: 'reopen' = first bar after the daily break, 'break' = last bar before it.
    Weekly open (Sunday) is excluded from the daily reopen; it is reported separately."""
    d = mm[(mm["mod_et"] >= 14 * 60) & (mm["mod_et"] <= 21 * 60)]
    if mode == "reopen":
        d = d[(d["mod_et"] >= 17 * 60 + 30)]
        anchor = d.groupby("date")["m"].transform("min")
    else:
        d = d[d["mod_et"] < 17 * 60 + 30]
        anchor = d.groupby("date")["m"].transform("max")
    d = d.assign(rel=d["m"] - anchor, anchor_mod=d.groupby("date")["mod_et"].transform("min" if mode == "reopen" else "max"))
    return d[d["rel"].between(-30, 30)]


def rollover(mm: pd.DataFrame, cur_start: pd.Timestamp) -> dict:
    out = {}
    for mode in ("reopen", "break"):
        d = _anchor_rel(mm, mode)
        if mode == "reopen":
            sun = d["date"].dt.dayofweek == 6
            out["weekly_open"] = d[sun].groupby("rel").agg(N=("r_max", "size"), r_med_mean=("r_med", "mean"), r_max_p99=("r_max", lambda x: x.quantile(.99)))
            d = d[~sun]
        anchors = d.groupby("date")["anchor_mod"].first()
        out[f"{mode}_anchor_times"] = anchors.map(hhmm).value_counts().head(5)
        g_all = d.groupby("rel")
        cur = d[d["date"] >= cur_start].groupby("rel")
        t = pd.DataFrame({"N_all": g_all.size(), "ratio_med_all": g_all["r_med"].median(), "ratio_p99_all": g_all["r_max"].quantile(.99),
                          "ratio_max_all": g_all["r_max"].max(), "N_cur": cur.size(), "p50_cur": cur["s_med_pt"].median(),
                          "p99_cur": cur["s_med_pt"].quantile(.99), "max_cur": cur["s_max_pt"].max()}).reindex(range(-30, 31))
        out[mode] = t
        # inferred rollover minute: the post-reopen minute with the highest mean max-spread ratio
        if mode == "reopen":
            prof = d.groupby("rel")["r_max"].mean()
            out["spike_rel_min"] = int(prof.idxmax())
            out["spike_mean_ratio"] = round(float(prof.max()), 2)
            tod = d.assign(t=d["mod_et"]).groupby("t")["r_max"].agg(["mean", "size"])
            tod = tod[tod["size"] >= 100]
            out["spike_clock_et"] = hhmm(tod["mean"].idxmax())
    return out


# ------------------------------------------------------------------ 2c events
def _matrix(dates: pd.DatetimeIndex, d_idx: np.ndarray, mod: np.ndarray, vals: np.ndarray) -> np.ndarray:
    a = np.full((len(dates), 1440), np.nan)
    a[d_idx, mod] = vals
    return a


def _z(rng: np.ndarray, anchor: int) -> np.ndarray:
    """Peak 1-min range in [anchor, anchor+2] over the median range in [anchor-45, anchor-15)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmax(rng[:, anchor:anchor + 3], axis=1) / np.nanmedian(rng[:, anchor - 45:anchor - 15], axis=1)


def load_events(path: str) -> pd.DataFrame | None:
    if not path:
        return None
    ev = pd.read_csv(path)
    ev["dt"] = pd.to_datetime(ev["datetime_et"])
    return ev


def events(mm: pd.DataFrame, m1: pd.DataFrame, clock, cur_start: pd.Timestamp, events_csv: str = "") -> dict:
    et = clock.to_et(pd.DatetimeIndex(pd.to_datetime(m1["time"], unit="s")).as_unit("ns"))
    dates = pd.DatetimeIndex(et.normalize().unique().union(pd.DatetimeIndex(mm["date"]).unique()).as_unit("ns"))
    d_idx = np.searchsorted(dates.asi8, et.normalize().asi8)
    mod = (et.hour * 60 + et.minute).to_numpy()
    rng = _matrix(dates, d_idx, mod, (m1["high"] - m1["low"]).to_numpy())
    # spread matrices (tick era only)
    sd_idx = np.searchsorted(dates.asi8, pd.DatetimeIndex(mm["date"]).asi8)
    sr = _matrix(dates, sd_idx, mm["mod_et"].to_numpy(), mm["r_med"].to_numpy())
    sm = _matrix(dates, sd_idx, mm["mod_et"].to_numpy(), mm["s_max_pt"].to_numpy())
    wd = dates.dayofweek.to_numpy()
    open_day = (wd < 5) & ((~np.isnan(rng[:, 8 * 60:17 * 60])).sum(axis=1) >= 400)
    has_ticks = (dates >= mm["date"].min()).astype(bool) if len(mm) else np.zeros(len(dates), bool)

    ev_csv = load_events(events_csv)
    anchors = {}
    for label, hh, mi in (("08:30 ET (US data releases)", 8, 30), ("14:00 ET (FOMC / Fed)", 14, 0)):
        a = hh * 60 + mi
        z = _z(rng, a)
        controls = np.concatenate([_z(rng, a + off)[open_day] for off in (-75, -60, -45, -30)])
        controls = controls[np.isfinite(controls)]
        thr = max(4.0, float(np.quantile(controls, 0.95)))
        if ev_csv is not None:
            sel = ev_csv[ev_csv["dt"].dt.hour * 60 + ev_csv["dt"].dt.minute == a]
            is_ev = np.isin(dates.asi8, pd.DatetimeIndex(sel["dt"].dt.normalize()).as_unit("ns").asi8) & open_day
            how = f"events file ({len(sel)} rows at this time)"
        else:
            is_ev = open_day & np.isfinite(z) & (z >= thr)
            how = f"APPROXIMATE: empirical, peak range in [0,+2] min >= {thr:.1f}x the median of [-45,-15); control false-positive rate "
            how += f"{100 * float((controls >= thr).mean()):.1f}%"
        non = open_day & ~is_ev & np.isfinite(z)
        cur_mask = np.asarray(dates >= cur_start)
        rows = []
        for r in REL:
            c = a + r
            def st(sel_, mat, f):
                v = mat[sel_, c]
                v = v[np.isfinite(v)]
                return (f(v) if len(v) else np.nan, len(v))
            e_r = st(is_ev, rng, np.median)
            n_r = st(non, rng, np.median)
            esel, nsel = is_ev & has_ticks, non & has_ticks
            rows.append({"rel_min": r, "range_med_event": e_r[0], "range_med_non": n_r[0],
                         "range_p90_event": st(is_ev, rng, lambda v: np.quantile(v, .9))[0], "range_p90_non": st(non, rng, lambda v: np.quantile(v, .9))[0],
                         "spread_ratio_med_event": st(esel, sr, np.median)[0], "spread_ratio_med_non": st(nsel, sr, np.median)[0],
                         "spread_ratio_p99_event": st(esel, sr, lambda v: np.quantile(v, .99))[0], "spread_ratio_p99_non": st(nsel, sr, lambda v: np.quantile(v, .99))[0],
                         "spread_max_event": st(esel, sm, np.max)[0], "spread_max_non": st(nsel, sm, np.max)[0],
                         "spread_max_event_cur": st(is_ev & cur_mask, sm, np.max)[0], "spread_max_non_cur": st(non & cur_mask, sm, np.max)[0],
                         "N_range_event": e_r[1], "N_spread_event": st(esel, sr, np.median)[1]})
        yrs = pd.Series(dates[is_ev].year).value_counts().sort_index()
        anchors[label] = {"table": pd.DataFrame(rows).round(3), "how": how, "n_event_days": int(is_ev.sum()), "n_non_event_days": int(non.sum()),
                          "n_event_days_with_ticks": int((is_ev & has_ticks).sum()), "n_event_days_cur": int((is_ev & cur_mask).sum()), "threshold": thr, "by_year": yrs}
    return anchors


def window_summary(tbl: pd.DataFrame) -> pd.DataFrame:
    """Aggregate the per-minute event table into a handful of windows for the report."""
    bins = [("-15..-1", -15, -1), ("0", 0, 0), ("+1..+2", 1, 2), ("+3..+5", 3, 5), ("+6..+15", 6, 15), ("+16..+30", 16, 30)]
    rows = []
    for name, lo, hi in bins:
        w = tbl[(tbl["rel_min"] >= lo) & (tbl["rel_min"] <= hi)]
        rows.append({"window (min)": name,
                     "range_med_event": w["range_med_event"].median(), "range_med_non": w["range_med_non"].median(),
                     "range_x": w["range_med_event"].median() / w["range_med_non"].median(),
                     "spread_ratio_med_event": w["spread_ratio_med_event"].median(), "spread_ratio_med_non": w["spread_ratio_med_non"].median(),
                     "spread_ratio_p99_event": w["spread_ratio_p99_event"].max(), "spread_ratio_p99_non": w["spread_ratio_p99_non"].max(),
                     "spread_max_event": w["spread_max_event"].max(), "spread_max_non": w["spread_max_non"].max(),
                     "spread_max_event_cur": w["spread_max_event_cur"].max(), "spread_max_non_cur": w["spread_max_non_cur"].max()})
    return pd.DataFrame(rows).round(3)


# ------------------------------------------------------------------ 2d monthly, 2e exceedance
def monthly(mm: pd.DataFrame, m1: pd.DataFrame, point: float) -> pd.DataFrame:
    b = m1[["time", "spread"]].copy()
    b["ym"] = pd.DatetimeIndex(pd.to_datetime(b["time"], unit="s")).to_period("M")
    b["pt"] = b["spread"] * point
    bm = b.groupby("ym")["pt"].agg(bars_median="median", bars_p99=lambda x: x.quantile(.99), bars_N="size")
    t = mm.assign(ym=pd.DatetimeIndex(mm["srv"]).to_period("M")).groupby("ym").agg(
        tick_median=("s_med_pt", "median"), tick_p99=("s_med_pt", lambda x: x.quantile(.99)), tick_max=("s_max_pt", "max"), tick_N=("s_med_pt", "size"))
    out = bm.join(t, how="left").round(3)
    out["tick_N"] = out["tick_N"].astype("Int64")
    out.index.name = "month"
    out["primary_source"] = np.where(out["tick_N"].notna(), "ticks", "bars (single snapshot/bar, biased)")
    return out


def exceedance(mm: pd.DataFrame, cur_start: pd.Timestamp) -> pd.DataFrame:
    rth = (mm["mod_et"] >= 9 * 60 + 30) & (mm["mod_et"] < 16 * 60)
    groups = {str(y): mm["date"].dt.year == y for y in sorted(mm["date"].dt.year.unique())}
    groups["ALL"] = pd.Series(True, index=mm.index)
    groups[f"current regime (since {cur_start.date()})"] = mm["date"] >= cur_start
    groups["ALL, cash session 09:30-16:00 ET only"] = rth
    rows = []
    for name, sel in groups.items():
        d = mm[sel]
        row = {"sample": name, "N_min": len(d)}
        for k in (2, 4, 8):
            row[f"s_med>{k}x"] = f"{100 * (d['r_med'] > k).mean():.4f}%"
        for k in (2, 4, 8):
            row[f"s_max>{k}x"] = f"{100 * (d['r_max'] > k).mean():.4f}%"
        rows.append(row)
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ bar spread vs ticks
def bar_vs_tick(m1: pd.DataFrame, mm: pd.DataFrame) -> pd.DataFrame:
    b = m1[["time", "spread"]].copy()
    b["m"] = b["time"] // 60
    j = b.merge(mm[["m", "s_carry", "s_last", "s_med", "s_min", "s_max"]], on="m", how="inner")
    rows = []
    for c in ("s_carry", "s_last", "s_med", "s_min", "s_max"):
        v = j[c].where(j[c] >= 0)
        d = (j["spread"] - v).dropna()
        rows.append({"tick-derived reference": {"s_carry": "spread at minute open (carried-in quote)", "s_last": "spread at last tick of the minute",
                                                 "s_med": "time-weighted median in the minute", "s_min": "minimum in the minute", "s_max": "maximum in the minute"}[c],
                     "N": len(d), "bar == ref %": round(100 * float((d == 0).mean()), 2), "mean(bar-ref) pts": round(float(d.mean()), 3),
                     "median(bar-ref) pts": float(d.median()), "p01 diff": float(d.quantile(.01)), "p99 diff": float(d.quantile(.99))})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ inputs for the cost model (task 6)
def cost_spreads(mm: pd.DataFrame, reg: pd.DataFrame, cur_start: pd.Timestamp) -> dict:
    """Spread statistics (index points) used by the hurdle table. Current regime = since the last level change."""
    rth = (mm["mod_et"] >= 9 * 60 + 30) & (mm["mod_et"] < 16 * 60)
    open_b = (mm["mod_et"] >= 9 * 60 + 30) & (mm["mod_et"] < 10 * 60)
    close_b = (mm["mod_et"] >= 15 * 60 + 30) & (mm["mod_et"] < 16 * 60)
    cur = mm["date"] >= cur_start
    big = reg[reg["days"] >= 30]
    worst = big.loc[big["level_pts"].idxmax()]
    wsel = (mm["date"] >= pd.Timestamp(worst["start"])) & (mm["date"] <= pd.Timestamp(worst["end"]))

    def st(sel):
        v = mm.loc[sel, "s_med_pt"]
        return {"N": int(len(v)), "p50": round(float(v.quantile(.5)), 3), "p99": round(float(v.quantile(.99)), 3),
                "max_tick": round(float(mm.loc[sel, "s_max_pt"].max()), 3)}
    return {"current_regime_start": str(cur_start.date()),
            "rth_current": st(rth & cur), "open_bucket_current": st(open_b & cur), "close_bucket_current": st(close_b & cur),
            "worst_regime": {"start": str(worst["start"]), "end": str(worst["end"]), "level_pts": float(worst["level_pts"]),
                             "open_bucket": st(open_b & wsel), "close_bucket": st(close_b & wsel)},
            "rth_all_history": st(rth), "open_bucket_all_history": st(open_b), "close_bucket_all_history": st(close_b)}


def bucket_ratio_table(mm: pd.DataFrame, col_b: str) -> pd.DataFrame:
    """Level-neutral view over ALL regimes: spread divided by the day's own median, per 30-minute bucket."""
    g = mm.groupby(col_b)
    t = pd.DataFrame({"N_min": g.size(), "p99 (s_med ratio)": g["r_med"].quantile(.99), "p99.9 (s_max ratio)": g["r_max"].quantile(.999),
                      "max (s_max ratio)": g["r_max"].max(), "share s_max > 2x %": 100 * g["r_max"].apply(lambda x: (x > 2).mean()),
                      "share s_max > 4x %": 100 * g["r_max"].apply(lambda x: (x > 4).mean())}).round(3)
    t.insert(0, "bucket", [bucket_label(b) for b in t.index])
    return t
