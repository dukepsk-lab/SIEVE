"""Task 5: data integrity.

Outlier rule: a 1-minute log return (only between consecutive minute bars) is an outlier when |ret| > 8 x sigma, where
sigma is the std of the previous 120 valid 1-minute returns (min 60), shifted one bar so the current return never
enters its own sigma (no lookahead). Returns across gaps (daily break, weekend, missing minutes) are not tested here.
"""
import logging

import numpy as np
import pandas as pd

log = logging.getLogger("audit")
SIGMA_WINDOW, SIGMA_MIN, K = 120, 60, 8.0
NEWS_WINDOWS = [(8 * 60 + 25, 8 * 60 + 36), (9 * 60 + 25, 9 * 60 + 41), (9 * 60 + 55, 10 * 60 + 6),
                (13 * 60 + 55, 14 * 60 + 6), (14 * 60 + 25, 14 * 60 + 36)]


def _et_series(m1, clock):
    srv = pd.DatetimeIndex(pd.to_datetime(m1["time"], unit="s")).as_unit("ns")
    return srv, clock.to_et(srv)


# ------------------------------------------------------------------ bars
def bar_integrity(m1: pd.DataFrame, point: float, load_attrs: dict) -> dict:
    o, h, l, c = (m1[x].to_numpy() for x in ("open", "high", "low", "close"))
    year = pd.DatetimeIndex(pd.to_datetime(m1["time"], unit="s")).year
    flat = h == l
    res = {
        "bars": len(m1),
        "duplicate_timestamps": int(load_attrs.get("n_dup_time", 0)),
        "non_monotonic_timestamps": int(load_attrs.get("n_nonmonotonic", 0)),
        "nan_prices": int(np.isnan(m1[["open", "high", "low", "close"]].to_numpy()).sum()),
        "nonpositive_prices": int((m1[["open", "high", "low", "close"]].to_numpy() <= 0).sum()),
        "high<low": int((h < l).sum()),
        "high<max(open,close)": int((h < np.maximum(o, c) - point / 2).sum()),
        "low>min(open,close)": int((l > np.minimum(o, c) + point / 2).sum()),
        "zero_range_bars (high==low)": int(flat.sum()),
        "zero_range_pct": round(100 * float(flat.mean()), 3),
        "bar_spread==0": int((m1["spread"] == 0).sum()),
        "bar_spread<0": int((m1["spread"] < 0).sum()),
        "tick_volume==0": int((m1["tick_volume"] == 0).sum()),
        "real_volume_nonzero": int((m1["real_volume"] != 0).sum()),
    }
    by_year = pd.DataFrame({"year": year, "zero_range": flat, "spread_zero": m1["spread"].to_numpy() == 0}) \
        .groupby("year").agg(bars=("zero_range", "size"), zero_range_pct=("zero_range", lambda x: round(100 * x.mean(), 2)),
                             bar_spread_zero_pct=("spread_zero", lambda x: round(100 * x.mean(), 2)))
    return {"summary": res, "by_year": by_year}


def stale_runs(m1: pd.DataFrame, clock) -> dict:
    """Consecutive bars with no price change at all (open=high=low=close=previous close)."""
    c, t = m1["close"].to_numpy(), m1["time"].to_numpy()
    same = np.r_[False, (m1["high"].to_numpy()[1:] == m1["low"].to_numpy()[1:]) & (c[1:] == c[:-1]) & (np.diff(t) == 60)]
    run_id = np.cumsum(~same)
    d = pd.DataFrame({"run": run_id[same], "t": t[same]})
    runs = d.groupby("run").agg(minutes=("t", "size"), first=("t", "min"), last=("t", "max"))
    runs["minutes"] += 1        # the bar that opened the run also had that price
    srv = pd.DatetimeIndex(pd.to_datetime(runs["first"], unit="s")).as_unit("ns")
    runs["start_server"], runs["start_et"] = srv, clock.to_et(srv)
    counts = pd.DataFrame({f">={n} min": [int((runs["minutes"] >= n).sum())] for n in (5, 15, 30, 60)}, index=["runs"])
    by_year = runs.groupby(runs["start_server"].dt.year).apply(lambda r: pd.Series({f">={n} min": int((r["minutes"] >= n).sum()) for n in (5, 15, 30, 60)}))
    return {"counts": counts, "by_year": by_year, "top": runs.nlargest(10, "minutes")[["start_server", "start_et", "minutes"]]}


