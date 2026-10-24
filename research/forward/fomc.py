"""Scheduled FOMC statement dates on or after FORWARD_START, parsed from the saved official Federal Reserve calendar page.

Source: research/data/events_sources/fed_fomccalendars.html (captured 2026-10-05, PLAN section 10). Nothing is typed from memory:
every date comes from the meeting tables of that page, and any structure that is not understood raises (stop and report) instead
of being guessed. The statement date is the last day of a meeting. Only regular (scheduled) meetings are in the tables, so
unscheduled meetings are excluded by construction. The statement time (14:00 ET) is fixed by PLAN section 9, because the page
carries no release time for future meetings.

Usage (repo root):  python -m research.forward.fomc      writes research/data/fomc_forward.csv
"""
import csv
import datetime as dt
import html
import re
from pathlib import Path

from . import FORWARD_START

DATA = Path(__file__).resolve().parents[1] / "data"
SOURCE_HTML = DATA / "events_sources" / "fed_fomccalendars.html"
FOMC_FORWARD_CSV = DATA / "fomc_forward.csv"
CAPTURED_ON = "2026-10-05"                     # PLAN section 10: "the official Federal Reserve calendar page saved on 2026-10-05"
STATEMENT_TIME_ET = "14:00"
COLUMNS = ["event", "date_et", "time_et", "scheduled", "source_url", "captured_on"]
MEETINGS_PER_YEAR = 8                          # the Fed's regular schedule; a table with another count is not parsed silently

MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September",
                                      "October", "November", "December"], 1)}
MON3 = {k[:3]: v for k, v in MONTHS.items()}
_DAYS = re.compile(r"(\d{1,2})(?:-(\d{1,2}))?\*?")      # '27-28', '17-18*', '31-1' (month change), '8' (one day)
_NOTATION = re.compile(r"\d{1,2} \(notation vote\)")   # a vote on a non-policy statement: no FOMC policy statement, not a meeting
_YEAR_HEAD = re.compile(r"(20\d\d) FOMC Meetings")


def text_lines(raw: str) -> list[str]:
    raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", raw, flags=re.S)
    return [x.strip() for x in html.unescape(re.sub(r"<[^>]+>", "\n", raw)).split("\n") if x.strip()]


def _end_date(year: int, month_label: str, days: str) -> dt.date:
    """'October' + '27-28' -> Oct 28; 'Jan/Feb' + '31-1' -> Feb 1. Raises on anything else."""
    m = _DAYS.fullmatch(days)
    if not m:
        raise ValueError(f"cannot parse meeting days {days!r} (month {month_label!r}, year {year})")
    first, last = int(m.group(1)), int(m.group(2) or m.group(1))
    if "/" in month_label:
        a, b = (MON3[p[:3]] for p in month_label.split("/"))
        if b != a + 1 or not first > last:
            raise ValueError(f"cannot resolve a meeting across months {month_label!r} {days!r} in {year}")
        month = b
    else:
        month = MONTHS[month_label]
        if last - first not in (0, 1):
            raise ValueError(f"unexpected meeting length {days!r} in {month_label} {year}")
    d = dt.date(year, month, last)
    if d.weekday() >= 5:
        raise ValueError(f"FOMC statement date {d} is a weekend")
    return d


def parse_meetings(raw: str, min_year: int) -> dict[int, list[dt.date]]:
    """{year: [statement date, ...]} for every 'YYYY FOMC Meetings' table with year >= min_year (older tables, with their notation
    votes and cancellations, are not needed and not read). A table with other than 8 regular meetings raises."""
    lines = text_lines(raw)
    out: dict[int, list[dt.date]] = {}
    year, i = None, 0
    while i < len(lines):
        head = _YEAR_HEAD.fullmatch(lines[i])
        if head:
            year = int(head.group(1))
            if year >= min_year:
                out[year] = []
        elif year in out and (lines[i] in MONTHS or re.fullmatch(r"[A-Z][a-z]{2}/[A-Z][a-z]{2}", lines[i])):
            if i + 1 >= len(lines):
                raise ValueError(f"month {lines[i]!r} is the last line of the page")
            if not _NOTATION.fullmatch(lines[i + 1]):
                out[year].append(_end_date(year, lines[i], lines[i + 1]))
            i += 1
        i += 1
    for y, ds in out.items():
        if len(ds) != MEETINGS_PER_YEAR or ds != sorted(set(ds)):
            raise ValueError(f"{y} FOMC table gives {len(ds)} meetings {[str(d) for d in ds]}; expected {MEETINGS_PER_YEAR} in date order")
    if not out:
        raise ValueError(f"no 'YYYY FOMC Meetings' table for {min_year} or later on the page")
    return out


def page_url(raw: str) -> str:
    m = re.search(r'<meta property="og:url" content="([^"]+)"', raw)
    if not m:
        raise ValueError("the saved page has no og:url meta tag")
    return m.group(1)


def last_update(raw: str) -> dt.date:
    lines = text_lines(raw)
    k = lines.index("Last Update:")
    return dt.datetime.strptime(lines[k + 1], "%B %d, %Y").date()


def forward_rows(raw: str, start=FORWARD_START) -> list[dict]:
    """Scheduled FOMC statements with date >= start, as rows of fomc_forward.csv."""
    if last_update(raw) > dt.date.fromisoformat(CAPTURED_ON):
        raise ValueError(f"page 'Last Update' {last_update(raw)} is after the capture date {CAPTURED_ON}")
    url = page_url(raw)
    dates = sorted(d for ds in parse_meetings(raw, start.year).values() for d in ds if d >= start.date())
    if not dates:
        raise ValueError(f"no scheduled FOMC meeting on or after {start.date()} on the saved page")
    return [dict(event="FOMC", date_et=d.isoformat(), time_et=STATEMENT_TIME_ET, scheduled=True, source_url=url,
                 captured_on=CAPTURED_ON) for d in dates]


def write_forward_csv(path: Path = FOMC_FORWARD_CSV, source: Path = SOURCE_HTML) -> list[dict]:
    rows = forward_rows(source.read_text(encoding="utf-8"))
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return rows


def main() -> None:
    rows = write_forward_csv()
    print(f"wrote {len(rows)} rows -> research/data/{FOMC_FORWARD_CSV.name}: " + ", ".join(r["date_et"] for r in rows))


if __name__ == "__main__":
    main()
