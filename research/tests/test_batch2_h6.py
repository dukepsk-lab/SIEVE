"""Batch 2: H6 (the one-day lag, the cap, the no-trade band, cost on |change in w|), Newey-West alpha, the gates, the holdout guard."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research.data import Costs
from research.evaluate import HoldoutError, score_positions
from research.inference import nw_ols, welch
from research.run_batch2 import gate_h6
from research.tests.synth import close_only_market, perturb, random_market
from research.variants2 import BAND, _h6, band_path, h6a, h6b

DAYS = pd.bdate_range("2024-01-01", periods=170)
RET = np.r_[np.random.default_rng(3).normal(0, 0.004, 70), np.random.default_rng(4).normal(0, 0.02, 40),   # calm, stormy, calm
            np.random.default_rng(5).normal(0, 0.004, 60)]
CLOSES = 100 * np.cumprod(1 + RET)
MKT = close_only_market(DAYS, CLOSES)
COSTS = Costs(2.43, 6.0, 10_000.0)                                                  # base 2.43 bp, stress 6 bp per round trip


def expected_h6(closes, cap, band=BAND):
    """Independent loop. Position at C(d) uses sigma_hat(d-1) = std of r[d-20 .. d-1], r(i) = C(i) / C(i-1) - 1."""
    c = np.asarray(closes, float)
    r = np.r_[np.nan, c[1:] / c[:-1] - 1]
    w, cur = np.full(len(c), np.nan), 0.0
    for d in range(len(c)):
        j = d - 1
        if j < 20:                                                                  # r[j-19 .. j] needs j - 19 >= 1
            cur = 0.0
            continue
        sigma = np.std(r[j - 19:j + 1], ddof=1) * np.sqrt(252)
        target = min(cap, 0.20 / sigma)
        if abs(target - cur) >= band:
            cur = target
        w[d] = cur
    return w


# ---------------------------------------------------------------- the signal: lag, cap, band
@pytest.mark.parametrize("build, cap", [(h6a, 2.0), (h6b, 1.0)])
def test_h6_matches_an_independent_loop(build, cap):
    pos = build(MKT).pos["pos"].to_numpy()
    exp = expected_h6(CLOSES, cap)
    assert np.isnan(pos[:21]).all() and not np.isnan(pos[21:]).any()                # 20 returns + the one-day lag of warm-up
    assert np.allclose(pos, exp, equal_nan=True, rtol=1e-9, atol=1e-12)
    assert len(np.unique(pos[21:])) > 4 and pos[21:].min() < cap                    # the test exercises several different weights


@pytest.mark.parametrize("build", [h6a, h6b])
def test_h6_weight_ignores_the_close_it_is_entered_at_and_everything_later(build):
    base = build(MKT).pos["pos"]
    for k, day in enumerate(base.index[25::15]):
        alt = build(perturb(MKT, day + pd.Timedelta(hours=16), seed=k)).pos["pos"]  # C(day) and all later closes are noise
        assert alt.loc[day] == base.loc[day]                                        # w at C(day) uses sigma_hat(day - 1) only
        assert (alt.loc[day:] != base.loc[day:]).any()                              # ... while later weights do react


def test_h6_one_day_lag_on_a_shock():
    k = 60
    r = np.where(np.arange(100) % 2 == 0, 0.005, -0.005)
    r[k] = -0.10                                                                    # a -10% day at close k
    closes = 100 * np.cumprod(1 + r)
    pos = h6a(close_only_market(DAYS[:100], closes)).pos["pos"]
    assert pos.iloc[k - 1] == pos.iloc[k] == 2.0                                    # the shock is in C(k): w at C(k) cannot see it
    assert pos.iloc[k + 1] < 0.7                                                    # w at C(k+1) = 0.2 / sigma_hat(k) sees it
    sigma_k = np.std(r[k - 19:k + 1], ddof=1) * np.sqrt(252)
    assert pos.iloc[k + 1] == pytest.approx(0.2 / sigma_k)


def test_h6_cap_binds_in_calm_markets_and_h6b_only_derisks():
    a, b = h6a(MKT).pos["pos"].dropna(), h6b(MKT).pos["pos"].dropna()
    assert a.max() == 2.0 and b.max() == 1.0 and (b <= 1.0).all() and (a <= 2.0).all() and a.min() > 0
    calm = np.arange(len(a)) < 40                                                   # first 40 weights: 0.4% daily vol -> 6.3% a year
    assert (a[calm] == 2.0).all() and (b[calm] == 1.0).all()
    storm = expected_h6(CLOSES, 2.0)[95]                                            # inside the high-vol stretch
    assert storm < 1.0 and a.iloc[95 - 21] == pytest.approx(storm)


def test_band_path_moves_only_on_a_big_enough_change():
    nan = np.nan
    assert band_path([1.0, 1.05, 1.09, 1.11, 1.0]).tolist() == [1.0, 1.0, 1.0, 1.11, 1.0]   # 0.05, 0.09 held; 0.11 and 0.11 move
    assert band_path([0.05, 0.0999]).tolist() == [0.0, 0.0]                         # starts flat; a target under the band is not entered
    assert band_path([1.0, 1.25, 1.0], band=0.25).tolist() == [1.0, 1.25, 1.0]      # |change| == band moves (>=)
    assert band_path([1.0, 1.2, 1.0], band=0.25).tolist() == [1.0, 1.0, 1.0]
    out = band_path([nan, nan, 1.0, 1.02, nan, 1.02])                               # warm-up not held; a gap resets to flat
    assert np.isnan(out[[0, 1, 4]]).all() and out[[2, 3, 5]].tolist() == [1.0, 1.0, 1.02]


def test_h6_band_invariant_and_it_reduces_trading():
    pos = h6a(MKT).pos["pos"].dropna().to_numpy()
    step = np.abs(np.diff(pos))
    assert ((step == 0) | (step >= BAND - 1e-12)).all() and (step > 0).sum() > 3
    free = _h6(MKT, "H6a", band=0.0).pos["pos"].dropna().to_numpy()
    assert (np.abs(np.diff(free)) > 0).sum() > 5 * (step > 0).sum()                 # without the band w moves almost every day


# ---------------------------------------------------------------- cost per unit change of w
def test_cost_is_half_a_round_trip_per_unit_change_of_w():
    idx = pd.bdate_range("2024-03-04", periods=4)
    pos = pd.DataFrame({"pos": [0.5, 1.5, 1.5, 0.0], "close": 100.0, "next_close": 100.0, "next_day": pd.Series(idx, index=idx).shift(-1)}, index=idx)
    s = score_positions(pos, idx, COSTS, idx[0], idx[-1])
    # flat -> 0.5, 0.5 -> 1.5, hold, 1.5 -> 0.0 : changes 0.5, 1.0, 0, 1.5 at 3 bp (stress) and 1.215 bp (base) per unit
    assert s.daily["stress"].round(9).tolist() == [-1.5, -3.0, 0.0, -4.5]
    assert s.daily["base"].round(9).tolist() == pytest.approx([-0.6075, -1.215, 0.0, -1.8225])
    assert s.n_changes == 3


def test_h6_total_cost_is_turnover_times_half_the_round_trip():
    p = h6a(MKT).pos
    s = score_positions(p, MKT.days, COSTS, MKT.days[0], MKT.days[-1])
    q = p["pos"].fillna(0.0).to_numpy()
    turnover = np.abs(np.diff(np.r_[0.0, q, 0.0])).sum()                            # entry, every change, final exit
    assert s.daily["gross"].sum() - s.daily["stress"].sum() == pytest.approx(turnover * 6.0 / 2)
    assert s.daily["gross"].sum() - s.daily["base"].sum() == pytest.approx(turnover * 2.43 / 2)


# ---------------------------------------------------------------- Newey-West alpha
def test_nw_recovers_exact_coefficients_without_noise():
    x = np.random.default_rng(0).normal(0, 50, 300)
    fit = nw_ols(3.0 + 0.5 * x, x)
    assert fit["alpha"] == pytest.approx(3.0) and fit["beta"] == pytest.approx(0.5)


def test_nw_alpha_on_synthetic_data_with_a_known_alpha():
    rng = np.random.default_rng(11)
    n, alpha, beta = 4000, 4.0, 0.7
    x = rng.normal(0, 100, n)
    y = alpha + beta * x + rng.normal(0, 40, n)
    fit = nw_ols(y, x)
    assert abs(fit["alpha"] - alpha) < 4 * fit["se_alpha"] and abs(fit["beta"] - beta) < 4 * fit["se_beta"]
    assert fit["se_alpha"] == pytest.approx(40 / np.sqrt(n), rel=0.15)              # iid errors: the usual standard error
    assert fit["alpha_t"] == pytest.approx(fit["alpha"] / fit["se_alpha"])
    assert abs(nw_ols(y - alpha, x)["alpha_t"]) < 4                                      # no alpha once the true alpha is removed
    assert nw_ols(y + 20, x)["alpha_t"] > 4                                         # an extra +20 bp/day is detected


def test_nw_widens_the_standard_error_for_autocorrelated_residuals():
    rng = np.random.default_rng(5)
    n = 3000
    e = np.zeros(n)
    for i in range(1, n):
        e[i] = 0.6 * e[i - 1] + rng.normal(0, 20)
    x = rng.normal(0, 100, n)
    y = 2.0 + 0.5 * x + e
    assert nw_ols(y, x, lags=5)["se_alpha"] > 1.3 * nw_ols(y, x, lags=0)["se_alpha"]


def test_nw_matches_statsmodels_hac():
    sm = pytest.importorskip("statsmodels.api")
    rng = np.random.default_rng(2)
    x = rng.normal(0, 80, 700)
    y = 1.5 + 0.8 * x + np.convolve(rng.normal(0, 30, 700), [1, 0.5, 0.25], mode="same")
    ref = sm.OLS(y, sm.add_constant(x)).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
    fit = nw_ols(y, x, lags=5)
    assert np.allclose([fit["alpha"], fit["beta"]], ref.params) and np.allclose([fit["se_alpha"], fit["se_beta"]], ref.bse)
    assert fit["alpha_t"] == pytest.approx(ref.tvalues[0])


def test_nw_returns_nan_instead_of_failing_on_degenerate_input():
    assert np.isnan(nw_ols(np.arange(30.0), np.ones(30))["alpha"])                  # constant x: no regression
    assert np.isnan(nw_ols([1.0, 2.0], [1.0, 2.0])["alpha"])                        # too short


def test_welch_matches_scipy():
    stats = pytest.importorskip("scipy.stats")
    rng = np.random.default_rng(8)
    a, b = rng.normal(2, 5, 120), rng.normal(0, 9, 700)
    w = welch(a, b)
    ref = stats.ttest_ind(a, b, equal_var=False)
    assert w["t"] == pytest.approx(ref.statistic) and w["df"] == pytest.approx(ref.df) and w["diff"] == pytest.approx(a.mean() - b.mean())
    assert np.isnan(welch([1.0], b)["t"])


# ---------------------------------------------------------------- H6 gates
def test_h6_gate():
    ok = {"alpha_bp_day": 1.0, "alpha_t_nw": 2.0, "sharpe_stress": 1.0, "sharpe_c2": 0.9, "resid_years_positive": 3}
    assert gate_h6("A", ok) and gate_h6("B", {"alpha_bp_day": 0.1, "alpha_t_nw": 1.5})
    assert not gate_h6("A", {**ok, "alpha_t_nw": 1.99}) and not gate_h6("A", {**ok, "alpha_bp_day": 0.0})
    assert not gate_h6("A", {**ok, "sharpe_stress": 0.9}) and not gate_h6("A", {**ok, "resid_years_positive": 2})   # Sharpe equal -> fail
    assert not gate_h6("B", {"alpha_bp_day": -0.1, "alpha_t_nw": 3.0}) and not gate_h6("B", {"alpha_bp_day": 1.0, "alpha_t_nw": 1.49})
    assert not gate_h6("A", {**ok, "alpha_t_nw": float("nan")})


# ---------------------------------------------------------------- the holdout stays locked
def test_the_guard_raises_for_h6_positions_that_reach_2026():
    days = pd.bdate_range("2025-11-03", "2026-02-27")
    p = h6a(random_market(days, minutes=[16 * 60])).pos
    with pytest.raises(HoldoutError):
        score_positions(p, pd.DatetimeIndex(days), COSTS, "2025-12-01", "2026-01-31")
    with pytest.raises(HoldoutError):                                               # the last 2025 position exits in 2026
        score_positions(p, pd.DatetimeIndex(days), COSTS, "2025-11-03", "2025-12-31")
    score_positions(p, pd.DatetimeIndex(days), COSTS, "2025-11-03", "2025-12-30")  # a window whose exits are all in 2025 is fine


def test_the_batch_2_runner_never_unlocks_the_holdout():
    src = (Path(__file__).resolve().parents[1] / "run_batch2.py").read_text(encoding="utf-8")
    assert "unlock_holdout=True" not in src and "before=None" not in src and "Stage C" in src
