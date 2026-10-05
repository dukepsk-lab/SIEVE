"""MT5 access layer.

READ-ONLY: only data-retrieval calls are used. No order_* / position / trade-request function is
imported or called anywhere in this package.

Time convention used across the whole package: "server time" = the broker server wall clock, which
the MT5 API returns as epoch seconds (i.e. wall clock labelled as UTC). We keep it as naive
datetimes / integer epoch seconds and only convert to real UTC / New York in audit.tz, using the
offset regimes measured in task 4. Datetimes handed to MT5 are tz-aware (UTC label) so that the
epoch the API sees equals the server-clock label.
"""
import logging
import os
import platform
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import MetaTrader5 as mt5

from . import config as C

log = logging.getLogger("audit")
UTC = timezone.utc
TF = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "H1": mt5.TIMEFRAME_H1, "D1": mt5.TIMEFRAME_D1}
TF_SECONDS = {"M1": 60, "M5": 300, "H1": 3600, "D1": 86400}
RATE_COLS = ["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]
DAY = timedelta(days=1)


def lab(naive: datetime) -> datetime:
    """Server-clock label -> tz-aware datetime whose epoch equals the label (what MT5 expects)."""
    return naive.replace(tzinfo=UTC)


def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_") or "sym"


# ---------------------------------------------------------------- connection
def find_terminal() -> str:
    if C.TERMINAL_PATH:
        return C.TERMINAL_PATH
    base = Path(os.environ.get("APPDATA", "")) / "MetaQuotes" / "Terminal"
    hits = []
    for origin in base.glob("*/origin.txt"):
        for enc in ("utf-16", "utf-8"):
            try:
                p = Path(origin.read_text(encoding=enc).strip())
                break
            except (UnicodeError, OSError):
                p = None
        if p is not None and C.BROKER_HINT.lower() in str(p).lower() and (p / "terminal64.exe").exists():
            hits.append(str(p / "terminal64.exe"))
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise SystemExit(f"Several {C.BROKER_HINT} terminals found {hits}; set MT5_TERMINAL_PATH.")
    return ""   # let the package pick the default terminal; broker is verified after connecting


def connect() -> dict:
    """initialize() or STOP with the exact failure. Returns redacted terminal/account info."""
    if platform.system() != "Windows":
        raise SystemExit(f"STOP: the MetaTrader5 package needs Windows (platform is {platform.system()}).")
    path = find_terminal()
    ok = mt5.initialize(path=path, timeout=60000) if path else mt5.initialize(timeout=60000)
    if not ok:
        raise SystemExit(f"STOP: mt5.initialize(path={path!r}) failed: {mt5.last_error()}")
    ti, ai = mt5.terminal_info(), mt5.account_info()
    if ai is None:
        raise SystemExit(f"STOP: terminal is not logged in to an account: {mt5.last_error()}")
    if C.BROKER_HINT.lower() not in f"{ti.company} {ai.server}".lower():
        raise SystemExit(f"STOP: connected terminal is '{ti.company}' / '{ai.server}', not {C.BROKER_HINT}. "
                         "Set MT5_TERMINAL_PATH to the right terminal64.exe.")
    # redacted: no login, name, password, balance
    info = {"terminal_company": ti.company, "terminal_name": ti.name, "build": ti.build, "connected": ti.connected,
            "algo_trading_allowed": bool(ti.trade_allowed), "maxbars": ti.maxbars,
            "server": ai.server, "currency": ai.currency, "leverage": ai.leverage,
            "account_trade_mode": {0: "DEMO", 1: "CONTEST", 2: "REAL"}.get(ai.trade_mode, ai.trade_mode),
            "margin_mode": {0: "RETAIL_NETTING", 1: "EXCHANGE", 2: "RETAIL_HEDGING"}.get(ai.margin_mode, ai.margin_mode),
            "terminal_path": path or "(default)"}
    log.info("connected: %s", info)
    return info


def pick_symbol() -> str:
    if C.SYMBOL:
        return C.SYMBOL
    pat = re.compile(C.SYMBOL_PATTERN, re.I)
    cands = [s for s in mt5.symbols_get() if pat.search(f"{s.name} {s.description}")]
    if len(cands) != 1:
        names = [(s.name, s.description) for s in cands]
        raise SystemExit(f"STOP: need exactly one symbol candidate, found {names}. Confirm with AUDIT_SYMBOL=<name>.")
    return cands[0].name


def select_symbol(sym: str, wait: float = 30.0) -> None:
    if not mt5.symbol_select(sym, True):
        raise SystemExit(f"STOP: symbol_select({sym}) failed: {mt5.last_error()}")
    t0 = time.time()
    while time.time() - t0 < wait:
        tk = mt5.symbol_info_tick(sym)
        if tk is not None and tk.time > 0:
            return
        time.sleep(0.5)
    log.warning("no live tick for %s after %.0fs (market closed?)", sym, wait)


def server_now(sym: str) -> datetime:
    """Latest tick time as a naive server-clock datetime."""
    tk = mt5.symbol_info_tick(sym)
    return datetime.fromtimestamp(tk.time, UTC).replace(tzinfo=None)


# ---------------------------------------------------------------- retry helper
def _call(fn, what: str, tries: int = 5):
    """MT5 returns None on error. None + last_error 'Success' is how an empty range can look: treat as empty."""
    for i in range(tries):
        r = fn()
        if r is not None:
            return r
        err = mt5.last_error()
        if err[0] == 1:
            return np.array([])
        wait = 1.5 * 2 ** i
        log.warning("%s -> None, last_error=%s; retry %d/%d in %.1fs", what, err, i + 1, tries, wait)
        time.sleep(wait)
    raise RuntimeError(f"{what} failed after {tries} tries: {mt5.last_error()}")


# ---------------------------------------------------------------- bars
def _rates_df(arr, start: datetime, end: datetime) -> pd.DataFrame:
    if len(arr) == 0:
        return pd.DataFrame({c: pd.Series(dtype="int64" if c in ("time", "tick_volume", "spread", "real_volume") else "float64")
                             for c in RATE_COLS})
    df = pd.DataFrame(arr)[RATE_COLS]
    for c in ("time", "tick_volume", "spread", "real_volume"):
        df[c] = df[c].astype("int64")
    lo, hi = int(start.replace(tzinfo=UTC).timestamp()), int(end.replace(tzinfo=UTC).timestamp())
    # MT5 can return a bar OUTSIDE the requested range (e.g. year 2010 probe returned a 2019 bar): filter strictly.
    return df[(df["time"] >= lo) & (df["time"] < hi)].reset_index(drop=True)


def rates_chunk(sym: str, tf: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Bars with open time in [start, end). Re-pulls until two consecutive pulls agree (history syncs lazily)."""
    prev, df = -1, None
    for i in range(6):
        arr = _call(lambda: mt5.copy_rates_range(sym, TF[tf], lab(start), lab(end - timedelta(seconds=1))),
                    f"rates {tf} {start:%Y-%m-%d}")
        df = _rates_df(arr, start, end)
        if len(df) == prev:
            return df
        prev = len(df)
        time.sleep(0.4 * (i + 1))
    log.warning("rates %s %s did not stabilise (last n=%d)", tf, start, len(df))
    return df


def first_data_year(sym: str, tf: str) -> int | None:
    """First calendar year with in-range bars (each empty year was pulled twice). Cached: empty probes cost ~5s each."""
    f = C.CACHE / "rates" / slug(sym) / f"first_year_{tf}_from{C.EARLIEST_YEAR}.txt"
    if f.exists():
        return int(f.read_text()) or None
    y0 = next((y for y in range(C.EARLIEST_YEAR, datetime.now().year + 1)
               if len(rates_chunk(sym, tf, datetime(y, 1, 1), datetime(y + 1, 1, 1)))), None)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(str(y0 or 0))
    return y0


def _month_starts(first: datetime, last: datetime):
    d = first.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while d <= last:
        yield d
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def load_rates(sym: str, tf: str, now: datetime) -> pd.DataFrame:
    """All bars from the first data year to `now`, monthly chunks, parquet-cached. The still-forming bar is dropped."""
    y0 = first_data_year(sym, tf)
    if y0 is None:
        return _rates_df([], datetime(2000, 1, 1), datetime(2000, 1, 2))
    cdir = C.CACHE / "rates" / slug(sym) / tf
    cdir.mkdir(parents=True, exist_ok=True)
    cutoff_day = datetime(now.year, now.month, now.day)
    parts = []
    for m in _month_starts(datetime(y0, 1, 1), now):
        m_end = (m.replace(day=28) + timedelta(days=4)).replace(day=1)
        f = cdir / f"{m:%Y-%m}.parquet"
        if f.exists():
            parts.append(pd.read_parquet(f))
            continue
        df = rates_chunk(sym, tf, m, m_end)
        if m_end <= cutoff_day:             # month is complete -> final, cache it
            df.to_parquet(f, compression="zstd", index=False)
        parts.append(df)
    df = pd.concat(parts, ignore_index=True)
    now_ts = int(now.replace(tzinfo=UTC).timestamp())
    df = df[df["time"] + TF_SECONDS[tf] <= now_ts]          # drop the still-forming bar
    quality = {"n_dup_time": int(df["time"].duplicated().sum()), "n_nonmonotonic": int((np.diff(df["time"].to_numpy()) < 0).sum())}
    df = df.sort_values("time").reset_index(drop=True)      # chunks arrive in order; quality counters above are taken before sorting
    df.attrs.update(quality)
    log.info("loaded %s %s: %d bars %s .. %s", sym, tf, len(df),
             pd.to_datetime(df["time"].iloc[0], unit="s") if len(df) else None,
             pd.to_datetime(df["time"].iloc[-1], unit="s") if len(df) else None)
    return df


# ---------------------------------------------------------------- ticks
_TICK_ENC = {"time_msc": "DELTA_BINARY_PACKED", "bid": "DELTA_BINARY_PACKED", "ask": "DELTA_BINARY_PACKED"}


def ticks_path(sym: str, day: datetime) -> Path:
    return C.CACHE / "ticks" / slug(sym) / f"{day:%Y}" / f"{day:%Y-%m-%d}.parquet"


def fetch_ticks_day(sym: str, day: datetime, point: float) -> pd.DataFrame:
    """All ticks with server time in [day, day+1). Prices stored as integer multiples of `point` (exact, compact)."""
    lo = int(day.replace(tzinfo=UTC).timestamp()) * 1000
    hi = lo + 86_400_000
    arr = _call(lambda: mt5.copy_ticks_range(sym, lab(day), lab(day + DAY) - timedelta(milliseconds=1), mt5.COPY_TICKS_ALL),
                f"ticks {day:%Y-%m-%d}")
    if len(arr) == 0:
        return pd.DataFrame({"time_msc": pd.Series(dtype="int64"), "bid": pd.Series(dtype="int32"), "ask": pd.Series(dtype="int32"),
                             "flags": pd.Series(dtype="uint16"), "last": pd.Series(dtype="int32"),
                             "volume": pd.Series(dtype="uint32"), "volume_real": pd.Series(dtype="float32")})
    arr = arr[(arr["time_msc"] >= lo) & (arr["time_msc"] < hi)]
    out = pd.DataFrame({
        "time_msc": arr["time_msc"].astype("int64"),
        "bid": np.rint(arr["bid"] / point).astype("int32"),
        "ask": np.rint(arr["ask"] / point).astype("int32"),
        "flags": arr["flags"].astype("uint16"),
        "last": np.rint(arr["last"] / point).astype("int32"),
        "volume": arr["volume"].astype("uint32"),
        "volume_real": arr["volume_real"].astype("float32"),
    })
    off_grid = int((np.abs(out["bid"] * point - arr["bid"]) > point * 1e-3).sum())
    if off_grid:
        log.warning("%s: %d bid prices not on the point grid", day.date(), off_grid)
    return out


def load_ticks_day(sym: str, day: datetime, point: float, cacheable: bool) -> pd.DataFrame:
    f = ticks_path(sym, day)
    if f.exists():
        return pd.read_parquet(f)
    df = fetch_ticks_day(sym, day, point)
    if cacheable:
        f.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pandas(df, preserve_index=False), f, compression="zstd",
                       use_dictionary=False, column_encoding=_TICK_ENC)
    return df


def first_tick_after(sym: str, day: datetime) -> datetime | None:
    """Earliest tick at/after `day` according to the terminal (naive server clock), or None."""
    arr = _call(lambda: mt5.copy_ticks_from(sym, lab(day), 1, mt5.COPY_TICKS_ALL), f"first tick after {day:%Y-%m-%d}")
    if len(arr) == 0:
        return None
    return datetime.fromtimestamp(int(arr[0]["time_msc"]) / 1000, UTC).replace(tzinfo=None)
