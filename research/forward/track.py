"""Forward paper-tracker for the frozen H6a and H3a variants (PLAN section 10). Paper only: nothing is ever traded.

Each run is stateless. It pulls USTEC. M1 bid bars read-only from MT5 (kept in memory, nothing is written to audit/cache), runs the
live checks, recomputes everything from the bars and rewrites research/forward/out/. Only snapshots.csv appends, one row per run.

Rules are the frozen ones and are reused, not re-implemented:
  H6a  research.variants2._h6 gives sigma_hat, the one-day lag, the cap and w*(d) (called with band = 0 so that w equals w*),
       research.variants2.band_path gives the 0.10 no-trade band, restarted flat at FORWARD_START. C2 is research.variants.c2.
  H3a  research.variants2.h3a builds the 14:00 (d-1) -> 13:55 (d) trades for the scheduled FOMC days of fomc_forward.csv.
  Costs and P&L: research.data.load_costs (frozen stress / base, P_REF from the audit cache) and research.evaluate.score_*.

Forward guard: nothing is scored before FORWARD_START. 2026-01-01 .. 2026-10-05 is a locked holdout and earlier prices are only
signal inputs. The evaluator's own holdout switch has to be unlocked for any date from 2026-01-01 on, so that is done in exactly
two wrappers (_score_positions, _score_trades), each only after forward_guard has checked the window and every date it will score.

Usage (repo root):  python -m research.forward.track
Exit code: 0 on success, 1 on a HALT (live clock offset differs from the frozen clock; nothing is scored).
"""
import csv
import datetime as dt
import hashlib
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from audit.tz import ServerClock

from ..data import CLOCK_JSON, M1_DIR, Costs, Market, build_market, load_costs, load_m1
from ..evaluate import HoldoutError, Scored, score_positions, score_trades, summarise
from ..inference import nw_ols
from ..run_stages import md_table
from ..variants import HM, R_SIGNAL, c2
from ..variants2 import CAPS, KINDS, SIGMA_STAR, VOL_WINDOW, _h6, _prev_day, band_path, h3a, read_events
from . import FORWARD_START, SYMBOL
from .fomc import FOMC_FORWARD_CSV, SOURCE_HTML

OUT = Path(__file__).resolve().parent / "out"
LOOKBACK_DAYS = 90                      # M1 pulled from FORWARD_START - 90 calendar days (H6a needs 21 valid closes)
SPREAD_FLAG_PTS = 2.0                   # the frozen stress spread; a live quote above it is flagged
CHECKPOINT = {"H6a": 756, "H3a": 24}    # PLAN section 10: forward trading days / scheduled FOMC events
H3A_ENTRY, H3A_EXIT = HM(14), HM(13, 55)
H3_COLS = ["event_date_et", "entry_et", "entry_server", "exit_et", "exit_server", "entry_px", "exit_px", "gross_bp", "net_bp_stress",
           "net_bp_base", "status", "note"]
SNAPSHOT_COLS = ["run_utc", "last_bar_server", "live_offset_h", "clock_offset_h", "live_spread_pts", "h6a_w_next", "h6a_days_scored",
                 "h6a_cum_net_bp_stress", "c2_cum_net_bp", "h3a_scored", "h3a_cum_net_bp_stress", "next_fomc_entry_et"]
DESCRIPTIVE = "descriptive only, no decision before the checkpoint (PLAN §10)"


# ------------------------------------------------------------------ forward guard
class ForwardGuardError(HoldoutError):
    pass


def _stamps(x) -> pd.DatetimeIndex:
    if x is None:
        return pd.DatetimeIndex([])
    if isinstance(x, (pd.Timestamp, dt.datetime, dt.date, np.datetime64, str)):
        x = [x]
    idx = pd.DatetimeIndex(x)
    return idx[~idx.isna()]


def forward_guard(*dates, start: pd.Timestamp = FORWARD_START) -> None:
    """Raise if any date (Timestamp, Series, Index, list) is earlier than the forward start. Empty input and NaT are ignored."""
    for d in dates:
        x = _stamps(d)
        if len(x) and x.min() < start:
            raise ForwardGuardError(f"refusing to score {x.min()}: before the forward start {start.date()} "
                                    "(2026-01-01 to 2026-10-05 is a locked holdout; earlier prices are signal inputs only)")


def _score_positions(pos, days, costs, start, end, forward_start=FORWARD_START) -> Scored:
    forward_guard(start, end, pos.index, pos["next_day"], start=forward_start)
    return score_positions(pos, days, costs, start, end, unlock_holdout=True)      # unlocked only after the forward guard


def _score_trades(trades, days, costs, start, end, forward_start=FORWARD_START) -> Scored:
    forward_guard(start, end, trades["entry_et"], trades["exit_et"], start=forward_start)
    return score_trades(trades, days, costs, start, end, unlock_holdout=True)      # unlocked only after the forward guard


# ------------------------------------------------------------------ live checks
@dataclass(frozen=True)
class Live:
    tick_s: float            # last tick time_msc / 1000, server wall clock labelled as epoch seconds
    bid: float
    ask: float
    now_utc_s: float         # time.time() when the tick was read

    @property
    def offset_h(self) -> int:
        return int(round((self.tick_s - self.now_utc_s) / 3600))

    @property
    def spread_pts(self) -> float:
        return float(self.ask - self.bid)

    @property
    def spread_flag(self) -> bool:
        return round(self.spread_pts, 6) > SPREAD_FLAG_PTS


