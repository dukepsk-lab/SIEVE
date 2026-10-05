"""Reviewer: live read-only checks against the MT5 terminal. Raw pulls go to SCRATCH (outside the repo); only small
result tables are written to audit/review/out/.   python audit/review/rv_live.py <scratch_dir>"""
import email.utils
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rv_common import CACHE, OUT, SYM, UTC, connect, lab  # noqa: E402

SCRATCH = Path(sys.argv[1])
SCRATCH.mkdir(parents=True, exist_ok=True)
res = {}
mt5 = connect()
try:
    # ---------------- 1. raw symbol_info (only the fields that matter) + swap arithmetic by hand
    si = mt5.symbol_info(SYM)._asdict()
    keep = ["name", "digits", "point", "trade_tick_size", "trade_tick_value", "trade_tick_value_profit", "trade_tick_value_loss",
            "trade_contract_size", "currency_profit", "currency_margin", "spread", "spread_float", "swap_mode", "swap_long",
            "swap_short", "swap_rollover3days", "trade_calc_mode", "trade_exemode", "filling_mode", "path", "bid", "ask"]
    res["symbol_info"] = {k: si[k] for k in keep}
    pt, tv, ts, cs = si["point"], si["trade_tick_value"], si["trade_tick_size"], si["trade_contract_size"]
    usd_per_idx_pt_per_lot = tv / ts                                  # account ccy per 1.0 price unit per lot
    price = (si["bid"] + si["ask"]) / 2
    res["swap_by_hand"] = {
        "usd_per_index_point_per_lot": usd_per_idx_pt_per_lot,
        "contract_size_x_1pt": cs * 1.0,
        "long_pts_per_night_if_POINTS": si["swap_long"] * pt,
        "short_pts_per_night_if_POINTS": si["swap_short"] * pt,
        "long_usd_per_lot_per_night_if_POINTS": si["swap_long"] * pt * usd_per_idx_pt_per_lot,
        "long_pct_pa_if_POINTS_at_live_mid": 100 * si["swap_long"] * pt * 365 / price,
        "live_mid": price,
        "live_spread_idx_pts_from_bid_ask": round(si["ask"] - si["bid"], 4),
        "live_spread_field_x_point": si["spread"] * pt,
    }

    # ---------------- 2. live offset: tick time vs PC clock, PC clock vs an independent HTTP Date (cloudflare)
    tk = mt5.symbol_info_tick(SYM)
    pc = time.time()
    skew = None
    try:
        with urllib.request.urlopen(urllib.request.Request("https://www.cloudflare.com", method="HEAD"), timeout=10) as r:
            skew = pc - email.utils.parsedate_to_datetime(r.headers["Date"]).timestamp()
    except Exception as e:  # noqa: BLE001
        skew = f"unavailable: {e}"
    raw = tk.time_msc / 1000 - pc
    res["live_offset"] = {"tick_server_label": str(datetime.fromtimestamp(tk.time_msc / 1000, UTC).replace(tzinfo=None)),
                          "pc_utc_now": str(datetime.fromtimestamp(pc, UTC).replace(tzinfo=None)),
                          "tick_minus_pc_s": round(raw, 2), "offset_h": round(raw / 3600), "resid_s": round(raw - 3600 * round(raw / 3600), 2),
                          "pc_minus_http_date_s": skew}

    # ---------------- 3. earliest / latest bars via copy_rates_from_pos (different call than the implementer's copy_rates_range)
    ext = {}
    for name, tf, n in (("M1", mt5.TIMEFRAME_M1, 4_000_000), ("M5", mt5.TIMEFRAME_M5, 1_000_000), ("H1", mt5.TIMEFRAME_H1, 200_000), ("D1", mt5.TIMEFRAME_D1, 20_000)):
        a = mt5.copy_rates_from_pos(SYM, tf, 0, n)
        if a is None:
            ext[name] = f"None {mt5.last_error()}"
            continue
        ext[name] = {"n_returned": int(len(a)), "first": str(pd.to_datetime(int(a["time"][0]), unit="s")), "last": str(pd.to_datetime(int(a["time"][-1]), unit="s")),
                     "requested": n}
        if name == "M1":
            df = pd.DataFrame(a)
            df.to_parquet(SCRATCH / "m1_live_all.parquet", index=False)
    # independent probe: anything before 2019-07-16 with copy_rates_range?
    a = mt5.copy_rates_range(SYM, mt5.TIMEFRAME_M1, lab(datetime(2010, 1, 1)), lab(datetime(2019, 7, 16)))
    ext["M1_range_2010_to_2019-07-16"] = {"n": 0 if a is None else int(len(a)),
                                          "times": [] if a is None else [str(pd.to_datetime(int(x), unit="s")) for x in a["time"][:3]]}
    a = mt5.copy_rates_range(SYM, mt5.TIMEFRAME_D1, lab(datetime(2010, 1, 1)), lab(datetime(2019, 7, 15)))
    ext["D1_range_2010_to_2019-07-15"] = {"n": 0 if a is None else int(len(a)),
                                          "times": [] if a is None else [str(pd.to_datetime(int(x), unit="s")) for x in a["time"][:3]]}
    res["extent"] = ext

    # ---------------- 4. earliest tick: copy_ticks_from 2015, plus monthly probes 2019-07 .. 2021-09 (non-contiguity check)
    a = mt5.copy_ticks_from(SYM, lab(datetime(2015, 1, 1)), 3, mt5.COPY_TICKS_ALL)
    res["first_tick_from_2015"] = None if a is None or len(a) == 0 else str(pd.to_datetime(int(a["time_msc"][0]), unit="ms"))
    probes = []
    d = datetime(2019, 7, 16)
    while d < datetime(2021, 9, 1):
        b = mt5.copy_ticks_range(SYM, lab(d), lab(d + timedelta(days=3)), mt5.COPY_TICKS_ALL)
        probes.append({"from": str(d.date()), "n_ticks_3d": 0 if b is None else int(len(b))})
        d += timedelta(days=14)
    res["tick_probes_pre_2021_08"] = probes

    # ---------------- 5. one day of live ticks vs the implementer's raw tick cache; bars vs bid OHLC rebuilt from those ticks
    cmp = {}
    for day in (datetime(2024, 8, 14), datetime(2026, 9, 16), datetime(2022, 3, 9)):
        b = mt5.copy_ticks_range(SYM, lab(day), lab(day + timedelta(days=1)) - timedelta(milliseconds=1), mt5.COPY_TICKS_ALL)
        lv = pd.DataFrame(b)
        lv = lv[(lv["time_msc"] >= int(lab(day).timestamp() * 1000)) & (lv["time_msc"] < int(lab(day + timedelta(days=1)).timestamp() * 1000))]
        f = CACHE / "ticks" / "USTEC" / f"{day:%Y}" / f"{day:%Y-%m-%d}.parquet"
        ca = pd.read_parquet(f)
        bid_pts, ask_pts = np.rint(lv["bid"].to_numpy() / pt).astype(np.int64), np.rint(lv["ask"].to_numpy() / pt).astype(np.int64)
        same_len = len(ca) == len(lv)
        r = {"live_ticks": int(len(lv)), "cache_ticks": int(len(ca)), "same_length": same_len}
        if same_len:
            r["time_equal"] = bool((ca["time_msc"].to_numpy() == lv["time_msc"].to_numpy()).all())
            r["bid_equal"] = bool((ca["bid"].to_numpy() == bid_pts).all())
            r["ask_equal"] = bool((ca["ask"].to_numpy() == ask_pts).all())
        sp = lv["ask"].to_numpy() - lv["bid"].to_numpy()
        r["live_spread_price_units_median_tickweighted"] = float(np.median(sp))
        r["cache_spread_points_median_tickweighted"] = float(np.median(ca["ask"] - ca["bid"]))
        # bars vs ticks (bid OHLC per minute)
        bars = pd.DataFrame(mt5.copy_rates_range(SYM, mt5.TIMEFRAME_M1, lab(day), lab(day + timedelta(days=1)) - timedelta(seconds=1)))
        bars = bars[(bars["time"] >= int(lab(day).timestamp())) & (bars["time"] < int(lab(day + timedelta(days=1)).timestamp()))]
        lv["m"] = lv["time_msc"] // 60000 * 60
        g = lv.groupby("m")
        oh = pd.DataFrame({"bo": g["bid"].first(), "bh": g["bid"].max(), "bl": g["bid"].min(), "bc": g["bid"].last(),
                           "ao": g["ask"].first(), "ac": g["ask"].last(), "n": g.size()})
        j = bars.set_index("time").join(oh, how="inner")
        r["bars_vs_ticks"] = {"minutes": int(len(j)),
                              "open==bid_first %": round(100 * float(np.isclose(j["open"], j["bo"]).mean()), 2),
                              "high==bid_max %": round(100 * float(np.isclose(j["high"], j["bh"]).mean()), 2),
                              "low==bid_min %": round(100 * float(np.isclose(j["low"], j["bl"]).mean()), 2),
                              "close==bid_last %": round(100 * float(np.isclose(j["close"], j["bc"]).mean()), 2),
                              "close==ask_last %": round(100 * float(np.isclose(j["close"], j["ac"]).mean()), 2),
                              "tick_volume==n_ticks %": round(100 * float((j["tick_volume"] == j["n"]).mean()), 2),
                              "bar_spread_pts_median": float(j["spread"].median())}
        cmp[str(day.date())] = r
    res["tick_cache_vs_live"] = cmp
finally:
    mt5.shutdown()

(OUT / "rv_live.json").write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
print(json.dumps(res, indent=1, default=str)[:12000])
