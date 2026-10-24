"""Variant rules on synthetic markets: no lookahead (H2a, H4a, H5a), the H5 one-day lag and flip cost, H1 skipping, skip reasons."""
import numpy as np
import pandas as pd
import pytest

from research.data import Costs, Market
from research.evaluate import score_positions
from research.tests.synth import close_only_market, perturb, random_market, stamps
from research.variants import R_ENTRY, R_NEXT, R_SIGNAL, h1a, h1b, h2a, h2b, h4a, h4b, h5a, h5b, c2

BDAYS = pd.bdate_range("2024-01-01", periods=130)
MKT = random_market(BDAYS)


# ---------------------------------------------------------------- no lookahead
@pytest.mark.parametrize("build, minute_of_entry", [(h2a, 15 * 60 + 31), (h2b, 15 * 60 + 31), (h4a, 9 * 60 + 35), (h4b, 9 * 60 + 35)])
def test_trade_direction_ignores_prices_at_or_after_entry(build, minute_of_entry):
    base = build(MKT).trades
    assert len(base) > 5                                               # the test must actually exercise trades
    for k in range(0, len(base), max(1, len(base) // 12)):             # a spread of trades over the whole sample
        tr = base.iloc[k]
        alt = build(perturb(MKT, tr["entry_et"], seed=k)).trades
        same = alt[alt["entry_et"] == tr["entry_et"]]
        assert len(same) == 1 and same["direction"].iloc[0] == tr["direction"]
        assert same["exit_px"].iloc[0] != tr["exit_px"]                # the perturbation did change later prices


@pytest.mark.parametrize("build", [h5a, h5b])
def test_h5_position_ignores_prices_at_or_after_entry(build):
    base = build(MKT).pos.dropna(subset=["pos"])
    assert len(base) > 20
    for k in range(0, len(base), max(1, len(base) // 12)):
        day = base.index[k]
        alt = build(perturb(MKT, day + pd.Timedelta(hours=16), seed=k)).pos
        assert alt.loc[day, "pos"] == base.loc[day, "pos"]


# ---------------------------------------------------------------- H5 lag and flip cost
def test_h5_one_day_lag():
    days = pd.bdate_range("2024-01-01", periods=140)
    closes = np.r_[100 * 1.005 ** np.arange(100), 100 * 1.005 ** 99 * 0.97 ** np.arange(1, 41)]    # up for 100 days, then down
    close = pd.Series(closes, index=days)
    mom = close / close.shift(60) - 1
    expected = np.sign(mom).shift(1)                                    # position at C(d) = sign(m(d-1))
    for build in (h5a,):
        pos = build(close_only_market(days, closes)).pos["pos"]
        ok = expected.notna()
        assert (pos[ok] == expected[ok]).all() and pos[~ok].isna().all()
    first_neg = mom[mom < 0].index[0]
    i = days.get_loc(first_neg)
    pos = h5a(close_only_market(days, closes)).pos["pos"]
    assert pos.iloc[i] == 1.0 and pos.iloc[i + 1] == -1.0               # signal turns at i; the position flips one day later
    long_flat = h5b(close_only_market(days, closes)).pos["pos"]
    assert long_flat.iloc[i] == 1.0 and long_flat.iloc[i + 1] == 0.0


def test_h5_flip_costs_one_full_round_trip():
    idx = pd.bdate_range("2024-03-04", periods=4)
    pos = pd.DataFrame({"pos": [1.0, -1.0, -1.0, 0.0], "close": 100.0, "next_close": 100.0, "next_day": pd.Series(idx, index=idx).shift(-1)}, index=idx)
    costs = Costs(2.43, 6.0, 10_000.0)                                  # stress 6 bp, base 2.43 bp per round trip
    s = score_positions(pos, idx, costs, idx[0], idx[-1])
    # entry +1: half round trip; flip +1 -> -1: |change| = 2 = one full round trip; hold; exit to flat: half
    assert s.daily["stress"].round(9).tolist() == [-3.0, -6.0, 0.0, -3.0]
    assert s.daily["base"].round(9).tolist() == pytest.approx([-1.215, -2.43, 0.0, -1.215])
    assert s.n_changes == 3


def test_positions_start_and_end_flat_and_charge_the_liquidation():
    idx = pd.bdate_range("2024-03-04", periods=3)
    pos = pd.DataFrame({"pos": 1.0, "close": [100.0, 110.0, 121.0], "next_close": [110.0, 121.0, 133.1],
                        "next_day": pd.Series(idx, index=idx).shift(-1)}, index=idx)
    s = score_positions(pos, idx, Costs(0.0, 6.0, 10_000.0), idx[0], idx[-1])
    assert s.daily["gross"].sum() == pytest.approx(3 * 1000.0)
    assert s.daily["stress"].sum() == pytest.approx(3000.0 - 6.0)       # one round trip in total (buy and hold)


def test_c2_is_a_single_round_trip():
    s = score_positions(c2(MKT).pos, MKT.days, Costs(0.0, 6.0, 10_000.0), MKT.days[0], MKT.days[-1])
    assert s.n_changes == 1
    assert s.daily["gross"].sum() - s.daily["stress"].sum() == pytest.approx(6.0)


# ---------------------------------------------------------------- H1 skipping
def week(start, drop=()):
    d = pd.bdate_range(start, periods=5)
    return [x for x in d if x not in pd.DatetimeIndex(drop)]


def test_h1a_skips_when_next_day_is_not_a_trading_day_and_h1b_needs_monday():
    # week 1 complete; week 2 has no Wednesday (holiday); week 3 has no Monday
    days = week("2024-01-01") + week("2024-01-08", drop=["2024-01-10"]) + week("2024-01-15", drop=["2024-01-15"])
    m = random_market(days, minutes=[9 * 60 + 30, 16 * 60])
    a = h1a(m)
    entries = [t.strftime("%a %d") for t in a.trades["entry_et"]]
    assert entries == ["Mon 01", "Tue 02", "Wed 03", "Thu 04", "Mon 08", "Thu 11", "Tue 16", "Wed 17", "Thu 18"]
    assert a.skips[["date", "reason"]].values.tolist() == [[pd.Timestamp("2024-01-09"), R_NEXT]]    # Tue -> missing Wed
    assert (a.trades["direction"] == 1).all()
    assert ((a.trades["exit_et"] - a.trades["entry_et"]) == pd.Timedelta(hours=17, minutes=30)).all()
    b = h1b(m)
    assert [t.strftime("%d") for t in b.trades["entry_et"]] == ["05"]                                  # Fri 05 -> Mon 08
    assert b.skips["date"].tolist() == [pd.Timestamp("2024-01-12"), pd.Timestamp("2024-01-19")]       # Mon 15 missing; no Mon 22
    assert (b.skips["reason"] == R_NEXT).all()
    assert ((b.trades["exit_et"] - b.trades["entry_et"]) == pd.Timedelta(days=2, hours=17, minutes=30)).all()


# ---------------------------------------------------------------- skip reasons, never filled
def test_missing_prices_are_skipped_not_filled():
    days = week("2024-01-01")
    idx = stamps(days, [9 * 60 + 30, 16 * 60])
    o = pd.Series(100.0, index=idx).drop(pd.Timestamp("2024-01-02 16:00"))        # Tue 16:00 bar missing, last bar is 20+ h old
    a = h1a(Market(o, o.copy()))
    reasons = dict(zip(a.skips["date"], a.skips["reason"]))
    assert reasons[pd.Timestamp("2024-01-02")] == R_ENTRY                          # no 16:00 price -> entry missing
    assert pd.Timestamp("2024-01-02") not in set(a.trades["entry_et"].dt.normalize())
    assert pd.Timestamp("2024-01-01") in set(a.trades["entry_et"].dt.normalize())  # Mon 16:00 -> Tue 09:30 still fine


def test_h2_first_day_has_no_signal_and_h4_needs_warm_up():
    a = h2a(MKT)
    assert a.skips.iloc[0]["date"] == BDAYS[0] and a.skips.iloc[0]["reason"] == R_SIGNAL
    g = h4a(MKT)
    assert (g.skips["reason"] == R_SIGNAL).sum() >= 41                              # needs 40 valid gaps before the first signal
    assert g.trades["entry_et"].min() > BDAYS[40]
    assert set(g.trades["direction"]) <= {1.0, -1.0}


# ---------------------------------------------------------------- independent re-implementations of the signal rules
def test_h4_matches_an_independent_loop_and_excludes_day_d_from_sigma():
    days = list(MKT.days)
    g = (MKT.px(9, 30) / MKT.px(16).shift(1) - 1).to_numpy()
    for build, thr in ((h4a, 1.0), (h4b, 1.5)):
        expect = {}
        for i in range(len(days)):
            hist = g[max(0, i - 60):i]                                  # the previous 60 trading days, day i excluded
            hist = hist[~np.isnan(hist)]
            if len(hist) >= 40 and not np.isnan(g[i]):
                z = g[i] / hist.std(ddof=1)
                if abs(z) >= thr:
                    expect[days[i]] = -np.sign(z)
        got = {t.normalize(): d for t, d in zip(build(MKT).trades["entry_et"], build(MKT).trades["direction"])}
        assert got == expect and len(expect) > 5


def test_h2b_needs_both_signs_to_agree():
    r1 = (MKT.px(10) / MKT.px(16).shift(1) - 1)
    r2 = (MKT.px(15, 30) / MKT.px(15) - 1)
    t = h2b(MKT).trades
    day = t["entry_et"].dt.normalize()
    assert (np.sign(r1.loc[day].to_numpy()) == t["direction"].to_numpy()).all()
    assert (np.sign(r2.loc[day].to_numpy()) == t["direction"].to_numpy()).all()
    both = (np.sign(r1) == np.sign(r2)) & r1.notna() & r2.notna()
    assert len(t) == both.sum() and 0 < len(t) < len(h2a(MKT).trades)


# ---------------------------------------------------------------- gates and the holdout stays locked
def test_stage_gates():
    from research.run_stages import gate
    ok = {"total_net_stress_bp": 10.0, "t_stress": 2.0, "years_positive": 3}
    assert gate("A", ok) and gate("B", {**ok, "t_stress": 1.5, "years_positive": 0})
    assert not gate("A", {**ok, "t_stress": 1.99}) and not gate("A", {**ok, "years_positive": 2})
    assert not gate("A", {**ok, "total_net_stress_bp": -1.0}) and not gate("A", {**ok, "t_stress": float("nan")})
    assert not gate("B", {**ok, "t_stress": 1.49})


def test_the_stage_runner_never_unlocks_the_holdout():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "run_stages.py").read_text(encoding="utf-8")
    assert "unlock_holdout=True" not in src and "before=None" not in src and "Stage C" in src
