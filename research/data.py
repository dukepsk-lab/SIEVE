"""Data access for the phase-2 research (PLAN sections 1-2): M1 bars, the New York trading-day calendar, P(T) and costs.

Everything is offline from the audit cache. Paths are resolved from this file, so the cwd does not matter.

Market holds the ET-indexed open/close series. Trading day = an ET weekday with at least one bar; the previous trading day is
the previous element of `days`. P(T) is audit.t6_vol.price_at (open at T, else the last close <= 5 minutes earlier, else NaN).

Holdout: build_market() cuts every bar stamped on or after 2026-01-01 ET unless told otherwise, so Stage A/B code cannot see
holdout prices at all: a trade whose exit would fall in 2026 simply has "missing exit price" and is skipped.
"""
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from audit.t6_vol import _price_lookup, price_at
from audit.tz import ServerClock

ROOT = Path(__file__).resolve().parents[1]
M1_DIR = ROOT / "audit" / "cache" / "rates" / "USTEC" / "M1"
CLOCK_JSON = ROOT / "audit" / "out" / "server_clock.json"
COST_JSON = ROOT / "audit" / "out" / "cost_model_inputs.json"
HOLDOUT_START = pd.Timestamp("2026-01-01")
P_REF_END = pd.Timestamp("2026-10-04")            # end of the P_REF averaging window (PLAN section 1)


def load_m1(m1_dir: Path = M1_DIR) -> pd.DataFrame:
    """All monthly M1 files (empty months skipped), sorted by server `time`, duplicate timestamps dropped."""
    frames = [pd.read_parquet(f) for f in sorted(Path(m1_dir).glob("*.parquet"))]
    m1 = pd.concat([f for f in frames if len(f)], ignore_index=True)
    return m1.sort_values("time").drop_duplicates("time").reset_index(drop=True)


# ------------------------------------------------------------------ costs
@dataclass(frozen=True)
class Costs:
    base_pts: float       # round trip, index points: spread + 2 x slippage + commission
    stress_pts: float
    p_ref: float          # mean close over the current spread regime; converts points to bp

    @property
    def base_bp(self) -> float:
        return self.base_pts / self.p_ref * 1e4

    @property
    def stress_bp(self) -> float:
        return self.stress_pts / self.p_ref * 1e4


def cost_points(j: dict) -> tuple[float, float]:
    """(base, stress) round-trip cost in index points from cost_model_inputs.json."""
    spread, slip, comm = j["spread"]["current_regime"], j["slippage_per_side"], j["commission"]["round_trip_index_points"]["value"]
    base = spread["rth_0930_1600_ET"]["p50"]["value"] + 2 * slip["base"]["value"] + comm
    stress = spread["stress_spread"]["value"] + 2 * slip["stress"]["value"] + comm
    return float(base), float(stress)


def p_ref(m1: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp = P_REF_END) -> float:
    """Mean M1 close over bars whose server date lies in [start, end] (a price level, not a strategy result)."""
    date = pd.DatetimeIndex(pd.to_datetime(m1["time"], unit="s")).as_unit("ns").normalize()
    sel = (date >= start) & (date <= end)
    if not sel.any():
        raise ValueError("no M1 bars in the P_REF window")
    return float(m1["close"].to_numpy()[sel].mean())


def load_costs(m1: pd.DataFrame, path: Path = COST_JSON) -> Costs:
    j = json.loads(Path(path).read_text(encoding="utf-8"))
    base, stress = cost_points(j)
    return Costs(base, stress, p_ref(m1, pd.Timestamp(j["spread"]["current_regime_start"]["value"])))


# ------------------------------------------------------------------ market
def _ns(t) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(t).as_unit("ns")


class Market:
    """ET-indexed open/close bars (sorted, unique) and the trading-day calendar."""

    def __init__(self, o: pd.Series, c: pd.Series):
        o, c = o.set_axis(_ns(o.index)), c.set_axis(_ns(c.index))
        self.P = (o, c)
        d = _ns(o.index.normalize().unique()).sort_values()
        self.days = d[d.dayofweek < 5]

    def price(self, t) -> np.ndarray:
        """P(T) at each ET timestamp (NaN when missing)."""
        return price_at(self.P, _ns(t))

    def px(self, hour: int, minute: int = 0) -> pd.Series:
        """P(day hh:mm) for every trading day, indexed by day."""
        return pd.Series(self.price(self.days + pd.Timedelta(hours=hour, minutes=minute)), index=self.days)


def build_market(m1: pd.DataFrame, clock: ServerClock, before: pd.Timestamp | None = HOLDOUT_START) -> Market:
    """Market from raw M1; bars stamped at or after `before` (ET) are dropped. before=None keeps everything (Stage C only)."""
    o, c, _ = _price_lookup(m1, clock)
    if before is not None:
        o, c = o[o.index < before], c[c.index < before]
    return Market(o, c)
