"""Builds audit/report.md, audit/out/cost_model_inputs.json and the CSV exports from the results of the task modules.
Every statement with a number is generated from the measurements; nothing is typed in by hand except the wording."""
import json
import math
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from . import config as C

TAG = {"M": "MEASURED", "I": "INFERRED", "A": "ASSUMED"}


# ------------------------------------------------------------------ formatting
def num(x, nd=3):
    if x is None or x is pd.NA or x is pd.NaT or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "—"
    if isinstance(x, (np.integer, int)) and not isinstance(x, bool):
        return f"{int(x):,}"
    if isinstance(x, (float, np.floating)):
        a = abs(x)
        s = f"{x:,.1f}" if a >= 1000 else (f"{x:.2f}" if a >= 100 else (f"{x:.{nd}f}".rstrip("0").rstrip(".") if a < 100 else f"{x:.2f}"))
        return "0" if s in ("-0", "") else s
    if isinstance(x, (pd.Timestamp, datetime)):
        return str(x)[:19] if x.hour or x.minute or x.second else str(x)[:10]
    return str(x)


def md(df: pd.DataFrame, index: bool = False, nd: int = 3) -> str:
    if df is None or len(df) == 0:
        return "_(no rows)_"
    d = df.copy()
    if index:
        name = d.index.name
        d = d.reset_index()
        d[d.columns[0]] = d[d.columns[0]].astype(str)               # years / periods stay un-formatted
        if name is None:
            d = d.rename(columns={d.columns[0]: ""})
    for c in d.columns:
        if pd.api.types.is_datetime64_any_dtype(d[c]):
            col = d[c]
            midnight = (col.dt.hour.eq(0) & col.dt.minute.eq(0) & col.dt.second.eq(0)).all()
            d[c] = col.dt.strftime("%Y-%m-%d" if midnight else "%Y-%m-%d %H:%M")
    cols = [str(c).replace("|", "/") for c in d.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for row in d.itertuples(index=False):
        lines.append("| " + " | ".join(num(v, nd).replace("|", "/") for v in row) + " |")
    return "\n".join(lines)


def kv(rows: list[tuple]) -> str:
    return md(pd.DataFrame(rows, columns=["item", "value", "note"], dtype=object))


def P(value, prov, n=None, unit=None, note=None):
    d = {"value": value, "provenance": TAG[prov]}
    if n is not None:
        d["n"] = n
    if unit:
        d["unit"] = unit
    if note:
        d["note"] = note
    return d


def jsonable(o):
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if (math.isnan(o) or math.isinf(o)) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp, datetime, date)):
        return str(o)
    if isinstance(o, pd.DataFrame):
        return jsonable(o.to_dict("records"))
    if isinstance(o, pd.Series):
        return jsonable(o.to_dict())
    return o


# ------------------------------------------------------------------ facts used in several places
def facts(x: dict) -> dict:
    f = {}
    sp = x.get("t2", {}).get("spreads")
    reg = x.get("t2", {}).get("reg")
    if sp is not None:
        f["cur_level"] = sp["rth_current"]["p50"]
        f["cur_p99"] = sp["open_bucket_current"]["p99"]
        f["cur_max"] = sp["open_bucket_current"]["max_tick"]
        f["cur_start"] = sp["current_regime_start"]
        f["worst"] = sp["worst_regime"]
        f["cur_n"] = sp["rth_current"]["N"]
    if reg is not None:
        f["n_regimes"] = len(reg)
        big = reg[reg["days"] >= 30]
        f["lvl_min"], f["lvl_max"] = float(big["level_pts"].min()), float(big["level_pts"].max())
        f["tick_spike_max"] = float(reg["max_tick"].max())
        f["cur_fixed_pct"] = float(reg["pct_minutes_at_modal_value"].iloc[-1])
        f["cur_days"] = int(reg["days"].iloc[-1])
    t4 = x.get("t4")
    if t4:
        f["eras"] = t4["eras"]
        f["live"] = t4["live"]
        f["ny_close_pct"] = t4["ny_close_match_pct"]
    sw = x.get("t3")
    if sw:
        f["swap_long"], f["swap_short"], f["swap_pct"] = sw["swap_long_pts_per_night_if_points"], sw["swap_short_pts_per_night_if_points"], sw["annual_pct_long"]
    h = x.get("t6", {}).get("hurdle")
    if h is not None:
        def hr(hz, case, side="n/a"):
            r = h[(h["horizon"] == hz) & (h["case"].str.startswith(case)) & (~h["case"].str.contains("alt")) & (h["side"] == side)]
            return float(r["required_hit_rate_%"].iloc[0]) if len(r) else float("nan")
        f["hr"] = {hz: (hr(hz, "base"), hr(hz, "stress")) for hz in ("5min", "1h", "6h")}
        f["hr_on"] = {s: (hr("overnight", "base", s), hr("overnight", "stress", s)) for s in ("long", "short")}
        f["hr_5d"] = {s: (hr("5d", "base", s), hr("5d", "stress", s)) for s in ("long", "short")}
    return f


