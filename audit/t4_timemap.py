"""Task 4: server time <-> UTC <-> New York, measured.

Method: for every trading day find where the New York cash open (09:30 ET) shows up in server time as a persistent
step in 1-minute range (mean range of the next 10 minutes / previous 10 minutes), testing the hypotheses
"server = UTC + h" for h in -2..4. The weekly median step decides h for that week. The 08:30 ET data-release
spike is detected independently and must sit 60 minutes before the open. Weekly offsets are then compared with
candidate conventions (UTC fixed, London, ET+5, NY-close ET+7, EET, ...) and segmented into eras (Viterbi with a
switching penalty). Mismatch weeks (US and EU DST differ) separate the US-linked from the EU-linked clocks.
"""
import email.utils
import logging
import urllib.request
import warnings
from datetime import datetime, timezone

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

from . import config as C
from . import tz

log = logging.getLogger("audit")
H_CAND = np.arange(-2, 5)
CANDIDATES = {
    "UTC fixed (UTC+0)": ("fixed", 0),
    "London (UTC+0/+1, EU DST)": ("eu", 0),
    "ET+5 (UTC+0/+1, US DST)": ("ny", 5),
    "Fixed UTC+1": ("fixed", 1),
    "EET (UTC+2/+3, EU DST)": ("eu", 2),
    "NY-close ET+7 (UTC+2/+3, US DST)": ("ny", 7),
    "Fixed UTC+2": ("fixed", 2),
    "Fixed UTC+3": ("fixed", 3),
}
SWITCH_PENALTY = 8        # weeks of disagreement that justify a new era


# ------------------------------------------------------------------ live offset
def pc_clock_skew() -> float | None:
    """PC clock minus an HTTP Date header, seconds (1 s resolution). None if the check could not run."""
    try:
        req = urllib.request.Request("https://www.google.com", method="HEAD")
        with urllib.request.urlopen(req, timeout=10) as r:
            remote = email.utils.parsedate_to_datetime(r.headers["Date"])
        return (datetime.now(timezone.utc) - remote).total_seconds()
    except Exception as e:           # noqa: BLE001 - network is optional here
        log.warning("PC clock check unavailable: %s", e)
        return None


def live_offset(sym: str) -> dict:
    tk = mt5.symbol_info_tick(sym)
    utc_now = datetime.now(timezone.utc).timestamp()
    raw = tk.time_msc / 1000 - utc_now
    hours = round(raw / 3600)
    resid = raw - hours * 3600
    return {"tick_server_minus_utc_s": round(raw, 2), "offset_hours": hours, "residual_s": round(resid, 2),
            "market_live": bool(abs(resid) < 120), "pc_clock_skew_s": pc_clock_skew()}


# ------------------------------------------------------------------ per-day matrices
def _matrix(m1: pd.DataFrame, values: np.ndarray):
    t = m1["time"].to_numpy()
    day, mod = t // 86400, (t % 86400) // 60
    d0 = day.min()
    a = np.full((day.max() - d0 + 1, 1440), np.nan)
    a[day - d0, mod] = values
    return a, d0


def _win(a: np.ndarray, n: int, forward: bool) -> np.ndarray:
    """Mean over [m, m+n) (forward) or [m-n, m) (backward); NaN unless >= 80% of the window has data."""
    ok = ~np.isnan(a)
    cz = np.cumsum(np.pad(np.where(ok, a, 0.0), ((0, 0), (1, 0))), axis=1)
    cc = np.cumsum(np.pad(ok.astype(float), ((0, 0), (1, 0))), axis=1)
    i = np.arange(1440)
    lo, hi = (i, np.minimum(i + n, 1440)) if forward else (np.maximum(i - n, 0), i)
    cnt = cc[:, hi] - cc[:, lo]
    return np.where(cnt >= 0.8 * n, (cz[:, hi] - cz[:, lo]) / np.maximum(cnt, 1), np.nan)


def _utc_minute_of_day(dates: pd.DatetimeIndex, hh: int, mm: int) -> np.ndarray:
    local = (dates + pd.Timedelta(hours=hh, minutes=mm)).tz_localize(C.ET, ambiguous=False, nonexistent="shift_forward")
    u = local.tz_convert("UTC")
    return (u.hour * 60 + u.minute).to_numpy()


