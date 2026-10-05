"""Tests for audit.tz: DST transitions, US/EU mismatch weeks, round trips, era switching."""
import numpy as np
import pandas as pd
import pytest

from audit.tz import NY_CLOSE, ServerClock

EET = ServerClock([("1900-01-01", "eu", 2)])          # UTC+2 winter / UTC+3 EU summer
LONDON = ServerClock([("1900-01-01", "eu", 0)])
NY5 = ServerClock([("1900-01-01", "ny", 5)])           # server = ET + 5h
UTC_FIXED = ServerClock([("1900-01-01", "fixed", 0)])


def ts(s):
    return pd.DatetimeIndex([s])


def et(clock, server):
    return str(clock.to_et(ts(server))[0])


def utc(clock, server):
    return str(clock.to_utc(ts(server))[0])


# ---- NY-close convention: 09:30 ET is always 16:30 server -------------------------------------------------
@pytest.mark.parametrize("server,expected_et", [
    ("2024-01-16 16:30", "2024-01-16 09:30:00"),      # deep winter
    ("2024-07-16 16:30", "2024-07-16 09:30:00"),      # deep summer
    ("2024-03-08 16:30", "2024-03-08 09:30:00"),      # Friday before US spring-forward
    ("2024-03-11 16:30", "2024-03-11 09:30:00"),      # Monday after it
    ("2024-03-18 16:30", "2024-03-18 09:30:00"),      # US/EU mismatch week (US summer, EU winter)
    ("2024-10-30 16:30", "2024-10-30 09:30:00"),      # mismatch week (EU winter again, US still summer)
    ("2024-11-01 16:30", "2024-11-01 09:30:00"),      # Friday before US fall-back
    ("2024-11-04 16:30", "2024-11-04 09:30:00"),      # Monday after it
])
def test_ny_close_open_is_1630(server, expected_et):
    assert et(NY_CLOSE, server) == expected_et


def test_ny_close_utc_offsets():
    assert utc(NY_CLOSE, "2024-01-16 16:30") == "2024-01-16 14:30:00"   # UTC+2
    assert utc(NY_CLOSE, "2024-07-16 16:30") == "2024-07-16 13:30:00"   # UTC+3
    assert utc(NY_CLOSE, "2024-03-18 16:30") == "2024-03-18 13:30:00"   # mismatch week: already UTC+3
    assert utc(NY_CLOSE, "2024-10-30 16:30") == "2024-10-30 13:30:00"   # mismatch week: still UTC+3


# ---- US/EU mismatch weeks tell the conventions apart --------------------------------------------------------
def test_mismatch_week_march_2024():
    """US DST began 2024-03-10, EU on 2024-03-31. On 2024-03-18 09:30 ET = 13:30 UTC."""
    s = {n: str(c.utc_to_server(ts("2024-03-18 13:30"))[0]) for n, c in
         dict(ny7=NY_CLOSE, ny5=NY5, eet=EET, london=LONDON, fixed=UTC_FIXED).items()}
    assert s == {"ny7": "2024-03-18 16:30:00", "ny5": "2024-03-18 14:30:00",
                 "eet": "2024-03-18 15:30:00", "london": "2024-03-18 13:30:00", "fixed": "2024-03-18 13:30:00"}


def test_mismatch_week_oct_2024():
    """EU DST ended 2024-10-27, US on 2024-11-03. On 2024-10-30 09:30 ET = 13:30 UTC."""
    s = {n: str(c.utc_to_server(ts("2024-10-30 13:30"))[0]) for n, c in
         dict(ny7=NY_CLOSE, ny5=NY5, eet=EET, london=LONDON).items()}
    assert s == {"ny7": "2024-10-30 16:30:00", "ny5": "2024-10-30 14:30:00",
                 "eet": "2024-10-30 15:30:00", "london": "2024-10-30 13:30:00"}


def test_ny5_and_london_agree_outside_mismatch_weeks():
    for d in ("2024-01-16 14:30", "2024-07-16 13:30", "2024-04-16 13:30", "2024-12-10 14:30"):
        assert NY5.utc_to_server(ts(d))[0] == LONDON.utc_to_server(ts(d))[0]


