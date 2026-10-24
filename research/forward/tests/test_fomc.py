"""FOMC forward dates: parsed from the saved official page, never typed into the code."""
import datetime as dt

import pandas as pd
import pytest

from research.forward import FORWARD_START
from research.forward.fomc import COLUMNS, FOMC_FORWARD_CSV, SOURCE_HTML, forward_rows, parse_meetings, write_forward_csv
from research.variants2 import read_events

# read from the saved page (research/data/events_sources/fed_fomccalendars.html): the last day of each 2026-Q4 and 2027 meeting
EXPECTED = ["2026-10-28", "2026-12-09", "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09", "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08"]


@pytest.fixture(scope="module")
def page() -> str:
    return SOURCE_HTML.read_text(encoding="utf-8")


def test_the_saved_page_gives_the_2026_q4_and_2027_meetings(page):
    rows = forward_rows(page)
    assert [r["date_et"] for r in rows] == EXPECTED
    assert all(r["event"] == "FOMC" and r["time_et"] == "14:00" and r["scheduled"] is True and r["captured_on"] == "2026-10-05" for r in rows)
    assert all(r["source_url"] == "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm" for r in rows)
    assert all(dt.date.fromisoformat(r["date_et"]).weekday() < 5 for r in rows)
    assert all(pd.Timestamp(r["date_et"]) >= FORWARD_START for r in rows)


def test_every_table_of_the_forward_years_has_eight_meetings_and_earlier_dates_are_dropped(page):
    tables = parse_meetings(page, 2026)
    assert sorted(tables) == [2026, 2027] and all(len(v) == 8 for v in tables.values())
    assert [str(d) for d in tables[2026]][:6] == ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16"]
    assert "2026-09-16" not in [r["date_et"] for r in forward_rows(page)]


def test_the_csv_on_disk_is_exactly_the_parse_of_the_saved_page(page, tmp_path):
    write_forward_csv(tmp_path / "x.csv")
    assert (tmp_path / "x.csv").read_bytes() == FOMC_FORWARD_CSV.read_bytes()
    head = FOMC_FORWARD_CSV.read_text(encoding="utf-8").splitlines()[0]
    assert head.split(",") == COLUMNS == ["event", "date_et", "time_et", "scheduled", "source_url", "captured_on"]


def test_the_frozen_events_reader_accepts_the_file():
    ev = read_events(FOMC_FORWARD_CSV)
    assert len(ev) == 10 and set(ev["event"]) == {"FOMC"} and ev["scheduled"].all()
    assert [d.strftime("%Y-%m-%d") for d in ev["date"]] == EXPECTED


def _page(tables: dict, update="September 16, 2026") -> str:
    body = "".join(f"<h4>{y} FOMC Meetings</h4>" + "".join(f"<strong>{m}</strong><div>{d}</div>" for m, d in ms) for y, ms in tables.items())
    return f'<meta property="og:url" content="https://example.org/cal.htm"/>{body}<p>Last Update:</p><p>{update}</p>'


REGULAR = [("January", "27-28"), ("March", "17-18*"), ("April", "28-29"), ("June", "16-17*"), ("July", "28-29"), ("September", "15-16*"),
           ("October", "27-28"), ("December", "8-9*")]


def test_synthetic_pages_month_change_notation_votes_and_failures():
    ok = _page({2031: REGULAR})
    assert [r["date_et"] for r in forward_rows(ok, pd.Timestamp("2031-06-01"))] == ["2031-06-17", "2031-07-29", "2031-09-16", "2031-10-28", "2031-12-09"]
    cross = [("Jan/Feb", "31-1")] + REGULAR[1:]
    assert parse_meetings(_page({2033: cross}), 2033)[2033][0] == dt.date(2033, 2, 1)       # Jan/Feb 31-1: the statement is on Feb 1
    vote = REGULAR[:5] + [("August", "22 (notation vote)")] + REGULAR[5:]              # a vote on a strategy statement is not a meeting
    assert len(parse_meetings(_page({2031: vote}), 2031)[2031]) == 8
    with pytest.raises(ValueError):                                                      # a day token that is not understood: stop, do not guess
        parse_meetings(_page({2031: REGULAR[:-1] + [("December", "8-9 (video)")]}), 2031)
    with pytest.raises(ValueError):                                                      # a table that does not have 8 meetings
        parse_meetings(_page({2031: REGULAR[:-1]}), 2031)
    with pytest.raises(ValueError):                                                      # a weekend statement date
        parse_meetings(_page({2031: REGULAR[:-1] + [("December", "6-7")]}), 2031)
    with pytest.raises(ValueError):                                                      # no table at or after the year
        parse_meetings(ok, 2032)
    with pytest.raises(ValueError):                                                      # a page updated after the capture date
        forward_rows(_page({2031: REGULAR}, update="October 06, 2026"), pd.Timestamp("2031-01-01"))
