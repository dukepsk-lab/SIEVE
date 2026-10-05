"""Hurdle table: the stress spread is the current regime's widest quote, and the comparison splits sigma from cost effects."""
import pytest

from audit.t6_vol import compare_with_assumptions, hurdle


def blk(p50, p99, mx, n=100):
    return {"N": n, "p50": p50, "p99": p99, "max_tick": mx}


SPREADS = {"regime_current": blk(1.43, 1.43, 2.0), "rth_current": blk(1.43, 1.43, 2.0),
           "open_bucket_current": blk(1.43, 1.43, 2.0), "close_bucket_current": blk(1.43, 1.43, 1.43),
           "worst_regime": {"open_bucket": blk(3.0, 3.4, 10.2), "close_bucket": blk(3.0, 3.6, 10.2)}}
SIG = {"5min": 28.0, "1h": 100.0, "6h": 250.0, "overnight": 230.0, "5d": 660.0}
MAD = {k: 0.8 * v for k, v in SIG.items()}


def test_stress_spread_is_widest_quote_for_every_horizon():
    h = hurdle(SIG, MAD, SPREADS, swap_long_pts=-4.0, commission_pts=0.0)
    stress = h[h["case"].str.startswith("stress (")]
    assert set(stress["horizon"]) == set(SIG)
    assert (stress["spread"] == 2.0).all()                     # not the p99 of the median (1.43)


def test_hit_rate_formula_and_swap():
    h = hurdle(SIG, MAD, SPREADS, swap_long_pts=-4.0, commission_pts=0.0)
    r = h[(h["horizon"] == "5min") & h["case"].str.startswith("stress (")].iloc[0]
    assert r["C_total_pts"] == pytest.approx(2.0 + 4.0)
    assert r["required_hit_rate_%"] == pytest.approx(100 * (0.5 + 6.0 / (1.6 * 28.0)), abs=0.01)
    on = h[(h["horizon"] == "overnight") & h["case"].str.startswith("stress (") & (h["side"] == "long")].iloc[0]
    assert on["C_total_pts"] == pytest.approx(2.0 + 4.0 + 4.0)   # one night of swap for the long


def test_stress_alt_uses_worst_past_regime():
    h = hurdle(SIG, MAD, SPREADS, swap_long_pts=-4.0, commission_pts=0.0)
    alt = h[h["case"].str.startswith("stress-alt")].set_index(["horizon", "side"])["spread"]
    assert alt[("5min", "n/a")] == 3.4 and alt[("overnight", "long")] == pytest.approx(3.5) and alt[("5d", "long")] == 3.6


def test_comparison_separates_sigma_and_cost():
    h = hurdle(SIG, MAD, SPREADS, swap_long_pts=-4.0, commission_pts=0.0)
    c = compare_with_assumptions(SIG, h, 0.0)
    r = c[(c["horizon"] == "5min") & (c["case"] == "stress")].iloc[0]
    assert r["hit rate: measured sigma, your C %"] == pytest.approx(100 * (0.5 + 12.0 / (1.6 * 28.0)), abs=0.01)   # 8 pt spread + 4 pt slippage
    assert r["hit rate measured %"] == pytest.approx(100 * (0.5 + 6.0 / (1.6 * 28.0)), abs=0.01)