def clock_offset_h(clock: ServerClock, now_utc: pd.Timestamp) -> int:
    return int(clock.offset_hours(pd.DatetimeIndex([now_utc]))[0])


def tick_age_min(live: Live, clock_off: int) -> float:
    """Age of the last tick if the frozen clock is right. A large value means the market is closed, and the offset check is unreliable."""
    return (live.now_utc_s + clock_off * 3600 - live.tick_s) / 60


def halt_text(live: Live, clock_off: int, now_utc: pd.Timestamp) -> str:
    return (f"# HALT: clock offset mismatch\n\nRun {now_utc:%Y-%m-%d %H:%M:%S} UTC. **Nothing was scored and no output was updated.** "
            f"The live server offset is {live.offset_h:+d} h (last tick time_msc / 1000 - time.time(), rounded to hours) but the frozen "
            f"`server_clock.json` expects {clock_off:+d} h. Every New York timestamp derived from the bars would be wrong by "
            f"{abs(live.offset_h - clock_off)} h.\n\nIf the broker changed its server clock, re-run the audit clock measurement (task 4), log the change in "
            f"PLAN §8 and re-run the tracker. Under the frozen clock the last tick would be {tick_age_min(live, clock_off):.0f} min old: if that is "
            "large the market is closed (daily break or weekend) and the check cannot be evaluated, so run again while the market is open.\n\n"
            "The csv files in this folder are from the last successful run and are stale.\n")


# ------------------------------------------------------------------ small helpers
def _ts(t) -> str:
    return "" if pd.isna(t) else pd.Timestamp(t).strftime("%Y-%m-%d %H:%M")


def _num(x, nd=2) -> str:
    return "" if x is None or pd.isna(x) else f"{x:.{nd}f}"


def _server(clock: ServerClock, et) -> pd.Timestamp:
    return clock.et_to_server(pd.DatetimeIndex([et]))[0]


def _bday(d: pd.Timestamp, k: int) -> pd.Timestamp:
    return (pd.Timestamp(d) + pd.offsets.BDay(k)).as_unit("ns")


def closes_market(m: Market, last_bar_et: pd.Timestamp) -> Market:
    """The market for the daily closes. While the last ET day has not reached its 16:00 bar, P(16:00) would silently fall back to the
    close of an earlier minute (the frozen 5-minute rule), i.e. a close that does not exist yet, so that day's bars are left out."""
    day = last_bar_et.normalize()
    if last_bar_et >= day + HM(16):
        return m
    o, c = m.P
    return Market(o[o.index < day], c[c.index < day])


def _sigma_used(close: pd.Series) -> pd.Series:
    """sigma_hat(d-1) at each close d, shown next to w*(d). Display only: the weights come from the frozen _h6, and _check_frozen
    stops the run if this ever disagrees with them (variants2 has no stand-alone sigma function, so it is recomputed from its constants)."""
    r = close / close.shift(1) - 1
    return (r.rolling(VOL_WINDOW, min_periods=VOL_WINDOW).std(ddof=1) * np.sqrt(252)).shift(1)


def _check_frozen(w_star: pd.Series, sigma_used: pd.Series) -> None:
    with np.errstate(divide="ignore"):
        expect = np.minimum(CAPS["H6a"], SIGMA_STAR / sigma_used.to_numpy(float))
    if not np.allclose(w_star.to_numpy(float), expect, rtol=1e-12, atol=0, equal_nan=True):
        raise RuntimeError("the displayed sigma_hat disagrees with the frozen H6a target weights")


def _empty_skips() -> pd.DataFrame:
    return pd.DataFrame({"date": pd.DatetimeIndex([]).as_unit("ns"), "reason": pd.Series(dtype=object)})


def _trim(s: Scored, last: pd.Timestamp) -> Scored:
    return Scored(s.daily.loc[:last], s.units.loc[:last], 0, s.start, last)


# ------------------------------------------------------------------ H6a and C2
@dataclass
class H6Forward:
    daily: pd.DataFrame            # one row per forward valid close; the last row is the open position (no P&L yet)
    scored: Scored | None          # complete days only, None while there is none
    c2: Scored | None
    stats: dict
    open_position: dict | None
    nxt: dict


def next_weight(m: Market, w_star_fwd: np.ndarray, last_close, close_last: float, forward_start, clock) -> dict:
    """Weight for the next entry at C(N), N = next weekday after the last close (not before the forward start), and when it becomes known.

    w*(N) = min(cap, sigma* / sigma_hat(P)) with P = the weekday before N, so it needs C(P). It is read from the frozen _h6 on the market
    extended by one placeholder close at N: w*(N) cannot depend on C(N), which is what the frozen one-day lag guarantees."""
    n_day = max(pd.Timestamp(forward_start), _bday(last_close, 1)) if last_close is not None else pd.Timestamp(forward_start)
    p_day = _bday(n_day, -1)
    out = {"entry_et": n_day + HM(16), "exit_et": _bday(n_day, 1) + HM(16), "w_star": np.nan, "w": np.nan, "w_prev": np.nan,
           "known": False, "known_after_et": p_day + HM(16, 1), "note": ""}
    if last_close is None or p_day > last_close:
        out["note"] = f"It uses sigma_hat({p_day.date()}) (one-day lag), which needs C({p_day.date()})"
        return out
    o, c = m.P
    stamp = pd.DatetimeIndex([n_day + HM(16)]).as_unit("ns")
    ext = Market(pd.concat([o, pd.Series([close_last], index=stamp)]), pd.concat([c, pd.Series([close_last], index=stamp)]))
    w_star = float(_h6(ext, "H6a", band=0.0).pos.loc[n_day, "pos"])
    out["known_after_et"] = p_day + HM(16, 1)
    if np.isnan(w_star):
        out["note"] = "Fewer than 21 valid closes of history are available"
        return out
    path = band_path(np.r_[w_star_fwd, w_star])                     # the frozen band over the forward w* so far, then w*(N)
    w, w_prev = float(path[-1]), (float(path[-2]) if len(w_star_fwd) else 0.0)
    out.update(known=True, w_star=w_star, w=w, w_prev=w_prev,
               note=(f"w* = {w_star:.4f}, held w = {w_prev:.4f}: the 0.10 band {'moves' if w != w_prev else 'keeps'} the weight" if len(w_star_fwd)
                     else f"w* = {w_star:.4f}; first entry from flat, pays the entry cost at C({n_day.date()})"))
    return out


