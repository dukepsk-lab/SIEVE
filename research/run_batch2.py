"""Run batch 2 (PLAN section 9): Stage A on H6a, H6b, H3a, H8a, H8b plus controls C2 and E0; Stage B on Stage A survivors only.
Stage C is never run: no code path here unlocks the holdout, and the market is cut at 2026-01-01 so no 2026 price is loaded.

Event variants are PENDING when research/data/events.csv is missing or has no scheduled rows for them; nothing else changes.

Usage (from the repo root):  python -m research.run_batch2
Outputs in research/out/: batch2_stage_{a,b}_summary.csv, batch2_stage_{a,b}_by_year.csv, RESULTS_BATCH2.md
"""
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .data import CLOCK_JSON, ServerClock, build_market, load_costs, load_m1
from .evaluate import score_positions, score_trades, summarise
from .inference import nw_ols, welch
from .run_stages import MIN_T, STAGES, _fmt, gate, md_table
from .variants import c2
from .variants2 import CAPS, EVENTS_CSV, KINDS, e0, event_days, h3a, h6a, h6b, h8a, h8b, read_events

OUT = Path(__file__).resolve().parent / "out"
ORDER = ["H6a", "H6b", "H3a", "H8a", "H8b", "C2", "E0"]
ROLE = {n: "candidate" for n in ORDER[:5]} | {"C2": "control", "E0": "control"}
MIN_RESID_YEARS = 3                                        # Stage A, H6: residual positive in >= 3 of the 5 calendar years
H6_COLS = ["alpha_bp_day", "alpha_t_nw", "beta_c2", "sharpe_c2", "resid_years_positive", "avg_w", "turnover_per_year"]
E0_COLS = ["h8a_minus_e0_bp", "welch_t", "welch_df", "n_h8a", "n_e0"]
YEAR_COLS = ["variant", "role", "year", "trades", "net_base_bp", "net_stress_bp", "positive", "resid_bp"]


def pending_status(ev: pd.DataFrame, market) -> dict:
    """PENDING text per event variant (None when it has scheduled event days). E0 needs H8a's events (else every day is 'non-event')."""
    out = {}
    for n in ("H3a", "H8a", "H8b"):
        if len(event_days(ev, market, KINDS[n])):
            out[n] = None
        else:
            out[n] = "PENDING (events.csv missing)" if ev.empty else f"PENDING (no scheduled {'/'.join(KINDS[n])} rows in events.csv)"
    out["E0"] = out["H8a"]
    return out


def gate_h6(stage: str, row: dict) -> bool:
    """Stage A: alpha > 0, NW t >= 2.0, Sharpe(H6) > Sharpe(C2), residual positive in >= 3 calendar years. Stage B: alpha > 0, t >= 1.5."""
    ok = row["alpha_bp_day"] > 0 and row["alpha_t_nw"] >= MIN_T[stage]               # NaN compares False
    if stage == "A":
        ok = ok and row["sharpe_stress"] > row["sharpe_c2"] and row["resid_years_positive"] >= MIN_RESID_YEARS
    return bool(ok)


def h6_stats(s, c2s, pos: pd.DataFrame):
    """Alpha vs C2 (daily stress net bp, Newey-West 5 lags), Sharpe of C2, per-year residual (variant - beta x C2), exposure stats."""
    y, x = s.daily["stress"], c2s.daily["stress"]
    fit = nw_ols(y.to_numpy(), x.to_numpy(), lags=5)
    resid = y - fit["beta"] * x
    by_year = resid.groupby(resid.index.year).sum()
    q = pos["pos"][(pos.index >= s.start) & (pos.index <= s.end)].fillna(0.0).to_numpy()
    yrs = ((s.end - s.start).days + 1) / 365.25
    sd = x.std(ddof=1)
    row = {"alpha_bp_day": fit["alpha"], "alpha_t_nw": fit["alpha_t"], "beta_c2": fit["beta"],
           "sharpe_c2": x.mean() / sd * np.sqrt(252) if sd > 0 else np.nan, "resid_years_positive": int((by_year > 0).sum()),
           "avg_w": q.sum() / len(y), "turnover_per_year": np.abs(np.diff(np.r_[0.0, q, 0.0])).sum() / yrs}
    return row, by_year


