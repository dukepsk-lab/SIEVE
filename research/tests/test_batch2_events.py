"""Batch 2 events: H3a, H8a, H8b entry/exit times, skips, one trade per day, E0, the events file, PENDING, the holdout guard."""
import numpy as np
import pandas as pd
import pytest

from research.data import Costs, Market
from research.evaluate import HoldoutError, score_trades
from research.inference import welch
from research.run_batch2 import pending_status, run_batch
from research.tests.synth import random_market
from research.variants import R_ENTRY, R_EXIT, R_SIGNAL
from research.variants2 import e0, event_days, h3a, h8a, h8b, parse_events, read_events

MINUTES = [9 * 60 + 30, 13 * 60 + 55, 14 * 60, 16 * 60]
DAYS = [d for d in pd.bdate_range("2024-01-01", periods=40) if d != pd.Timestamp("2024-01-15")]    # Mon 15 Jan: market holiday
MKT = random_market(DAYS, minutes=MINUTES)
T = pd.Timestamp
COSTS = Costs(2.43, 6.0, 10_000.0)


def events(rows) -> pd.DataFrame:
    """rows: (event, date, scheduled) -> normalised frame, through the real parser (raw csv column names)."""
    return parse_events(pd.DataFrame([{"event": e, "date_et": d, "time_et": "", "scheduled": str(s)} for e, d, s in rows]))


EV = events([("FOMC", "2024-01-16", True),     # Tue after the Monday holiday: d-1 is Fri 12 Jan
             ("FOMC", "2024-01-31", True),
             ("CPI", "2024-01-31", True),      # coincides with the FOMC day
             ("CPI", "2024-01-11", True),
             ("CPI", "2024-02-13", True),
             ("NFP", "2024-02-02", True),
             ("FOMC", "2024-02-14", False),    # unscheduled: in no variant, and not a "non-event" day for E0 either
             ("CPI", "2024-02-20", False)])


def open_at(m: Market, ts) -> float:
    return float(m.P[0].loc[pd.Timestamp(ts)])


def without(m: Market, *stamps) -> Market:
    o, c = m.P
    drop = pd.DatetimeIndex(stamps)
    return Market(o.drop(drop), c.drop(drop))


def entries_exits(r):
    return [(a.strftime("%m-%d %H:%M"), b.strftime("%m-%d %H:%M")) for a, b in zip(r.trades["entry_et"], r.trades["exit_et"])]


# ---------------------------------------------------------------- H3a
def test_h3a_enters_1400_the_previous_trading_day_and_exits_1355_on_the_fomc_day():
    r = h3a(MKT, EV)
    assert entries_exits(r) == [("01-12 14:00", "01-16 13:55"), ("01-30 14:00", "01-31 13:55")]    # unscheduled 14 Feb excluded
    assert (r.trades["direction"] == 1).all() and r.skips.empty
    assert r.trades["entry_px"].tolist() == [open_at(MKT, "2024-01-12 14:00"), open_at(MKT, "2024-01-30 14:00")]
    assert r.trades["exit_px"].tolist() == [open_at(MKT, "2024-01-16 13:55"), open_at(MKT, "2024-01-31 13:55")]


def test_h3a_skips_a_missing_price_and_never_fills_it():
    m = without(MKT, "2024-01-12 14:00", "2024-01-12 13:55", "2024-01-31 13:55")      # no bar within 5 minutes before either price
    r = h3a(m, EV)
    assert r.trades.empty
    assert dict(zip(r.skips["date"], r.skips["reason"])) == {T("2024-01-16"): R_ENTRY, T("2024-01-31"): R_EXIT}


def test_h3a_uses_the_last_bar_when_it_started_within_5_minutes():
    m = without(MKT, "2024-01-30 14:00")                                              # 13:55 bar is exactly 5 minutes older: still valid
    r = h3a(m, EV)
    assert r.skips.empty and r.trades["entry_px"].iloc[1] == float(m.P[1].loc[T("2024-01-30 13:55")])


# ---------------------------------------------------------------- H8a
def test_h8a_is_one_trade_per_day_for_the_union_of_event_days():
    r = h8a(MKT, EV)
    assert entries_exits(r) == [("01-10 16:00", "01-11 16:00"), ("01-12 16:00", "01-16 16:00"), ("01-30 16:00", "01-31 16:00"),
                                ("02-01 16:00", "02-02 16:00"), ("02-12 16:00", "02-13 16:00")]
    assert r.trades["exit_et"].dt.normalize().is_unique                               # FOMC + CPI on 31 Jan: a single trade
    assert (r.trades["direction"] == 1).all() and r.skips.empty


