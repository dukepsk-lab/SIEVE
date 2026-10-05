"""Entry point: python -m audit.run   (Windows + logged-in MT5 terminal). Read-only."""
import json
import logging
import sys
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

from . import config as C
from . import mt5io as io
from . import report, tickdigest as td, tz
from . import t0_preflight as t0, t1_coverage as t1, t2_spread as t2, t3_swap as t3, t4_timemap as t4, t5_integrity as t5, t6_vol as t6

log = logging.getLogger("audit")
SIGMA_KEY = {"5min": "5min|RTH", "1h": "1h|RTH", "6h": "6h|09:30-15:30 ET", "overnight": "overnight|Mon-Thu nights", "5d": "5d|Fri 16:00 - next Fri 16:00"}


def setup_logging():
    C.OUT.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(C.OUT / "run.log", mode="w", encoding="utf-8")
    sh = logging.StreamHandler(sys.stdout)
    for h in (fh, sh):
        h.setFormatter(fmt)
    log.setLevel(logging.INFO)
    log.handlers[:] = [fh, sh]
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def tick_integrity(counters: pd.DataFrame) -> pd.DataFrame:
    c = counters.copy()
    cols = ["n_ticks", "n_valid", "n_nonmonotonic", "n_exact_duplicates", "n_nonpositive_price", "n_crossed", "n_zero_spread", "n_last_nonzero", "n_volume_nonzero"]
    s = {k: int(pd.to_numeric(c[k], errors="coerce").fillna(0).sum()) for k in cols if k in c}
    tot = s["n_ticks"]
    rows = [("ticks", tot, ""), ("time_msc going backwards", s["n_nonmonotonic"], "sorted before use"),
            ("exact duplicate ticks (time, bid, ask, flags)", s["n_exact_duplicates"], ""), ("bid<=0 or ask<=0", s["n_nonpositive_price"], "ignored for spread"),
            ("crossed quotes (bid > ask)", s["n_crossed"], "excluded from spread stats"), ("zero spread (bid == ask)", s["n_zero_spread"], "kept"),
            ("last != 0", s["n_last_nonzero"], ""), ("volume != 0", s["n_volume_nonzero"], "")]
    return pd.DataFrame([{"check": a, "count": b, "share_of_ticks_%": round(100 * b / tot, 5) if tot else None, "handling": h} for a, b, h in rows])


def export(x: dict):
    o = C.OUT
    t1g, tc, t4r, t2r, t5r, t6r = (x.get(k) or {} for k in ("gap", "tickcov", "t4", "t2", "t5", "t6"))

    def save(df, name, index=False):
        if df is not None and len(df):
            df.to_csv(o / name, index=index, encoding="utf-8")
    save(t1g.get("gaps"), "gaps_all.csv")
    save(tc.get("monthly"), "ticks_per_day_by_month.csv", True)
    save(t4r.get("weekly"), "server_time_weekly.csv")
    save(t4r.get("runs"), "server_offset_runs.csv")
    for k in ("et_cur", "srv_cur", "et_all", "srv_all"):
        save(t2r.get(k), {"et_cur": "spread_buckets_ET_current_regime.csv", "srv_cur": "spread_buckets_server_current_regime.csv",
                         "et_all": "spread_buckets_ET_all.csv", "srv_all": "spread_buckets_server_all.csv"}[k], True)
    save(t2r.get("et_ratio"), "spread_ratio_ET_all.csv", True)
    save(t2r.get("srv_ratio"), "spread_ratio_server_all.csv", True)
    save(t2r.get("reg"), "spread_regimes.csv")
    save(t2r.get("monthly"), "spread_monthly.csv", True)
    ro = t2r.get("roll") or {}
    save(ro.get("reopen"), "rollover_reopen_window.csv", True)
    save(ro.get("break"), "rollover_break_window.csv", True)
    for label, a in (t2r.get("events") or {}).items():
        save(a["table"], f"events_{label[:5].replace(':', '')}.csv")
    save((t5r.get("outl") or {}).get("top"), "outliers_top.csv")
    save((t5r.get("roll") or {}).get("windows"), "roll_windows.csv")
    for name, tbl in (t6r.get("sigma") or {}).items():
        save(tbl, "sigma_" + "".join(ch if ch.isalnum() else "_" for ch in name) + ".csv", True)
    save(t6r.get("hurdle"), "hurdle_table.csv")
    save(t6r.get("compare"), "hurdle_vs_assumptions.csv")


