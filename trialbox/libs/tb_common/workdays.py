"""The site's working days (10C-14, JP-15): the one place TrialBox decides whether a day is a working day.

A working day is Monday to Friday that is not one of the site's days off. The days off are, per country, data:

* the public holidays, from ``refdata_src/holidays_<country>.csv`` (``date,name,kind``; kind ``holiday``, or
  ``substitute`` and ``citizens`` for the two kinds the source calls 休日). Japan's file is the Cabinet Office's list
  (内閣府「国民の祝日について」, ``syukujitsu.csv``, CP932) for 2025 to 2027 as read on 2026-11-18, names unchanged;
  licence register row ``jp-holidays`` (Public Data License 1.0). The file ships inside the images of the signed
  update bundle, beside the other reference files TrialBox keeps itself (``refdata_src``); a new year's list comes
  with an update;
* the country's default end-of-year break (Japan: 12-29 to 01-03, the 年末年始 of 行政機関の休日に関する法律 art. 1;
  not in the Cabinet Office list), which a site changes because hospitals differ;
* the site's own changes (declared settings, written by the settings wizard into ``deploy/.env``):
  ``TB_NEW_YEAR_BREAK`` (``MM-DD/MM-DD``, or ``none``), ``TB_DAYS_OFF`` (more days off, ``YYYY-MM-DD`` comma
  separated) and ``TB_DAYS_OPEN`` (holidays or break days the hospital works).

The country is the site's (``tb_common.derived.country_of`` of ``site.tz``). A site with no country, or of a country
with no holiday file, has no days off: Monday to Friday, exactly as before this module (and the site's changes are
not read). The day itself is always the site's date (the caller passes the site-local day, D-270).

Who reads it: the coordinator's digest and the investigator's weekly mail (``console.notify``: no digest on a day off;
it comes on the next working day) and a visit window the protocol counts in working days
(``datacore.lifecycle.visit_status``). The serious adverse event clocks never read it: their deadlines are calendar
days and their notices go out every day (``console.saerecord``, ``datacore.lifecycle.report_clock``).

Standard library only, Python 3.10: the settings wizard imports it with the host's ``python3``.
"""

from __future__ import annotations

import csv
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

SRC = Path(__file__).resolve().parent / "refdata_src"
KINDS = ("holiday", "substitute", "citizens")
DAY_OFF_KINDS = (*KINDS, "new_year", "site")  # why a weekday is off (:meth:`Calendar.day_off`, less "weekend")
# the end-of-year break each country's offices close by default; a site changes it (TB_NEW_YEAR_BREAK)
NEW_YEAR_BREAK: dict[str, tuple[tuple[int, int], tuple[int, int]]] = {"JP": ((12, 29), (1, 3))}
ENV_BREAK, ENV_OFF, ENV_OPEN = "TB_NEW_YEAR_BREAK", "TB_DAYS_OFF", "TB_DAYS_OPEN"
_MD = re.compile(r"^(\d{2})-(\d{2})$")


@dataclass(frozen=True)
class Holidays:
    """One country's public holidays as the file lists them, and the last day the list covers."""

    days: dict[date, tuple[str, str]]  # day -> (name, kind)
    until: date | None


@lru_cache(maxsize=8)
def holidays(country: str) -> Holidays | None:
    """The country's holiday file, or None when there is none (the country has no calendar)."""
    code = (country or "").strip().lower()
    path = SRC / f"holidays_{code}.csv"
    if not code.isalpha() or not path.is_file():
        return None
    days: dict[date, tuple[str, str]] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            kind = row["kind"].strip()
            if kind not in KINDS:
                raise ValueError(f"{path.name}: kind {kind!r} on {row['date']}")
            days[date.fromisoformat(row["date"].strip())] = (row["name"].strip(), kind)
    last = max(days) if days else None
    return Holidays(days, date(last.year, 12, 31) if last else None)


def parse_break(text: str) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """``MM-DD/MM-DD`` (the first and last day off, across the year end), or ``none``. Raises ValueError."""
    t = (text or "").strip().lower()
    if t in ("none", "-"):
        return None
    a, sep, b = t.partition("/")
    ma, mb = _MD.match(a.strip()), _MD.match(b.strip())
    if not sep or ma is None or mb is None:
        raise ValueError(f"the New Year break is MM-DD/MM-DD or none: {text!r}")
    first = (int(ma.group(1)), int(ma.group(2)))
    last = (int(mb.group(1)), int(mb.group(2)))
    for m, d in (first, last):
        date(2024, m, d)  # a real day (2024: 02-29 exists)
    return first, last


