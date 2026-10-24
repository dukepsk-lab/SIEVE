"""Scoring and metrics (PLAN sections 4-6).

Per trade: gross_bp = direction x (exit / entry - 1) x 1e4. Net = gross minus the round-trip cost in bp: base, stress
(points / P_REF) and point-cost sensitivity (stress points / the trade's own entry price). Position series (H5, C2): daily
P&L = pos x (C(d+1) / C(d) - 1) x 1e4 - |change in pos| x cost_bp / 2; every window starts and ends flat, so the entry and the
final liquidation are charged (the liquidation is booked on the last position day of the window).

The daily series covers EVERY trading day of the window (0 where nothing is held or traded) and books P&L on the entry day:
t = mean / std x sqrt(N_days), Sharpe = mean / std x sqrt(252), std with ddof = 1.

Holdout guard: scoring anything whose entry date, exit date or window end is on or after 2026-01-01 raises HoldoutError unless
unlock_holdout=True. Only the user can authorise Stage C; no code in this repo passes it.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data import HOLDOUT_START, Costs
from .variants import SKIP_REASONS

COLS = ["gross", "base", "stress", "pt"]          # bp; gross and net under base / stress / point-cost sensitivity
DAY = pd.Timedelta(days=1)


class HoldoutError(RuntimeError):
    pass


def check_holdout(unlock_holdout: bool, end, *dates) -> None:
    if unlock_holdout:
        return
    for x in (pd.DatetimeIndex([end]), *(pd.DatetimeIndex(d) for d in dates)):
        if len(x) and x.max() >= HOLDOUT_START:
            raise HoldoutError(f"refusing to score {x.max().date()}: on or after {HOLDOUT_START.date()} (holdout is locked)")


@dataclass
class Scored:
    daily: pd.DataFrame      # every trading day of the window x COLS (net of costs except 'gross')
    units: pd.DataFrame      # one row per trade (or per position-day), indexed by entry day, same columns
    n_changes: int           # position changes (position series only)
    start: pd.Timestamp
    end: pd.Timestamp


def _window(days: pd.DatetimeIndex, start, end):
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    return start, end, days[(days >= start) & (days <= end)]


def score_trades(trades: pd.DataFrame, days: pd.DatetimeIndex, costs: Costs, start, end, unlock_holdout: bool = False) -> Scored:
    start, end, wd = _window(days, start, end)
    t = trades[(trades["entry_et"] >= start) & (trades["entry_et"] < end + DAY)]
    check_holdout(unlock_holdout, end, t["entry_et"], t["exit_et"])
    gross = t["direction"] * (t["exit_px"] / t["entry_px"] - 1) * 1e4
    u = pd.DataFrame({"gross": gross, "base": gross - costs.base_bp, "stress": gross - costs.stress_bp,
                      "pt": gross - costs.stress_pts / t["entry_px"] * 1e4})
    u.index = pd.DatetimeIndex(t["entry_et"]).normalize()
    if not u.index.isin(wd).all():
        raise ValueError("a trade enters on a day that is not a trading day of the calendar")
    return Scored(u.groupby(level=0).sum().reindex(wd, fill_value=0.0), u, 0, start, end)


def score_positions(pos: pd.DataFrame, days: pd.DatetimeIndex, costs: Costs, start, end, unlock_holdout: bool = False) -> Scored:
    start, end, wd = _window(days, start, end)
    p = pos[(pos.index >= start) & (pos.index <= end)]
    check_holdout(unlock_holdout, end, p.index, p["next_day"].dropna())
    if p.empty:
        return Scored(pd.DataFrame(0.0, index=wd, columns=COLS), pd.DataFrame(columns=COLS), 0, start, end)
    q = p["pos"].fillna(0.0).to_numpy()
    dq = np.abs(np.diff(np.r_[0.0, q, 0.0]))                                          # flat before and after the window
    turn = dq[:-1].copy()
    turn[-1] += dq[-1]
    gross = q * (p["next_close"].to_numpy() / p["close"].to_numpy() - 1) * 1e4
    gross = np.nan_to_num(gross)                                                      # no exit close (end of data): no P&L
    d = pd.DataFrame({"gross": gross, "base": gross - turn * costs.base_bp / 2, "stress": gross - turn * costs.stress_bp / 2,
                      "pt": gross - turn * costs.stress_pts / p["close"].to_numpy() * 1e4 / 2}, index=p.index)
    return Scored(d.reindex(wd, fill_value=0.0), d[q != 0], int((dq[:-1] > 0).sum()), start, end)


def max_drawdown(x: pd.Series) -> float:
    cum = x.cumsum()
    return float((cum.cummax().clip(lower=0) - cum).max())


def summarise(s: Scored, skips: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    """One summary row and the per-calendar-year table for a scored variant over its window."""
    d, n, st = s.daily, len(s.units), s.daily["stress"]
    sd = st.std(ddof=1) if len(st) > 1 else np.nan
    sk = skips[(skips["date"] >= s.start) & (skips["date"] <= s.end)]
    yrs = ((s.end - s.start).days + 1) / 365.25
    by_year = d[["stress", "base"]].groupby(d.index.year).sum().rename(columns={"stress": "net_stress_bp", "base": "net_base_bp"})
    by_year["trades"] = s.units.groupby(pd.DatetimeIndex(s.units.index).year).size().reindex(by_year.index, fill_value=0)
    by_year["positive"] = by_year["net_stress_bp"] > 0
    by_year.index.name = "year"
    per = lambda c: d[c].sum() / n if n else np.nan
    row = {"trades": n, "trades_per_year": n / yrs, "position_changes": s.n_changes, "skipped": len(sk),
           **{f"skip_{r.split(' (')[0].replace(' ', '_')}": int((sk["reason"] == r).sum()) for r in SKIP_REASONS},
           "gross_mean_bp": per("gross"), "net_base_mean_bp": per("base"), "net_stress_mean_bp": per("stress"),
           "net_pt_mean_bp": per("pt"), "days": len(d),
           "t_stress": st.mean() / sd * np.sqrt(len(st)) if sd and sd > 0 else np.nan,
           "sharpe_stress": st.mean() / sd * np.sqrt(252) if sd and sd > 0 else np.nan,
           "hit_rate_stress": float((s.units["stress"] > 0).mean()) if n else np.nan,
           "max_dd_stress_bp": max_drawdown(st), "total_net_stress_bp": float(st.sum()),
           "years_positive": int(by_year["positive"].sum()), "years": len(by_year)}
    return row, by_year.reset_index()
