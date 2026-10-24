"""Build research/data/events.csv from the raw official-source captures in research/data/events_sources/.

Nothing here is typed from memory: every date and time is parsed from a saved source file.

Sources (all saved under events_sources/):
  FOMC  fed_fomccalendars.html            federalreserve.gov calendar page (meetings 2021-2027)
        fed_fomchistorical2019/2020.html  federalreserve.gov historical pages (2019, 2020 meetings, unscheduled meetings, notation votes)
        fed_statements/monetary*.htm      the press-release page of every statement (date line + "For release at H:MM a.m./p.m. EDT|EST")
  CPI   bls_cpi_archive_anchors.txt       BLS archive page; the archive file name embeds the actual release date
  NFP   bls_empsit_archive_anchors.txt    same, Employment Situation
        bls_schedule_pages_2019_2025.txt  BLS yearly release calendars: independent cross-check of every CPI/NFP date, and the source of the release time
        bls_shutdown_release_excerpts.txt text of the four releases affected by the Oct 1 - Nov 12 2025 lapse in appropriations

Window: 2019-07-01 .. 2025-12-31 (2026 is a locked holdout and is never added).
"""
from __future__ import annotations

import csv
import datetime as dt
import html
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "events_sources"
OUT = HERE / "events.csv"
START, END = dt.date(2019, 7, 1), dt.date(2025, 12, 31)

MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"], 1)}
MON3 = {k[:3]: v for k, v in MONTHS.items()}
FED = "https://www.federalreserve.gov"


def text_lines(fn: Path) -> list[str]:
    t = fn.read_text(encoding="utf-8")
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", t, flags=re.S)
    t = html.unescape(re.sub(r"<[^>]+>", "\n", t))
    return [l.strip() for l in t.split("\n") if l.strip()]


def end_month_day(mon_label: str, days: str, year: int) -> dt.date:
    """'Jan/Feb' + '31-1' -> (Feb 1); 'March' + '18-19*' -> Mar 19; 'March' + '2' -> Mar 2."""
    days = days.replace("*", "").strip()
    last = int(days.split("-")[-1])
    if "/" in mon_label:
        mon = MON3[mon_label.split("/")[-1][:3]]
    else:
        mon = MONTHS[mon_label] if mon_label in MONTHS else MON3[mon_label[:3]]
    return dt.date(year, mon, last)


def statement_page(sid: str) -> tuple[dt.date, str, str]:
    """Parse a saved Fed press-release page -> (date on page, HH:MM ET, headline)."""
    L = text_lines(SRC / "fed_statements" / f"monetary{sid}.htm")
    i = next(k for k, l in enumerate(L) if re.search(r"For release at", l))
    m = re.fullmatch(r"For release at (\d{1,2}):(\d{2}) ([ap])\.m\. (EDT|EST)", L[i])
    assert m, L[i]
    hh = int(m.group(1)) % 12 + (12 if m.group(3) == "p" else 0)
    d = dt.datetime.strptime(L[i - 2], "%B %d, %Y").date()
    return d, f"{hh:02d}:{m.group(2)}", L[i - 1]