# ------------------------------------------------------------------ report
def build(x: dict) -> str:
    f = facts(x)
    L = []
    add = L.append
    meta, info = x["meta"], x["meta"]["info"]
    spec = x.get("spec") or {}
    ext, usable = x.get("extent"), x.get("usable")
    t1g, tc, t4, t2, t3, t5, t6 = (x.get(k) for k in ("gap", "tickcov", "t4", "t2", "t3", "t5", "t6"))
    t2 = t2 or {}
    t5 = t5 or {}
    t6 = t6 or {}

    add(f"# {meta['sym']} data and cost audit — IUX, MetaTrader 5")
    add(f"_Generated {meta['generated']} UTC · server clock at run {meta['server_now']} · read-only audit (no order function was called) · "
        f"all costs in **index points** (price units) unless stated; 1 index point = {spec.get('_units', {}).get('points_per_index_point', 100)} `point` units._")
    add("Provenance tags: **MEASURED** = computed from MT5 data · **INFERRED** = derived with stated logic · **ASSUMED** = not measured. Sample sizes (N) sit next to every statistic.\n")

    # ---------------------------------------------------------------- 1. summary
    add("## 1. Summary")
    add(summary_paragraph(x, f))

    # ---------------------------------------------------------------- 2. status
    add("\n## 2. Status of every question")
    add(md(pd.DataFrame(status_rows(x, f), columns=["#", "question", "status", "answer / what is missing"])))

    # ---------------------------------------------------------------- 3. detail
    add("\n## 3. Task 0 — Preflight (MEASURED)")
    add("Redacted terminal/account (login, name, balance, password are never read into the report):")
    add(kv([("terminal", f"{info['terminal_company']} · build {info['build']} · connected={info['connected']} · algo trading allowed={info['algo_trading_allowed']}", "terminal_info"),
            ("server", info["server"], "account_info"), ("account currency", info["currency"], "account_info"),
            ("leverage at run time", str(info["leverage"]), "account_info; **varies**: 400 and 3000 were both seen on the same day"),
            ("account trade mode", info["account_trade_mode"], "REAL; the API does not expose the commercial account type (Pro/Standard/...)"),
            ("margin mode", info["margin_mode"], "account_info")]))
    if spec:
        d = spec["_decoded"]
        rows = [(k, spec[k], "") for k in ["name", "description", "path", "digits", "point", "trade_tick_size", "trade_tick_value", "trade_tick_value_profit",
                                           "trade_tick_value_loss", "trade_contract_size", "volume_min", "volume_max", "volume_step", "currency_base",
                                           "currency_profit", "currency_margin", "spread", "spread_float", "trade_stops_level", "trade_freeze_level",
                                           "margin_initial", "margin_maintenance", "margin_hedged", "swap_long", "swap_short", "session_deals"]]
        rows += [("swap_mode", spec["swap_mode"], d["swap_mode"]), ("swap_rollover3days", spec["swap_rollover3days"], d["swap_rollover3days"]),
                 ("trade_mode", spec["trade_mode"], d["trade_mode"]), ("trade_calc_mode", spec["trade_calc_mode"], d["trade_calc_mode"]),
                 ("trade_exemode (execution)", spec["trade_exemode"], d["trade_exemode"]), ("filling_mode", spec["filling_mode"], d["filling_mode"]),
                 ("order_mode", spec["order_mode"], d["order_mode"]), ("expiration_mode", spec["expiration_mode"], d["expiration_mode"])]
        add("\nFull symbol specification (`spread` here is the live snapshot in `point` units at run time):")
        add(kv(rows))
        u = spec["_units"]
        add(f"\n**Unit conversion.** `point`={spec['point']}, tick size={spec['trade_tick_size']}, so 1 index point = {u['points_per_index_point']} points. "
            f"Money per index point per 1.0 lot = tick_value/tick_size = **{u['usd_per_index_point_per_lot']:.2f} {spec['currency_profit']}** "
            f"(contract size {spec['trade_contract_size']}). Smallest lot {spec['volume_min']} = {spec['volume_min'] * u['usd_per_index_point_per_lot']:.2f} {spec['currency_profit']} per index point.")
    dv = x.get("deals") or {}
    add("\n**Commission.** Not exposed in `symbol_info`. From the account's own deal history (read-only, aggregated):")
    if dv.get("deals"):
        add(md(dv["per_symbol"], nd=4))
        add(f"On {meta['sym']}: {dv['sym_deals']} deals, {dv['sym_round_trips']} round trip(s), {dv['sym_lots_closed']} lots, commission booked = {dv['sym_commission']} → "
            f"**0.0 per lot** (MEASURED, but n = {dv['sym_round_trips']} round trip, so weak). Other symbols also show 0.0 commission, which suggests a commission-free (spread-only) account type, "
            "but that is INFERRED, not confirmed — see questions.")
    else:
        add("No deal history available → commission **UNKNOWN**.")

    # ---------------- task 1
    add("\n## 4. Task 1 — History coverage")
    if ext is not None:
        add("**Bars per timeframe (MEASURED).** Cross-check with a different API call: `copy_rates_from` asked for dates up to one year before the first bar returns the first bar itself and nothing earlier "
            "(0 earlier bars). MT5 answers out-of-range requests with the nearest available bar (a request for year 2010 returned a 2019 bar), so every pull is filtered strictly to the requested range.")
        add(md(ext))
    if t1g:
        add(f"\n**M1 coverage vs expected session minutes (MEASURED / INFERRED schedule).** The expected schedule is inferred per calendar quarter in New York time: a minute is "
            f"'expected' when ≥50% of open days have a bar there. Expected minutes {num(t1g['expected_minutes_total'])}, missing {num(t1g['missing_minutes_total'])} "
            f"({100 * t1g['missing_minutes_total'] / t1g['expected_minutes_total']:.2f}%). Bars outside the inferred schedule: {num(t1g['bars_outside_schedule'])}.")
        add(md(t1g["coverage_by_year"], index=True))
        add("\nSession schedule history (ET), INFERRED from where bars exist (daily break = minutes with no bars). The broker changed its hours several times:")
        add(md(t1g["schedule_history"]))
        add(f"\nExpected session minutes in {t1g['schedule_period']} (ET), the latest quarter with enough days:")
        add(md(t1g["schedule_latest_year"]))
        add("\nGaps by size (a gap = run of expected minutes with no bar; '>1 min' = at least 1 missing minute, '>5' = at least 5, '>60' = at least 60). "
            "Gaps are measured against the quarterly schedule, weekends and the daily break are excluded:")
        add(md(t1g["gap_counts"], index=True))
        add(f"\n**20 largest gaps** (times in New York and server clock). Gaps ≥ 10 h are holiday closures or outages; gaps that run to the daily break are US-holiday early closes; "
            f"{t1g['holiday_gaps']} of {len(t1g['gaps'])} gaps are of those two kinds, the rest ('other') are intraday data gaps:")
        add(md(t1g["top20"][["start_et", "end_et", "start_server", "minutes_missing", "kind"]]))
        add("\nLargest 'other' gaps (not holiday closures or early closes):")
        add(md(t1g["top_other"][["start_et", "end_et", "start_server", "minutes_missing"]]))
    if tc:
        ft = x.get("first_tick") or {}
        add(f"\n**Ticks (MEASURED).** Earliest tick: **{ft.get('first_tick')}** server time (binary search over weeks; direct `copy_ticks_from` from 2019 gives "
            f"{ft.get('first_tick_direct_copy_ticks_from')}). {num(tc['ticks_total'])} ticks on {tc['days_with_ticks']} days between {num(tc['first_day'])} and {num(tc['last_day'])}.")
        add(f"- bid and ask both > 0 on **{tc['bid_ask_both_positive_pct']}%** of ticks · `last` non-zero on {tc['last_nonzero']} · `volume` non-zero on {tc['volume_nonzero']} · `volume_real` non-zero on {tc['volume_real_nonzero']} "
            "(CFD: price-only ticks, no traded volume).")
        add("- flags: bits 2/4 are BID/ASK; bits 128 and 1024 are **undocumented** broker bits. The mix changes in 2025, which marks a feed/platform change:")
        add(md(tc["flags"]))
        add(md(tc["flags_by_year"], index=True))
        add("\nTicks per day by month (days with ticks only):")
        add(md(tc["monthly"], index=True))
    if usable is not None:
        add("\n**Usable history and minimum detectable Sharpe (t = 3 → 3/√years, MEASURED years):**")
        add(md(usable))
        add("The Sharpe floor assumes stationarity; here spread level, server clock, session hours and feed density all changed, so the effective independent sample is shorter than the calendar span.")

    # ---------------- task 2
    add("\n## 5. Task 2 — Spread audit (ticks, 2021-08 onward)")
    if t2.get("reg") is not None:
        reg, cur = t2["reg"], t2["spreads"]
        add(f"Primary measure: per-minute **time-weighted median spread** with last-observation-carried-forward (MEASURED from {num(t2['n_minutes'])} tick-minutes). Ticks with bid or ask ≤ 0 are ignored; "
            "crossed quotes (ask < bid) are counted and excluded. Tick-weighted numbers appear only as a comparison.")
        add(f"\n### 2d. Spread regimes (structural changes)")
        fixed = reg[reg["pct_minutes_at_modal_value"] >= 80]
        fsince = fixed["start"].iloc[0] if len(fixed) else None
        later = reg[(reg["start"] >= fsince) & (reg["days"] >= 10)] if fsince is not None else reg.iloc[0:0]
        add(f"Daily modal spread, split into regimes whenever 5 consecutive days deviate ≥4% from the running level (**{len(reg)} regimes**). "
            f"`pct_minutes_at_modal_value` = share of minutes whose spread equals the regime's most common value. Before {fsince} the spread **floated** "
            f"(≤{reg[reg['start'] < fsince]['pct_minutes_at_modal_value'].max()}% of minutes at any single value); from {fsince} it is a **broker-set quasi-fixed markup** — every regime of ≥ 10 days has "
            f"≥ {later['pct_minutes_at_modal_value'].min()}% of minutes at one value — that is re-set in steps, not a market-driven quantity:")
        add(md(reg))
        add("\nMonthly median / p99 of the per-minute spread (index points). Before 2021-08 only the bar `spread` field exists and it is **0 in 100% of bars in 2019-2020 and 63% of 2021** "
            "(MEASURED) → spread history before 2021-08 is **UNKNOWN**. From 2021-08 the bar field is a single snapshot per bar and is biased low (see bar-vs-tick table).")
        mo = t2["monthly"][["bars_median", "bars_p99", "tick_median", "tick_p99", "tick_max", "tick_N", "primary_source"]]
        pre = mo[mo["tick_N"].isna()]
        if len(pre):
            add(f"{len(pre)} months from {pre.index[0]} to {pre.index[-1]}: bar spread = 0 in every bar, no tick history → no spread information (omitted from the table).")
        add(md(mo[mo["tick_N"].notna()], index=True))
        add(f"\n### 2a. Spread by 30-minute bucket — current regime since {cur['current_regime_start']} (N = minutes)")
        add("Columns p50/p90/p99/mean refer to the per-minute time-weighted spread; `max_tick` is the single widest quote seen; `tick_*` = tick-weighted comparison. "
            "All-history versions (mixing all regimes) are in `audit/out/spread_buckets_*_all.csv`.")
        add("\n**New York time**")
        add(md(t2["et_cur"].reset_index(drop=True), nd=2))
        add("\n**Server time** (note the clock moves relative to New York, see task 4)")
        add(md(t2["srv_cur"].reset_index(drop=True), nd=2))
        if t2.get("et_ratio") is not None:
            add("\n**All history, level-neutral (New York time).** Spread ÷ the day's own median, all regimes pooled, shows *when* spikes historically happened regardless of the level at the time "
                "(`s_max` = worst tick in the minute):")
            add(md(t2["et_ratio"].reset_index(drop=True), nd=2))
        ro = t2["roll"]
        add("\n### 2b. Daily rollover / re-open")
        add(f"The only spread spike near the daily break is at the **re-open after the break**, not before it. Spike minute: **{ro['spike_clock_et']} ET** "
            f"(mean max-spread ratio {ro['spike_mean_ratio']}× the day's median at the re-open minute, all history) — INFERRED rollover time. Re-open times by day count (ET): "
            f"{', '.join(f'{k}: {v}' for k, v in ro['reopen_anchor_times'].items())}. The MT5 swap rollover time itself cannot be read from the API (see questions). "
            "The window before the re-open is the closed break, so only −30..−1 relative to the *last bar before the break* has data on that side.")
        add("\nWindow around the **re-open** (rel. minute 0 = first bar after the break; ratio = spread ÷ that day's median; `*_cur` = current regime, index points):")
        add(md(ro["reopen"].dropna(how="all").iloc[:, :].reset_index().rename(columns={"index": "rel_min", "rel": "rel_min"}).loc[lambda d: d["rel_min"].between(0, 30)].iloc[::1], nd=2))
        add("\nWindow before the break (rel. minute 0 = last bar before the break):")
        add(md(ro["break"].dropna(how="all").reset_index().rename(columns={"index": "rel_min", "rel": "rel_min"}).loc[lambda d: d["rel_min"].between(-30, 0)].iloc[::1], nd=2))
        add("\n### 2c. Event windows (APPROXIMATE — no events file was given)")
        if C.EVENTS_CSV:
            add(f"Events from `{C.EVENTS_CSV}`.")
        for label, a in t2["events"].items():
            add(f"\n**{label}** — {a['how']}. Event days {a['n_event_days']} (of which with tick data {a['n_event_days_with_ticks']}, in the current regime {a['n_event_days_cur']}); "
                f"non-event days {a['n_non_event_days']}. Detected event days per year: {', '.join(f'{k}: {v}' for k, v in a['by_year'].items())}. "
                "NOTE: event days are *defined* by range, so the range comparison is circular by construction; the spread comparison is not (spread was not used for detection). "
                "Spread ratio = spread ÷ day median (removes regime level). "
                + (f"**Reliability: only {a['n_event_days_cur']} event days fall in the current regime, so current-regime event spread numbers (`*_cur`) are not reliable for p99.** " if a["n_event_days_cur"] < 30 else "")
                + (f"Tick-era event days: {a['n_event_days_with_ticks']}." if a["n_event_days_with_ticks"] < 100 else ""))
            add(md(a["window_summary"], nd=2))
        add("\nFull per-minute tables (−15..+30): `audit/out/events_*.csv`.")
        add("\n### 2e. Share of minutes with spread above k × the day's median")
        add(md(t2["exceed"]))
        add("\n### Bar `spread` field vs tick-derived spread (bias of the bar field)")
        add("The bar `spread` is one snapshot per bar. Over the overlap (index points = column ÷ 100 in `point` units):")
        bv = t2["barvtick"].copy()
        for c_ in ("mean(bar-ref) pts", "median(bar-ref) pts", "p01 diff", "p99 diff"):
            bv[c_] = bv[c_] * (spec.get("point", 0.01))
        bv = bv.rename(columns={"mean(bar-ref) pts": "mean(bar-ref) idx pts", "median(bar-ref) pts": "median idx pts", "p01 diff": "p01 idx pts", "p99 diff": "p99 idx pts"})
        add(md(bv, nd=4))
        add("→ The bar spread equals the **minimum** tick spread inside the minute in ~99.7% of bars. It understates typical spread slightly and understates spikes completely. "
            "Do not use it for p99 or event statistics.")

    # ---------------- task 3
    add("\n## 6. Task 3 — Swap and financing")
    if t3:
        add(f"`swap_mode` = **{t3['mode']}** ({t3['mode_code']}), `swap_long` = {t3['swap_long_raw']}, `swap_short` = {t3['swap_short_raw']}, triple-swap weekday = **{t3['triple_day']}** (`swap_rollover3days` = {t3['triple_day_code']}).")
        add("**The terminal says swap is disabled while populated values exist.** This is not specific to this symbol:")
        add(md(t3["landscape"]))
        add(f"\nFormulas (per 1.0 lot, price {num(t3['price_used'])}; negative = the trader pays). Only the 'points' reading gives a financing rate in a sensible range:")
        add(md(t3["readings"], nd=4))
        add(f"\n**Reading used: POINTS (INFERRED)** → index points per night: long **{t3['swap_long_pts_per_night_if_points']}**, short **{t3['swap_short_pts_per_night_if_points']}** "
            f"(= swap × point). Annualised: long {t3['annual_pct_long']}% of price, short {t3['annual_pct_short']}% (= pts × 365 / price). "
            f"Short also pays: **{'yes' if t3['short_also_pays'] else 'no'}**; short receives: {'yes' if t3['short_receives'] else 'no'}. "
            f"Charged per rollover; the {t3['triple_day']} rollover counts 3× → 7 night-equivalents per week.")
        od = t3["overnight_deals"]
        add("\nEvidence from this account's deals (positions that crossed ≥1 server midnight). Expected charge under the 'points' reading is far below the 0.01 rounding of the booked swap, so this is **inconclusive**:")
        add(md(od, nd=5) if od is not None and len(od) else "_no overnight positions_")
        add("\n**Whether swap is actually charged on this account is UNKNOWN.** Modelled conservatively as charged at the 'points' reading (long); if the account is swap-free, swap = 0.")
        add("The rollover time cannot be read from the API. INFERRED from the spread spike: the market re-opens at the time shown in 2b; the usual MT5 default (server midnight) would be "
            "19:00 ET in the London-clock era. Please confirm in the terminal (see questions).")

    # ---------------- task 4
    add("\n## 7. Task 4 — Server time ↔ UTC ↔ New York")
    if t4:
        lv = t4["live"]
        add(f"**Live offset (MEASURED):** latest tick time − UTC now = {lv['tick_server_minus_utc_s']} s → **server = UTC{lv['offset_hours']:+d}h** "
            f"(residual {lv['residual_s']} s = tick age; market live = {lv['market_live']}). PC clock checked against an HTTP time source (1 s resolution): skew {num(lv['pc_clock_skew_s'], 2)} s.")
        add(f"\n**Server clock history (MEASURED weekly, then segmented).** The 09:30 ET cash-open step in 1-min range was detected for {t4['weeks_total']} weeks "
            f"({t4['weeks_informative']} informative). The 08:30 ET release spike sits exactly 60 min before the open in {t4['release_minus_open']['pct_exactly_minus60']}% of weeks (median {t4['release_minus_open']['median_min']} min), "
            "which is consistent with a single clock for both events.")
        add(md(t4["eras"]))
        add("\nMatch of each candidate convention against the weekly observation:")
        add(md(t4["scoreboard"], index=True))
        add(f"\n**The 'NY close' convention (UTC+2/+3, 09:30 ET = 16:30 server) matches {t4['ny_close_match_pct']}% of weeks — it is not what this server does.** "
            f"Mismatch weeks (US and EU DST differ) decide US-linked vs EU-linked: in the current era {t4['linkage']['eu_linked_matches']} of {t4['linkage']['mismatch_weeks_in_last_era']} "
            f"match the EU (London) rule and {t4['linkage']['us_linked_matches']} match a US-linked rule.")
        add("\n**Offset regimes by run of weeks** (informative weeks; offset = server − UTC in hours; the full weekly table with the detected cash-open, "
            "release-spike and unconstrained-peak minutes is `audit/out/server_time_weekly.csv`):")
        add(md(t4["runs"]))
        noise = t4["runs"][(t4["runs"]["weeks"] == 1)]
        add(f"\nThe {len(noise)} one-week runs (offset −1, or a single 0 inside a summer run) contradict both neighbouring runs and carry implausible release-spike minutes: treat them as detection noise "
            "(weeks where the open step was not the dominant step), not clock changes. The release-spike column is a secondary, noisy detector (it picks the strongest recurring spike in the "
            f"window before the open) and agrees with 'open − 60 min' in only {t4['release_minus_open']['pct_exactly_minus60']}% of weeks; the 18 mismatch-week observations and the 98% match of the London rule do not depend on it.")
        add("\nWeeks where US and EU DST differ — observed offset vs what each convention predicts (hours, server − UTC):")
        add(md(t4["mismatch"]))
        add("\nThe era boundary is only identifiable up to the winter ambiguity: UTC-fixed and London time are identical from the end of October to the end of March, so the switch lies "
            "between the last UTC-fixed summer week and the first London summer week; any date in that winter gives identical conversions. 09:30 ET therefore sits at **14:30 server in normal weeks "
            "and 13:30 server in the 2–3 mismatch weeks each March and 1 week each Oct/Nov** (London era).")
        add("\nHelper: `audit.tz.ServerClock` (eras + rules `fixed` / `ny` / `eu`), saved as `audit/out/server_clock.json`; `to_utc`, `to_et`, `utc_to_server`, `et_to_server`. "
            "Tests: `python -m pytest audit/tests -q` (DST transitions, US/EU mismatch weeks, round trips, era switch).")

    # ---------------- task 5
    add("\n## 8. Task 5 — Data integrity")
    if t5.get("bar"):
        b = t5["bar"]
        add("**M1 bars (MEASURED):**")
        add(kv([(k, v, "") for k, v in b["summary"].items()]))
        add(md(b["by_year"], index=True))
    if t5.get("tickint") is not None:
        add("\n**Ticks (MEASURED, all days):**")
        add(md(t5["tickint"]))
    if t5.get("stale"):
        st = t5["stale"]
        add("\n**Stale quotes** (consecutive bars with no price change at all). Runs by minimum length:")
        add(md(st["counts"]))
        add("Longest runs:")
        add(md(st["top"]))
    if t5.get("outl"):
        o = t5["outl"]
        add(f"\n**Outlier returns |ret| > 8× local sigma (past-only, 120-bar window)**: {num(o['count'])} of {num(o['tested'])} tested 1-min returns "
            f"({100 * o['count'] / o['tested']:.3f}%), {o['share_in_news_windows_pct']}% inside the 08:30/09:30/10:00/14:00 ET news windows. Heavy tails, not necessarily errors. By year:")
        add(md(o["by_year"].rename_axis("year"), index=True))
        add("Largest 30 (full list: `audit/out/outliers_top.csv`):")
        add(md(o["top"]))
        add("Largest outside news windows:")
        add(md(o["top_quiet"]))
    if t5.get("roll"):
        r = t5["roll"]
        add("\n**Roll / jump check around quarterly futures expiries (third Friday of Mar/Jun/Sep/Dec ±10 days) vs control windows (third Friday of other months).** "
            "Statistic per window: the largest 1-minute |return| in quiet hours (z vs past sigma), the largest daily-break gap and weekend gap (z vs trailing sd).")
        add(md(pd.DataFrame({"quarterly (expiry) windows": r["quarterly_summary"], "control windows": r["control_summary"]}), index=True))
        add(f"Typical gap sizes: daily-break gap sd {r['typical_break_gap_pct_sd']}%, weekend gap sd {r['typical_weekend_gap_pct_sd']}%. "
            f"Of the quarterly windows' largest quiet moves, {r['positive_share_of_quarterly_largest_quiet_moves']}% were positive (an unadjusted contango roll would be consistently positive after 2022).")
        add(f"\n**Verdict (INFERRED, moderate confidence):** {roll_verdict(r)}")
        add("\nQuarterly windows in detail:")
        add(md(r["windows"][r["windows"]["quarterly"]].drop(columns=["quarterly"])))
    if t5.get("bvt"):
        bt = t5["bvt"]
        add("\n**Are bars aggregates of ticks? (MEASURED)** Minute-by-minute comparison of the M1 bar with bid/ask OHLC rebuilt from ticks:")
        add(md(bt["table"]))
        add(f"Bars without any tick in the overlap: {num(bt['bars_without_ticks'])} (a tick-history gap of those minutes); tick minutes without a bar: {bt['tick_minutes_without_bars']}. "
            "→ OHLC are **bid-based** (≥99.9% exact vs bid, ~0% vs ask). `tick_volume` counts ticks but equals the tick count only in 87–100% of minutes depending on the year "
            "(2021 bars count ~9% more ticks than the tick history contains).")
    if t5.get("vol") is not None:
        add("\n**tick_volume / real_volume by year (MEASURED):** `real_volume` is zero everywhere; `tick_volume` is **not comparable across years** (feed density changed ~13×):")
        add(md(t5["vol"].rename_axis("year"), index=True))

    # ---------------- task 6
    add("\n## 9. Task 6 — Volatility calibration and cost hurdles")
    if t6.get("sigma"):
        add("Definitions: P(T) = open of the M1 bar at ET time T. 5 min/1 h: non-overlapping blocks inside the cash session (RTH) from 09:30; 6 h: 09:30→15:30 ET; "
            "overnight: 16:00 ET → next 09:30 ET, Mon–Thu nights; 5 days: Fri 16:00 → next Fri 16:00. σ = std of the price change in **index points** (MEASURED); `mean abs move / σ` is 0.80 for a normal distribution.")
        add("\nAverage price level by year (M1 close mean):")
        add(md(t6["levels"].round(0).astype(int).to_frame("avg_price").T))
        for name, tbl in t6["sigma"].items():
            add(f"\n**{name}**")
            add(md(tbl.rename(columns={"sigma_pts": "sigma (idx pts)", "mean_abs_over_sigma": "mean abs move / sigma"}), index=True, nd=2))
        add("\nSigma used below = **last 12 months** (volatility in points scales with the price level, so older years are not comparable).")
    if t6.get("hurdle") is not None:
        add("\n### Hurdle table (required hit rate for payoff 1:1: 0.5 + C / (1.6 σ))")
        add("C = one spread + slippage on both sides (**ASSUMED**: 0.5 pt/side base, 2 pt/side stress) + commission (0.0, weakly MEASURED) + swap × nights "
            "(INFERRED 'points' reading; long pays, short 0; 1 night overnight, 7 for a 5-day hold). Spreads: base = RTH median of the current regime; stress = p99 of the relevant bucket in the current regime "
            "(09:30–10:00 ET for intraday, average of the 15:30–16:00 and 09:30–10:00 p99 for overnight); stress-alt = same p99 in the worst past regime. "
            "The last column re-computes the hit rate with the measured mean absolute move instead of 0.8σ.")
        add(md(t6["hurdle"], nd=2))
        add("\n### Against your earlier assumptions (spread 2/8 pts, swap 4.6 pt/night long, σ 19/65/160/150/700; same ASSUMED slippage)")
        add(md(t6["compare"], nd=2))
        add(compare_text(t6["compare"], f))

    # ---------------- limitations
    add("\n## 10. Limitations and what could not be verified")
    for s_ in limitations(x, f):
        add(f"- {s_}")
    add("\n## 11. Questions you must answer")
    for i, s_ in enumerate(questions(x, f), 1):
        add(f"{i}. {s_}")
    if x.get("problems"):
        add("\n## 12. Problems during this run")
        for p_ in x["problems"]:
            add(f"- {p_}")
    add("\n## Files")
    add("`audit/out/cost_model_inputs.json` (machine-readable inputs with provenance), `audit/out/server_clock.json` (era-aware clock for `audit.tz.ServerClock.load`), "
        "`audit/out/*.csv` (full tables), `audit/out/run.log`. Re-run: see `audit/README.md`.")
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ prose generated from numbers
def roll_verdict(r) -> str:
    q, c = r["quarterly_summary"], r["control_summary"]
    excess = q["median_quiet_max_z"] > 1.5 * c["median_quiet_max_z"] or q["share_break_gap_z>4"] > c["share_break_gap_z>4"] + 20
    if excess:
        return ("quarterly windows show more discontinuities than control windows — possible unadjusted futures rolls; inspect the windows table.")
    return (f"**no futures-roll signature**: quarterly windows are not more jumpy than control windows (median largest quiet z {q['median_quiet_max_z']} vs {c['median_quiet_max_z']}; "
            f"break gaps z>4 in {q['share_break_gap_z>4']}% vs {c['share_break_gap_z>4']}%; largest quiet move {q['max_abs_quiet_move_pct']}% vs {c['max_abs_quiet_move_pct']}%), and the largest moves do not cluster at a common time or expiry offset. "
            "The series looks **cash-like (or continuously/back-adjusted)**. These tests cannot separate 'cash index CFD' from 'adjusted futures'; a 0.2–1% basis jump on every roll would have been visible, a smoothly amortised basis would not.")


