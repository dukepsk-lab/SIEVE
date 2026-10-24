"""Run Stage A (8 candidates + controls C1, C2) and Stage B (Stage A survivors only). Stage C is never run: there is no
code path here that unlocks the holdout, and the market is cut at 2026-01-01 so no 2026 price is even loaded into a variant.

Usage (from the repo root):  python -m research.run_stages
Outputs in research/out/: stage_{a,b}_summary.csv, stage_{a,b}_by_year.csv, stage_a_skips.csv, RESULTS.md
"""
import time
from pathlib import Path

import pandas as pd

from .data import CLOCK_JSON, ServerClock, build_market, load_costs, load_m1
from .evaluate import score_positions, score_trades, summarise
from .variants import CANDIDATES, CONTROLS

OUT = Path(__file__).resolve().parent / "out"
STAGES = {"A": ("2019-07-16", "2023-12-31"), "B": ("2024-01-01", "2025-12-31")}   # entry dates, PLAN section 4
MIN_T = {"A": 2.0, "B": 1.5}
MIN_POSITIVE_YEARS = {"A": 3, "B": 0}                                              # Stage A: >= 3 of the 5 calendar years


def gate(stage: str, row: dict) -> bool:
    """Stress-cost gate (PLAN section 4): net mean > 0, t >= threshold and, in Stage A, >= 3 positive calendar years."""
    return bool(row["total_net_stress_bp"] > 0 and row["t_stress"] >= MIN_T[stage] and row["years_positive"] >= MIN_POSITIVE_YEARS[stage])


def run_stage(stage, names, results, market, costs):
    start, end = STAGES[stage]
    rows, years, skips = [], [], []
    for name in names:
        r = results[name]
        s = (score_positions(r.pos, market.days, costs, start, end) if r.pos is not None
             else score_trades(r.trades, market.days, costs, start, end))
        row, by = summarise(s, r.skips)
        role = "control" if name in CONTROLS else "candidate"
        rows.append({"variant": name, "role": role, **row, "gate_pass": gate(stage, row) if role == "candidate" else None})
        years.append(by.assign(variant=name, role=role)[["variant", "role", "year", "trades", "net_base_bp", "net_stress_bp", "positive"]])
        skips.append(r.skips[(r.skips["date"] >= start) & (r.skips["date"] <= end)])
    return pd.DataFrame(rows), pd.concat(years, ignore_index=True), pd.concat(skips, ignore_index=True)


# ------------------------------------------------------------------ report
def _fmt(x, nd=2):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return ""
    return f"{x:.{nd}f}" if isinstance(x, float) else str(x)


def md_table(df: pd.DataFrame) -> str:
    head = "| " + " | ".join(df.columns) + " |\n|" + "---|" * len(df.columns) + "\n"
    return head + "".join("| " + " | ".join(_fmt(v) for v in r) + " |\n" for r in df.itertuples(index=False))


def stage_tables(summary: pd.DataFrame, by_year: pd.DataFrame) -> str:
    main = pd.DataFrame({"variant": summary["variant"], "role": summary["role"], "trades": summary["trades"],
                         "skipped": summary["skipped"], "mean net stress bp": summary["net_stress_mean_bp"],
                         "t": summary["t_stress"], "Sharpe": summary["sharpe_stress"],
                         "yrs+/yrs": summary["years_positive"].astype(str) + "/" + summary["years"].astype(str),
                         "gate": summary["gate_pass"].map({True: "PASS", False: "FAIL"}).fillna("control")})
    detail = summary[["variant", "trades_per_year", "gross_mean_bp", "net_base_mean_bp", "net_stress_mean_bp", "net_pt_mean_bp",
                      "hit_rate_stress", "max_dd_stress_bp", "total_net_stress_bp"]]
    detail.columns = ["variant", "trades/yr", "gross", "net base", "net stress", "net pt-cost", "hit rate", "max DD bp", "total net stress bp"]
    yr = by_year.pivot(index="variant", columns="year", values="net_stress_bp").reindex(summary["variant"]).reset_index()
    yr.columns = [str(c) for c in yr.columns]
    skips = summary[["variant"] + [c for c in summary.columns if c.startswith("skip_")]]
    return (md_table(main) + "\nPer trade (or per position-day for H5a, H5b, C2), bp:\n\n" + md_table(detail) +
            "\nNet stress bp per calendar year (sum of daily P&L):\n\n" + md_table(yr) + "\nSkipped counts by reason:\n\n" + md_table(skips))