def h6a_forward(m: Market, costs: Costs, clock: ServerClock, forward_start=FORWARD_START) -> H6Forward:
    """H6a and C2 from the forward start. m must already be the daily-close market (see closes_market)."""
    frozen = _h6(m, "H6a", band=0.0).pos                      # all valid closes: pos = w*(d), NaN in the warm-up
    sigma = _sigma_used(frozen["close"])
    _check_frozen(frozen["pos"], sigma)
    fw = frozen[frozen.index >= forward_start].copy()
    forward_guard(fw.index, start=forward_start)
    w_star = fw["pos"].to_numpy(float)
    if np.isnan(w_star).any():
        raise RuntimeError("H6a target weight unavailable inside the forward window: not enough history was pulled")
    fw["w_star"] = w_star
    fw["pos"] = band_path(w_star)                            # the frozen band, flat before the first forward close
    cp = c2(m).pos
    cp = cp[cp.index >= forward_start].copy()
    n = len(fw)
    daily = pd.DataFrame({"date": [d.strftime("%Y-%m-%d") for d in fw.index], "close": fw["close"].to_numpy(),
                          "sigma_hat": sigma.reindex(fw.index).to_numpy(), "w_star": w_star, "w": fw["pos"].to_numpy(),
                          "return": (fw["next_close"] / fw["close"] - 1).to_numpy(), "net_bp_stress": np.nan, "net_bp_base": np.nan,
                          "c2_net_bp": np.nan}, index=fw.index)
    scored = c2s = None
    if n >= 2:
        last_scored = fw.index[-2]
        # the window ends at the open row, which therefore carries the evaluator's final-liquidation cost; it is dropped again below
        scored = _trim(_score_positions(fw, m.days, costs, forward_start, fw.index[-1], forward_start), last_scored)
        c2s = _trim(_score_positions(cp, m.days, costs, forward_start, cp.index[-1], forward_start), last_scored)
        daily.loc[:last_scored, "net_bp_stress"] = scored.daily["stress"].reindex(fw.index[:-1]).to_numpy()
        daily.loc[:last_scored, "net_bp_base"] = scored.daily["base"].reindex(fw.index[:-1]).to_numpy()
        daily.loc[:last_scored, "c2_net_bp"] = c2s.daily["stress"].reindex(fw.index[:-1]).to_numpy()
    opn = None
    if n:
        r = fw.iloc[-1]
        prev_w = float(fw["pos"].iloc[-2]) if n >= 2 else 0.0
        opn = {"entry_et": fw.index[-1] + HM(16), "w": float(r["pos"]), "w_star": float(r["w_star"]), "w_prev": prev_w,
               "close": float(r["close"]), "exit_et": _bday(fw.index[-1], 1) + HM(16)}
    last_close = frozen.index[-1] if len(frozen) else None
    nxt = next_weight(m, w_star, last_close, float(frozen["close"].iloc[-1]) if len(frozen) else np.nan, forward_start, clock)
    stats = describe_h6(scored, c2s, fw.iloc[:-1]["pos"] if n >= 1 else fw["pos"], costs)
    return H6Forward(daily, scored, c2s, stats, opn, nxt)


def describe_h6(s: Scored | None, c2s: Scored | None, w_scored: pd.Series, costs: Costs) -> dict:
    """Interim descriptive statistics over the complete forward days; empty dict while there is no complete day."""
    if s is None or c2s is None or len(s.daily) == 0:
        return {}
    y, x = s.daily["stress"], c2s.daily["stress"]
    a, b = summarise(s, _empty_skips())[0], summarise(c2s, _empty_skips())[0]
    fit = nw_ols(y.to_numpy(), x.to_numpy(), lags=5)
    q = w_scored.to_numpy(float)
    return {"days": len(y), "cum_stress": float(y.sum()), "cum_base": float(s.daily["base"].sum()), "c2_cum": float(x.sum()),
            "mean_day": float(y.mean()), "c2_mean_day": float(x.mean()), "t": a["t_stress"], "sharpe": a["sharpe_stress"],
            "c2_sharpe": b["sharpe_stress"], "max_dd": a["max_dd_stress_bp"], "alpha": fit["alpha"], "alpha_t": fit["alpha_t"],
            "beta": fit["beta"], "avg_w": float(q.mean()), "turnover": float(np.abs(np.diff(np.r_[0.0, q])).sum())}