def run_stage(stage, names, res, market, costs, status):
    start, end = STAGES[stage]
    score = lambda r: (score_positions(r.pos, market.days, costs, start, end) if r.pos is not None
                       else score_trades(r.trades, market.days, costs, start, end))
    c2s = score(res["C2"])
    rows, years, units = {}, [], {}
    for name in names:
        role = ROLE[name]
        if status.get(name):
            rows[name] = {"variant": name, "role": role, "status": status[name]}
            continue
        r = res[name]
        s = score(r)
        units[name] = s.units
        row, by = summarise(s, r.skips)
        by["resid_bp"] = np.nan
        if name in CAPS:
            extra, resid = h6_stats(s, c2s, r.pos)
            row.update(extra)
            by["resid_bp"] = by["year"].map(resid)
            ok = gate_h6(stage, row)
        else:
            ok = gate(stage, row) if role == "candidate" else None
        rows[name] = {"variant": name, "role": role, **row, "gate_pass": ok,
                      "status": "control" if ok is None else "PASS" if ok else "FAIL"}
        years.append(by.assign(variant=name, role=role)[YEAR_COLS])
    if "H8a" in units and "E0" in units:                       # report only: per-trade net stress bp, event days vs non-event days
        w = welch(units["H8a"]["stress"], units["E0"]["stress"])
        rows["E0"].update(h8a_minus_e0_bp=w["diff"], welch_t=w["t"], welch_df=w["df"], n_h8a=w["n_a"], n_e0=w["n_b"])
    summary = pd.DataFrame(list(rows.values()))
    tail = ["gate_pass", "status"]
    summary = summary[[c for c in summary.columns if c not in tail] + tail]
    return summary, pd.concat(years, ignore_index=True)


def run_batch(market, costs, ev):
    """Stage A on all batch 2 variants and controls, Stage B on Stage A survivors only. Returns the four frames and the survivors."""
    res = {"H6a": h6a(market), "H6b": h6b(market), "C2": c2(market), "H3a": h3a(market, ev), "H8a": h8a(market, ev),
           "H8b": h8b(market, ev), "E0": e0(market, ev)}
    status = pending_status(ev, market)
    a, a_year = run_stage("A", ORDER, res, market, costs, status)
    survivors = a.loc[a["status"] == "PASS", "variant"].tolist()
    if survivors:
        b, b_year = run_stage("B", survivors, res, market, costs, status)
    else:
        b, b_year = pd.DataFrame(columns=a.columns), pd.DataFrame(columns=a_year.columns)
    return a, a_year, b, b_year, survivors


# ------------------------------------------------------------------ report
def _int(s: pd.Series) -> pd.Series:
    """Counts as ints (blank for pending rows) so a NaN elsewhere in the column does not print 1078 as 1078.00."""
    return pd.Series([None if pd.isna(v) else int(v) for v in s], index=s.index, dtype=object)


def _pending(summary):
    return summary["status"].str.startswith("PENDING")


