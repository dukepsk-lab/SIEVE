"""Reviewer's own helpers. Deliberately does NOT import anything from the implementer's audit package.

READ-ONLY: only initialize / symbol_info / symbol_info_tick / copy_rates_* / copy_ticks_* / shutdown are used.
No account fields other than "is logged in" are touched; nothing about the account is printed or stored.
"""
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)
AUDIT = HERE.parent
CACHE = AUDIT / "cache"                       # implementer's RAW pulls (ticks as integer points, rates as returned)
SYM = "USTEC."
TERMINAL = r"C:\Program Files\IUX Markets MT5 Terminal\terminal64.exe"
UTC = timezone.utc
LON = ZoneInfo("Europe/London")
NY = ZoneInfo("America/New_York")


def connect():
    import MetaTrader5 as mt5
    if not mt5.initialize(path=TERMINAL, timeout=60000):
        raise SystemExit(f"initialize failed: {mt5.last_error()}")
    if mt5.account_info() is None:                   # only checks that a session exists; nothing is read from it
        raise SystemExit("terminal not logged in")
    if not mt5.symbol_select(SYM, True):
        raise SystemExit(f"symbol_select failed {mt5.last_error()}")
    return mt5


def lab(dt: datetime) -> datetime:
    """naive server-clock datetime -> tz-aware UTC-labelled datetime (MT5 reads the epoch as the server label)."""
    return dt.replace(tzinfo=UTC)


# ---------------------------------------------------------------- reviewer's own clock model
# Hypothesis under test (implementer's claim): server == UTC until the 2021/22 winter, then server == Europe/London wall clock.
# Implemented independently with zoneinfo, applied per element (slow but transparent). ERA_SWITCH can be anywhere in the
# winter 2021-11-01 .. 2022-03-26 without changing any conversion.
ERA_SWITCH = datetime(2021, 12, 1)


def server_to_utc_one(s: datetime) -> datetime:
    if s < ERA_SWITCH:
        return s
    return s.replace(tzinfo=LON, fold=0).astimezone(UTC).replace(tzinfo=None)


def server_to_et_index(srv: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Vectorised via per-day offsets (offsets only change on Sunday nights when the market is shut)."""
    days = srv.normalize().unique()
    off = {}
    for d in days:
        noon = d.to_pydatetime() + pd.Timedelta(hours=12)
        u = server_to_utc_one(noon)
        et = u.replace(tzinfo=UTC).astimezone(NY).replace(tzinfo=None)
        off[d] = et - noon
    shift = pd.to_timedelta(srv.normalize().map(off))
    return (srv + shift).as_unit("ns")


def epoch_s_to_server(t) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(np.asarray(t), unit="s")).as_unit("ns")   # pandas 3 infers [s] otherwise