# ------------------------------------------------------------------ weekly detection
def weekly_detection(m1: pd.DataFrame) -> pd.DataFrame:
    rng, d0 = _matrix(m1, (m1["high"] - m1["low"]).to_numpy())
    step = _win(rng, 10, True) / _win(rng, 10, False)
    spike = rng / _win(rng, 30, False)
    n_days = rng.shape[0]
    dates = pd.DatetimeIndex(pd.to_datetime((d0 + np.arange(n_days)) * 86400, unit="s")).as_unit("ns")
    weekday = dates.dayofweek.to_numpy()
    present = (~np.isnan(rng[:, 12 * 60:18 * 60])).sum(axis=1)
    use = (weekday < 5) & (present >= 240)
    open_utc = _utc_minute_of_day(dates, 9, 30)

    cand_min = open_utc[:, None] + 60 * H_CAND[None, :]                      # [days, hypotheses]
    s_open = np.take_along_axis(step, cand_min, axis=1)
    win = np.arange(1440)
    in_win = (win >= 12 * 60) & (win < 18 * 60)
    free_min = np.where(np.isnan(step) | ~in_win, -1.0, step).argmax(axis=1)  # unconstrained argmax, for reference

    rows = []
    week = (dates - pd.to_timedelta(weekday, unit="D")).to_numpy()
    for w in np.unique(week[use]):
        d = np.flatnonzero(use & (week == w))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)       # hypotheses with no data in the week
            med = np.nanmedian(s_open[d], axis=0)
        if np.isnan(med).all():
            continue
        order = np.argsort(-np.nan_to_num(med, nan=-1))
        best_h = int(H_CAND[order[0]])
        margin = med[order[0]] / med[order[1]] if med[order[1]] > 0 else np.inf
        open_m = int(cand_min[d[0], order[0]])
        modal = pd.Series(free_min[d]).mode().iloc[0]
        agree = int((free_min[d] == modal).sum())
        # release spike: strongest summed spike inside [open-150, open-30] minutes
        lo, hi = max(open_m - 150, 0), open_m - 30
        sp = np.nansum(np.where(np.isnan(spike[d][:, lo:hi]), 0, spike[d][:, lo:hi]), axis=0)
        rel_m = lo + int(sp.argmax())
        rows.append({"week": pd.Timestamp(w), "n_days": len(d), "obs_offset_h": best_h, "margin": round(float(margin), 2),
                     "open_hhmm": f"{open_m // 60:02d}:{open_m % 60:02d}", "free_modal_hhmm": f"{modal // 60:02d}:{modal % 60:02d}",
                     "free_agree_days": agree, "release_hhmm": f"{rel_m // 60:02d}:{rel_m % 60:02d}",
                     "release_minus_open_min": rel_m - open_m, "release_spike_sum": round(float(sp.max()), 1)})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ candidate comparison and eras
def predicted_offsets(weeks: pd.Series) -> pd.DataFrame:
    """Offset each candidate convention predicts for every week (evaluated Wednesday 12:00 UTC)."""
    mid = pd.DatetimeIndex(weeks + pd.Timedelta(days=2, hours=12)).as_unit("ns")
    return pd.DataFrame({name: tz.ServerClock([("1900-01-01", k, p)]).offset_hours(mid) for name, (k, p) in CANDIDATES.items()},
                        index=weeks.index)


def segment_eras(obs: np.ndarray, pred: np.ndarray, informative: np.ndarray) -> list[tuple[int, int]]:
    """Viterbi over candidate states; cost 1 per week the state's prediction disagrees with the observation.
    Returns [(first_week_index, state_index), ...]."""
    n, k = pred.shape
    cost = ((pred != obs[:, None]) & informative[:, None]).astype(float)
    best = np.zeros((n, k))
    back = np.zeros((n, k), dtype=int)
    best[0] = cost[0]
    for i in range(1, n):
        stay = best[i - 1]
        jump = best[i - 1].min() + SWITCH_PENALTY
        take_jump = jump < stay
        best[i] = np.where(take_jump, jump, stay) + cost[i]
        back[i] = np.where(take_jump, best[i - 1].argmin(), np.arange(k))
    path = np.zeros(n, dtype=int)
    path[-1] = best[-1].argmin()
    for i in range(n - 1, 0, -1):
        path[i - 1] = back[i, path[i]]
    return [(i, int(path[i])) for i in range(n) if i == 0 or path[i] != path[i - 1]]