def test_h8a_skip_reasons_missing_prices_non_trading_days_and_first_day():
    ev = pd.concat([EV, events([("NFP", "2024-01-15", True), ("CPI", "2024-01-20", True), ("FOMC", "2024-01-01", True)])], ignore_index=True)
    m = without(MKT, "2024-01-10 16:00", "2024-02-02 16:00")
    r = h8a(m, ev)
    got = dict(zip(r.skips["date"], r.skips["reason"]))
    assert got == {T("2024-01-01"): R_SIGNAL,                                          # no previous trading day
                   T("2024-01-11"): R_ENTRY,                                           # no P(16:00, 10 Jan)
                   T("2024-01-15"): R_SIGNAL,                                          # holiday: not a trading day
                   T("2024-01-20"): R_SIGNAL,                                          # Saturday
                   T("2024-02-02"): R_EXIT}                                            # no P(16:00, 2 Feb)
    assert entries_exits(r) == [("01-12 16:00", "01-16 16:00"), ("01-30 16:00", "01-31 16:00"), ("02-12 16:00", "02-13 16:00")]


# ---------------------------------------------------------------- H8b
def test_h8b_covers_cpi_and_nfp_and_exits_at_the_open():
    r = h8b(MKT, EV)
    assert entries_exits(r) == [("01-10 16:00", "01-11 09:30"), ("01-30 16:00", "01-31 09:30"),
                                ("02-01 16:00", "02-02 09:30"), ("02-12 16:00", "02-13 09:30")]   # the FOMC-only day 16 Jan is not in it
    assert r.skips.empty and (r.trades["direction"] == 1).all()
    assert r.trades["exit_px"].tolist() == [open_at(MKT, f"2024-{d} 09:30") for d in ("01-11", "01-31", "02-02", "02-13")]


def test_h8b_skips_a_missing_open():
    r = h8b(without(MKT, "2024-02-02 09:30"), EV)
    assert r.skips[["date", "reason"]].values.tolist() == [[T("2024-02-02"), R_EXIT]] and len(r.trades) == 3


def test_one_trade_per_day_when_events_coincide():
    ev = events([("CPI", "2024-02-02", True), ("NFP", "2024-02-02", True), ("FOMC", "2024-02-02", True)])
    for build in (h3a, h8a, h8b):
        assert len(build(MKT, ev).trades) == 1


def test_events_outside_the_market_are_ignored_and_the_holdout_is_never_a_candidate():
    ev = events([("FOMC", "2019-03-20", True), ("FOMC", "2026-03-18", True), ("CPI", "2026-01-13", True), ("NFP", "2024-02-02", True)])
    assert list(event_days(ev, MKT, ("FOMC", "CPI", "NFP"))) == [T("2024-02-02")]
    assert len(h8a(MKT, ev).trades) == 1 and h8a(MKT, ev).skips.empty and h3a(MKT, ev).trades.empty and h3a(MKT, ev).skips.empty


# ---------------------------------------------------------------- E0
def test_e0_is_the_h8a_trade_on_every_non_event_day_and_excludes_event_days():
    r = e0(MKT, EV)
    event_dates = {T(x) for x in ["2024-01-16", "2024-01-31", "2024-01-11", "2024-02-13", "2024-02-02", "2024-02-14", "2024-02-20"]}
    exit_days = set(r.trades["exit_et"].dt.normalize())
    assert exit_days.isdisjoint(event_dates)                                           # incl. the unscheduled 14 and 20 Feb
    assert exit_days | set(r.skips["date"]) | event_dates >= set(MKT.days)             # every other trading day is a candidate
    assert set(r.skips["date"]) == {T("2024-01-01")}                                   # the first day has no previous close
    assert ((r.trades["exit_et"] - r.trades["entry_et"]) >= pd.Timedelta(hours=24)).all()
    assert (r.trades["entry_et"].dt.hour == 16).all() and (r.trades["exit_et"].dt.hour == 16).all()
    assert len(r.trades) == len(MKT.days) - len(event_dates & set(MKT.days)) - 1
    both = set(h8a(MKT, EV).trades["exit_et"].dt.normalize())
    assert both.isdisjoint(exit_days)                                                  # H8a and E0 never share a day


def test_e0_with_an_empty_events_file_would_be_every_day_so_it_is_pending():
    ev = events([])
    assert len(e0(MKT, ev).trades) == len(MKT.days) - 1
    assert set(pending_status(ev, MKT).values()) == {"PENDING (events.csv missing)"}


# ---------------------------------------------------------------- the events file and PENDING
def test_read_events_handles_a_missing_empty_and_real_file(tmp_path):
    assert read_events(tmp_path / "nope.csv").empty
    (tmp_path / "zero.csv").write_text("", encoding="utf-8")
    assert read_events(tmp_path / "zero.csv").empty
    (tmp_path / "head.csv").write_text("event,date_et,time_et,scheduled,source_url,note\n", encoding="utf-8")
    assert read_events(tmp_path / "head.csv").empty
    (tmp_path / "ev.csv").write_text("event,date_et,time_et,scheduled,source_url,note\n"
                                     "FOMC,2024-01-31,14:00,True,https://x,\n"
                                     "cpi,2024-02-13,08:30,true,https://y,\n"
                                     "FOMC,2024-03-04,14:00,False,https://z,emergency\n", encoding="utf-8")
    ev = read_events(tmp_path / "ev.csv")
    assert ev["event"].tolist() == ["FOMC", "CPI", "FOMC"] and ev["scheduled"].tolist() == [True, True, False]
    assert ev["date"].dtype == "datetime64[ns]" and ev["date"].iloc[0] == T("2024-01-31")
    assert list(event_days(ev, MKT, ("FOMC",))) == [T("2024-01-31")]                   # the unscheduled meeting is not a candidate