def build_fomc() -> list[dict]:
    rows: list[dict] = []
    # ---- regular meetings 2021-2025 from the calendar page --------------------------------------
    cal_html = (SRC / "fed_fomccalendars.html").read_text(encoding="utf-8")
    L = text_lines(SRC / "fed_fomccalendars.html")
    year, i, meetings = None, 0, []
    while i < len(L):
        m = re.fullmatch(r"(20\d\d) FOMC Meetings", L[i])
        if m:
            year = int(m.group(1)); i += 1; continue
        if year and (L[i] in MONTHS or re.fullmatch(r"[A-Z][a-z]{2}/[A-Z][a-z]{2}", L[i])):
            meetings.append((year, L[i], L[i + 1])); i += 2; continue
        i += 1
    for yr, mon, days in meetings:
        if "notation vote" in days:
            # Aug 22 2025: notation vote on the Statement on Longer-Run Goals; no policy statement -> excluded (see report).
            continue
        d_end = end_month_day(mon, days, yr)
        if not (START <= d_end <= END):
            continue
        sid = d_end.strftime("%Y%m%d") + "a"
        assert f'href="/newsevents/pressreleases/monetary{sid}.htm"' in cal_html, f"calendar has no statement link for {d_end}"
        pd_, tm, head = statement_page(sid)
        assert pd_ == d_end, (pd_, d_end)
        assert head == "Federal Reserve issues FOMC statement", head
        rows.append(dict(event="FOMC", date_et=d_end.isoformat(), time_et=tm, scheduled=True,
                         source_url=f"{FED}/newsevents/pressreleases/monetary{sid}.htm",
                         note=f"Meeting {mon} {days.replace('*', '')} {yr}; dates from {FED}/monetarypolicy/fomccalendars.htm; time from statement page"))
    # ---- 2019-2020 from the historical pages ----------------------------------------------------
    for hy in (2019, 2020):
        raw = (SRC / f"fed_fomchistorical{hy}.html").read_text(encoding="utf-8")
        page_url = f"{FED}/monetarypolicy/fomchistorical{hy}.htm"
        parts = re.split(r'<h5 class="panel-heading[^"]*">', raw)[1:]
        for p in parts:
            title, body = p.split("</h5>", 1)
            body = body.split('<div class="panel panel-default', 1)[0]
            title = html.unescape(title).strip()
            m = re.fullmatch(r"([A-Za-z/]+) ([\d\-]+)(?: \(([^)]+)\))?(?: Meeting)? - (\d{4})", title)
            if not m:
                continue
            mon, days, tag, yr = m.group(1), m.group(2), m.group(3), int(m.group(4))
            d_nom = end_month_day(mon, days, yr)
            if tag == "cancelled":
                continue                                   # Mar 17-18 2020 meeting never took place
            if not (START <= d_nom <= END):
                continue                                   # outside the window (statement pages were fetched only for in-window items)
            # anchors whose text is exactly "Statement" or "Press Release" (policy releases); the strategy-statement-only
            # notation vote (Aug 27 2020) has only a "Statement on Longer-Run Goals ..." anchor and is therefore excluded
            links = re.findall(r'<a href="(/newsevents/pressreleases/monetary(\d{8}[a-z]))\.htm">(Statement|Press Release)</a>', body)
            if not links:
                assert tag and "notation vote" in tag, f"no statement link in block {title}"
                continue
            href, sid, _ = links[0]
            pd_, tm, head = statement_page(sid)
            if not (START <= pd_ <= END):
                continue
            sched = tag is None
            if sched:
                assert pd_ == d_nom, (title, pd_, d_nom)
                assert head == "Federal Reserve issues FOMC statement", head
                note = f"Meeting {mon} {days} {yr}; dates from {page_url}; time from statement page"
            else:
                note = (f"UNSCHEDULED: Fed page lists '{title}'; release page '{head}' dated {pd_.isoformat()}; "
                        f"nominal date {d_nom.isoformat()}; listed on {page_url}")
            rows.append(dict(event="FOMC", date_et=pd_.isoformat(), time_et=tm, scheduled=sched,
                             source_url=f"{FED}{href}.htm", note=note))
    return rows


def parse_archive(fn: Path, prefix: str) -> list[tuple[str, dt.date, str]]:
    out = []
    for l in fn.read_text(encoding="utf-8").split("\n"):
        if not l or l.startswith("#"):
            continue
        text, href = [x.strip() for x in l.split("|")]
        m = re.fullmatch(rf"{prefix}_(\d{{2}})(\d{{2}})(\d{{4}})\.htm", href)
        ref = re.match(r"([A-Z][a-z]+ \d{4}) ", text).group(1)
        out.append((ref, dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2))), href))
    return out


