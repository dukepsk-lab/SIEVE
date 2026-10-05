"""P(T) for the volatility samples: bar open at T, else the last close within MAX_STALE (past-only), else dropped and counted."""
import numpy as np
import pandas as pd

from audit.t6_vol import _diff, dropped_samples, price_at, sigma_tables


def series(stamps, opens, closes):
    idx = pd.DatetimeIndex(stamps)
    return pd.Series(opens, index=idx, dtype=float), pd.Series(closes, index=idx, dtype=float)


# session ends with the 15:58 bar (no 15:59 / 16:00 bars), as in 2021-22 and on the 2025-04 session-shift days
P = series(["2025-04-02 15:57", "2025-04-02 15:58", "2025-04-03 09:30"], [100, 101, 90], [101, 102, 91])


def test_open_at_t_is_used_when_the_bar_exists():
    assert price_at(P, pd.DatetimeIndex(["2025-04-03 09:30"]))[0] == 90


def test_last_close_within_5_min_is_used():
    assert price_at(P, pd.DatetimeIndex(["2025-04-02 16:00"]))[0] == 102            # close of the 15:58 bar


def test_stale_price_is_dropped_not_carried():
    assert np.isnan(price_at(P, pd.DatetimeIndex(["2025-04-02 16:10"]))[0])        # last bar started 12 min earlier


def test_future_bars_are_never_used():
    assert np.isnan(price_at(P, pd.DatetimeIndex(["2025-04-02 15:50"]))[0])        # only later bars exist


def test_drops_are_counted_and_listed():
    t0 = pd.DatetimeIndex(["2025-04-02 16:00", "2025-04-02 16:10"])
    d = _diff(P, t0, pd.DatetimeIndex(["2025-04-03 09:30", "2025-04-03 09:30"]))
    tbl = sigma_tables({"overnight": d}, pd.Timestamp("2025-04-03"))["overnight"]
    assert (tbl.loc[2025, "N"], tbl.loc[2025, "N_candidates"], tbl.loc[2025, "N_dropped"]) == (1, 2, 1)
    dr = dropped_samples({"overnight": d})
    assert len(dr) == 1 and dr["missing"].iloc[0] == "start"
