"""Hand-computed checks of the per-minute time-weighted spread (LOCF) and the integrity counters."""
import numpy as np
import pandas as pd

from audit.tickdigest import digest_day

M = 28_000_000                       # an arbitrary minute index
T0 = M * 60_000                      # its start in ms


def ticks(rows):
    """rows: (offset_ms_from_T0, bid_pts, ask_pts[, flags])"""
    df = pd.DataFrame(rows, columns=["dt", "bid", "ask", "flags"][:len(rows[0])])
    if "flags" not in df:
        df["flags"] = 6
    out = pd.DataFrame({"time_msc": (T0 + df["dt"]).astype("int64"), "bid": df["bid"].astype("int32"), "ask": df["ask"].astype("int32"),
                        "flags": df["flags"].astype("uint16"), "last": np.int32(0), "volume": np.uint32(0), "volume_real": np.float32(0)})
    return out


def test_time_weighted_stats_inside_one_minute():
    # spread 10 for 20 s, 30 for 10 s, 10 for 30 s
    m, h, c = digest_day(ticks([(0, 100000, 100010), (20_000, 100005, 100035), (30_000, 100000, 100010)]))
    r = m.iloc[0]
    assert r["m"] == M and r["n"] == 3
    assert (r["s_min"], r["s_med"], r["s_max"], r["s_last"]) == (10, 10, 30, 10)
    assert abs(r["s_mean"] - (10 * 50 + 30 * 10) / 60) < 1e-9
    assert (r["bo"], r["bh"], r["bl"], r["bc"]) == (100000, 100005, 100000, 100000)
    assert (r["ao"], r["ah"], r["al"], r["ac"]) == (100010, 100035, 100010, 100010)
    assert r["s_carry"] == -1                                   # nothing before the first tick of the day


def test_weighted_median_follows_time_not_tick_count():
    # one tick at spread 10 for 5 s, then spread 40 for 55 s; plus two more quick ticks at 10 -> tick-median is 10, time-median is 40
    m, _, _ = digest_day(ticks([(0, 100000, 100010), (1_000, 100000, 100010), (2_000, 100000, 100010), (5_000, 100000, 100040)]))
    assert m.iloc[0]["s_med"] == 40
    assert m.iloc[0]["s_min"] == 10 and m.iloc[0]["s_max"] == 40


def test_carry_in_from_previous_minute():
    # last quote of minute M-1 has spread 50 and is carried into minute M until its first tick at +15 s
    m, _, _ = digest_day(ticks([(-30_000, 100000, 100050), (15_000, 100000, 100010)]))
    r = m[m["m"] == M].iloc[0]
    assert r["s_carry"] == 50
    assert r["s_max"] == 50 and r["s_min"] == 10 and r["s_med"] == 10          # 50 for 15 s, 10 for 45 s
    assert abs(r["s_mean"] - (50 * 15 + 10 * 45) / 60) < 1e-9


def test_no_carry_across_a_long_gap():
    m, _, _ = digest_day(ticks([(-20 * 60_000, 100000, 100050), (15_000, 100000, 100010)]))     # previous quote is 20 min old
    assert m[m["m"] == M].iloc[0]["s_carry"] == -1


def test_integrity_counters_and_exclusions():
    tk = ticks([(0, 100000, 100010), (1_000, 0, 100010), (2_000, 100020, 100000), (3_000, 100000, 100000), (3_000, 100000, 100000)])
    m, h, c = digest_day(tk)
    assert c["n_ticks"] == 5 and c["n_nonpositive_price"] == 1
    assert c["n_crossed"] == 1 and c["n_zero_spread"] == 2                  # crossed quote excluded, zero spread kept
    assert c["n_exact_duplicates"] == 1
    assert m.iloc[0]["s_max"] == 10 and m.iloc[0]["s_min"] == 0


def test_non_monotonic_time_is_counted_and_sorted():
    m, _, c = digest_day(ticks([(5_000, 100000, 100010), (1_000, 100000, 100030), (9_000, 100000, 100010)]))
    assert c["n_nonmonotonic"] == 1
    assert m.iloc[0]["s_max"] == 30 and m.iloc[0]["bo"] == 100000


def test_tick_weighted_histogram():
    _, h, _ = digest_day(ticks([(0, 100000, 100010), (1_000, 100000, 100010), (2_000, 100000, 100030)]))
    got = {int(s): int(n) for s, n in zip(h["s"], h["n"])}
    assert got == {10: 2, 30: 1}
    assert (h["bucket"] == ((T0 // 1000) % 86400) // 1800).all()