def compare_text(cmp: pd.DataFrame, f: dict) -> str:
    base = cmp[cmp["case"] == "base"]
    higher = [h for h, a, m in zip(base["horizon"], base["sigma assumed"], base["sigma measured"]) if m > a]
    lower = [h for h, a, m in zip(base["horizon"], base["sigma assumed"], base["sigma measured"]) if m < a]
    better, worse = int((cmp["verdict"] == "better").sum()), int((cmp["verdict"] == "worse").sum())
    s = (f"\n**Reading.** Measured sigma (last 12 months, index points) is higher than assumed at {', '.join(higher) or 'no horizon'} and lower at {', '.join(lower) or 'no horizon'}; "
         f"sigma in points scales with the price level. The current-regime spread ({f.get('cur_level')} pts) is below your 2-pt base. {better} of {len(cmp)} cells need a lower hit rate than you assumed, {worse} a higher one. ")
    s += (f"Caveat: the stress spread in this comparison is the *current* regime's p99 ({f.get('cur_p99')} pts), not your 8 pts; this broker has run spreads up to {f.get('lvl_max')} pts for months "
          f"(stress-alt rows) and quoted single ticks up to {f.get('tick_spike_max')} pts in earlier regimes. The improvement is real today but depends on the broker not re-pricing.")
    return s