def run(m1: pd.DataFrame, sym: str) -> dict:
    weekly = weekly_detection(m1)
    good = (weekly["margin"] >= 1.15) & (weekly["n_days"] >= 3)
    pred = predicted_offsets(weekly["week"])
    names = list(CANDIDATES)
    seg = segment_eras(weekly["obs_offset_h"].to_numpy(), pred.to_numpy(), good.to_numpy())
    eras, era_rows = [], []
    for j, (i, s) in enumerate(seg):
        end_i = seg[j + 1][0] - 1 if j + 1 < len(seg) else len(weekly) - 1
        kind, p = CANDIDATES[names[s]]
        start = pd.Timestamp("1900-01-01") if j == 0 else weekly["week"].iloc[i]
        eras.append((start, kind, p))
        sl = slice(i, end_i + 1)
        inf = good.iloc[sl]
        era_rows.append({"era_start_week": weekly["week"].iloc[i].date(), "era_end_week": weekly["week"].iloc[end_i].date(),
                         "weeks": end_i - i + 1, "convention": names[s],
                         "weeks_matching": int((weekly["obs_offset_h"].iloc[sl][inf] == pred[names[s]].iloc[sl][inf]).sum()),
                         "weeks_informative": int(inf.sum())})
    clock = tz.ServerClock(eras)
    eras_df = pd.DataFrame(era_rows)
    eras_df["match_pct"] = (100 * eras_df["weeks_matching"] / eras_df["weeks_informative"].clip(lower=1)).round(1)

    # convention scoreboard overall and by era
    score = pd.DataFrame({n: [(weekly["obs_offset_h"][good] == pred[n][good]).mean() * 100] for n in names}, index=["match_pct_all_weeks"]).T.round(1)
    score["weeks"] = int(good.sum())
    # mismatch weeks: US DST and EU DST disagree
    us, eu = pred["ET+5 (UTC+0/+1, US DST)"], pred["London (UTC+0/+1, EU DST)"]
    mm = weekly[(us != eu) & good].copy()
    for n in ["UTC fixed (UTC+0)", "London (UTC+0/+1, EU DST)", "ET+5 (UTC+0/+1, US DST)", "NY-close ET+7 (UTC+2/+3, US DST)", "EET (UTC+2/+3, EU DST)"]:
        mm[n.split(" (")[0]] = pred[n][mm.index].astype(int)
    mm = mm[["week", "obs_offset_h", "margin", "open_hhmm", "UTC fixed", "London", "ET+5", "NY-close ET+7", "EET"]]
    # which linkage wins in the mismatch weeks of the latest era
    last_start = pd.Timestamp(eras[-1][0]) if len(eras) > 1 else weekly["week"].iloc[0]
    late = mm[mm["week"] >= last_start]
    link = {"mismatch_weeks_in_last_era": int(len(late)),
            "us_linked_matches": int((late["obs_offset_h"] == late["ET+5"]).sum()),
            "eu_linked_matches": int((late["obs_offset_h"] == late["London"]).sum())}

    # raw runs of observed offset (for the regimes table)
    runs = weekly[good].copy()
    runs["grp"] = (runs["obs_offset_h"] != runs["obs_offset_h"].shift()).cumsum()
    runs = runs.groupby("grp").agg(first_week=("week", "min"), last_week=("week", "max"), weeks=("week", "size"), offset_h=("obs_offset_h", "first"),
                                   open_0930ET_server=("open_hhmm", lambda x: "/".join(sorted(x.unique()))),
                                   release_spike_server_secondary=("release_hhmm", lambda x: x.mode().iloc[0]))
    runs["first_week"], runs["last_week"] = runs["first_week"].dt.date, runs["last_week"].dt.date
    rel = weekly[good]["release_minus_open_min"]
    ny_close_share = float((weekly["obs_offset_h"][good] == pred["NY-close ET+7 (UTC+2/+3, US DST)"][good]).mean() * 100)

    return {"live": live_offset(sym), "weekly": weekly, "scoreboard": score, "eras": eras_df, "mismatch": mm, "linkage": link,
            "runs": runs.reset_index(drop=True), "clock": clock,
            "release_minus_open": {"weeks": int(len(rel)), "pct_exactly_minus60": round(float((rel == -60).mean() * 100), 1),
                                   "median_min": float(rel.median())},
            "ny_close_match_pct": round(ny_close_share, 1), "weeks_total": int(len(weekly)), "weeks_informative": int(good.sum())}