def main():
    setup_logging()
    problems = []

    def step(name, fn, *a, **k):
        try:
            return fn(*a, **k)
        except Exception as e:                              # noqa: BLE001 - keep going, report the failure
            log.exception("STEP FAILED: %s", name)
            problems.append(f"{name}: {type(e).__name__}: {e}")
            return None

    info = io.connect()
    try:
        sym = io.pick_symbol()
        io.select_symbol(sym)
        now = io.server_now(sym)
        log.info("symbol %s, server now %s", sym, now)
        x = {"meta": {"sym": sym, "info": info, "server_now": str(now), "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"), }}

        # ---- task 0
        spec = step("preflight/symbol_info", t0.symbol_spec, sym)
        point = spec["point"]
        deals = step("preflight/deals", t0.deal_evidence, sym) or {}
        landscape = step("preflight/swap landscape", t0.swap_landscape)
        x.update(spec=spec, deals=deals, landscape=landscape)

        # ---- data pulls (cached)
        data = {tf: io.load_rates(sym, tf, now) for tf in ("D1", "H1", "M5", "M1")}
        m1 = data["M1"]
        last_price = float(m1["close"].iloc[-1])

        # ---- task 4 first: every other time-of-day analysis needs the clock
        r4 = step("task4/time mapping", t4.run, m1, sym)
        if r4 is None:
            raise SystemExit("STOP: server clock could not be determined; cannot continue time-of-day analyses.")
        clock = r4["clock"]
        clock.save(C.OUT / "server_clock.json", {"note": "era-aware server clock measured by audit.t4_timemap", "eras_table": r4["eras"].astype(str).to_dict("records")})
        x["t4"] = r4

        # ---- ticks
        first_bar_day = datetime.fromtimestamp(int(m1["time"].iloc[0]), io.UTC).replace(tzinfo=None)
        ft = step("task1/first tick", t1.find_first_tick, sym, first_bar_day, now)
        x["first_tick"] = ft
        mins = hist = counters = None
        if ft and ft.get("first_tick"):
            fday = pd.Timestamp(ft["first_tick"]).normalize().to_pydatetime()
            cutoff = datetime(now.year, now.month, now.day)
            res = step("ticks/digest", td.build_digests, sym, fday, cutoff, point)
            if res:
                mins, hist, counters = res

        # ---- task 1
        x["extent"] = step("task1/extent", t1.tf_extent, sym, data)
        x["gap"] = step("task1/gaps", t1.gap_analysis, m1, clock)
        if counters is not None:
            x["tickcov"] = step("task1/tick coverage", t1.tick_coverage, counters)
            tcv = x["tickcov"]
            x["usable"] = step("task1/usable", t1.usable_history, m1, tcv["first_day"], tcv["last_day"] + timedelta(days=1)) if tcv else None
        else:
            x["usable"] = step("task1/usable", t1.usable_history, m1, pd.Timestamp(m1["time"].iloc[0], unit="s"), pd.Timestamp(m1["time"].iloc[0], unit="s") + timedelta(days=1))

        # ---- task 2
        t2r = {}
        if mins is not None:
            mm = t2.prepare(mins, clock, point)
            mm["b_et"], mm["b_srv"] = mm["mod_et"] // 30, mm["mod_srv"] // 30
            reg, cur = t2.regime_table(mm)
            t2r.update(reg=reg, n_minutes=len(mm))
            tw = lambda since, et_: t2.tick_weighted(hist, clock, point, since, et_)
            t2r["et_cur"] = t2.bucket_table(mm, "b_et", cur, tw(cur, True))
            t2r["srv_cur"] = t2.bucket_table(mm, "b_srv", cur, tw(cur, False))
            t2r["et_all"] = t2.bucket_table(mm, "b_et", None, tw(None, True))
            t2r["srv_all"] = t2.bucket_table(mm, "b_srv", None, tw(None, False))
            t2r["et_ratio"] = t2.bucket_ratio_table(mm, "b_et")
            t2r["srv_ratio"] = t2.bucket_ratio_table(mm, "b_srv")
            t2r["roll"] = step("task2/rollover", t2.rollover, mm, cur)
            ev = step("task2/events", t2.events, mm, m1, clock, cur, C.EVENTS_CSV)
            for a in (ev or {}).values():
                a["window_summary"] = t2.window_summary(a["table"])
            t2r["events"] = ev
            t2r["monthly"] = t2.monthly(mm, m1, point)
            t2r["exceed"] = t2.exceedance(mm, cur)
            t2r["barvtick"] = t2.bar_vs_tick(m1, mm)
            t2r["spreads"] = t2.cost_spreads(mm, reg, cur)
        x["t2"] = t2r

        # ---- task 3
        if spec:
            x["t3"] = step("task3/swap", t3.run, spec, last_price, deals, landscape)

        # ---- task 5
        t5r = {}
        t5r["bar"] = step("task5/bars", t5.bar_integrity, m1, point, m1.attrs)
        t5r["stale"] = step("task5/stale", t5.stale_runs, m1, clock)
        rs = t5.returns_and_sigma(m1)
        t5r["outl"] = step("task5/outliers", t5.outliers, rs, clock)
        t5r["roll"] = step("task5/roll", t5.roll_check, m1, rs, clock)
        t5r["vol"] = step("task5/volume", t5.volume_summary, m1)
        if mins is not None:
            t5r["bvt"] = step("task5/bars vs ticks", t5.bars_vs_ticks, m1, mins, point)
            t5r["tickint"] = tick_integrity(counters)
        x["t5"] = t5r

        # ---- task 6
        smp = step("task6/samples", t6.samples, m1, clock)
        if smp and t2r.get("spreads") and x.get("t3"):
            last_date = clock.to_et(pd.DatetimeIndex(pd.to_datetime(m1["time"].iloc[[-1]], unit="s")).as_unit("ns"))[0].normalize()
            st = t6.sigma_tables(smp, last_date)
            sig = {h: float(st[k].loc["last 12 months", "sigma_pts"]) for h, k in SIGMA_KEY.items()}
            mad = {h: float(st[k].loc["last 12 months", "sigma_pts"] * st[k].loc["last 12 months", "mean_abs_over_sigma"]) for h, k in SIGMA_KEY.items()}
            n = {h: int(st[k].loc["last 12 months", "N"]) for h, k in SIGMA_KEY.items()}
            usd_pt = spec["_units"]["usd_per_index_point_per_lot"]
            comm_pts = (deals.get("sym_commission_per_lot_round_trip_usd") or 0.0) / usd_pt
            hur = t6.hurdle(sig, mad, t2r["spreads"], x["t3"]["swap_long_pts_per_night_if_points"], comm_pts)
            x["t6"] = {"sigma": st, "levels": t6.price_levels(m1, last_date), "sig": sig, "mad": mad, "n": n, "hurdle": hur,
                       "compare": t6.compare_with_assumptions(sig, hur, comm_pts)}

        x["problems"] = problems
        export(x)
        (C.ROOT / "report.md").write_text(report.build(x), encoding="utf-8")
        (C.OUT / "cost_model_inputs.json").write_text(json.dumps(report.cost_inputs(x), indent=2), encoding="utf-8")
        log.info("wrote audit/report.md and audit/out/cost_model_inputs.json; %d problem(s)", len(problems))
        for p in problems:
            log.warning("PROBLEM %s", p)
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