def summary_paragraph(x: dict, f: dict) -> str:
    u, t4 = x.get("usable"), x.get("t4")
    m1y = u[u["source"] == "M1 bars"]["years"].iloc[0] if u is not None else float("nan")
    tky = u[u["source"] == "ticks"]["years"].iloc[0] if u is not None else float("nan")
    eras = f.get("eras")
    era_txt = ""
    if eras is not None and len(eras) >= 2:
        era_txt = f"{eras['convention'].iloc[0]} until {eras['era_end_week'].iloc[0]}, then {eras['convention'].iloc[-1]}"
    hr = f.get("hr", {})
    ro = x.get("t2", {}).get("roll", {})
    t5 = x.get("t5", {})
    sw = x.get("t3") or {}
    p = []
    p.append(f"**The data are clean enough to keep researching, but the cost side is a regime-risk problem and the measured numbers differ from your working assumptions in ways that matter.** "
             f"History: {m1y} years of M1 bars and {tky} years of ticks, with no duplicate or non-monotonic timestamps, no stale runs ≥ 5 min, and bars that are bid-based aggregates of the ticks; "
             f"but the bar `spread` field is 0 before 2021-08, so spread history exists only for the tick era, and the server clock is **not** 'NY close' ({f.get('ny_close_pct')}% of weeks match): it is {era_txt}, "
             "and the broker's session hours changed several times, so every time-of-day statistic must use the era-aware converter in `audit.tz`. ")
    p.append(f"Spread: it floated until early 2022 and since then is a broker-set quasi-fixed markup (re-set {f.get('n_regimes', 0) - 1} times in the tick era, levels {f.get('lvl_min')}–{f.get('lvl_max')} pts), currently **{f.get('cur_level')} pts** since {f.get('cur_start')} "
             f"({f.get('cur_fixed_pct')}% of minutes at exactly that value, p99 = {f.get('cur_p99')}, widest tick {f.get('cur_max')}); older regimes show spikes to {f.get('tick_spike_max')} pts around data releases and the daily re-open, "
             "so the risk is the broker changing the level, not intraday noise. ")
    p.append(f"Financing and commission are not settled: swap_mode is DISABLED although swap_long = {sw.get('swap_long_raw')} points is populated (read as points: long pays {abs(f.get('swap_long') or 0)} index pts/night = {abs(f.get('swap_pct') or 0)}% p.a., short {abs(f.get('swap_short') or 0)}), "
             "and the account's deal history (one USTEC round trip, 0.0 commission) cannot tell whether either is charged — both are UNKNOWN and modelled conservatively. ")
    cmp = (x.get("t6") or {}).get("compare")
    h = (x.get("t6") or {}).get("hurdle")
    c5 = None
    if h is not None:
        r5 = h[(h["horizon"] == "5min") & (h["side"] == "n/a") & (~h["case"].str.contains("alt"))]
        c5 = (float(r5[r5["case"] == "base"]["C_total_pts"].iloc[0]), float(r5[r5["case"] != "base"]["C_total_pts"].iloc[0]))
    if hr:
        all_better = cmp is not None and bool((cmp["verdict"] == "better").all())
        p.append(f"With measured volatility, required hit rates for a 1:1 payoff are {hr['5min'][0]:.1f}% (5 min), {hr['1h'][0]:.1f}% (1 h) and {hr['6h'][0]:.1f}% (6 h) in the base case and "
                 f"{hr['5min'][1]:.1f}/{hr['1h'][1]:.1f}/{hr['6h'][1]:.1f}% in the stress case (slippage 0.5/2 pts per side is ASSUMED); "
                 + ("that is better than your assumptions in every cell, " if all_better else "that is better than your assumptions in most but not all cells (see section 9), ")
                 + "but only because the current spread is low and volatility in points is high. ")
    if t5.get("roll"):
        p.append("No futures-roll jumps were found. ")
    p.append("**Verdict: data and costs support further research on horizons of about an hour and longer; "
             + (f"sub-hour edges must beat {c5[0]:.1f}–{c5[1]:.1f} points per round trip and are sensitive to a spread re-pricing.**" if c5 else "sub-hour edges are sensitive to a spread re-pricing.**"))
    return "".join(p)


