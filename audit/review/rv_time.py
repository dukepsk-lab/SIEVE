"""Reviewer: independent server-clock checks from the live M1 pull (no hypothesis list, no implementer code).

A. Cash-open step: per server minute m, ratio = mean 1-min range over [m, m+10) / mean over [m-10, m), median over the
   week's weekdays; the argmax is searched over ALL minutes 06:00-22:00 server (unconstrained, so not circular).
B. FOMC statements (14:00 ET, dates from the public Fed calendar, supplied by the reviewer => APPROXIMATE source):
   the largest 1-min range between 16:00 and 21:59 server on that day. London clock and a US-DST-linked clock
   (ET+5) predict different minutes in the US/EU DST mismatch weeks.
C. Daily re-open after the break, in SERVER time, per week type: the underlying futures halt 17:00-18:00 ET, so if the
   server followed US DST the re-open would sit at the same server minute all year.
   python audit/review/rv_time.py <scratch_dir>"""
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rv_common import NY, OUT, UTC, LON  # noqa: E402

SCRATCH = Path(sys.argv[1])
m1 = pd.read_parquet(SCRATCH / "m1_live_all.parquet")
m1 = m1.iloc[:-1]                                           # drop the bar that was still forming at pull time
t = m1["time"].to_numpy()
day, mod = t // 86400, (t % 86400) // 60
d0 = day.min()
R = np.full((day.max() - d0 + 1, 1440), np.nan)
R[day - d0, mod] = (m1["high"] - m1["low"]).to_numpy()
dates = pd.to_datetime((d0 + np.arange(R.shape[0])) * 86400, unit="s")


def roll_mean(a, n, fwd):
    out = np.full_like(a, np.nan)
    for m in range(n, 1440 - n):
        w = a[:, m:m + n] if fwd else a[:, m - n:m]
        ok = np.isfinite(w).sum(axis=1) >= 0.8 * n
        with np.errstate(all="ignore"):
            out[ok, m] = np.nanmean(w[ok], axis=1)
    return out


def predicted(week_monday: str):
    """Server minute of 09:30 ET on the Wednesday of that week under each clock hypothesis."""
    wed = pd.Timestamp(week_monday) + pd.Timedelta(days=2)
    utc = datetime(wed.year, wed.month, wed.day, 9, 30, tzinfo=NY).astimezone(UTC)
    lon = utc.astimezone(LON)
    ny = datetime(wed.year, wed.month, wed.day, 9, 30)
    return {"UTC_fixed": utc.strftime("%H:%M"), "London": lon.strftime("%H:%M"), "ET+5": (ny + pd.Timedelta(hours=5)).strftime("%H:%M"),
            "NY_close_ET+7": (ny + pd.Timedelta(hours=7)).strftime("%H:%M")}


out = {"A_cash_open_step": [], "B_fomc": [], "C_reopen_server_time": {}}
weeks = {"winter 2025-01-13": "2025-01-13", "summer 2025-07-14": "2025-07-14", "mismatch Mar 2025-03-17": "2025-03-17",
         "mismatch Oct 2024-10-28": "2024-10-28", "mismatch Mar 2026-03-16": "2026-03-16", "UTC-era summer 2021-07-12": "2021-07-12",
         "London-era summer 2022-07-11": "2022-07-11", "winter 2023-01-09": "2023-01-09"}
for label, wk in weeks.items():
    w0 = pd.Timestamp(wk)
    rows = np.flatnonzero((dates >= w0) & (dates < w0 + pd.Timedelta(days=5)))
    sub = R[rows]
    with np.errstate(all="ignore"):
        ratio = roll_mean(sub, 10, True) / roll_mean(sub, 10, False)
        med = np.nanmedian(ratio, axis=0)
    med[:6 * 60] = np.nan
    med[22 * 60:] = np.nan
    order = np.argsort(-np.nan_to_num(med, nan=-1))[:3]
    top = [(f"{m // 60:02d}:{m % 60:02d}", round(float(med[m]), 2)) for m in order]
    out["A_cash_open_step"].append({"week": label, "days": int(len(rows)), "argmax_server": top[0][0], "top3": top, "predicted": predicted(wk)})

# B. FOMC statement days (14:00 ET). Reviewer-supplied from the public FOMC calendar.
fomc = ["2022-03-16", "2023-03-22", "2024-03-20", "2025-03-19", "2022-11-02", "2023-11-01", "2025-10-29",   # US/EU mismatch weeks
        "2024-07-31", "2025-07-30", "2024-12-18", "2025-01-29", "2021-07-28", "2021-11-03"]                   # controls
for d in fomc:
    i = int(np.flatnonzero(dates == pd.Timestamp(d))[0])
    seg = R[i, 16 * 60:22 * 60]
    m = 16 * 60 + int(np.nanargmax(seg))
    base = np.nanmedian(R[i, 16 * 60:17 * 60 + 30])
    utc = datetime(*map(int, d.split("-")), 14, 0, tzinfo=NY).astimezone(UTC)
    win = {f"x_at_{h}:{mm_:02d}-{h}:{mm_ + 2:02d}": round(float(np.nanmax(R[i, h * 60 + mm_:h * 60 + mm_ + 3]) / base), 1)
           for h, mm_ in ((18, 0), (19, 0), (18, 30), (19, 30))}
    out["B_fomc"].append({"date": d, "max_range_minute_server": f"{m // 60:02d}:{m % 60:02d}", "range_pts": float(R[i, m]),
                          "x_median_16:00-17:30": round(float(R[i, m] / base), 1), **win,
                          "pred_London": utc.astimezone(LON).strftime("%H:%M"), "pred_ET+5": (datetime(*map(int, d.split("-")), 19, 0)).strftime("%H:%M"),
                          "pred_UTC_fixed": utc.strftime("%H:%M")})

# C. re-open after the daily break, server clock, London era only, Mon-Thu server dates
srv = pd.to_datetime(t, unit="s")
gap = np.diff(t)
idx = np.flatnonzero(gap >= 30 * 60)                     # bar i is followed by a gap of >= 30 min
reo = pd.DataFrame({"last_before": srv[idx], "reopen": srv[idx + 1], "gap_min": gap[idx] // 60})
reo = reo[(reo["reopen"].dt.hour >= 21) & (reo["reopen"].dt.hour <= 23) & (reo["reopen"].dt.dayofweek <= 3) & (reo["gap_min"] < 240)]
reo = reo[reo["reopen"] >= "2022-04-01"]


def week_type(ts):
    d = ts.to_pydatetime()
    us = datetime(d.year, d.month, d.day, 12, tzinfo=NY).utcoffset().total_seconds() / 3600 + 5          # 1 if US DST
    eu = datetime(d.year, d.month, d.day, 12, tzinfo=LON).utcoffset().total_seconds() / 3600               # 1 if EU DST
    return "mismatch (US DST, EU not)" if us != eu else "normal"


reo["type"] = reo["reopen"].map(week_type)
reo["reopen_hhmm"] = reo["reopen"].dt.strftime("%H:%M")
tab = reo.groupby(["type", "reopen_hhmm"]).size().rename("days").reset_index()
tab = tab[tab["days"] >= 3].sort_values(["type", "days"], ascending=[True, False])
out["C_reopen_server_time"] = tab.to_dict("records")
out["C_note"] = ("London-era re-opens (Mon-Thu, from 2022-04). Under ET+5 or NY-close the re-open would sit at the SAME server minute in normal "
                 "and mismatch weeks; under London it is 1 h earlier in mismatch weeks.")
(OUT / "rv_time.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
print(json.dumps(out, indent=1, default=str))
