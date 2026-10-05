"""Gap kinds: holiday closures, broker session shifts after DST changes, early closes, intraday data gaps."""
import pandas as pd

from audit.t1_coverage import KIND_CLOSURE, KIND_DST, KIND_EARLY, KIND_OTHER, classify_gaps, dst_change_days


def test_dst_change_days_from_tz_database():
    d = dst_change_days(pd.Timestamp("2025-01-01"), pd.Timestamp("2025-12-31"))
    # US: 2nd Sunday of March, 1st Sunday of November; EU: last Sundays of March and October
    assert [str(x.date()) for x in d] == ["2025-03-09", "2025-03-30", "2025-10-26", "2025-11-02"]


def gap(start, end, minutes):
    return {"start_et": pd.Timestamp(start), "end_et": pd.Timestamp(end), "minutes_missing": minutes}


def test_classification():
    g = pd.DataFrame([
        gap("2025-04-02 15:59", "2025-04-02 16:59", 61),     # 3 days after the EU change: session shift
        gap("2025-04-04 15:59", "2025-04-04 16:54", 56),     # Friday break is earlier: still a session shift
        gap("2025-11-28 13:15", "2025-11-28 16:54", 220),    # day after Thanksgiving: early close
        gap("2025-06-10 15:59", "2025-06-10 16:58", 60),     # 1 h short but far from any DST change: early close
        gap("2025-12-24 18:00", "2025-12-25 16:58", 1379),   # holiday closure
        gap("2025-11-27 22:25", "2025-11-28 06:02", 458),    # overnight outage: other
    ])
    days = dst_change_days(pd.Timestamp("2025-01-01"), pd.Timestamp("2025-12-31"))
    assert list(classify_gaps(g, days)) == [KIND_DST, KIND_DST, KIND_EARLY, KIND_EARLY, KIND_CLOSURE, KIND_OTHER]