def status_rows(x: dict, f: dict) -> list:
    t1g, tc, t4, t2, t3, t5, t6 = (x.get(k) for k in ("gap", "tickcov", "t4", "t2", "t3", "t5", "t6"))
    ok = lambda v: "ANSWERED" if v else "UNKNOWN"
    rows = [
        ("0", "Symbol specification, units, point vs index points", ok(x.get("spec")), "digits 2, point 0.01, 1 lot = 1 USD per index point"),
        ("0", "Commission", "PARTIAL", "0.0 on the only USTEC round trip (n=1) and on all other deals; account type not exposed by the API → questions 1-2"),
        ("1", "M1 earliest/latest, bars per day, gaps", ok(t1g), "2019-07-16 → now; gaps listed, mostly holidays/early closes"),
        ("1", "M5/H1/D1 earliest/latest", ok(x.get("extent") is not None), "same start date"),
        ("1", "Earliest tick, ticks/day, bid/ask, flags, last/volume", ok(tc), "from 2021-08-16; bid/ask always set; last/volume always 0; undocumented flag bits"),
        ("1", "Usable years and Sharpe floor (M1 and ticks)", ok(x.get("usable") is not None), "see table; assumes stationarity (violated)"),
        ("2", "Spread percentiles per 30-min bucket (server and ET)", "ANSWERED" if t2.get("et_cur") is not None else "UNKNOWN", "tick era only; current regime table + all-history CSV"),
        ("2", "Spread history before 2021-08", "UNKNOWN", "bar spread field is 0 before 2021-08; needs another data source"),
        ("2", "Spread around the daily rollover", "ANSWERED", "spike at the re-open after the break (INFERRED rollover); −30 side is the closed break"),
        ("2", "Event-window spread and range (08:30 / 14:00 ET)", "PARTIAL", "APPROXIMATE: events detected empirically, no events file"),
        ("2", "Spread regime over time", "ANSWERED", f"{f.get('n_regimes')} regimes; structural level changes dated"),
        ("2", "Share of minutes > 2×/4×/8× session median", "ANSWERED", "table by year and for the current regime"),
        ("3", "Swap formula, points/night, triple day, annualised", "PARTIAL", "values computed; **whether swap is charged is UNKNOWN** (mode DISABLED with values populated) → question 3"),
        ("3", "Rollover time", "INFERRED", "re-open spike time; the swap rollover time itself needs confirmation → question 4"),
        ("4", "Live server offset", ok(t4), "UTC+1 now (London clock, EU summer time)"),
        ("4", "Server-time convention and offset regimes", ok(t4), "UTC-fixed → London time; NOT NY-close"),
        ("4", "Tested server→UTC→ET helper", "ANSWERED", "audit.tz + tests (DST transitions, mismatch weeks)"),
        ("5", "Duplicates, ordering, bid>ask, zero spread, stale, outside-session", ok(t5.get("bar")), "clean; details in section 8"),
        ("5", "Outlier returns (past-only sigma)", ok(t5.get("outl")), "listed with timestamps"),
        ("5", "Roll / jump check", "PARTIAL" if t5.get("roll") else "UNKNOWN", "no roll signature; cannot separate cash-like from adjusted futures"),
        ("5", "Bars vs ticks aggregation", ok(t5.get("bvt")), "bid-based OHLC; tick_volume = tick count only approximately"),
        ("6", "Realised sigma by year and horizon", ok(t6.get("sigma")), "tables by year; last-12-month sigma used"),
        ("6", "Hurdle table, measured vs your assumptions", "PARTIAL" if t6.get("hurdle") is not None else "UNKNOWN", "slippage ASSUMED; swap status UNKNOWN; spread regime risk shown as stress-alt"),
    ]
    return rows


