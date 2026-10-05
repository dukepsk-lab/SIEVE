"""Reviewer: per-minute time-weighted spread (LOCF) recomputed from the RAW tick parquet files (verified identical to a
live re-pull for 3 days in rv_live.py), with the reviewer's own clock model. Two ET buckets: 09:30-09:59 (cash open)
and 03:00-03:29 (quiet). Each quote lives from its tick to the next tick, but at most 5 minutes (no fill across the
daily break / weekend / gaps); ticks with bid<=0, ask<=0 or ask<bid are dropped.

Two minute populations are reported: 'tick minutes' (minutes with >=1 valid tick, the implementer's definition) and
'covered minutes' (any minute where a quote <=5 min old is live, i.e. full LOCF).
   python audit/review/rv_spread.py <scratch_dir>"""
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rv_common import CACHE, NY, OUT, UTC, server_to_utc_one  # noqa: E402

SCRATCH = Path(sys.argv[1])
CARRY = 300_000
BUCKETS = {"09:30-09:59 ET": 9 * 60 + 30, "03:00-03:29 ET": 3 * 60}


def et_minus_server_min(day: datetime) -> int:
    noon = day.replace(hour=12)
    et = server_to_utc_one(noon).replace(tzinfo=UTC).astimezone(NY).replace(tzinfo=None)
    return int((et - noon).total_seconds() // 60)


def per_minute(t, s, w0, w1):
    """time-weighted median / max / tick count for every minute in [w0, w1) ms."""
    grid = np.arange(w0, w1 + 1, 60_000)
    inside = t[(t >= w0) & (t < w1)]
    pts = np.unique(np.r_[inside, grid])
    st, en = pts[:-1], pts[1:]
    idx = np.searchsorted(t, st, side="right") - 1
    ok = (idx >= 0)
    ok[ok] &= (st[ok] - t[idx[ok]] <= CARRY)
    st, en, idx = st[ok], en[ok], idx[ok]
    minute, spr, w = st // 60_000, s[idx], en - st
    o = np.lexsort((spr, minute))
    minute, spr, w = minute[o], spr[o], w[o]
    rows = []
    for m in np.unique(minute):
        a, b = np.searchsorted(minute, [m, m + 1])
        cw = np.cumsum(w[a:b])
        med = spr[a:b][np.searchsorted(cw, 0.5 * cw[-1])]
        lo, hi = np.searchsorted(t, [m * 60_000, (m + 1) * 60_000])
        n_ticks = int(hi - lo)
        rows.append((m, med, spr[a:b].max(), n_ticks))
    return rows


days = sorted((CACHE / "ticks" / "USTEC").glob("*/*.parquet"))
recs = []
for f in days:
    day = datetime.strptime(f.stem, "%Y-%m-%d")
    tk = pd.read_parquet(f, columns=["time_msc", "bid", "ask"])
    if tk.empty:
        continue
    tk = tk.sort_values("time_msc", kind="stable")
    t, bid, ask = tk["time_msc"].to_numpy(), tk["bid"].to_numpy().astype(np.int64), tk["ask"].to_numpy().astype(np.int64)
    ok = (bid > 0) & (ask > 0) & (ask >= bid)
    t, s = t[ok], (ask - bid)[ok]
    shift = et_minus_server_min(day)                   # ET = server + shift
    d0 = int(pd.Timestamp(day).value // 1_000_000)
    for name, et_min in BUCKETS.items():
        srv_min = et_min - shift
        if not 0 <= srv_min < 1440:
            continue
        w0 = d0 + srv_min * 60_000
        for m, med, mx, n in per_minute(t, s, w0, w0 + 30 * 60_000):
            recs.append((name, m, med, mx, n))
df = pd.DataFrame(recs, columns=["bucket", "m", "s_med", "s_max", "n_ticks"])
srv = pd.to_datetime(df["m"] * 60, unit="s")
df["et_date"] = (srv + pd.to_timedelta([et_minus_server_min(d.to_pydatetime()) for d in srv.dt.normalize()], unit="min")).dt.normalize()
df.to_parquet(SCRATCH / "rv_spread_minutes.parquet", index=False)

periods = {"current regime 2026-05-14..2026-10-04": ("2026-05-14", "2026-10-04"),
           "worst regime 2024-07-23..2024-10-27": ("2024-07-23", "2024-10-27"),
           "all tick history": ("2021-08-16", "2026-10-04"),
           "year 2023": ("2023-01-01", "2023-12-31")}
res = []
for pname, (a, b) in periods.items():
    for bname in BUCKETS:
        sel = df[(df["bucket"] == bname) & (df["et_date"] >= a) & (df["et_date"] <= b)]
        for pop, d in (("tick minutes", sel[sel["n_ticks"] > 0]), ("covered minutes", sel)):
            v = d["s_med"].to_numpy() / 100.0                 # points -> index points (point = 0.01)
            res.append({"period": pname, "bucket": bname, "population": pop, "N_min": int(len(v)),
                        "p50": round(float(np.quantile(v, .5)), 3), "p90": round(float(np.quantile(v, .9)), 3),
                        "p99": round(float(np.quantile(v, .99)), 3), "max_tick": round(float(d["s_max"].max() / 100), 3),
                        "p99_of_minute_max": round(float(np.quantile(d["s_max"].to_numpy() / 100, .99)), 3),
                        "p99.9_of_minute_max": round(float(np.quantile(d["s_max"].to_numpy() / 100, .999)), 3)})
(OUT / "rv_spread.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
print(pd.DataFrame(res).to_string())