def returns_and_sigma(m1: pd.DataFrame) -> pd.DataFrame:
    t, c = m1["time"].to_numpy(), m1["close"].to_numpy()
    consec = np.r_[False, np.diff(t) == 60]
    ret = np.where(consec, np.log(c / np.r_[np.nan, c[:-1]]), np.nan)
    sigma = pd.Series(ret).rolling(SIGMA_WINDOW, min_periods=SIGMA_MIN).std().shift(1).to_numpy()
    sigma = np.maximum(sigma, 1e-6)
    return pd.DataFrame({"time": t, "close": c, "ret": ret, "sigma": sigma, "z": np.abs(ret) / sigma, "tick_volume": m1["tick_volume"].to_numpy()})


def outliers(rs: pd.DataFrame, clock) -> dict:
    out = rs[rs["z"] > K].copy()
    srv = pd.DatetimeIndex(pd.to_datetime(out["time"], unit="s")).as_unit("ns")
    out["server"], out["et"] = srv, clock.to_et(srv)
    out["move_pts"] = (out["ret"] * out["close"]).round(2)
    out["sigma_pts"] = (out["sigma"] * out["close"]).round(2)
    mod = out["et"].dt.hour * 60 + out["et"].dt.minute
    news = np.zeros(len(out), dtype=bool)
    for a, b in NEWS_WINDOWS:
        news |= ((mod >= a) & (mod < b)).to_numpy()
    out["in_news_window"] = news
    valid = rs["ret"].notna() & rs["sigma"].notna()
    by_year = out.groupby(out["server"].dt.year).size().rename("outliers").to_frame()
    by_year["tested_returns"] = rs[valid].groupby(pd.DatetimeIndex(pd.to_datetime(rs.loc[valid, "time"], unit="s")).year).size()
    by_year["per_100k"] = (1e5 * by_year["outliers"] / by_year["tested_returns"]).round(1)
    return {"count": len(out), "tested": int(valid.sum()), "share_in_news_windows_pct": round(100 * float(news.mean()), 1) if len(out) else 0.0,
            "by_year": by_year, "top": out.nlargest(30, "z")[["server", "et", "move_pts", "sigma_pts", "z", "tick_volume", "in_news_window"]].round({"move_pts": 1, "sigma_pts": 2, "z": 1}),
            "top_quiet": out[~out["in_news_window"]].nlargest(15, "z")[["server", "et", "move_pts", "sigma_pts", "z", "tick_volume"]].round({"move_pts": 1, "sigma_pts": 2, "z": 1})}


# ------------------------------------------------------------------ roll / jump check
def _third_fridays(start, end) -> pd.DatetimeIndex:
    return pd.date_range(start, end, freq="WOM-3FRI")