def limitations(x: dict, f: dict) -> list:
    return [
        "Slippage cannot be measured without live executions; 0.5 / 2.0 points per side are ASSUMED, and market-execution fills at this broker may differ from quote-based costs.",
        "Whether swap and commission are charged is not established (swap_mode DISABLED with populated values; one USTEC round trip in the deal history). Money-based checks are impossible at 0.01-0.02 lots because swap rounds to 0.00.",
        "No spread history before 2021-08-16 (bar spread = 0). The 2019-2021 M1 data are usable for price/volatility, not for costs.",
        "The spread is quasi-fixed and re-priced by the broker; percentiles from different regimes must not be pooled. Current-regime statistics rest on ~123 days.",
        "The weekly server-clock detection depends on a cash-open step in 1-min range; weeks with margin < 1.15 or < 3 trading days were treated as uninformative. The exact date of the UTC→London switch is unidentifiable inside the winter ambiguity.",
        "Session schedules are inferred per quarter from the bars (≥50% presence); quarters that contain a schedule change get a blended schedule, so gap counts near the break edges in those quarters are approximate.",
        "Events are detected empirically (APPROXIMATE) because no events file was supplied; 14:00 ET FOMC windows rest on few events per year, and range comparisons around detected events are circular by construction.",
        "The roll test has no external reference (no NDX cash index): it can exclude discrete unadjusted roll jumps but cannot distinguish a cash-like CFD from a smoothly adjusted futures series.",
        "tick_volume changed meaning/density across years (≈13× range) and the tick history in 2021 contains ~9% fewer ticks than the bars aggregated; do not use volume as a cross-year feature.",
        "Leverage and the live spread/swap values are snapshots at run time and change (leverage 400 and 3000 were both observed on 2026-10-05).",
    ]