# ------------------------------------------------------------------ H3a
@dataclass
class H3Forward:
    trades: pd.DataFrame           # one row per forward FOMC event: scored, planned or skipped
    scored: Scored | None
    stats: dict
    excluded: list                 # events whose d-1 is before the forward start (not part of the forward test)
    window_end: pd.Timestamp | None


def _fomc_dates(ev: pd.DataFrame, forward_start) -> pd.DatetimeIndex:
    sel = ev["event"].isin(KINDS["H3a"]) & ev["scheduled"] & (ev["date"] >= forward_start)
    return pd.DatetimeIndex(ev.loc[sel, "date"]).as_unit("ns").unique().sort_values()


def h3a_forward(m: Market, ev: pd.DataFrame, costs: Costs, clock: ServerClock, last_bar_et: pd.Timestamp,
                forward_start=FORWARD_START) -> H3Forward:
    """Scored when both P(14:00, d-1) and P(13:55, d) are observed; planned while the exit is still in the future."""
    dates = _fomc_dates(ev, forward_start)
    res = h3a(m, ev[ev["date"] >= forward_start]) if len(dates) else None   # frozen builder: trades whose two prices exist, market range only
    priced = {} if res is None else {pd.Timestamp(r.exit_et).normalize(): r for r in res.trades.itertuples()}
    skip_reason = {} if res is None else {pd.Timestamp(r.date): r.reason for r in res.skips.itertuples()}
    rows, excluded, scored_days, scored_entry, in_flight = [], [], [], [], []
    for d in dates:
        in_data = d in m.days
        prev = _prev_day(m, pd.DatetimeIndex([d]))[0] if in_data else _bday(d, -1)
        if pd.notna(prev) and prev < forward_start:
            excluded.append(d)
            continue
        entry = (prev if pd.notna(prev) else d) + H3A_ENTRY
        exit_ = d + H3A_EXIT
        row = dict.fromkeys(H3_COLS, np.nan) | {"event_date_et": d.strftime("%Y-%m-%d"), "entry_et": _ts(entry), "entry_server": _ts(_server(clock, entry)),
                                                 "exit_et": _ts(exit_), "exit_server": _ts(_server(clock, exit_)), "status": "", "note": ""}
        if exit_ > last_bar_et:                                   # the exit price cannot be observed yet (this also blocks the 5-minute fallback)
            flight = entry <= last_bar_et
            row.update(status="planned", note="entered, exit pending" if flight else "" if in_data else "d-1 assumed to be the previous weekday")
            if flight:
                in_flight.append(prev)
        elif d in priced:
            row.update(status="scored", entry_px=priced[d].entry_px, exit_px=priced[d].exit_px)
            scored_days.append(d)
            scored_entry.append(prev)
        else:
            row.update(status="skipped", note=skip_reason.get(d, R_SIGNAL))
        rows.append(row)
    table = pd.DataFrame(rows, columns=H3_COLS)
    done = m.days[(m.days + HM(16)) <= last_bar_et]               # complete ET days only
    end = done.max() if len(done) else pd.NaT
    if in_flight:                                                 # a trade that is still open is not a complete day
        before = m.days[m.days < min(in_flight)]
        end = min(end, before.max()) if len(before) and pd.notna(end) else pd.NaT
    scored = None
    if scored_days and pd.notna(end) and end >= forward_start:
        tr = res.trades[res.trades["exit_et"].dt.normalize().isin(pd.DatetimeIndex(scored_days))]
        scored = _score_trades(tr, m.days, costs, forward_start, end, forward_start)
        sel, key = table["status"] == "scored", pd.DatetimeIndex(scored_entry).as_unit("ns")
        for col, src in (("gross_bp", "gross"), ("net_bp_stress", "stress"), ("net_bp_base", "base")):
            table.loc[sel, col] = scored.units[src].reindex(key).to_numpy()
    stats = {}
    if scored is not None and len(scored.daily):
        row = summarise(scored, _empty_skips())[0]
        stats = {"events": len(scored.units), "days": len(scored.daily), "mean_event": row["net_stress_mean_bp"],
                 "mean_event_base": row["net_base_mean_bp"], "gross_mean": row["gross_mean_bp"], "t": row["t_stress"],
                 "hit_rate": row["hit_rate_stress"], "cum_stress": row["total_net_stress_bp"], "cum_base": float(scored.daily["base"].sum())}
    return H3Forward(table, scored, stats, excluded, end if pd.notna(end) else None)


# ------------------------------------------------------------------ one run
@dataclass
class Report:
    status: str
    h6: H6Forward
    h3: H3Forward
    upcoming: pd.DataFrame
    next_fomc_entry_et: str