def roll_check(m1: pd.DataFrame, rs: pd.DataFrame, clock) -> dict:
    srv, et = _et_series(m1, clock)
    mod = (et.hour * 60 + et.minute).to_numpy()
    quiet = np.ones(len(m1), dtype=bool)
    for a, b in NEWS_WINDOWS:
        quiet &= ~((mod >= a) & (mod < b))
    quiet &= ~((mod >= 17 * 60 + 58) & (mod < 18 * 60 + 5))                  # first minutes after the daily re-open
    date = et.normalize()
    b = pd.DataFrame({"date": date, "mod": mod, "open": m1["open"].to_numpy(), "close": m1["close"].to_numpy(), "t": m1["time"].to_numpy()})
    # break / weekend gaps: last bar before 17:30 ET vs first bar at/after 17:30 ET of the same ET date (Mon-Thu), Fri close vs Sun re-open
    pre = b[b["mod"] < 17 * 60 + 30].groupby("date").last()
    post = b[b["mod"] >= 17 * 60 + 30].groupby("date").first()
    g = pre.join(post, lsuffix="_pre", rsuffix="_post", how="inner")
    g["gap"] = g["open_post"] - g["close_pre"]
    g["gap_pct"] = 100 * g["gap"] / g["close_pre"]
    g["z"] = np.abs(g["gap"]) / g["gap"].rolling(60, min_periods=20).std().shift(1)
    fri = b[(b["date"].dt.dayofweek == 4) & (b["mod"] < 17 * 60 + 30)].groupby("date").last()
    sun = b[(b["date"].dt.dayofweek == 6) & (b["mod"] >= 17 * 60 + 30)].groupby("date").first()
    wk = pd.DataFrame({"open": sun["open"]})
    wk["close_ref"] = fri["close"].reindex(wk.index - pd.Timedelta(days=2)).to_numpy()
    wk["gap"] = wk["open"] - wk["close_ref"]
    wk = wk.dropna()
    wk["gap_pct"] = 100 * wk["gap"] / wk["close_ref"]
    wk["z"] = np.abs(wk["gap"]) / wk["gap"].rolling(40, min_periods=15).std().shift(1)

    zq = np.where(quiet, rs["z"].to_numpy(), np.nan)
    qdf = pd.DataFrame({"date": date, "z": zq, "move_pct": 100 * rs["ret"].to_numpy(), "price": m1["close"].to_numpy(),
                        "et": et, "server": srv}).dropna(subset=["z"])
    first, last = et.min().normalize() + pd.Timedelta(days=12), et.max().normalize() - pd.Timedelta(days=12)
    fridays = _third_fridays(first, last)
    rows = []
    for exp in fridays:
        d = qdf[(qdf["date"] >= exp - pd.Timedelta(days=10)) & (qdf["date"] <= exp + pd.Timedelta(days=10))]
        if d.empty:
            continue
        top = d.loc[d["z"].idxmax()]
        gg = g[(g.index >= exp - pd.Timedelta(days=10)) & (g.index <= exp + pd.Timedelta(days=10))]
        ww = wk[(wk.index >= exp - pd.Timedelta(days=10)) & (wk.index <= exp + pd.Timedelta(days=10))]
        gtop = gg.loc[gg["z"].idxmax()] if gg["z"].notna().any() else None
        wtop = ww.loc[ww["z"].idxmax()] if ww["z"].notna().any() else None
        rows.append({"expiry": exp.date(), "quarterly": exp.month in (3, 6, 9, 12),
                     "quiet_max_z": round(float(top["z"]), 1), "quiet_day_offset": int((top["date"] - exp).days),
                     "quiet_et": str(top["et"].time())[:5], "quiet_move_pct": round(float(top["move_pct"]), 3),
                     "break_gap_max_z": round(float(gtop["z"]), 1) if gtop is not None else np.nan,
                     "break_gap_pct": round(float(gtop["gap_pct"]), 3) if gtop is not None else np.nan,
                     "break_gap_day_offset": int((gtop.name - exp).days) if gtop is not None else np.nan,
                     "weekend_gap_max_z": round(float(wtop["z"]), 1) if wtop is not None else np.nan,
                     "weekend_gap_pct": round(float(wtop["gap_pct"]), 3) if wtop is not None else np.nan})
    t = pd.DataFrame(rows)
    q, ctl = t[t["quarterly"]], t[~t["quarterly"]]

    def summ(x):
        return {"windows": len(x), "median_quiet_max_z": round(float(x["quiet_max_z"].median()), 1),
                "share_quiet_z>8": round(100 * float((x["quiet_max_z"] > 8).mean()), 1),
                "median_break_gap_max_z": round(float(x["break_gap_max_z"].median()), 1),
                "share_break_gap_z>4": round(100 * float((x["break_gap_max_z"] > 4).mean()), 1),
                "median_weekend_gap_max_z": round(float(x["weekend_gap_max_z"].median()), 1),
                "share_weekend_gap_z>4": round(100 * float((x["weekend_gap_max_z"] > 4).mean()), 1),
                "max_abs_quiet_move_pct": round(float(x["quiet_move_pct"].abs().max()), 3),
                "max_abs_break_gap_pct": round(float(x["break_gap_pct"].abs().max()), 3)}
    # pooled: largest |break/weekend gap| in % of price anywhere, to size a hypothetical roll jump
    return {"windows": t, "quarterly_summary": summ(q), "control_summary": summ(ctl),
            "typical_break_gap_pct_sd": round(float(g["gap_pct"].std()), 3), "typical_weekend_gap_pct_sd": round(float(wk["gap_pct"].std()), 3),
            "positive_share_of_quarterly_largest_quiet_moves": round(100 * float((q["quiet_move_pct"] > 0).mean()), 1)}


