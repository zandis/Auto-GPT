"""gen_calendar: the plan calendar is data (TB-PLAN-06 card T-662), checked by weekday and by site days off.

    python -m tools.gen_calendar                            # print the calendar as one Markdown table, by date
    python -m tools.gen_calendar --check                    # exit 1 on a wrong weekday or a milestone on a day off
    python -m tools.gen_calendar --span TW 2027-03-29 2027-04-23   # working days at a site, both ends included
    python -m tools.gen_calendar --verify-sources           # download the official files and compare (network)

The data is ``docs/plan/calendar.yaml``. Milestones are build milestones only (D-311). Holidays come from the
Japan Cabinet Office list (plus the statutory 年末年始 office closure) and the Taiwan DGPA office calendar, one
source per country and year. A year whose source could not be fetched is marked ``unverified`` and printed as a
note; it is never filled in from memory. Deep review PLAN-011, PLAN-012, PLAN-013 and PLAN-016.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CALENDAR = ROOT / "docs" / "plan" / "calendar.yaml"
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
KINDS = ("holiday", "closure")
STATUSES = ("verified", "unverified")
# Japan's 年末年始: offices close 12-29 to 01-03 (行政機関の休日に関する法律, art. 1). Not in the Cabinet Office list.
JP_CLOSURE = ((12, 29), (12, 30), (12, 31), (1, 2), (1, 3))
TW_DAYS = {"一": "Mon", "二": "Tue", "三": "Wed", "四": "Thu", "五": "Fri", "六": "Sat", "日": "Sun"}


@dataclass(frozen=True)
class DayOff:
    site: str
    date: date
    day: str
    kind: str
    name: str


@dataclass(frozen=True)
class Milestone:
    id: str
    date: date
    day: str
    what: str
    sites: tuple[str, ...]


@dataclass
class Calendar:
    start: date
    end: date
    sites: dict[str, str]
    milestones: list[Milestone] = field(default_factory=list)
    days_off: list[DayOff] = field(default_factory=list)
    sources: dict[str, dict[int, dict[str, str]]] = field(default_factory=dict)

    def off(self, site: str) -> dict[date, DayOff]:
        return {d.date: d for d in self.days_off if d.site == site}


def _date(value: object) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def parse(data: dict[str, Any]) -> Calendar:
    window = data["window"]
    cal = Calendar(start=_date(window["start"]), end=_date(window["end"]), sites=dict(data["sites"]))
    for m in data.get("milestones") or []:
        cal.milestones.append(
            Milestone(str(m["id"]), _date(m["date"]), str(m["day"]), str(m["what"]), tuple(m["sites"]))
        )
    for site, rows in (data.get("holidays") or {}).items():
        for h in rows:
            cal.days_off.append(DayOff(site, _date(h["date"]), str(h["day"]), str(h["kind"]), str(h["name"])))
    for site, years in (data.get("sources") or {}).items():
        cal.sources[site] = {int(y): {k: str(v) for k, v in (s or {}).items()} for y, s in years.items()}
    return cal


def load(path: Path = CALENDAR) -> Calendar:
    return parse(yaml.safe_load(path.read_text(encoding="utf-8")))


def weekday(d: date) -> str:
    return DAYS[d.weekday()]


def is_working_day(cal: Calendar, site: str, d: date) -> bool:
    return d.weekday() < 5 and d not in cal.off(site)


def working_days(cal: Calendar, site: str, start: date, end: date) -> int:
    """Working days at ``site`` from ``start`` to ``end``, both included."""
    off = cal.off(site)
    n, d = 0, start
    while d <= end:
        if d.weekday() < 5 and d not in off:
            n += 1
        d += timedelta(days=1)
    return n


def years(cal: Calendar) -> range:
    return range(cal.start.year, cal.end.year + 1)


def check(cal: Calendar) -> tuple[list[str], list[str]]:
    """Return (errors, notes). Errors fail ``--check``; notes are printed only."""
    errors: list[str] = []
    notes: list[str] = []
    seen: set[tuple[str, date]] = set()
    for h in cal.days_off:
        where = f"{h.site} {h.date} {h.name}"
        if h.site not in cal.sites:
            errors.append(f"{where}: unknown site")
        if h.day != weekday(h.date):
            errors.append(f"{where}: printed {h.day}, is {weekday(h.date)}")
        if h.kind not in KINDS:
            errors.append(f"{where}: kind {h.kind!r} not in {KINDS}")
        if not cal.start <= h.date <= cal.end:
            errors.append(f"{where}: outside the window {cal.start} to {cal.end}")
        if (h.site, h.date) in seen:
            errors.append(f"{where}: listed twice")
        seen.add((h.site, h.date))
    for site in cal.sites:
        for year in years(cal):
            src = cal.sources.get(site, {}).get(year)
            if src is None:
                errors.append(f"{site} {year}: no source")
                continue
            status = src.get("status", "")
            if status not in STATUSES:
                errors.append(f"{site} {year}: status {status!r} not in {STATUSES}")
            elif status == "unverified":
                notes.append(f"{site} {year}: holidays unverified, source could not be fetched")
            elif not src.get("url", "").startswith("https://") or not src.get("checked"):
                errors.append(f"{site} {year}: a verified year needs an https url and a checked date")
    for m in cal.milestones:
        where = f"{m.id} {m.date}"
        if m.day != weekday(m.date):
            errors.append(f"{where}: printed {m.day}, is {weekday(m.date)}")
        for site in m.sites:
            if site not in cal.sites:
                errors.append(f"{where}: unknown site {site}")
            elif m.date.weekday() >= 5:
                errors.append(f"{where}: on a weekend")
            elif m.date in cal.off(site):
                errors.append(f"{where}: on a day off at {site} ({cal.off(site)[m.date].name})")
    return errors, notes


def render(cal: Calendar) -> str:
    rows: list[tuple[date, str, str]] = []
    for m in cal.milestones:
        rows.append((m.date, f"**{m.id}**", m.what))
    for h in cal.days_off:
        rows.append((h.date, h.site, h.name + (" (office closure)" if h.kind == "closure" else "")))
    rows.sort(key=lambda r: (r[0], r[1]))
    out = ["| Date | Day | Site or milestone | What |", "| --- | --- | --- | --- |"]
    out += [f"| {d} | {weekday(d)} | {who} | {what} |" for d, who, what in rows]
    return "\n".join(out) + "\n"


# ---- the official sources -------------------------------------------------------------------------------------


def parse_jp_csv(text: str) -> dict[date, str]:
    """The Cabinet Office ``syukujitsu.csv``: ``YYYY/M/D,name`` after one header row."""
    out: dict[date, str] = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2 or "/" not in row[0]:
            continue
        y, m, d = (int(x) for x in row[0].split("/"))
        out[date(y, m, d)] = row[1].strip()
    return out


def jp_closures(start: date, end: date) -> dict[date, str]:
    out: dict[date, str] = {}
    for year in range(start.year, end.year + 1):
        for m, d in JP_CLOSURE:
            day = date(year, m, d)
            if start <= day <= end:
                out[day] = "年末年始"
    return out


def parse_tw_csv(text: str) -> tuple[dict[date, str], list[date]]:
    """The DGPA office calendar: ``YYYYMMDD,weekday,flag,remark``; flag 2 is a day off, 0 a working day.

    Returns the named days off (a remark and flag 2) and the make-up working days (flag 0 on a weekend), which
    the calendar does not model and must be reported.
    """
    named: dict[date, str] = {}
    makeup: list[date] = []
    for row in csv.reader(io.StringIO(text.lstrip("﻿"))):
        if len(row) < 3 or not row[0].strip().isdigit():
            continue
        raw = row[0].strip()
        day = date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
        flag, remark = row[2].strip(), (row[3].strip() if len(row) > 3 else "")
        if flag == "2" and remark:
            named[day] = remark
        elif flag == "2" and day.weekday() < 5:
            named[day] = "放假"
        elif flag == "0" and day.weekday() >= 5:
            makeup.append(day)
    return named, makeup


def compare(cal: Calendar, site: str, official: dict[date, str]) -> list[str]:
    """Differences between the file's days off at ``site`` and an official list, inside the window."""
    ours = {d: h.name for d, h in cal.off(site).items()}
    theirs = {d: n for d, n in official.items() if cal.start <= d <= cal.end}
    errors = [f"{site} {d}: official {theirs[d]} missing from the file" for d in sorted(theirs.keys() - ours.keys())]
    errors += [
        f"{site} {d}: {ours[d]} in the file, not in the official list" for d in sorted(ours.keys() - theirs.keys())
    ]
    errors += [
        f"{site} {d}: name {ours[d]} vs official {theirs[d]}"
        for d in sorted(ours.keys() & theirs.keys())
        if ours[d] != theirs[d]
    ]
    return errors


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "trialbox-gen-calendar"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        body: bytes = resp.read()
    return body


