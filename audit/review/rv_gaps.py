"""Reviewer: M1 bar count and gaps >= 5 missing minutes for two calendar months, from the LIVE pull, compared with the
implementer's raw monthly cache file and its gaps_all.csv. Gap = consecutive bars more than 5 minutes apart (>= 5 missing
minutes). The regular daily break and the weekend are removed with the reviewer's own rule (ET clock via rv_common):
daily break = gap starting 16:50-17:01 ET and ending 17:58-18:06 ET; weekend = Friday >= 16:50 ET to Sunday 17:58-18:06 ET.
   python audit/review/rv_gaps.py <scratch_dir>"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rv_common import AUDIT, CACHE, OUT, epoch_s_to_server, server_to_et_index  # noqa: E402

SCRATCH = Path(sys.argv[1])
m1 = pd.read_parquet(SCRATCH / "m1_live_all.parquet")
res = {}
impl_gaps = pd.read_csv(AUDIT / "out" / "gaps_all.csv", parse_dates=["start_et", "end_et"])
for month in ("2024-09", "2025-11"):
    a = int(pd.Timestamp(month + "-01").value // 1e9)
    b = int((pd.Timestamp(month + "-01") + pd.offsets.MonthBegin(1)).value // 1e9)
    live = m1[(m1["time"] >= a) & (m1["time"] < b)]
    cache = pd.read_parquet(CACHE / "rates" / "USTEC" / "M1" / f"{month}.parquet")
    same = len(live) == len(cache) and bool((live["time"].to_numpy() == cache["time"].to_numpy()).all()) \
        and bool(np.allclose(live[["open", "high", "low", "close"]].to_numpy(), cache[["open", "high", "low", "close"]].to_numpy()))
    # gaps over the month (+ the bar before, so a gap straddling the month start is seen)
    w = m1[(m1["time"] >= a - 7 * 86400) & (m1["time"] < b + 86400)]
    t = w["time"].to_numpy()
    d = np.diff(t) // 60 - 1                                       # missing minutes between consecutive bars
    i = np.flatnonzero(d >= 5)
    s_srv, e_srv = epoch_s_to_server(t[i] + 60), epoch_s_to_server(t[i + 1] - 60)
    s_et, e_et = server_to_et_index(s_srv), server_to_et_index(e_srv)
    g = pd.DataFrame({"start_et": s_et, "end_et": e_et, "start_server": s_srv, "missing": d[i]})
    smod, emod = g["start_et"].dt.hour * 60 + g["start_et"].dt.minute, g["end_et"].dt.hour * 60 + g["end_et"].dt.minute
    brk = smod.between(16 * 60 + 50, 17 * 60 + 1) & emod.between(17 * 60 + 58, 18 * 60 + 6) & (g["missing"] < 120)
    wkd = (g["start_et"].dt.dayofweek == 4) & (smod >= 16 * 60 + 50) & (g["end_et"].dt.dayofweek == 6) & emod.between(17 * 60 + 58, 18 * 60 + 6)
    g = g[~brk & ~wkd]
    g = g[(g["start_et"] >= pd.Timestamp(month + "-01")) & (g["start_et"] < pd.Timestamp(month + "-01") + pd.offsets.MonthBegin(1))]
    ig = impl_gaps[(impl_gaps["minutes_missing"] >= 5) & (impl_gaps["start_et"].dt.strftime("%Y-%m") == month)]
    res[month] = {"live_bars": int(len(live)), "cache_bars": int(len(cache)), "live_equals_cache": same,
                  "reviewer_gaps_ge5": int(len(g)), "implementer_gaps_ge5": int(len(ig)),
                  "reviewer_list": g.astype(str).to_dict("records"),
                  "implementer_list": ig[["start_et", "end_et", "minutes_missing", "kind"]].astype(str).to_dict("records")}
(OUT / "rv_gaps.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
for k, v in res.items():
    print(k, {x: v[x] for x in ("live_bars", "cache_bars", "live_equals_cache", "reviewer_gaps_ge5", "implementer_gaps_ge5")})
    print("  reviewer:");  [print("   ", r) for r in v["reviewer_list"]]
    print("  implementer:"); [print("   ", r) for r in v["implementer_list"]]