# ------------------------------------------------------------------ bars vs ticks, volumes
def bars_vs_ticks(m1: pd.DataFrame, mins: pd.DataFrame, point: float) -> dict:
    first_m, last_m = int(mins["m"].min()), int(mins["m"].max())
    b = m1[(m1["time"] // 60 >= first_m) & (m1["time"] // 60 <= last_m)].copy()
    b["m"] = b["time"] // 60
    for k in ("open", "high", "low", "close"):
        b[k + "_pts"] = np.rint(b[k] / point).astype("int64")
    j = b.merge(mins, on="m", how="outer", indicator=True)
    both = j[j["_merge"] == "both"].copy()
    both["year"] = pd.DatetimeIndex(pd.to_datetime(both["m"] * 60, unit="s")).year
    cols = {"O": ("open_pts", "bo", "ao"), "H": ("high_pts", "bh", "ah"), "L": ("low_pts", "bl", "al"), "C": ("close_pts", "bc", "ac")}
    rows = []
    for y, d in list(both.groupby("year")) + [("ALL", both)]:
        r = {"year": y, "minutes_compared": len(d)}
        for k, (bar, bid, ask) in cols.items():
            r[f"{k} bar==bid %"] = round(100 * float((d[bar] == d[bid]).mean()), 2)
        for k, (bar, bid, ask) in cols.items():
            r[f"{k} bar==ask %"] = round(100 * float((d[bar] == d[ask]).mean()), 2)
        r["tick_vol==ticks %"] = round(100 * float((d["tick_volume"] == d["n_all"]).mean()), 2)
        r["tick_vol==bid-changes %"] = round(100 * float((d["tick_volume"] == d["n_bidchg"]).mean()), 2)
        r["sum(tick_vol)/sum(ticks)"] = round(float(d["tick_volume"].sum() / d["n_all"].sum()), 4)
        rows.append(r)
    return {"table": pd.DataFrame(rows), "bars_without_ticks": int((j["_merge"] == "left_only").sum()),
            "tick_minutes_without_bars": int((j["_merge"] == "right_only").sum())}


def volume_summary(m1: pd.DataFrame) -> pd.DataFrame:
    y = pd.DatetimeIndex(pd.to_datetime(m1["time"], unit="s")).year
    g = m1.groupby(y)
    t = pd.DataFrame({"bars": g.size(), "tick_volume_mean": g["tick_volume"].mean().round(1), "tick_volume_median": g["tick_volume"].median(),
                      "tick_volume_p99": g["tick_volume"].quantile(.99), "tick_volume_max": g["tick_volume"].max(),
                      "tick_volume_zero_bars": g["tick_volume"].apply(lambda x: int((x == 0).sum())),
                      "real_volume_nonzero_bars": g["real_volume"].apply(lambda x: int((x != 0).sum()))})
    return t