def parse_schedule() -> dict[tuple[str, str], tuple[dt.date, str]]:
    """(kind, 'Month YYYY' reference) -> (date, 'HH:MM') from the BLS yearly calendar pages."""
    out = {}
    for l in (SRC / "bls_schedule_pages_2019_2025.txt").read_text(encoding="utf-8").split("\n"):
        if not l or l.startswith("#"):
            continue
        m = re.fullmatch(r"(\w+), ([A-Z][a-z]+ \d{1,2}, \d{4}) (\d{2}):(\d{2}) (AM|PM) (Employment Situation|Consumer Price Index) for ([A-Z][a-z]+ \d{4})", l)
        assert m, l
        d = dt.datetime.strptime(m.group(2), "%B %d, %Y").date()
        assert d.strftime("%A") == m.group(1), l
        hh = int(m.group(3)) % 12 + (12 if m.group(5) == "PM" else 0)
        kind = "CPI" if m.group(6).startswith("Consumer") else "NFP"
        key = (kind, m.group(7))
        assert key not in out, key
        out[key] = (d, f"{hh:02d}:{m.group(4)}")
    return out


SHUTDOWN_NOTES = {
    ("CPI", "September 2025"): ("released 2025-10-24 during the Oct 1 - Nov 12 2025 lapse in appropriations; BLS release page: "
                                "'September CPI data collection was completed before the lapse in appropriations'; "
                                "BLS 2025 calendar lists it on this date"),
    ("CPI", "November 2025"): ("released 2025-12-18; covers Sep->Nov (BLS did not collect October 2025 survey data due to the lapse); "
                               "October 2025 CPI was NOT published (archive page: 'Not published because of 2025 lapse in federal government appropriations')"),
    ("NFP", "September 2025"): ("released 2025-11-20; RESCHEDULED: BLS release page says publication of September data was delayed by more than 6 weeks "
                                "because of the lapse in appropriations"),
    ("NFP", "November 2025"): ("released 2025-12-16; RESCHEDULED: BLS release page says publication of November data was delayed by more than a week "
                               "(lapse Oct 1 - Nov 12 2025); BLS did not publish an October 2025 Employment Situation release"),
}
READ_PAGES = {("CPI", "September 2025"), ("CPI", "November 2025"), ("NFP", "September 2025"), ("NFP", "November 2025")}


def build_bls() -> list[dict]:
    sched = parse_schedule()
    rows = []
    for kind, fn, prefix, idx in (("CPI", "bls_cpi_archive_anchors.txt", "cpi", "https://www.bls.gov/bls/news-release/cpi.htm"),
                                  ("NFP", "bls_empsit_archive_anchors.txt", "empsit", "https://www.bls.gov/bls/news-release/empsit.htm")):
        for ref, d, href in parse_archive(SRC / fn, prefix):
            if not (START <= d <= END):
                continue
            s = sched.get((kind, ref))
            assert s is not None, f"{kind} {ref}: not on the BLS calendar pages"
            assert s[0] == d, f"{kind} {ref}: archive says {d}, calendar says {s[0]}"
            assert d.weekday() < 5
            note = f"ref {ref}; date from archive index {idx}; matches BLS calendar https://www.bls.gov/schedule/{d.year}/home.htm (time {s[1]} ET)"
            if (kind, ref) in SHUTDOWN_NOTES:
                note = f"ref {ref}; " + SHUTDOWN_NOTES[(kind, ref)] + f"; archive index {idx}; calendar https://www.bls.gov/schedule/{d.year}/home.htm"
                if (kind, ref) in READ_PAGES:
                    note += "; release page read (embargo line confirms 8:30 a.m. ET)"
            rows.append(dict(event=kind, date_et=d.isoformat(), time_et=s[1], scheduled=True,
                             source_url=f"https://www.bls.gov/news.release/archives/{href}", note=note))
    # every calendar entry inside the window must have appeared in the archive (two-way check)
    arch = {(r["event"], r["date_et"]) for r in rows}
    for (kind, ref), (d, tm) in sched.items():
        if START <= d <= END:
            assert (kind, d.isoformat()) in arch, f"calendar has {kind} {ref} on {d} but the archive does not"
    return rows


def main() -> None:
    rows = build_fomc() + build_bls()
    rows.sort(key=lambda r: (r["date_et"], r["time_et"], r["event"]))
    cols = ["event", "date_et", "time_et", "scheduled", "source_url", "note"]
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> research/data/{OUT.name}")  # not the absolute path: it contains Thai characters (cp1252 console)
    from collections import Counter
    c = Counter((r["event"], r["date_et"][:4], r["scheduled"]) for r in rows)
    for k in sorted(c):
        print(k, c[k])


if __name__ == "__main__":
    sys.exit(main())
