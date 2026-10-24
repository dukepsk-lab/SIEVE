"""Synthetic M1 bars for the forward-tracker tests: ET-stamped bars turned into server-time epoch rows, like an MT5 pull."""
import numpy as np
import pandas as pd

from audit.tz import ServerClock
from research.data import CLOCK_JSON, Costs

CLOCK = ServerClock.load(CLOCK_JSON)
COSTS = Costs(2.43, 6.0, 10_000.0)                                    # base 2.43 bp, stress 6.00 bp per round trip
SESSION = range(9 * 60 + 30, 16 * 60 + 6)                              # 09:30 .. 16:05 ET, one bar per minute


def et_stamps(days, minutes) -> pd.DatetimeIndex:
    return pd.DatetimeIndex([pd.Timestamp(d) + pd.Timedelta(minutes=m) for d in days for m in minutes]).as_unit("ns")


def make_bars(days, minutes=SESSION, seed: int = 0, step: float = 0.0007, clock: ServerClock = CLOCK) -> pd.DataFrame:
    """Random-walk M1 bars stamped at the given ET minutes of the given days, as MT5 rows (time = server epoch seconds)."""
    et = et_stamps(days, minutes)
    rng = np.random.default_rng(seed)
    px = 100 * np.exp(np.cumsum(rng.normal(0, step, len(et))))
    server = clock.et_to_server(et).as_unit("s")
    return pd.DataFrame({"time": server.asi8.astype("int64"), "open": px, "high": px * 1.0002, "low": px * 0.9998, "close": px * (1 + rng.normal(0, 1e-4, len(et))),
                         "tick_volume": 10, "spread": 143, "real_volume": 0})


def server_epoch(et_stamp, clock: ServerClock = CLOCK) -> float:
    """The server-clock epoch seconds of an ET wall-clock stamp."""
    return float(clock.et_to_server(pd.DatetimeIndex([et_stamp])).as_unit("s").asi8[0])


def now_utc_of(now_et) -> pd.Timestamp:
    return pd.Timestamp(now_et).tz_localize("America/New_York").tz_convert("UTC").tz_localize(None).as_unit("ns")


def scenario(bars: pd.DataFrame, now_et, offset_shift_h: int = 0, spread: float = 1.43):
    """(bars known at that moment, Live, now_utc) for a run at the given New York wall-clock time: the last tick is `now`, the
    terminal clock is the frozen one, shifted by offset_shift_h hours to simulate a broker clock change."""
    from research.forward.track import Live
    tick = server_epoch(now_et) + 3600 * offset_shift_h
    now_utc = now_utc_of(now_et)
    return bars[bars["time"] <= tick], Live(tick, 100.0, 100.0 + spread, now_utc.timestamp()), now_utc