def _days(text: str, problems: list[str]) -> frozenset[date]:
    out: set[date] = set()
    for part in (text or "").replace(";", ",").split(","):
        if not part.strip():
            continue
        try:
            out.add(date.fromisoformat(part.strip()))
        except ValueError:
            problems.append(part.strip()[:20])
    return frozenset(out)


@dataclass(frozen=True)
class Calendar:
    """The site's working days. ``country`` "" (or a country with no file): Monday to Friday, no day off."""

    country: str = ""
    holidays: Holidays | None = None
    new_year: tuple[tuple[int, int], tuple[int, int]] | None = None
    off: frozenset[date] = frozenset()
    open: frozenset[date] = frozenset()
    problems: tuple[str, ...] = field(default=())  # settings that could not be read (shown, never silently ignored)

    @property
    def has_days_off(self) -> bool:
        return self.holidays is not None

    def _in_break(self, d: date) -> bool:
        if self.new_year is None:
            return False
        (m1, d1), (m2, d2) = self.new_year
        md = (d.month, d.day)
        if (m1, d1) <= (m2, d2):
            return (m1, d1) <= md <= (m2, d2)
        return md >= (m1, d1) or md <= (m2, d2)

    def day_off(self, d: date) -> str:
        """Why ``d`` is a day off at this site ("" when it is not one): ``holiday``, ``substitute``, ``citizens``,
        ``new_year``, ``site``, or ``weekend``."""
        if d.weekday() >= 5:
            return "weekend"
        if self.holidays is None or d in self.open:
            return ""
        if d in self.holidays.days:
            return self.holidays.days[d][1]
        if self._in_break(d):
            return "new_year"
        return "site" if d in self.off else ""

    def name(self, d: date) -> str:
        """The holiday's name in the source's words (Japanese for Japan), "" for another day."""
        hit = self.holidays.days.get(d) if self.holidays is not None else None
        return hit[0] if hit else ""

    def is_working_day(self, d: date) -> bool:
        return not self.day_off(d)

    def next_working_day(self, d: date) -> date:
        """``d`` when it is a working day, else the first working day after it."""
        for _ in range(400):
            if self.is_working_day(d):
                return d
            d += timedelta(days=1)
        raise ValueError("no working day within 400 days: check TB_DAYS_OFF")

    def add_working_days(self, d: date, n: int) -> date:
        """The day ``n`` working days after ``d`` (before it when ``n`` is negative); ``d`` itself is not counted."""
        step = 1 if n >= 0 else -1
        left = abs(n)
        for _ in range(400 + 3 * left):
            if left == 0:
                return d
            d += timedelta(days=step)
            if self.is_working_day(d):
                left -= 1
        raise ValueError("too few working days: check TB_DAYS_OFF")

    def days_off(self, start: date, end: date) -> list[tuple[date, str, str]]:
        """The weekday days off from ``start`` to ``end`` (both included): (day, why, name)."""
        out = []
        d = start
        while d <= end:
            why = self.day_off(d)
            if why and why != "weekend":
                out.append((d, why, self.name(d)))
            d += timedelta(days=1)
        return out


WEEKDAYS_ONLY = Calendar()


def for_country(country: str, environ: Mapping[str, str] | None = None) -> Calendar:
    """The calendar of a site of ``country`` with the site's changes from ``environ`` (default: the process's)."""
    code = (country or "").strip().upper()
    hol = holidays(code)
    if hol is None:
        return WEEKDAYS_ONLY
    env = os.environ if environ is None else environ
    problems: list[str] = []
    new_year = NEW_YEAR_BREAK.get(code)
    raw = (env.get(ENV_BREAK) or "").strip()
    if raw:
        try:
            new_year = parse_break(raw)
        except ValueError:
            problems.append(f"{ENV_BREAK}={raw[:20]}")
    bad: list[str] = []
    off, open_ = _days(env.get(ENV_OFF) or "", bad), _days(env.get(ENV_OPEN) or "", bad)
    problems += [f"{ENV_OFF}/{ENV_OPEN}: {b}" for b in bad]
    return Calendar(code, hol, new_year, off, open_, tuple(problems))


def for_zone(tz: str | None, environ: Mapping[str, str] | None = None) -> Calendar:
    """The calendar of the site whose zone is ``tz`` (``site.tz``): its country decides the holidays."""
    from tb_common.derived import country_of

    return for_country(country_of(tz) or "", environ)
