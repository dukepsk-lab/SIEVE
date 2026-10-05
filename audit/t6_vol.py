"""Task 6: volatility calibration and the cost-hurdle table.

Prices: P(T) = open of the M1 bar at New York time T (the price at the start of that minute); when there is no bar at T
(e.g. the session already ended at 15:59 ET) the close of the bar at T-1min, which is the last recorded price before T.
A sample is dropped when either end price is missing; nothing is interpolated. Sigma = std of the price difference in index points over the horizon
(non-overlapping samples), grouped by the calendar year of the start date.

Horizons
  5min / 1h   non-overlapping blocks aligned to 09:30 ET inside the cash session (RTH), and, for reference, every aligned
              block of the clock day (all hours)
  6h          09:30 -> 15:30 ET (6.0h); 09:30 -> 16:00 ET (6.5h, the full cash session) is also reported
  overnight   16:00 ET -> next day 09:30 ET, Monday-Thursday nights only (Friday -> Monday reported separately)
  5d          Friday 16:00 ET -> next Friday 16:00 ET (5 trading days)

Hurdle: required hit rate = 0.5 + C / (1.6 sigma_h) for payoff 1:1 (1.6 sigma = 2 x 0.8 sigma, 0.8 sigma ~ mean |move|).
"""
import numpy as np
import pandas as pd

from . import config as C

HORIZONS = ["5min", "1h", "6h", "overnight", "5d"]
NIGHTS = {"5min": 0, "1h": 0, "6h": 0, "overnight": 1, "5d": 7}


def _price_lookup(m1: pd.DataFrame, clock):
    """Series of open prices by ET timestamp, with a fallback for missing minutes (see module docstring)."""
    srv = pd.DatetimeIndex(pd.to_datetime(m1["time"], unit="s")).as_unit("ns")
    et = clock.to_et(srv)
    o = pd.Series(m1["open"].to_numpy(), index=et)
    c = pd.Series(m1["close"].to_numpy(), index=et)
    return o[~o.index.duplicated(keep="first")], c[~c.index.duplicated(keep="first")], et


def _diff(P, t0: pd.DatetimeIndex, t1: pd.DatetimeIndex) -> pd.DataFrame:
    o, c = P

    def price(t):
        return o.reindex(t).fillna(pd.Series(c.reindex(t - pd.Timedelta(minutes=1)).to_numpy(), index=t)).to_numpy()
    a, b = price(t0), price(t1)
    return pd.DataFrame({"start": t0, "move": b - a, "p0": a}).dropna()


def samples(m1: pd.DataFrame, clock) -> dict:
    o, c, et = _price_lookup(m1, clock)
    P = (o, c)
    dates = pd.DatetimeIndex(et.normalize().unique()).sort_values()
    dates = dates[dates.dayofweek < 5]
    out = {}

    def grid(step_min, n_steps, start_min=9 * 60 + 30):
        offs = pd.to_timedelta(start_min + step_min * np.arange(n_steps), unit="min")
        return pd.DatetimeIndex((dates.to_numpy()[:, None] + offs.to_numpy()[None, :]).ravel())

    t0 = grid(5, 78)                                                                  # 09:30 .. 15:55
    out["5min|RTH"] = _diff(P, t0, t0 + pd.Timedelta(minutes=5))
    t0 = grid(60, 6)                                                                  # 09:30 .. 14:30 -> ends 15:30
    out["1h|RTH"] = _diff(P, t0, t0 + pd.Timedelta(hours=1))
    allm = o.index[(o.index.minute % 5 == 0) & (o.index.second == 0)]
    out["5min|all hours"] = _diff(P, allm, allm + pd.Timedelta(minutes=5))
    allh = o.index[o.index.minute == 0]
    out["1h|all hours"] = _diff(P, allh, allh + pd.Timedelta(hours=1))
    d930 = dates + pd.Timedelta(hours=9, minutes=30)
    out["6h|09:30-15:30 ET"] = _diff(P, d930, d930 + pd.Timedelta(hours=6))
    out["6.5h|09:30-16:00 ET (full cash session)"] = _diff(P, d930, d930 + pd.Timedelta(hours=6, minutes=30))
    d16 = dates + pd.Timedelta(hours=16)
    nxt = d16 + pd.Timedelta(days=1, hours=-6, minutes=-30)                           # next calendar day 09:30
    mon_thu = dates.dayofweek <= 3
    out["overnight|Mon-Thu nights"] = _diff(P, d16[mon_thu], nxt[mon_thu])
    fri = dates.dayofweek == 4
    out["weekend|Fri 16:00 - Mon 09:30"] = _diff(P, d16[fri], (d16 + pd.Timedelta(days=3, hours=-6, minutes=-30))[fri])
    out["5d|Fri 16:00 - next Fri 16:00"] = _diff(P, d16[fri], (d16 + pd.Timedelta(days=7))[fri])
    return out


def _sigma_row(d: pd.DataFrame) -> dict:
    m = d["move"].to_numpy()
    return {"N": len(m), "sigma_pts": float(np.std(m, ddof=1)) if len(m) > 2 else np.nan,
            "mean_abs_over_sigma": float(np.mean(np.abs(m)) / np.std(m, ddof=1)) if len(m) > 2 else np.nan}


