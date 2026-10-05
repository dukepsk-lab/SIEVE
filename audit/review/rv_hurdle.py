"""Reviewer: recompute every hurdle row from the implementer's MEASURED inputs (sigma, spread, swap) with
required hit rate = 0.5 + C / (1.6 sigma), compare with audit/out/hurdle_table.csv, and add alternative stress rows.
Reviewer's stress spreads come from rv_spread.json (independent): current-regime worst tick at the open (2.0), all-history
p99 of the per-minute MAX spread in the 09:30 bucket, and the user's original 8 pts.   python audit/review/rv_hurdle.py"""
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from rv_common import AUDIT, OUT  # noqa: E402

J = json.loads((AUDIT / "out" / "cost_model_inputs.json").read_text(encoding="utf-8"))
sig = {h: v["value"] for h, v in J["volatility"]["sigma_last_12m_index_points"].items()}
cur = J["spread"]["current_regime"]
base = cur["rth_0930_1600_ET"]["p50"]["value"]
p99o, p99c = cur["open_bucket_0930_1000_ET"]["p99"]["value"], cur["close_bucket_1530_1600_ET"]["p99"]["value"]
w = J["spread"]["worst_past_regime"]
wo, wc = w["open_bucket"]["p99"]["value"], w["close_bucket"]["p99"]["value"]
swap = -J["swap"]["long_pts_per_night_if_points"]["value"]          # positive = cost to the long
nights = {"5min": 0, "1h": 0, "6h": 0, "overnight": 1, "5d": 7}
rv = {r["period"] + "|" + r["bucket"] + "|" + r["population"]: r for r in json.loads((OUT / "rv_spread.json").read_text())}
alt_max_cur = rv["current regime 2026-05-14..2026-10-04|09:30-09:59 ET|tick minutes"]["max_tick"]
alt_p99max_all = rv["all tick history|09:30-09:59 ET|tick minutes"]["p99_of_minute_max"]

rows = []
for h in nights:
    intraday = nights[h] == 0
    spreads = {"base": base,
               "stress (p99, current regime)": p99o if intraday else (p99c if h == "5d" else (p99o + p99c) / 2),
               "stress-alt (p99, worst past regime)": wo if intraday else (wc if h == "5d" else (wo + wc) / 2),
               "REVIEWER stress: current-regime worst tick at open": alt_max_cur,
               "REVIEWER stress: all-history p99 of minute-max at open": alt_p99max_all,
               "REVIEWER stress: user's 8 pt spread": 8.0}
    for case, s in spreads.items():
        slip = 1.0 if case == "base" else 4.0
        for side in (["long", "short"] if nights[h] else ["n/a"]):
            c = s + slip + (swap * nights[h] if side == "long" else 0.0)
            rows.append({"horizon": h, "case": case, "side": side, "sigma": round(sig[h], 2), "spread": s, "C": round(c, 3),
                         "hit_rate_%": round(100 * (0.5 + c / (1.6 * sig[h])), 2)})
mine = pd.DataFrame(rows)
theirs = pd.read_csv(AUDIT / "out" / "hurdle_table.csv", keep_default_na=False)          # side "n/a" must stay a string
j = mine.merge(theirs[["horizon", "case", "side", "C_total_pts", "required_hit_rate_%"]], on=["horizon", "case", "side"], how="left")
j["abs_diff_pp"] = (j["hit_rate_%"] - j["required_hit_rate_%"]).abs().round(3)
OUT.joinpath("rv_hurdle.csv").write_text(j.to_csv(index=False), encoding="utf-8")
print(j.to_string())
print("\nmax |diff| vs implementer on its own rows (pp):", j["abs_diff_pp"].max())