def test_parse_events_is_strict_about_unknown_values():
    with pytest.raises(ValueError):
        events([("PCE", "2024-01-31", True)])
    with pytest.raises(ValueError):
        parse_events(pd.DataFrame({"event": ["CPI"], "date_et": ["2024-01-31"], "scheduled": ["maybe"]}))
    with pytest.raises(ValueError):
        parse_events(pd.DataFrame({"event": ["CPI"], "date": ["2024-01-31"]}))
    assert parse_events(pd.DataFrame({"event": ["CPI"], "date_et": ["2024-01-31"], "scheduled": [""]}))["scheduled"].tolist() == [False]


def test_pending_status_per_variant():
    only_fomc = events([("FOMC", "2024-01-31", True)])
    st = pending_status(only_fomc, MKT)
    assert st["H3a"] is None and st["H8a"] is None and st["E0"] is None and st["H8b"].startswith("PENDING")
    assert pending_status(EV, MKT) == {"H3a": None, "H8a": None, "H8b": None, "E0": None}


# ---------------------------------------------------------------- end to end on a synthetic market, 2019-07-16 .. 2025-12-31
LONG = random_market(pd.bdate_range("2019-07-16", "2025-12-31"), seed=1, minutes=MINUTES)


def test_run_batch_marks_event_variants_pending_without_failing():
    a, a_year, b, b_year, survivors = run_batch(LONG, COSTS, events([]))
    st = a.set_index("variant")["status"]
    assert list(a["variant"]) == ["H6a", "H6b", "H3a", "H8a", "H8b", "C2", "E0"]
    assert st[["H3a", "H8a", "H8b", "E0"]].tolist() == ["PENDING (events.csv missing)"] * 4
    assert st["C2"] == "control" and st["H6a"] in ("PASS", "FAIL") and set(survivors) <= {"H6a", "H6b"}
    assert set(a_year["variant"]) == {"H6a", "H6b", "C2"} and set(b["variant"]) == set(survivors) == set(b_year["variant"]) or b.empty


def test_run_batch_with_events_scores_event_variants_and_reports_e0_against_h8a():
    rng = np.random.default_rng(0)
    d = pd.DatetimeIndex(rng.choice(LONG.days[100:1100], 90, replace=False)).sort_values()
    ev = events([(k, x.strftime("%Y-%m-%d"), True) for k, x in zip(np.resize(["FOMC", "CPI", "NFP"], 90), d)])
    a, _, _, _, _ = run_batch(LONG, COSTS, ev)
    row = a.set_index("variant")
    assert (row.loc[["H3a", "H8a", "H8b", "E0"], "status"] != "PENDING (events.csv missing)").all()
    assert row.loc["E0", "role"] == "control" and row.loc["E0", "status"] == "control"
    assert row.loc["H8a", "trades"] == 90 and row.loc["E0", "n_h8a"] == 90
    assert row.loc["E0", "n_e0"] == row.loc["E0", "trades"] and row.loc["E0", "n_h8a"] + row.loc["E0", "n_e0"] <= row.loc["E0", "days"]   # entry days are disjoint
    assert np.isfinite(row.loc["E0", ["h8a_minus_e0_bp", "welch_t", "welch_df"]].astype(float)).all()


def test_welch_difference_and_t_for_a_known_example():
    w = welch([1.0, 2.0, 3.0, 4.0], [10.0, 12.0, 14.0, 16.0, 18.0])
    assert w["diff"] == pytest.approx(2.5 - 14.0) and w["n_a"] == 4 and w["n_b"] == 5
    assert w["t"] == pytest.approx(-11.5 / np.sqrt(1.6667 / 4 + 10.0 / 5), rel=1e-3)


# ---------------------------------------------------------------- the holdout guard still raises for 2026 dates
def test_guard_raises_when_an_event_trade_reaches_2026():
    days = [d for d in pd.bdate_range("2025-12-15", "2026-02-27")]
    m = random_market(days, minutes=MINUTES)                                           # an UNCUT market that includes 2026
    ev = events([("FOMC", "2025-12-17", True), ("CPI", "2026-01-13", True)])
    for build in (h3a, h8a, h8b):
        r = build(m, ev)
        with pytest.raises(HoldoutError):
            score_trades(r.trades, pd.DatetimeIndex(days), COSTS, "2025-12-01", "2026-03-31")
    r = h8a(m, ev)
    with pytest.raises(HoldoutError):                                                  # enters 2025-12-31 -> exits 2026: still refused
        score_trades(h8a(m, events([("CPI", "2026-01-01", True)])).trades, pd.DatetimeIndex(days), COSTS, "2025-12-01", "2025-12-31")
    score_trades(r.trades.iloc[:1], pd.DatetimeIndex(days), COSTS, "2025-12-01", "2025-12-31")   # the 2025 trade alone is fine