def build_upcoming(h6: H6Forward, h3: H3Forward, clock: ServerClock, last_bar_et: pd.Timestamp) -> pd.DataFrame:
    cols = ["item", "date_et", "entry_et", "entry_server", "exit_et", "exit_server", "value", "known_after_et", "known_after_server", "note"]
    rows = []
    if h6.open_position is not None:
        o = h6.open_position
        rows.append({"item": "H6a_open_position", "date_et": o["entry_et"].strftime("%Y-%m-%d"), "entry_et": _ts(o["entry_et"]),
                     "entry_server": _ts(_server(clock, o["entry_et"])), "exit_et": _ts(o["exit_et"]), "exit_server": _ts(_server(clock, o["exit_et"])),
                     "value": o["w"], "note": f"current exposure w = {o['w']:.4f} (w* {o['w_star']:.4f}), entered at C, not scored until the next close"})
    n = h6.nxt
    rows.append({"item": "H6a_next_weight", "date_et": n["entry_et"].strftime("%Y-%m-%d"), "entry_et": _ts(n["entry_et"]),
                 "entry_server": _ts(_server(clock, n["entry_et"])), "exit_et": _ts(n["exit_et"]), "exit_server": _ts(_server(clock, n["exit_et"])),
                 "value": n["w"] if n["known"] else np.nan, "known_after_et": _ts(n["known_after_et"]),
                 "known_after_server": _ts(_server(clock, n["known_after_et"])),
                 "note": ("known now: " if n["known"] else "") + n["note"]})
    for r in h3.trades[h3.trades["status"] == "planned"].itertuples():
        rows.append({"item": "H3a_trade", "date_et": r.event_date_et, "entry_et": r.entry_et, "entry_server": r.entry_server,
                     "exit_et": r.exit_et, "exit_server": r.exit_server, "note": r.note or "planned"})
    return pd.DataFrame(rows, columns=cols)


def next_fomc_entry(h3: H3Forward, last_bar_et: pd.Timestamp) -> str:
    pl = h3.trades[(h3.trades["status"] == "planned")] if len(h3.trades) else h3.trades
    nxt = [e for e in pl["entry_et"] if pd.Timestamp(e) > last_bar_et] if len(pl) else []
    return nxt[0] if nxt else ""


def compute_report(m: Market, costs: Costs, ev: pd.DataFrame, clock: ServerClock, last_bar_et: pd.Timestamp, forward_start=FORWARD_START) -> Report:
    """Everything the tracker reports, from an ET-indexed Market of complete bars and the last complete bar's ET stamp."""
    mc = closes_market(m, last_bar_et)
    if not len(mc.days):
        raise RuntimeError("no complete trading day in the pulled bars")
    h6 = h6a_forward(mc, costs, clock, forward_start)
    h3 = h3a_forward(m, ev, costs, clock, last_bar_et, forward_start)
    status = "RUNNING" if len(h6.daily) else "PRE-WINDOW"
    return Report(status, h6, h3, build_upcoming(h6, h3, clock, last_bar_et), next_fomc_entry(h3, last_bar_et))


def guard_outputs(rep: Report, forward_start=FORWARD_START) -> None:
    """Last line of defence: every date that is about to be written is on or after the forward start."""
    forward_guard(pd.to_datetime(rep.h6.daily["date"]), pd.to_datetime(rep.h3.trades["entry_et"]), pd.to_datetime(rep.h3.trades["exit_et"]),
                  pd.to_datetime(rep.upcoming["entry_et"]), start=forward_start)


# ------------------------------------------------------------------ writing
def append_snapshot(path: Path, row: dict) -> None:
    """Append one row; the header is written once and an existing file is never rewritten."""
    path = Path(path)
    exists = path.exists() and path.stat().st_size > 0
    if exists:
        with path.open(encoding="utf-8", newline="") as f:
            head = next(csv.reader(f))
        if head != SNAPSHOT_COLS:
            raise RuntimeError(f"{path.name} has columns {head}, expected {SNAPSHOT_COLS}; refusing to touch it")
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        if not exists:
            w.writerow(SNAPSHOT_COLS)
        w.writerow([row[c] for c in SNAPSHOT_COLS])


def snapshot_row(rep: Report, live: Live, clock_off: int, now_utc: pd.Timestamp, last_bar_server: pd.Timestamp) -> dict:
    s6, s3 = rep.h6.stats, rep.h3.stats
    w = rep.h6.nxt["w"] if rep.h6.nxt["known"] else ""
    return {"run_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"), "last_bar_server": last_bar_server.strftime("%Y-%m-%d %H:%M:%S"),
            "live_offset_h": live.offset_h, "clock_offset_h": clock_off, "live_spread_pts": f"{live.spread_pts:.4f}",
            "h6a_w_next": "" if w == "" else f"{w:.6f}", "h6a_days_scored": s6.get("days", 0),
            "h6a_cum_net_bp_stress": f"{s6.get('cum_stress', 0.0):.6f}", "c2_cum_net_bp": f"{s6.get('c2_cum', 0.0):.6f}",
            "h3a_scored": s3.get("events", 0), "h3a_cum_net_bp_stress": f"{s3.get('cum_stress', 0.0):.6f}",
            "next_fomc_entry_et": rep.next_fomc_entry_et}