def sigma_tables(smp: dict, last_date: pd.Timestamp) -> dict:
    by_year = {}
    for name, d in smp.items():
        rows = {}
        for y, g in d.groupby(d["start"].dt.year):
            rows[y] = _sigma_row(g)
        rows["ALL"] = _sigma_row(d)
        rows["last 12 months"] = _sigma_row(d[d["start"] > last_date - pd.Timedelta(days=365)])
        tbl = pd.DataFrame(rows).T
        tbl["N"] = tbl["N"].astype(int)
        tbl.index.name = "year"
        by_year[name] = tbl
    return by_year


def price_levels(m1: pd.DataFrame, last_date: pd.Timestamp) -> pd.Series:
    y = pd.DatetimeIndex(pd.to_datetime(m1["time"], unit="s")).year
    lv = m1.groupby(y)["close"].mean().round(0)
    last12 = m1[m1["time"] > m1["time"].iloc[-1] - 365 * 86400]["close"].mean()
    lv["last 12 months"] = round(last12, 0)
    return lv


# ------------------------------------------------------------------ hurdle table
def required_hit_rate(cost: float, sigma: float) -> float:
    return 0.5 + cost / (1.6 * sigma)


def hurdle(sig: dict, mad: dict, spreads: dict, swap_long_pts: float, commission_pts: float) -> pd.DataFrame:
    """sig / mad: {'5min': sigma, ...} and mean |move| in points, measured over the last 12 months. spreads: t2.cost_spreads.
    swap_long_pts: signed index points per night as MT5 books it (negative = the long pays). Round-trip cost
    C = one spread + slippage on both sides + commission + swap x nights; the spread is paid once per round trip
    (half at entry, half at exit), so for horizons crossing two different time buckets the two p99s are averaged."""
    s_base = spreads["rth_current"]["p50"]
    p99_open, p99_close = spreads["open_bucket_current"]["p99"], spreads["close_bucket_current"]["p99"]
    w_open, w_close = spreads["worst_regime"]["open_bucket"]["p99"], spreads["worst_regime"]["close_bucket"]["p99"]
    rows = []
    for h in HORIZONS:
        intraday = NIGHTS[h] == 0
        entry_exit = {"base": s_base, "stress (p99, current regime)": p99_open if intraday else (p99_close + p99_open) / 2,
                      "stress-alt (p99, worst past regime)": w_open if intraday else (w_close + w_open) / 2}
        if h == "5d":
            entry_exit["stress (p99, current regime)"] = p99_close
            entry_exit["stress-alt (p99, worst past regime)"] = w_close
        for case, spr in entry_exit.items():
            slip = 2 * (C.SLIP_BASE_PER_SIDE if case == "base" else C.SLIP_STRESS_PER_SIDE)
            for side in (["long", "short"] if NIGHTS[h] else ["n/a"]):
                swap = (-swap_long_pts if side == "long" else 0.0) * NIGHTS[h]
                cost = spr + slip + commission_pts + swap
                rows.append({"horizon": h, "case": case, "side": side, "sigma_pts": round(sig[h], 1), "spread": round(spr, 2),
                             "slippage (ASSUMED)": slip, "commission": round(commission_pts, 2), "swap": round(swap, 2),
                             "C_total_pts": round(cost, 2), "required_hit_rate_%": round(100 * required_hit_rate(cost, sig[h]), 2),
                             "required_hit_rate_% using measured mean abs move": round(100 * (0.5 + cost / (2 * mad[h])), 2)})
    return pd.DataFrame(rows)


def compare_with_assumptions(sig_meas: dict, hurdle_df: pd.DataFrame, commission_pts: float) -> pd.DataFrame:
    """Same formula with the user's earlier assumptions (spread 2/8 pts, swap 4.6 pt/night long, sigma 19/65/160/150/700)
    and the same ASSUMED slippage, vs the measured base/stress rows."""
    A = C.USER_ASSUMED
    rows = []
    for h in HORIZONS:
        n = NIGHTS[h]
        for case, spr, slip in (("base", A["spread_base"], 2 * C.SLIP_BASE_PER_SIDE), ("stress", A["spread_stress"], 2 * C.SLIP_STRESS_PER_SIDE)):
            c_assumed = spr + slip + A["swap_long_per_night"] * n
            rate_assumed = required_hit_rate(c_assumed, A["sigma"][h])
            meas = hurdle_df[(hurdle_df["horizon"] == h) & (hurdle_df["case"].str.startswith(case)) & (hurdle_df["side"].isin(["n/a", "long"]))]
            meas = meas[~meas["case"].str.contains("alt")].iloc[0]
            rows.append({"horizon": h, "case": case,
                         "sigma assumed": A["sigma"][h], "sigma measured": meas["sigma_pts"],
                         "C assumed": round(c_assumed, 2), "C measured": meas["C_total_pts"],
                         "hit rate assumed %": round(100 * rate_assumed, 2), "hit rate measured %": meas["required_hit_rate_%"],
                         "verdict": "better" if meas["required_hit_rate_%"] < 100 * rate_assumed - 0.05 else ("worse" if meas["required_hit_rate_%"] > 100 * rate_assumed + 0.05 else "same")})
    return pd.DataFrame(rows)