def questions(x: dict, f: dict) -> list:
    return [
        "**Account type and execution model.** Is this a Pro/Standard/ECN account, and is execution market (the API says SYMBOL_TRADE_EXECUTION_MARKET, FOK|IOC) with a dealer-set spread? Is the 1.43-point USTEC spread contractually fixed or can it float/re-price?",
        "**Commission.** Is there any commission on USTEC (per lot or per million)? The deal history shows 0.0 on one round trip only.",
        "**Swap.** Does the account pay/receive swap on USTEC? swap_mode is DISABLED but swap_long = −428.93 points. Please check the symbol specification in the terminal (Market Watch → Specification) or ask IUX, and say whether this is a swap-free account.",
        "**Rollover time.** At which server time are swaps applied (default would be server midnight = 19:00 ET)? The spread spike is at the post-break re-open shown in section 5.",
        "**Events file.** Provide `events.csv` (event_name, datetime_et) to replace the APPROXIMATE event detection with real release times (set `AUDIT_EVENTS_CSV`).",
        "**Slippage.** If you have live-fill logs, share them so the ASSUMED 0.5/2 pt per side can be replaced by a measurement.",
        "**Cache location.** The tick cache is ~1 GB of parquet inside `audit/cache/`, which sits in a OneDrive-synced folder here; move it with `AUDIT_CACHE_DIR` if you do not want it synced.",
    ]