def render_md(rep: Report, live: Live, clock_off: int, clock: ServerClock, costs: Costs, now_utc: pd.Timestamp, last_bar_server: pd.Timestamp,
              last_bar_et: pd.Timestamp, n_bars: int, diag: dict, forward_start=FORWARD_START) -> str:
    h6, h3 = rep.h6, rep.h3
    now_et = now_utc.tz_localize("UTC").tz_convert("America/New_York")
    s6, s3 = h6.stats, h3.stats
    n6, n3 = s6.get("days", 0), s3.get("events", 0)
    skipped = int((h3.trades["status"] == "skipped").sum()) if len(h3.trades) else 0
    planned = int((h3.trades["status"] == "planned").sum()) if len(h3.trades) else 0
    L = [f"# Forward paper-tracker: H6a and H3a (research/PLAN.md §10)\n",
         f"**STATUS: {rep.status}**" + (f" (the forward window starts {forward_start.date()}; entries on or after that New York trading day)"
                                        if rep.status == "PRE-WINDOW" else f" (forward window from {forward_start.date()})"),
         "\nPaper only: nothing is traded and no order function is ever called. Rules, costs and the P&L convention are the frozen ones "
         "(§9, §1); no interim decisions and no early stopping (§10). Nothing is computed for 2026-01-01 to 2026-10-05, a locked holdout.\n",
         f"Run {now_utc:%Y-%m-%d %H:%M:%S} UTC ({now_et:%Y-%m-%d %H:%M} New York). Bars are complete through {last_bar_et:%Y-%m-%d %H:%M} ET "
         f"({last_bar_server:%Y-%m-%d %H:%M} server). Costs: stress {costs.stress_pts:.2f} pts = {costs.stress_bp:.3f} bp per round trip (primary), "
         f"base {costs.base_pts:.2f} pts = {costs.base_bp:.3f} bp; P_REF {costs.p_ref:,.1f}.\n",
         "## Checkpoint progress\n",
         md_table(pd.DataFrame({"variant": ["H6a", "H3a"],
                                "progress": [f"{n6} / {CHECKPOINT['H6a']} forward trading days ({100 * n6 / CHECKPOINT['H6a']:.1f}%)",
                                             f"{n3} / {CHECKPOINT['H3a']} scheduled FOMC events scored ({100 * n3 / CHECKPOINT['H3a']:.1f}%); "
                                             f"{skipped} skipped, {planned} planned"],
                                "rule at the checkpoint (§10)": ["alpha vs C2 > 0 with Newey-West(5) t >= 2.0, and Sharpe(H6a) > Sharpe(C2)",
                                                                 "forward net-stress mean > 0 and forward t >= 2.0 (daily series)"]})),
         "## H6a (volatility-managed long, cap 2.0, band 0.10) and C2 (buy and hold)\n"]
    o, n = h6.open_position, h6.nxt
    if o:
        L.append(f"**Current exposure (open position, not scored):** w = {o['w']:.4f} of capital, long USTEC., entered at C({o['entry_et']:%Y-%m-%d}) "
                 f"= {o['close']:,.2f} (w* {o['w_star']:.4f}, previous w {o['w_prev']:.4f}). It is held to the next close, "
                 f"{o['exit_et']:%Y-%m-%d} 16:00 ET, and is scored then. No liquidation cost is charged in interim reports.\n")
    else:
        L.append("**Current exposure:** flat. Positions start flat; the first entry is at "
                 f"C({n['entry_et']:%Y-%m-%d}) = {n['entry_et']:%Y-%m-%d} 16:00 ET ({_ts(_server(clock, n['entry_et']))} server) and pays the entry cost then.\n")
    ka = (f"{n['known_after_et']:%Y-%m-%d} 16:00 ET close (the first complete 16:00 bar is there at {n['known_after_et']:%H:%M} ET = "
          f"{_ts(_server(clock, n['known_after_et']))} server)")
    when = f"C({n['entry_et']:%Y-%m-%d}) = {n['entry_et']:%Y-%m-%d} 16:00 ET ({_ts(_server(clock, n['entry_et']))} server)"
    if n["known"]:
        L.append(f"**Next weight:** w for the entry at {when} is known now (it became known after the {ka}): {n['note']}; **w = {n['w']:.4f}**.\n")
    else:
        L.append(f"**Next weight:** w for the entry at {when} is **not known yet**. {n['note']}, so it becomes known after the {ka}.\n")
    L.append(f"### Interim statistics ({DESCRIPTIVE})\n")
    if s6:
        L.append(md_table(pd.DataFrame({"statistic": ["complete forward days", "cumulative net bp, H6a stress (primary)", "cumulative net bp, H6a base",
                                                      "cumulative net bp, C2 stress", "mean net bp per day, H6a / C2 (stress)",
                                                      "t (daily series, stress), H6a", "Sharpe (annualised, stress), H6a / C2",
                                                      "alpha vs C2, bp per day (NW5 t)", "beta vs C2", "max drawdown bp (stress), H6a",
                                                      "average w / turnover (sum of absolute changes in w)"],
                                        "value": [str(n6), _num(s6["cum_stress"]), _num(s6["cum_base"]), _num(s6["c2_cum"]),
                                                  f"{_num(s6['mean_day'])} / {_num(s6['c2_mean_day'])}", _num(s6["t"]),
                                                  f"{_num(s6['sharpe'])} / {_num(s6['c2_sharpe'])}",
                                                  "n/a (needs > 7 days)" if pd.isna(s6["alpha"]) else f"{_num(s6['alpha'])} ({_num(s6['alpha_t'])})",
                                                  _num(s6["beta"], 3), _num(s6["max_dd"]), f"{_num(s6['avg_w'], 3)} / {_num(s6['turnover'], 3)}"]})))
    else:
        L.append("No complete forward day yet: a day is scored once the next close exists, so there is no H6a or C2 statistic. "
                 "The day's P&L, including the entry cost, is booked on the entry day.\n")
    d = h6.daily
    if len(d):
        t = d.tail(10).copy()
        t = pd.DataFrame({"date": t["date"], "close": t["close"].map(lambda v: f"{v:,.2f}"), "sigma_hat": t["sigma_hat"].map(lambda v: _num(v, 3)),
                          "w*": t["w_star"].map(lambda v: _num(v, 3)), "w": t["w"].map(lambda v: _num(v, 3)),
                          "return bp": (t["return"] * 1e4).map(lambda v: _num(v)), "net stress bp": t["net_bp_stress"].map(_num),
                          "net base bp": t["net_bp_base"].map(_num), "C2 net bp": t["c2_net_bp"].map(_num)})
        L.append(f"\nLast {len(t)} forward rows (sigma_hat is the lagged value used for that row's w*; blank P&L = the open position):\n\n" + md_table(t))
    L.append("\n## H3a (pre-FOMC drift: long P(14:00, d-1) to P(13:55, d), scheduled FOMC days)\n")
    t = h3.trades
    if len(t):
        show = pd.DataFrame({"event date": t["event_date_et"], "entry ET": t["entry_et"], "entry server": t["entry_server"],
                             "exit ET": t["exit_et"], "exit server": t["exit_server"], "net stress bp": t["net_bp_stress"].map(_num),
                             "status": t["status"] + t["note"].map(lambda s: f" ({s})" if s else "")})
        L.append(md_table(show))
    else:
        L.append("No scheduled FOMC event on or after the forward start in `research/data/fomc_forward.csv`.\n")
    if h3.excluded:
        L.append("\nExcluded (the previous trading day is before the forward start): " + ", ".join(str(x.date()) for x in h3.excluded) + ".\n")
    L.append(f"\n### Interim statistics ({DESCRIPTIVE})\n")
    if s3:
        L.append(md_table(pd.DataFrame({"statistic": ["scored events", "daily-series days in the forward window", "mean net bp per event, stress / base",
                                                      "mean gross bp per event", "hit rate (stress)", "cumulative net bp (stress)", "t (daily series, stress)"],
                                        "value": [str(s3["events"]), str(s3["days"]), f"{_num(s3['mean_event'])} / {_num(s3['mean_event_base'])}",
                                                  _num(s3["gross_mean"]), _num(s3["hit_rate"], 2), _num(s3["cum_stress"]), _num(s3["t"])]})))
    else:
        L.append("No scored event yet. A trade is scored once both prices are observed; until then it stays planned. Exit times are "
                 "listed in New York and in server time, so the run after the exit can be timed.\n")
    L.append("\n## Live diagnostics\n")
    age = tick_age_min(live, clock_off)
    L.append(md_table(pd.DataFrame({"check": ["live server offset (round((last tick time_msc / 1000 - time.time()) / 3600))",
                                              "frozen clock offset at run time (server_clock.json)", "offset check",
                                              "last tick (server time) / age under the frozen clock",
                                              "live spread (ask - bid)", "bars pulled", "pull vs audit cache (read-only overlap check)",
                                              "FOMC calendar page sha256 (saved 2026-10-05) / fomc_forward.csv sha256"],
                                    "value": [f"{live.offset_h:+d} h", f"{clock_off:+d} h", "OK" if live.offset_h == clock_off else "MISMATCH",
                                              f"{pd.Timestamp(live.tick_s, unit='s'):%Y-%m-%d %H:%M:%S} / {age:.1f} min"
                                              + (" (stale: market closed or a daily break)" if abs(age) > 30 else ""),
                                              f"{live.spread_pts:.2f} pts = {live.spread_pts / ((live.bid + live.ask) / 2) * 1e4:.2f} bp of the price"
                                              + (f" **FLAG: above the {SPREAD_FLAG_PTS:.1f} pt frozen stress spread**" if live.spread_flag
                                                 else f" (not above the {SPREAD_FLAG_PTS:.1f} pt frozen stress spread)"),
                                              str(n_bars), diag.get("cache", "n/a"), diag.get("sha", "n/a")]})))
    L.append("\n## Conventions\n")
    L.append("- H6a w*(d) = min(2.0, 0.20 / sigma_hat(d-1)) with the frozen sigma_hat (20 returns, ddof 1, x sqrt(252)); w moves to w* only when |w* - w| >= 0.10; "
             "it starts at 0 at the forward start and each unit change costs half a round trip. P&L of the position entered at C(d) is booked on d and scored "
             "once C(next day) exists. C2 is long 1 from the first forward close and pays half a round trip on entry.\n"
             "- H3a: P(T) is the open of the bar stamped T, else the close of the last bar stamped at most 5 minutes earlier (never past the last complete bar); "
             "a missing price skips the trade, it is never filled. d-1 is the previous trading day in the bars, or the previous weekday while d is in the future.\n"
             "- The daily series for t and Sharpe covers every complete trading day from the forward start (0 when nothing is held); Sharpe uses sqrt(252).\n"
             "- Power warning (§10): at the validation effect sizes both checkpoints would most likely miss even if the effects are real.\n")
    return "\n".join(L).replace("\n\n\n", "\n\n")


