"""Reviewer: test the implementer's SAVED clock (audit/out/server_clock.json via audit.tz) against the reviewer's own
zoneinfo model on every M1 bar timestamp, and on the DST-transition / mismatch days explicitly. The implementer's helper is
the object under test here, not a tool used to verify its numbers.   python audit/review/rv_clock_vs_helper.py <scratch_dir>"""
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))                      # repo root, to import audit.tz (subject under test)
from rv_common import OUT, epoch_s_to_server, server_to_et_index  # noqa: E402
from audit.tz import ServerClock  # noqa: E402

SCRATCH = Path(sys.argv[1])
m1 = pd.read_parquet(SCRATCH / "m1_live_all.parquet", columns=["time"])
srv = epoch_s_to_server(m1["time"])
mine = server_to_et_index(srv)
clk = ServerClock.load(HERE.parent / "out" / "server_clock.json")
theirs = clk.to_et(srv).as_unit("ns")
diff = (theirs - mine)
bad = diff != pd.Timedelta(0)
res = {"bars_compared": int(len(srv)), "bars_differing": int(bad.sum()),
       "differences": pd.Series(diff[bad]).value_counts().astype(int).rename(lambda x: str(x)).to_dict()}
if bad.any():
    b = pd.DataFrame({"server": srv[bad], "theirs_et": theirs[bad], "mine_et": mine[bad]})
    res["differing_server_dates"] = b["server"].dt.date.astype(str).value_counts().sort_index().to_dict()
# explicit spot checks (server wall clock -> expected ET), London era
spots = {"2025-03-17 13:30": "2025-03-17 09:30",   # mismatch week (US DST, EU not): server = UTC+0, ET = UTC-4
         "2025-03-31 14:30": "2025-03-31 09:30",   # both DST
         "2024-10-28 13:30": "2024-10-28 09:30",   # mismatch week Oct
         "2024-11-04 14:30": "2024-11-04 09:30",   # both standard
         "2021-07-12 13:30": "2021-07-12 09:30",   # UTC-fixed era summer
         "2026-10-05 05:16": "2026-10-05 00:16"}   # run time
res["spot_checks"] = {k: {"expected_et": v, "helper_et": str(clk.to_et(pd.DatetimeIndex([k]))[0])[:16]} for k, v in spots.items()}
(OUT / "rv_clock_vs_helper.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
print(json.dumps(res, indent=1, default=str))