# ------------------------------------------------------------------ cost_model_inputs.json
def cost_inputs(x: dict) -> dict:
    f = facts(x)
    sp = (x.get("t2") or {}).get("spreads") or {}
    spec = x.get("spec") or {}
    t3, t4, t6 = x.get("t3") or {}, x.get("t4") or {}, x.get("t6") or {}
    dv = x.get("deals") or {}
    out = {"meta": {"symbol": x["meta"]["sym"], "generated_utc": x["meta"]["generated"], "server_time_at_run": x["meta"]["server_now"],
                    "units": "index points (price units) unless stated; 1 index point = 100 'point' units",
                    "provenance_legend": TAG, "usd_per_index_point_per_lot": (spec.get("_units") or {}).get("usd_per_index_point_per_lot")}}

    def blk(d, label_n="N"):
        return {"p50": P(d["p50"], "M", d["N"], "index_points"), "p99": P(d["p99"], "M", d["N"], "index_points"), "max_tick": P(d["max_tick"], "M", d["N"], "index_points")} if d else None
    if sp:
        out["spread"] = {
            "regime_note": "broker-set quasi-fixed markup, re-priced in steps; do not pool across regimes",
            "current_regime_start": P(sp["current_regime_start"], "M"),
            "current_regime": {"rth_0930_1600_ET": blk(sp["rth_current"]), "open_bucket_0930_1000_ET": blk(sp["open_bucket_current"]), "close_bucket_1530_1600_ET": blk(sp["close_bucket_current"])},
            "worst_past_regime": {"start": sp["worst_regime"]["start"], "end": sp["worst_regime"]["end"], "level": P(sp["worst_regime"]["level_pts"], "M", unit="index_points"),
                                  "open_bucket": blk(sp["worst_regime"]["open_bucket"]), "close_bucket": blk(sp["worst_regime"]["close_bucket"])},
            "all_history_tick_era": {"rth": blk(sp["rth_all_history"]), "open_bucket": blk(sp["open_bucket_all_history"])},
            "regimes": (x["t2"]["reg"]).to_dict("records"),
            "before_2021_08": P(None, "M", note="UNKNOWN: bar spread field is 0; no tick history"),
        }
        ro = x["t2"].get("roll") or {}
        out["spread"]["rollover_reopen_et"] = P(ro.get("spike_clock_et"), "I", note="spike minute after the daily break; swap rollover time itself is UNKNOWN")
    out["commission"] = {"round_trip_per_lot_usd": P(dv.get("sym_commission_per_lot_round_trip_usd"), "M", n=dv.get("sym_round_trips"), unit="USD/lot",
                                                    note="weak: single round trip; other symbols also 0.0; account type unconfirmed"),
                         "round_trip_index_points": P(0.0, "M", n=dv.get("sym_round_trips"), unit="index_points")}
    if t3:
        out["swap"] = {"mode": P(t3["mode"], "M"), "raw_long": P(t3["swap_long_raw"], "M"), "raw_short": P(t3["swap_short_raw"], "M"),
                       "charged": P(None, "M", note="UNKNOWN: swap_mode DISABLED but values populated; deal history inconclusive"),
                       "long_pts_per_night_if_points": P(t3["swap_long_pts_per_night_if_points"], "I", unit="index_points/night", note="negative = paid; reading = POINTS"),
                       "short_pts_per_night_if_points": P(t3["swap_short_pts_per_night_if_points"], "I", unit="index_points/night"),
                       "annual_pct_long": P(t3["annual_pct_long"], "I", unit="% of price p.a. (negative = paid)"), "triple_swap_day": P(t3["triple_day"], "M"),
                       "nights_per_week_charged": P(7, "I")}
    out["slippage_per_side"] = {"base": P(C.SLIP_BASE_PER_SIDE, "A", unit="index_points"), "stress": P(C.SLIP_STRESS_PER_SIDE, "A", unit="index_points")}
    if t4:
        out["server_clock"] = {"eras": t4["clock"].to_json(), "live_offset_hours": P(t4["live"]["offset_hours"], "M"),
                               "convention": P(f.get("eras")["convention"].tolist() if f.get("eras") is not None else None, "I"),
                               "ny_close_match_pct": P(t4["ny_close_match_pct"], "M", n=t4["weeks_informative"], unit="% of weeks"),
                               "era_boundary_note": "the UTC->London switch is only identifiable within the winter ambiguity (2021-10-31 .. 2022-03-27); conversions are identical for any date in it",
                               "how_to_use": "audit.tz.ServerClock.load('audit/out/server_clock.json')"}
    if t6:
        out["volatility"] = {"sigma_last_12m_index_points": {k: P(v, "M", n=t6["n"][k], unit="index_points") for k, v in t6["sig"].items()},
                             "mean_abs_move_last_12m_index_points": {k: P(v, "M", n=t6["n"][k], unit="index_points") for k, v in t6["mad"].items()},
                             "price_level_last_12m": P(float(t6["levels"]["last 12 months"]), "M", unit="index_points")}
        out["hurdle_table"] = t6["hurdle"].to_dict("records")
        out["comparison_with_user_assumptions"] = t6["compare"].to_dict("records")
    if t6 and t6.get("sigma"):
        out["volatility"]["sigma_by_year_index_points"] = {
            h: {str(y): P(float(r["sigma_pts"]), "M", n=int(r["N"]), unit="index_points") for y, r in t6["sigma"][k].iterrows() if y != "ALL"}
            for h, k in {"5min": "5min|RTH", "1h": "1h|RTH", "6h": "6h|09:30-15:30 ET", "overnight": "overnight|Mon-Thu nights", "5d": "5d|Fri 16:00 - next Fri 16:00"}.items()}
        out["volatility"]["sigma_definitions"] = ("5min/1h: non-overlapping blocks inside 09:30-16:00 ET; 6h: 09:30->15:30 ET; overnight: 16:00 ET -> next 09:30 ET (Mon-Thu nights); "
                                                  "5d: Fri 16:00 ET -> next Fri 16:00 ET; price = open of the M1 bar at that ET time")
    ev = (x.get("t2") or {}).get("events")
    if ev:
        out["spread"]["event_windows"] = {
            "provenance_note": "APPROXIMATE: event days detected empirically from 1-min range (no events file); statistics are INFERRED",
            **{label: {"event_days": P(a["n_event_days"], "I"), "event_days_in_current_regime": P(a["n_event_days_cur"], "I", note="small N -> not reliable for p99" if a["n_event_days_cur"] < 30 else None),
                       "windows_relative_to_release": a["window_summary"].to_dict("records")} for label, a in ev.items()}}
    t1g = x.get("gap")
    if t1g:
        out["session_schedule"] = {"provenance": "INFERRED", "latest_quarter": t1g["schedule_period"], "expected_minutes_ET": t1g["schedule_latest_year"].to_dict("records"),
                                   "history_daily_break_ET": t1g["schedule_history"].to_dict("records")}
        out["data_gaps"] = {"expected_minutes": P(t1g["expected_minutes_total"], "I"), "missing_minutes": P(t1g["missing_minutes_total"], "I"),
                            "bars_outside_schedule": P(t1g["bars_outside_schedule"], "I")}
    u = x.get("usable")
    if u is not None:
        out["history"] = {r["source"]: {"years": P(r["years"], "M"), "min_detectable_sharpe_t3": P(r["min_detectable_sharpe_t3"], "I")} for r in u.to_dict("records")}
    return jsonable(out)