def write_outputs(out: Path, rep: Report, md: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    fmt = dict(index=False, float_format="%.8g", lineterminator="\n", encoding="utf-8")
    rep.h6.daily.to_csv(out / "h6a_daily.csv", **fmt)
    rep.h3.trades.to_csv(out / "h3a_trades.csv", **fmt)
    rep.upcoming.to_csv(out / "upcoming.csv", **fmt)
    (out / "FORWARD.md").write_text(md, encoding="utf-8", newline="\n")


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def run_once(bars: pd.DataFrame, live: Live, costs: Costs, clock: ServerClock, events: pd.DataFrame, out: Path = OUT,
             now_utc: pd.Timestamp | None = None, forward_start=FORWARD_START, diag: dict | None = None) -> int:
    """One stateless run on complete-or-forming M1 bars (server-time epoch seconds). Returns the exit code (1 = HALT, nothing scored)."""
    now_utc = pd.Timestamp(live.now_utc_s, unit="s").as_unit("ns") if now_utc is None else now_utc
    clock_off = clock_offset_h(clock, now_utc)
    out = Path(out)
    if live.offset_h != clock_off:
        out.mkdir(parents=True, exist_ok=True)
        (out / "FORWARD.md").write_text(halt_text(live, clock_off, now_utc), encoding="utf-8", newline="\n")
        return 1
    bars = bars[bars["time"] + 60 <= int(live.tick_s)].sort_values("time").drop_duplicates("time")   # drop the still-forming bar
    if bars.empty:
        raise RuntimeError("no complete M1 bar was pulled")
    last_server = pd.Timestamp(int(bars["time"].iloc[-1]), unit="s").as_unit("ns")
    last_et = clock.to_et(pd.DatetimeIndex([last_server]))[0]
    market = build_market(bars, clock, before=None)           # forward bars are needed; the guard keeps pre-start dates unscored
    rep = compute_report(market, costs, events, clock, last_et, forward_start)
    guard_outputs(rep, forward_start)
    md = render_md(rep, live, clock_off, clock, costs, now_utc, last_server, last_et, len(bars), diag or {}, forward_start)
    write_outputs(out, rep, md)
    append_snapshot(out / "snapshots.csv", snapshot_row(rep, live, clock_off, now_utc, last_server))
    return 0


# ------------------------------------------------------------------ MT5 (read-only) and the entry point
def cache_overlap(bars: pd.DataFrame, m1_dir: Path = M1_DIR) -> str:
    """Read-only comparison of the fresh pull with the audit cache where they overlap (diagnostic only, never writes)."""
    try:
        files = sorted(Path(m1_dir).glob("*.parquet"))
        t0, t1 = int(bars["time"].min()), int(bars["time"].max())
        cache = pd.concat([pd.read_parquet(f, columns=["time", "open", "close"]) for f in files[-4:]], ignore_index=True)
        cache = cache[(cache["time"] >= t0) & (cache["time"] <= min(t1, int(cache["time"].max())))]
        j = cache.merge(bars[["time", "open", "close"]], on="time", how="left", suffixes=("", "_pull"))
        missing = int(j["open_pull"].isna().sum())
        diff = int(((j["open"] - j["open_pull"]).abs() > 1e-9).sum() + ((j["close"] - j["close_pull"]).abs() > 1e-9).sum())
        return f"{len(j) - missing} of {len(j)} cache bars in the overlap are in the pull; {missing} missing from the pull; {diff} open/close differences"
    except Exception as e:                                     # a diagnostic must never stop a run
        return f"not available ({type(e).__name__})"


def read_live(sym: str) -> Live:
    import MetaTrader5 as mt5
    tick = mt5.symbol_info_tick(sym)
    if tick is None:
        raise SystemExit(f"STOP: no tick for {sym}: {mt5.last_error()}")
    return Live(tick.time_msc / 1000.0, float(tick.bid), float(tick.ask), time.time())


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    from audit import mt5io as io                                 # read-only layer: connect, select_symbol, rates_chunk, ticks
    import MetaTrader5 as mt5
    clock = ServerClock.load(CLOCK_JSON)
    io.connect()                                                  # initialize + account presence; login, name and balance are never read or printed
    try:
        io.select_symbol(SYMBOL)
        if mt5.symbol_info(SYMBOL) is None:
            raise SystemExit(f"STOP: symbol_info({SYMBOL}) is None")
        live = read_live(SYMBOL)
        now_utc = pd.Timestamp(live.now_utc_s, unit="s").as_unit("ns")
        print(f"live offset {live.offset_h:+d} h, frozen clock {clock_offset_h(clock, now_utc):+d} h, live spread {live.spread_pts:.2f} pts"
              + (" FLAG" if live.spread_flag else ""))
        bars = None
        if live.offset_h == clock_offset_h(clock, now_utc):
            start = (FORWARD_START - pd.Timedelta(days=LOOKBACK_DAYS)).to_pydatetime()          # server-clock label, as in the audit
            end = dt.datetime.fromtimestamp(live.tick_s, dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(days=2)
            bars = io.rates_chunk(SYMBOL, "M1", start, end)
    finally:
        mt5.shutdown()
    costs = load_costs(load_m1())                                 # frozen P_REF from the audit cache (read-only); the fresh pull never enters it
    events = read_events(FOMC_FORWARD_CSV)
    if events.empty:
        raise SystemExit("STOP: research/data/fomc_forward.csv is missing or empty; run python -m research.forward.fomc")
    diag = {"cache": cache_overlap(bars) if bars is not None else "n/a", "sha": f"{sha256(SOURCE_HTML)} / {sha256(FOMC_FORWARD_CSV)}"}
    code = run_once(bars if bars is not None else pd.DataFrame({"time": []}), live, costs, clock, events, OUT, now_utc, FORWARD_START, diag)
    if code:
        print("HALT: live clock offset differs from server_clock.json; nothing was scored (see research/forward/out/FORWARD.md)")
    else:
        print("wrote research/forward/out (FORWARD.md, h6a_daily.csv, h3a_trades.csv, upcoming.csv) and appended snapshots.csv")
    return code


if __name__ == "__main__":
    sys.exit(main())
