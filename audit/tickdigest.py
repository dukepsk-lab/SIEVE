"""Per-day tick digest (so analyses never re-read raw ticks).

For each server day we keep:
  * a per-minute table: time-weighted spread stats under last-observation-carried-forward (LOCF),
    bid/ask OHLC and tick counts (used for the spread audit and the bars-vs-ticks check);
  * a tick-weighted spread histogram per 30-min server bucket (comparison only);
  * integrity counters (non-monotonic times, crossed quotes, zero spreads, flag values, ...).
Spread is in integer `point` units (ask_pts - bid_pts); ticks with bid<=0 or ask<=0 are ignored.
"""
import json
import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from . import config as C
from . import mt5io as io

log = logging.getLogger("audit")
DIGEST_VERSION = "v2"
CARRY_MS = 300_000          # carry the last quote into a minute only if it is at most 5 minutes old
MINUTE_COLS = ["m", "n", "n_all", "n_bidchg", "bo", "bh", "bl", "bc", "ao", "ah", "al", "ac",
               "s_min", "s_med", "s_max", "s_mean", "s_last", "s_carry"]


def _groups(key: np.ndarray):
    """Start index of every run of equal consecutive values."""
    return np.flatnonzero(np.r_[True, key[1:] != key[:-1]])


def digest_day(tk: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    t_all = tk["time_msc"].to_numpy()
    cnt = {"n_ticks": int(len(tk))}
    if len(tk) == 0:
        return pd.DataFrame(columns=MINUTE_COLS), pd.DataFrame(columns=["bucket", "s", "n"]), cnt

    order = np.argsort(t_all, kind="stable")
    cnt["n_nonmonotonic"] = int((np.diff(t_all) < 0).sum())
    tk = tk.iloc[order] if cnt["n_nonmonotonic"] else tk
    t_all = tk["time_msc"].to_numpy()
    bid_all, ask_all = tk["bid"].to_numpy(), tk["ask"].to_numpy()
    same = (np.diff(t_all) == 0) & (np.diff(bid_all) == 0) & (np.diff(ask_all) == 0) & (np.diff(tk["flags"].to_numpy().astype(np.int32)) == 0)
    cnt["n_exact_duplicates"] = int(same.sum())
    cnt["n_nonpositive_price"] = int(((bid_all <= 0) | (ask_all <= 0)).sum())
    cnt["flags"] = {int(k): int(v) for k, v in tk["flags"].value_counts().items()}
    cnt["n_last_nonzero"] = int((tk["last"] != 0).sum())
    cnt["n_volume_nonzero"] = int((tk["volume"] != 0).sum())
    cnt["n_volume_real_nonzero"] = int((tk["volume_real"] != 0).sum())
    cnt["first_msc"], cnt["last_msc"] = int(t_all[0]), int(t_all[-1])

    ok = (bid_all > 0) & (ask_all > 0)
    t, bid, ask = t_all[ok], bid_all[ok], ask_all[ok]
    s = (ask - bid).astype(np.int64)
    cnt["n_crossed"] = int((s < 0).sum())          # bid > ask
    cnt["n_zero_spread"] = int((s == 0).sum())
    keep = s >= 0                                   # crossed quotes are data errors: counted, excluded from spread stats
    t, bid, ask, s = t[keep], bid[keep], ask[keep], s[keep]
    if len(t) == 0:
        return pd.DataFrame(columns=MINUTE_COLS), pd.DataFrame(columns=["bucket", "s", "n"]), cnt
    cnt["n_valid"] = int(len(t))
    cnt["spread_max_pts"] = int(s.max())

    mi = t // 60_000
    # LOCF segments: each quote lives until the next tick or the end of its minute
    nxt = np.r_[t[1:], (mi[-1] + 1) * 60_000]            # the last quote of the day lives to the end of its minute
    seg_m, seg_s, seg_w = mi, s, np.minimum(nxt, (mi + 1) * 60_000) - t
    # carry-in: quote from the previous minute covers [minute start, first tick of this minute)
    f = _groups(mi)
    f = f[f > 0]
    carry_ok = (mi[f] * 60_000 - t[f - 1] <= CARRY_MS)
    f = f[carry_ok]
    c_m, c_s, c_w = mi[f], s[f - 1], t[f] - mi[f] * 60_000
    all_m, all_s, all_w = np.r_[seg_m, c_m], np.r_[seg_s, c_s], np.r_[seg_w, c_w]

    o = np.lexsort((all_s, all_m))
    sm, ss, sw = all_m[o], all_s[o], all_w[o]
    st = _groups(sm)
    en = np.r_[st[1:], len(sm)] - 1
    tot = np.add.reduceat(sw, st)
    cw = np.cumsum(sw)
    base = np.r_[0, cw[st[1:] - 1]]
    gid = np.repeat(np.arange(len(st)), en - st + 1)
    hit = (cw - base[gid]) >= 0.5 * tot[gid]
    med = ss[np.minimum.reduceat(np.where(hit, np.arange(len(sm)), len(sm)), st)]
    mean = np.add.reduceat(sw * ss, st) / np.where(tot > 0, tot, 1)

    # per-minute tick aggregates (time-ordered)
    g = _groups(mi)
    ge = np.r_[g[1:], len(t)] - 1
    mins = mi[g]
    carry_s = np.full(len(mins), -1, dtype=np.int64)
    carry_s[np.searchsorted(mins, c_m)] = c_s
    bidchg = np.r_[True, np.diff(bid) != 0]
    n_all = np.add.reduceat(np.ones(len(t_all), dtype=np.int64), _groups(t_all // 60_000))
    n_all = pd.Series(n_all, index=(t_all // 60_000)[_groups(t_all // 60_000)])

    mdf = pd.DataFrame({
        "m": mins, "n": ge - g + 1, "n_all": n_all.reindex(mins).to_numpy(), "n_bidchg": np.add.reduceat(bidchg.astype(np.int64), g),
        "bo": bid[g], "bh": np.maximum.reduceat(bid, g), "bl": np.minimum.reduceat(bid, g), "bc": bid[ge],
        "ao": ask[g], "ah": np.maximum.reduceat(ask, g), "al": np.minimum.reduceat(ask, g), "ac": ask[ge],
        "s_last": s[ge], "s_carry": carry_s,
    })
    sdf = pd.DataFrame({"m": sm[st], "s_min": ss[st], "s_med": med, "s_max": ss[en], "s_mean": mean})
    mdf = mdf.merge(sdf, on="m", how="left")[MINUTE_COLS]
    for c in MINUTE_COLS:
        mdf[c] = mdf[c].astype("float64" if c == "s_mean" else "int64")

    bucket = ((t // 1000) % 86400) // 1800
    h = pd.Series(bucket * 10_000_000 + s).value_counts().sort_index()
    hdf = pd.DataFrame({"bucket": (h.index // 10_000_000).astype("int64"), "s": (h.index % 10_000_000).astype("int64"), "n": h.to_numpy()})
    return mdf, hdf, cnt


# ---------------------------------------------------------------- driver with cache
def _dir(sym: str, kind: str):
    d = C.CACHE / f"digest_{DIGEST_VERSION}" / io.slug(sym) / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_digests(sym: str, first_day: datetime, cutoff_day: datetime, point: float):
    """Pull (cached) ticks day by day, digest each, return (minutes, hist, counters) for the whole span."""
    dm, dh, dc = _dir(sym, "minute"), _dir(sym, "hist"), _dir(sym, "counters")
    mins, hists, cnts = [], [], []
    day, n_new = first_day, 0
    while day < cutoff_day:
        key = f"{day:%Y-%m-%d}"
        fm, fh, fc = dm / f"{key}.parquet", dh / f"{key}.parquet", dc / f"{key}.json"
        if fm.exists() and fh.exists() and fc.exists():
            m, h, c = pd.read_parquet(fm), pd.read_parquet(fh), json.loads(fc.read_text())
        else:
            tk = io.load_ticks_day(sym, day, point, cacheable=True)
            m, h, c = digest_day(tk)
            m.to_parquet(fm, compression="zstd", index=False)
            h.to_parquet(fh, compression="zstd", index=False)
            fc.write_text(json.dumps(c))
            n_new += 1
            if n_new % 100 == 0:
                log.info("digested %d new days, now at %s (%d ticks that day)", n_new, key, c["n_ticks"])
        if len(m):
            mins.append(m)
            h = h.copy()
            h["day"] = key
            hists.append(h)
        c["day"] = key
        cnts.append(c)
        day += timedelta(days=1)
    return (pd.concat(mins, ignore_index=True), pd.concat(hists, ignore_index=True), pd.DataFrame(cnts))