def verify_sources(cal: Calendar, fetch: Callable[[str], bytes] = _fetch) -> list[str]:
    errors: list[str] = []
    jp: dict[date, str] = {}
    for year, src in sorted(cal.sources.get("JP", {}).items()):
        if src.get("status") != "verified":
            continue
        rows = parse_jp_csv(fetch(src["file"]).decode("shift_jis"))
        jp.update({d: n for d, n in rows.items() if d.year == year})
        jp.update({d: n for d, n in jp_closures(cal.start, cal.end).items() if d.year == year and d not in jp})
    if jp:
        errors += compare(cal, "JP", jp)
    tw: dict[date, str] = {}
    for year, src in sorted(cal.sources.get("TW", {}).items()):
        if src.get("status") != "verified":
            continue
        named, makeup = parse_tw_csv(fetch(src["file"]).decode("utf-8-sig"))
        tw.update({d: n for d, n in named.items() if d.year == year})
        errors += [f"TW {d}: make-up working day, not modelled" for d in makeup if cal.start <= d <= cal.end]
    if tw:
        errors += compare(cal, "TW", tw)
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", type=Path, default=CALENDAR)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--span", nargs=3, metavar=("SITE", "START", "END"))
    ap.add_argument("--verify-sources", action="store_true")
    args = ap.parse_args(argv)
    cal = load(args.file)
    errors, notes = check(cal)
    for n in notes:
        print(f"note: {n}")
    if args.span:
        site, start, end = args.span
        print(f"{site} {start}..{end} wd {working_days(cal, site, date.fromisoformat(start), date.fromisoformat(end))}")
        return 0
    if args.verify_sources:
        errors += verify_sources(cal)
    elif not args.check:
        sys.stdout.write(render(cal))
    for e in errors:
        print(f"error: {e}", file=sys.stderr)
    if not errors and (args.check or args.verify_sources):
        print(f"calendar: {len(cal.milestones)} milestones, {len(cal.days_off)} days off, ok")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