def stage_tables(summary: pd.DataFrame, by_year: pd.DataFrame) -> str:
    done = summary[~_pending(summary)]
    yrs = done["years_positive"].astype(int).astype(str) + "/" + done["years"].astype(int).astype(str)
    main = pd.DataFrame({"variant": summary["variant"], "role": summary["role"], "trades": _int(summary["trades"]), "skipped": _int(summary["skipped"]),
                         "mean net stress bp": summary["net_stress_mean_bp"], "t (daily)": summary["t_stress"],
                         "Sharpe": summary["sharpe_stress"], "yrs+/yrs": yrs.reindex(summary.index), "status": summary["status"]})
    out = md_table(main) + "\nPer trade (or per position-day for H6a, H6b, C2), bp:\n\n"
    out += md_table(done[["variant", "trades_per_year", "gross_mean_bp", "net_base_mean_bp", "net_stress_mean_bp", "net_pt_mean_bp",
                          "hit_rate_stress", "max_dd_stress_bp", "total_net_stress_bp"]].set_axis(
        ["variant", "trades/yr", "gross", "net base", "net stress", "net pt-cost", "hit rate", "max DD bp", "total net stress bp"], axis=1))
    h6 = summary[summary["variant"].isin(CAPS)]
    if len(h6):
        t = pd.DataFrame({"variant": h6["variant"], "alpha bp/day": h6["alpha_bp_day"], "alpha t (NW5)": h6["alpha_t_nw"],
                          "beta vs C2": h6["beta_c2"], "Sharpe": h6["sharpe_stress"], "Sharpe C2": h6["sharpe_c2"],
                          "resid yrs+": h6["resid_years_positive"].astype(int).astype(str) + "/" + h6["years"].astype(int).astype(str),
                          "avg w": h6["avg_w"], "turnover/yr": h6["turnover_per_year"], "w changes": _int(h6["position_changes"]),
                          "status": h6["status"]})
        out += "\nH6 against the C2 benchmark (daily net stress bp; turnover = sum of |change in w| per year incl. entry and final exit):\n\n" + md_table(t)
    if len(by_year):
        pv = by_year.pivot(index="variant", columns="year", values="net_stress_bp").reindex(done["variant"]).reset_index()
        pv.columns = [str(c) for c in pv.columns]
        out += "\nNet stress bp per calendar year (sum of daily P&L):\n\n" + md_table(pv)
        rv = by_year[by_year["variant"].isin(CAPS)].pivot(index="variant", columns="year", values="resid_bp").reset_index()
        if len(rv):
            rv.columns = [str(c) for c in rv.columns]
            out += "\nH6 residual (variant - beta x C2) per calendar year, bp:\n\n" + md_table(rv)
    sk = done[["variant"] + [c for c in done.columns if c.startswith("skip_")]].apply(lambda c: c if c.name == "variant" else _int(c))
    out += "\nSkipped counts by reason:\n\n" + md_table(sk)
    e = summary[summary["variant"] == "E0"]
    if len(e) and not _pending(e).iloc[0]:
        r = e.iloc[0]
        out += (f"\nControl E0 (report only): H8a - E0 mean per trade = {_fmt(float(r['h8a_minus_e0_bp']))} bp "
                f"(H8a n = {_fmt(r['n_h8a'])}, E0 n = {_fmt(r['n_e0'])}), Welch t = {_fmt(float(r['welch_t']))}, "
                f"df = {_fmt(float(r['welch_df']), 1)}. Per-trade net stress bp; the cost is the same on both sides, so the gross difference is identical.\n")
    return out


def verdicts(summary: pd.DataFrame) -> str:
    lines = []
    for r in summary[summary["role"] == "candidate"].itertuples():
        if r.status.startswith("PENDING"):
            lines.append(f"- {r.variant}: **{r.status}**")
        elif r.variant in CAPS:
            lines.append(f"- {r.variant}: **{r.status}** (alpha = {_fmt(r.alpha_bp_day)} bp/day, t_NW = {_fmt(r.alpha_t_nw)}, beta = {_fmt(r.beta_c2)}, "
                         f"Sharpe {_fmt(r.sharpe_stress)} vs C2 {_fmt(r.sharpe_c2)}, residual positive in {int(r.resid_years_positive)}/{int(r.years)} years)")
        else:
            lines.append(f"- {r.variant}: **{r.status}** (t = {_fmt(r.t_stress)}, mean net stress {_fmt(r.net_stress_mean_bp)} bp, "
                         f"{int(r.years_positive)}/{int(r.years)} years positive)")
    return "\n".join(lines)


def events_section(ev: pd.DataFrame, market) -> str:
    if ev.empty:
        return f"`research/data/events.csv` was missing or empty at run time ({'exists' if EVENTS_CSV.exists() else 'not found'}): H3a, H8a, H8b and E0 are PENDING.\n"
    d = ev[(ev["date"] >= market.days[0]) & (ev["date"] <= market.days[-1])]
    t = d.groupby(["event", "scheduled"]).size().rename("rows").reset_index()
    return (f"`research/data/events.csv`, rows inside the market range {market.days[0].date()} to {market.days[-1].date()} "
            f"(first {d['date'].min().date() if len(d) else 'n/a'}, last {d['date'].max().date() if len(d) else 'n/a'}); only scheduled = True rows "
            f"enter H3a, H8a and H8b:\n\n" + md_table(t))


