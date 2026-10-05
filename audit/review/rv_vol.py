"""Reviewer: realised sigma (index points) re-derived from the LIVE M1 pull with the reviewer's own ET conversion.
P(T) = open of the M1 bar stamped T (ET); if absent, close of the bar stamped T-1min; else the sample is dropped
(the implementer's stated definition, re-implemented). Also measures how many overnight / 5d samples are lost because
the broker session ended before 16:00 ET, and what sigma looks like with a 'last price at or before 16:00' rule.
   python audit/review/rv_vol.py <scratch_dir>"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rv_common import OUT, epoch_s_to_server, server_to_et_index  # noqa: E402

SCRATCH = Path(sys.argv[1])
m1 = pd.read_parquet(SCRATCH / "m1_live_all.parquet")
m1 = m1[m1["time"] <= int(pd.Timestamp("2026-10-05 05:15").value // 1_000_000_000)]     # same cut as the implementer's run
et = server_to_et_index(epoch_s_to_server(m1["time"]))
O = dict(zip(et.asi8, m1["open"].to_numpy()))
Cl = dict(zip(et.asi8, m1["close"].to_numpy()))
ets = pd.Series(m1["close"].to_numpy(), index=et)                 # for the 'last price at or before T' rule
MIN = 60_000_000_000


def P(ts):
    k = ts.value
    if k in O:
        return O[k]
    return Cl.get(k - MIN, np.nan)


def P_asof(ts):
    s = ets.loc[:ts]
    if len(s) == 0 or (ts - s.index[-1]) > pd.Timedelta(minutes=30):
        return np.nan
    return s.iloc[-1] if s.index[-1] < ts else O.get(ts.value, s.iloc[-1])


days = pd.DatetimeIndex(sorted(set(et.normalize())))
wd = days[days.dayofweek < 5]


def moves(pairs, f=P):
    out = []
    for a, b in pairs:
        pa, pb = f(a), f(b)
        if np.isfinite(pa) and np.isfinite(pb):
            out.append((a, pb - pa))
    return pd.DataFrame(out, columns=["start", "move"])


def sig(d):
    m = d["move"].to_numpy()
    return {"N": int(len(m)), "sigma": round(float(np.std(m, ddof=1)), 2) if len(m) > 2 else None}


H, Mi = pd.Timedelta(hours=1), pd.Timedelta(minutes=1)
res = {}
last12 = pd.Timestamp("2026-10-05") - pd.Timedelta(days=365)
# 1h RTH, calendar 2024
d24 = wd[(wd.year == 2024)]
res["1h|RTH 2024"] = sig(moves([(d + pd.Timedelta(hours=9, minutes=30) + k * H, d + pd.Timedelta(hours=10, minutes=30) + k * H) for d in d24 for k in range(6)]))
# 6h, calendar 2025
d25 = wd[(wd.year == 2025)]
res["6h|09:30-15:30 2025"] = sig(moves([(d + pd.Timedelta(hours=9, minutes=30), d + pd.Timedelta(hours=15, minutes=30)) for d in d25]))
# 5min RTH, last 12 months
dl = wd[wd > last12]
res["5min|RTH last12m"] = sig(moves([(d + pd.Timedelta(hours=9, minutes=30) + 5 * k * Mi, d + pd.Timedelta(hours=9, minutes=35) + 5 * k * Mi) for d in dl for k in range(78)]))
# overnight Mon-Thu, last 12 months and by year, both price rules
for yr_label, sel in (("last12m", dl), ("2021", wd[wd.year == 2021]), ("2023", wd[wd.year == 2023]), ("2025", wd[wd.year == 2025])):
    mt = sel[sel.dayofweek <= 3]
    pairs = [(d + pd.Timedelta(hours=16), d + pd.Timedelta(days=1, hours=9, minutes=30)) for d in mt]
    res[f"overnight {yr_label} (impl rule)"] = sig(moves(pairs))
    res[f"overnight {yr_label} (last price <=16:00 rule)"] = sig(moves(pairs, P_asof))
    res[f"overnight {yr_label} candidate nights"] = int(len(pairs))
fr = dl[dl.dayofweek == 4]
res["5d last12m (impl rule)"] = sig(moves([(d + pd.Timedelta(hours=16), d + pd.Timedelta(days=7, hours=16)) for d in fr]))
(OUT / "rv_vol.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
print(json.dumps(res, indent=1))