# ---- DST transition instants -----------------------------------------------------------------------------------
def test_ny_close_spring_forward_instant():
    """US spring-forward 2024-03-10 07:00 UTC: server jumps from UTC+2 (08:59) to UTC+3 (10:00)."""
    before = NY_CLOSE.utc_to_server(ts("2024-03-10 06:59"))[0]
    after = NY_CLOSE.utc_to_server(ts("2024-03-10 07:00"))[0]
    assert str(before) == "2024-03-10 08:59:00" and str(after) == "2024-03-10 10:00:00"


def test_ny_close_fall_back_instant():
    """US fall-back 2024-11-03 06:00 UTC: server falls from UTC+3 (08:59) to UTC+2 (08:00)."""
    before = NY_CLOSE.utc_to_server(ts("2024-11-03 05:59"))[0]
    after = NY_CLOSE.utc_to_server(ts("2024-11-03 06:00"))[0]
    assert str(before) == "2024-11-03 08:59:00" and str(after) == "2024-11-03 08:00:00"


def test_ambiguous_and_nonexistent_server_times_are_deterministic():
    amb = NY_CLOSE.to_utc(ts("2024-11-03 08:30"))[0]            # happens twice -> first occurrence (earlier UTC)
    assert str(amb) == "2024-11-03 05:30:00"
    gap = NY_CLOSE.to_utc(ts("2024-03-10 09:30"))[0]            # never happens -> pre-transition offset (UTC+3 read)
    assert str(gap) == "2024-03-10 06:30:00"


# ---- round trips ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("clock", [NY_CLOSE, EET, LONDON, NY5, UTC_FIXED], ids=["ny7", "eet", "london", "ny5", "fixed"])
def test_round_trip_utc_server_utc(clock):
    rng = np.random.default_rng(0)
    base = pd.Timestamp("2019-07-01")
    utc_idx = pd.DatetimeIndex(base + pd.to_timedelta(rng.integers(0, 8 * 365 * 24 * 60, 5000), unit="min")).sort_values()
    back = clock.to_utc(clock.utc_to_server(utc_idx))
    diff = utc_idx - back                       # only the repeated fall-back hour may differ (second pass -> first pass)
    assert set(diff.unique()) <= {pd.Timedelta(0), pd.Timedelta(hours=1)}
    assert (utc_idx[diff != pd.Timedelta(0)].dayofweek == 6).all()      # ... and only on Sundays


def test_round_trip_et():
    et_idx = pd.DatetimeIndex(["2024-01-16 09:30", "2024-07-16 09:30", "2024-03-18 08:30", "2024-10-30 14:00"])
    back = NY5.to_et(NY5.et_to_server(et_idx))
    assert (back == et_idx).all()


# ---- eras ---------------------------------------------------------------------------------------------------------
def test_era_switch():
    """UTC-fixed until 2022-03-01, then ET+5."""
    clk = ServerClock([("1900-01-01", "fixed", 0), ("2022-03-01", "ny", 5)])
    assert str(clk.utc_to_server(ts("2021-07-15 13:30"))[0]) == "2021-07-15 13:30:00"   # summer 2021: server = UTC
    assert str(clk.utc_to_server(ts("2022-07-15 13:30"))[0]) == "2022-07-15 14:30:00"   # summer 2022: server = UTC+1
    assert str(clk.utc_to_server(ts("2022-12-15 14:30"))[0]) == "2022-12-15 14:30:00"   # winter 2022: server = UTC
    assert et(clk, "2021-07-15 13:30") == "2021-07-15 09:30:00"
    assert et(clk, "2022-07-15 14:30") == "2022-07-15 09:30:00"


def test_json_round_trip(tmp_path):
    clk = ServerClock([("1900-01-01", "fixed", 0), ("2022-03-01", "ny", 5)])
    f = tmp_path / "c.json"
    clk.save(f, {"note": "x"})
    again = ServerClock.load(f)
    t = pd.DatetimeIndex(["2021-07-15 13:30", "2022-07-15 14:30"])
    assert (again.to_et(t) == clk.to_et(t)).all()