def write_results(costs, market, ev, a, a_year, b, b_year, survivors, runtime):
    ds = ", ".join(f"{k} = {v}" for k, v in {"sigma*": "0.20", "window": "20 returns", "band": "0.10", "H6a cap": "2.0", "H6b cap": "1.0"}.items())
    text = f"""# Phase 2 results, batch 2: Stage A and Stage B (research/PLAN.md section 9, frozen)

All numbers are **MEASURED** on USTEC. M1 **bid** bars from the audit cache (server clock converted to New York time). Slippage
is **ASSUMED** (0.5 / 2.0 points per side) and cannot be measured without live fills. Commission and swap are USER-CONFIRMED zero.
No bar stamped on or after 2026-01-01 ET was loaded into any variant, so Stage C (holdout) was not run and no 2026 result exists.
Run time of `python -m research.run_batch2`: {runtime:.1f} s. Frozen H6 constants: {ds}.

## Costs used

| item | points | provenance | bp of notional |
|---|---|---|---|
| P_REF (mean M1 close, current spread regime to 2026-10-04) | {costs.p_ref:,.1f} | MEASURED | n/a |
| round trip, base (spread 1.43 + 2 x 0.5) | {costs.base_pts:.2f} | spread MEASURED, slippage ASSUMED | {costs.base_bp:.3f} |
| round trip, stress (spread 2.0 + 2 x 2.0) | {costs.stress_pts:.2f} | spread MEASURED, slippage ASSUMED | {costs.stress_bp:.3f} |

Every unit change in H6's weight w costs |change| x cost_bp / 2. The gates use the **stress** cost.

## Events file

{events_section(ev, market)}
## Stage A: development, entry dates {STAGES['A'][0]} to {STAGES['A'][1]}
Gates: H6 = alpha vs C2 > 0 with Newey-West(5) t >= 2.0, Sharpe(H6) > Sharpe(C2), residual positive in >= 3 of 5 calendar years.
H3a, H8a, H8b = net stress mean > 0, daily-series t >= 2.0, >= 3 of 5 calendar years positive. Controls C2 and E0 are never candidates.

{stage_tables(a, a_year)}
### Stage A gate verdicts (5 candidates)

{verdicts(a)}

Survivors carried to Stage B: {', '.join(survivors) if survivors else 'none'}.

## Stage B: validation, entry dates {STAGES['B'][0]} to {STAGES['B'][1]} (gate: H6 alpha > 0 and t_NW >= 1.5; events net stress mean > 0 and t >= 1.5)

"""
    if b.empty:
        text += "No survivors: Stage B was not run.\n"
    else:
        text += stage_tables(b, b_year) + "\n" + verdicts(b) + "\n"
    text += """
## Definitions and resolved ambiguities

- Daily series and t as in batch 1: every trading day of the window (0 where nothing is held or traded), P&L booked on the entry
  day, t = mean / std x sqrt(N_days), Sharpe = mean / std x sqrt(252), ddof = 1. Position variants (H6a, H6b, C2) count a
  position-day as a trade; each window starts and ends flat, so the entry and the final liquidation are charged.
- H6 alpha: OLS of the variant's daily net stress bp on C2's, same window, Newey-West standard errors (Bartlett kernel, 5 lags, no
  small-sample correction). The residual is the literal (variant - beta x C2), including the alpha, summed per calendar year.
- H6 starts flat; during the warm-up (21 valid closes: 20 returns plus the one-day lag) it holds nothing, while C2 is long from
  the first close. The band applies from the first available target (|target - 0| >= 0.10). A zero sigma_hat would give the cap.
- Event variants: d - 1 is the previous trading day of the market (no calendar-adjacency requirement); the FOMC statement time is
  fixed at 14:00 as in the plan (time_et is not used); events on non-trading days or with no previous trading day are skipped as
  "signal unavailable"; events outside the market range (before the first bar, or in the holdout) are ignored.
- E0 excludes every date that has an event row of any kind (scheduled or not) and is evaluated in Stage A only.
- Stage C (2026-01-01 onward) is locked and untouched. Batch 1 files are not modified by this run.
"""
    (OUT / "RESULTS_BATCH2.md").write_text(text, encoding="utf-8")


def main():
    t0 = time.time()
    OUT.mkdir(exist_ok=True)
    m1 = load_m1()
    costs = load_costs(m1)
    market = build_market(m1, ServerClock.load(CLOCK_JSON))             # cut at 2026-01-01: holdout prices never enter
    ev = read_events()
    a, a_year, b, b_year, survivors = run_batch(market, costs, ev)
    a.round(4).to_csv(OUT / "batch2_stage_a_summary.csv", index=False)
    a_year.round(4).to_csv(OUT / "batch2_stage_a_by_year.csv", index=False)
    b.round(4).to_csv(OUT / "batch2_stage_b_summary.csv", index=False)
    b_year.round(4).to_csv(OUT / "batch2_stage_b_by_year.csv", index=False)
    write_results(costs, market, ev, a, a_year, b, b_year, survivors, time.time() - t0)
    print(f"Batch 2 Stage A survivors: {survivors or 'none'}; wrote research/out in {time.time() - t0:.1f} s")


if __name__ == "__main__":
    main()