def write_results(costs, a, a_year, b, b_year, survivors, runtime):
    verdict = "\n".join(f"- {r.variant}: **{'PASS' if r.gate_pass else 'FAIL'}** (t = {_fmt(r.t_stress)}, mean net stress "
                        f"{_fmt(r.net_stress_mean_bp)} bp, {r.years_positive}/{r.years} years positive)" for r in a[a["role"] == "candidate"].itertuples())
    text = f"""# Phase 2 results: Stage A and Stage B (research/PLAN.md rules, frozen)

All numbers are **MEASURED** on USTEC. M1 **bid** bars from the audit cache (server clock converted to New York time). Slippage
is **ASSUMED** (0.5 / 2.0 points per side) and cannot be measured without live fills. Commission and swap are USER-CONFIRMED zero.
No bar stamped on or after 2026-01-01 ET was loaded into any variant, so Stage C (holdout) was not run and no 2026 result exists.
Run time of `python -m research.run_stages`: {runtime:.1f} s.

## Costs used

| item | points | provenance | bp of notional |
|---|---|---|---|
| P_REF (mean M1 close, 2026-05-14 to 2026-10-04) | {costs.p_ref:,.1f} | MEASURED | n/a |
| round trip, base (spread 1.43 + 2 x 0.5) | {costs.base_pts:.2f} | spread MEASURED, slippage ASSUMED | {costs.base_bp:.3f} |
| round trip, stress (spread 2.0 + 2 x 2.0) | {costs.stress_pts:.2f} | spread MEASURED, slippage ASSUMED | {costs.stress_bp:.3f} |

Point-cost sensitivity ("net pt-cost"): the stress points divided by each trade's own entry price (harsher in early years).
Gates use the **stress** cost.

## Stage A: development, entry dates {STAGES['A'][0]} to {STAGES['A'][1]} (gate: net mean > 0, t >= 2.0, >= 3 of 5 calendar years positive)

{stage_tables(a, a_year)}
### Stage A gate verdicts (8 candidates; controls are never candidates)

{verdict}

Survivors carried to Stage B: {', '.join(survivors) if survivors else 'none'}.

## Stage B: validation, entry dates {STAGES['B'][0]} to {STAGES['B'][1]} (gate: net mean > 0, t >= 1.5)

"""
    if b is None or b.empty:
        text += "No survivors: Stage B was not run.\n"
    else:
        text += stage_tables(b, b_year) + "\n" + "\n".join(
            f"- {r.variant}: **{'PASS' if r.gate_pass else 'FAIL'}** (t = {_fmt(r.t_stress)}, mean net stress {_fmt(r.net_stress_mean_bp)} bp)"
            for r in b.itertuples()) + "\n"
    text += """
## Definitions

- t = mean / std x sqrt(N_days) of the daily net stress P&L over every trading day of the window (0 on days without a position;
  P&L booked on the entry day). Sharpe = mean / std x sqrt(252). std uses ddof = 1.
- Controls: C1 = long 09:30 to 16:00 every day; C2 = buy and hold (one round trip per window). Reported only.
- Position variants (H5a, H5b, C2): "trades" = position-days (days with a non-zero position); each window starts and ends flat, so
  the entry and the final liquidation are charged; a flip costs one full round trip.
- The five Stage A calendar years are 2019 (partial, from 2019-07-16) to 2023.
- Stage C (2026-01-01 onward) is locked and untouched.
"""
    (OUT / "RESULTS.md").write_text(text, encoding="utf-8")


def main():
    t0 = time.time()
    OUT.mkdir(exist_ok=True)
    m1 = load_m1()
    costs = load_costs(m1)
    market = build_market(m1, ServerClock.load(CLOCK_JSON))             # cut at 2026-01-01: holdout prices never enter
    results = {name: fn(market) for name, fn in {**CANDIDATES, **CONTROLS}.items()}

    a, a_year, a_skips = run_stage("A", list(CANDIDATES) + list(CONTROLS), results, market, costs)
    survivors = a.loc[a["gate_pass"] == True, "variant"].tolist()      # noqa: E712 (None for controls)
    if survivors:
        b, b_year, _ = run_stage("B", survivors, results, market, costs)
    else:
        b, b_year = pd.DataFrame(columns=a.columns), pd.DataFrame(columns=a_year.columns)

    a.round(4).to_csv(OUT / "stage_a_summary.csv", index=False)
    a_year.round(4).to_csv(OUT / "stage_a_by_year.csv", index=False)
    a_skips.to_csv(OUT / "stage_a_skips.csv", index=False)
    b.round(4).to_csv(OUT / "stage_b_summary.csv", index=False)
    b_year.round(4).to_csv(OUT / "stage_b_by_year.csv", index=False)
    write_results(costs, a, a_year, b, b_year, survivors, time.time() - t0)
    print(f"Stage A survivors: {survivors or 'none'}; wrote research/out in {time.time() - t0:.1f} s")


if __name__ == "__main__":
    main()
