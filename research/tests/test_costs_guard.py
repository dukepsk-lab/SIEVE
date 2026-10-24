"""Cost conversion from cost_model_inputs.json, the holdout guard, long/short gross sign, and the 2026 cut of the market."""
import json

import numpy as np
import pandas as pd
import pytest

from audit.tz import ServerClock
from research.data import COST_JSON, Costs, build_market, cost_points, p_ref
from research.evaluate import HoldoutError, score_positions, score_trades
from research.variants import TRADE_COLS

ZERO = Costs(0.0, 0.0, 1e4)
COSTS = Costs(2.43, 6.0, 10_000.0)                       # P_REF 10,000: 1 point = 1 bp


def jval(v):
    return {"value": v}


def test_cost_points_from_json_synthetic():
    j = {"spread": {"current_regime": {"rth_0930_1600_ET": {"p50": jval(1.5)}, "stress_spread": jval(3.0)}},
         "slippage_per_side": {"base": jval(0.25), "stress": jval(1.0)}, "commission": {"round_trip_index_points": jval(0.5)}}
    assert cost_points(j) == (1.5 + 0.5 + 0.5, 3.0 + 2.0 + 0.5)


def test_cost_points_from_the_audit_json():
    base, stress = cost_points(json.loads(COST_JSON.read_text(encoding="utf-8")))
    assert base == pytest.approx(2.43) and stress == pytest.approx(6.00)


def test_bp_conversion_and_p_ref_window():
    t = pd.to_datetime(["2026-05-13 12:00", "2026-05-14 00:00", "2026-10-04 23:59", "2026-10-05 00:00"])
    m1 = pd.DataFrame({"time": (t - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1), "close": [1.0, 100.0, 200.0, 999.0]})
    ref = p_ref(m1, pd.Timestamp("2026-05-14"))
    assert ref == 150.0                                   # only server dates in [2026-05-14, 2026-10-04]
    c = Costs(2.43, 6.0, ref)
    assert c.base_bp == pytest.approx(2.43 / 150 * 1e4) and c.stress_bp == pytest.approx(6.0 / 150 * 1e4)


def test_p_ref_real_value_is_about_29495():
    from research.data import load_m1
    j = json.loads(COST_JSON.read_text(encoding="utf-8"))
    assert p_ref(load_m1(), pd.Timestamp(j["spread"]["current_regime_start"]["value"])) == pytest.approx(29495, abs=5)


# ---------------------------------------------------------------- long / short sign
def trade_frame(rows):
    return pd.DataFrame([dict(variant="X", entry_et=pd.Timestamp(e), exit_et=pd.Timestamp(x), direction=d, entry_px=a, exit_px=b)
                         for e, x, d, a, b in rows], columns=TRADE_COLS)


def test_gross_sign_long_and_short():
    days = pd.DatetimeIndex(["2024-03-04", "2024-03-05", "2024-03-06"])
    tr = trade_frame([("2024-03-04 09:30", "2024-03-04 16:00", 1, 100.0, 101.0),     # long, price up   -> +100 bp
                      ("2024-03-05 09:30", "2024-03-05 16:00", -1, 100.0, 101.0),    # short, price up  -> -100 bp
                      ("2024-03-06 09:30", "2024-03-06 16:00", -1, 100.0, 99.0)])    # short, price down -> +100 bp
    s = score_trades(tr, days, ZERO, "2024-03-01", "2024-03-31")
    assert s.daily["gross"].round(6).tolist() == [100.0, -100.0, 100.0]
    assert s.daily["stress"].round(6).tolist() == [100.0, -100.0, 100.0]             # zero costs


def test_net_costs_per_trade():
    days = pd.DatetimeIndex(["2024-03-04"])
    tr = trade_frame([("2024-03-04 09:30", "2024-03-04 16:00", 1, 100.0, 101.0)])
    row = score_trades(tr, days, COSTS, "2024-03-01", "2024-03-31").units.iloc[0]
    assert row["gross"] == pytest.approx(100.0)
    assert row["base"] == pytest.approx(100.0 - 2.43) and row["stress"] == pytest.approx(100.0 - 6.0)
    assert row["pt"] == pytest.approx(100.0 - 6.0 / 100.0 * 1e4)                    # stress points / entry price


# ---------------------------------------------------------------- holdout guard
def test_guard_raises_for_a_trade_in_2026_and_works_when_unlocked():
    days = pd.DatetimeIndex(["2025-12-30", "2026-01-05"])
    tr = trade_frame([("2026-01-05 09:30", "2026-01-05 16:00", 1, 100.0, 101.0)])
    with pytest.raises(HoldoutError):
        score_trades(tr, days, COSTS, "2026-01-01", "2026-03-31")
    s = score_trades(tr, days, COSTS, "2026-01-01", "2026-03-31", unlock_holdout=True)
    assert s.daily["gross"].sum() == pytest.approx(100.0)


def test_guard_raises_for_an_exit_in_2026_and_for_a_window_reaching_2026():
    days = pd.DatetimeIndex(["2025-12-31"])
    tr = trade_frame([("2025-12-31 16:00", "2026-01-02 09:30", 1, 100.0, 101.0)])
    with pytest.raises(HoldoutError):                      # enters in 2025 but exits in the holdout
        score_trades(tr, days, COSTS, "2025-01-01", "2025-12-31")
    with pytest.raises(HoldoutError):                      # nothing traded, but the window itself covers 2026
        score_trades(tr.iloc[0:0], days, COSTS, "2025-01-01", "2026-01-31")
    score_trades(tr.iloc[0:0], days, COSTS, "2025-01-01", "2025-12-31")    # a 2025 window is fine


def test_guard_for_position_series():
    idx = pd.DatetimeIndex(["2025-12-30", "2025-12-31", "2026-01-02"])
    pos = pd.DataFrame({"pos": [1.0, 1.0, 1.0], "close": [100.0, 101.0, 102.0], "next_close": [101.0, 102.0, np.nan],
                        "next_day": [idx[1], idx[2], pd.NaT]}, index=idx)
    with pytest.raises(HoldoutError):
        score_positions(pos, idx, COSTS, "2025-12-01", "2026-01-31")
    with pytest.raises(HoldoutError):                      # the last 2025 day exits on 2026-01-02
        score_positions(pos, idx, COSTS, "2025-12-01", "2025-12-31")
    s = score_positions(pos, idx, COSTS, "2025-12-01", "2026-01-31", unlock_holdout=True)
    assert len(s.daily) == 3


def test_market_is_cut_at_the_holdout():
    clock = ServerClock([("1900-01-01", "ny", 7)])         # server = New York + 7 h
    et = pd.to_datetime(["2025-12-31 16:00", "2026-01-02 09:30"])
    srv = et + pd.Timedelta(hours=7)
    m1 = pd.DataFrame({"time": (srv - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1), "open": [1.0, 2.0], "close": [1.0, 2.0]})
    assert list(build_market(m1, clock).days) == [pd.Timestamp("2025-12-31")]
    assert len(build_market(m1, clock, before=None).days) == 2
