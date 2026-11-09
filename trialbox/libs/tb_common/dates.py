"""Dates as Japanese and Taiwanese records write them (T-118, D-215; review E-05, MR-015, R-95): one module.

Before D-215 six modules each carried their own regular expressions for ISO, 民國 (Minguo / ROC) and 和暦 (Japanese
era) dates, each slightly different. They now take their patterns and era arithmetic from here, **unchanged**: the
recorded corpus ``tests/fixtures/dates/six_modules.json`` shows every one of them answering as it did before.

* :func:`parse` reads **one** date written on its own (a sheet cell, a form field): ISO and its slashed and
  ``年月日`` forms, ``YYYYMMDD``, 和暦 (``令和5年3月1日``, ``R5.3.1``, ``平成元年``), 民國 (``民國112年3月15日``,
  ``112/03/15``, the NHI's ``1120315``) and the ROC year written without 民國 (``112年3月15日``, MR-015). It returns
  None for anything it cannot read for certain: a slashed day/month that could swap, a two-digit year, a date the
  era never had (``平成31年5月1日``: the era had changed), a day the month lacks. :func:`read` says why
  (``check_dates``); a person checks, nothing is guessed.
* :func:`find` is the first plausible date inside free text (CASE's chart excerpts).
* ``*_SPAN`` are the span patterns the detectors use (PHI scrubbing, the stub chart reader, site set-up's chart date);
  they are kept exactly as each detector had them. Unifying them changes what is scrubbed and is left to a reviewed
  change of its own.

A two-digit year written with 年 and no era (``99年3月15日``) is ROC 99 in Taiwan and 1999 in Japan, so it is read
only when the language is ``zh-TW``; a three-digit one (``100``–``199``) can only be ROC (2011–2110).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date

from tb_common.reasons import Reason

CHECK_DATES = Reason.CHECK_DATES.value

# ------------------------------------------------------------------------------------------------ eras
ERAS: dict[str, tuple[int, date, date | None]] = {  # name -> (year offset, first day, last day)
    "令和": (2018, date(2019, 5, 1), None),
    "平成": (1988, date(1989, 1, 8), date(2019, 4, 30)),
    "昭和": (1925, date(1926, 12, 25), date(1989, 1, 7)),
    "大正": (1911, date(1912, 7, 30), date(1926, 12, 25)),
    "明治": (1867, date(1868, 10, 23), date(1912, 7, 29)),
}
ERA_ABBR = {"R": "令和", "H": "平成", "S": "昭和", "T": "大正", "M": "明治"}
MINGUO_OFFSET = 1911  # 民國 1 = 1912


def ymd(y: int, m: int, d: int) -> date | None:
    """The date, or None for a day the calendar lacks (2月30日)."""
    try:
        return date(y, m, d)
    except ValueError:
        return None


def era_date(era: str, year: str, month: int, day: int) -> tuple[date | None, bool]:
    """``(date, inside the era)`` for a 和暦 date; ``era`` is the name or its letter (R, H, S, T, M), ``year`` a
    number or ``元`` (the first year). ``(None, False)`` for a day the calendar lacks; ``(date, False)`` for a date the
    era never had (``平成31年5月1日`` is 2019-05-01, but 平成 had ended on 4月30日)."""
    name = ERA_ABBR.get(era.upper(), era)
    offset, first, last = ERAS[name]
    d = ymd(offset + (1 if year == "元" else int(year)), month, day)
    if d is None:
        return None, False
    return d, not (d < first or (last is not None and d > last))


def minguo_date(year: int, month: int, day: int) -> date | None:
    """A 民國 (ROC) date: year + 1911."""
    return ymd(MINGUO_OFFSET + year, month, day)


# ------------------------------------------------------------------------------------------------ cell patterns
# one date on its own (a sheet cell): the patterns of sitesetup.messy, moved here unchanged
SEP = r"\s*[年./\-]\s*"
MD = r"(\d{1,2})\s*[月./\-]\s*(\d{1,2})\s*日?"
CELL_ERA = re.compile(rf"^(令和|平成|昭和|大正|明治|[RHSTMrhstm])\s*(元|\d{{1,2}}){SEP}{MD}$")
CELL_MINGUO = re.compile(rf"^(?:民國|民国|中華民國)\s*(\d{{1,3}}){SEP}{MD}$")
CELL_ROC3 = re.compile(r"^(1\d{2})[./\-](\d{1,2})[./\-](\d{1,2})$")
CELL_ROC7 = re.compile(r"^(1\d{2})(\d{2})(\d{2})$")
# MR-015 (R-95): the usual Taiwanese form writes the ROC year with 年 and no 民國: 112年3月15日
CELL_ROC_NIAN = re.compile(r"^(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?$")
CELL_ISO = re.compile(rf"^(\d{{4}}){SEP}{MD}(?:[ T]\d{{1,2}}:\d{{2}}(?::\d{{2}})?)?$")
CELL_YMD8 = re.compile(r"^((?:19|20)\d{2})(\d{2})(\d{2})$")


def roc_nian(text: str, lang: str | None = None) -> date | None:
    """``112年3月15日`` (the ROC year with 年 and no 民國): a three-digit year 100-199 always (it cannot be anything
    else); a two-digit one only for ``zh-TW`` (in Japan ``99年`` is 1999). None when it is not this form or not a
    real day."""
    m = CELL_ROC_NIAN.match(text)
    if m is None:
        return None
    y = m.group(1)
    if len(y) == 3 and not y.startswith("1"):
        return None
    if len(y) == 2 and (lang or "").lower() not in ("zh-tw", "zh_tw", "zh-hant"):
        return None
    return minguo_date(int(y), int(m.group(2)), int(m.group(3)))


# ------------------------------------------------------------------------------------------------ span patterns
# the detectors' patterns, kept exactly as each module had them (see the module docstring)
_ERA_SPAN = r"(?:令和|平成|昭和|R|H|S)\s?\d{1,2}[./年]\s?\d{1,2}[./月]\s?\d{1,2}日?"
_MINGUO_SPAN = r"民國\s?\d{2,3}[./年]\s?\d{1,2}[./月]\s?\d{1,2}日?"
_GREGORIAN_SPAN = r"(?:19|20)\d{2}[-/.年]\s?\d{1,2}[-/.月]\s?\d{1,2}日?"
# a date of any of the three kinds in a chart line (the stub chart reader, site set-up's chart date)
CHART_SPAN = re.compile(rf"(?:{_ERA_SPAN})|(?:{_MINGUO_SPAN})|(?:{_GREGORIAN_SPAN})")
# the PHI guard's: Gregorian, and 民國 written out in full (年月日)
PHI_SPAN = re.compile(r"(?:19|20)\d{2}[/\-.年]\s?\d{1,2}[/\-.月]\s?\d{1,2}日?|民國\s?\d{2,3}年\s?\d{1,2}月\s?\d{1,2}日")
# the guard's date of birth value: ISO, 年月日, 民國, 和暦 (年月日), US slashed and English month names
DOB_SPAN = (
    r"(?:(?:19|20)\d{2}[/\-.]\d{1,2}[/\-.]\d{1,2}|(?:19|20)\d{2}年\s?\d{1,2}月\s?\d{1,2}日"
    r"|民國\s?\d{2,3}年\s?\d{1,2}月\s?\d{1,2}日|(?:昭和|平成|令和)\s?(?:\d{1,2}|元)年\s?\d{1,2}月\s?\d{1,2}日"
    r"|\d{1,2}/\d{1,2}/(?:19|20)\d{2}"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? \d{1,2}, (?:19|20)\d{2})"
)

# ------------------------------------------------------------------------------------------------ in free text
# CASE's chart text: ISO, slashed, 2026年3月14日, 民國115年3月14日 / 115.03.14, 令和8年3月14日 / R8.3.14, 平成31年
FIND_ISO = re.compile(r"(?<!\d)((?:19|20)\d{2})[-/.年]\s?(\d{1,2})[-/.月]\s?(\d{1,2})日?(?!\d)")
FIND_MINGUO = re.compile(r"(?:民國\s?)?(?<![\d.])(1[0-2]\d)[./年]\s?(\d{1,2})[./月]\s?(\d{1,2})日?(?!\d)")
FIND_ERA = re.compile(r"(令和|平成|R|H)\s?(\d{1,2})[./年]\s?(\d{1,2})[./月]\s?(\d{1,2})日?(?!\d)")
_FIND_ERA_BASE = {"令和": 2018, "R": 2018, "平成": 1988, "H": 1988}


def find(text: str) -> date | None:
    """The first plausible calendar date in ``text`` (ISO or slashed first, then a Japanese era, then Minguo)."""
    for m in FIND_ISO.finditer(text):
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
    for m in FIND_ERA.finditer(text):
        try:
            return date(_FIND_ERA_BASE[m.group(1)] + int(m.group(2)), int(m.group(3)), int(m.group(4)))
        except ValueError:
            continue
    for m in FIND_MINGUO.finditer(text):
        try:
            return date(MINGUO_OFFSET + int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
    return None


# ------------------------------------------------------------------------------------------------ one date
def _fold(text: str) -> str:
    """NFKC (full-width digits and letters to half-width; the ideographic space to a space), trimmed."""
    return unicodedata.normalize("NFKC", text).strip()


def parse(text: str | None, lang: str | None = None, era: bool = True) -> date | None:
    """One date written on its own, or None when it cannot be read for certain (see the module docstring).
    ``era=False`` reads Gregorian forms only (a field that must not hold an era or ROC year)."""
    s = _fold(text or "")
    if not s:
        return None
    m = CELL_ISO.match(s)
    if m:
        return ymd(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = CELL_YMD8.match(s)
    if m:
        return ymd(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if not era:
        return None
    m = CELL_ERA.match(s)
    if m:
        d, inside = era_date(m.group(1), m.group(2), int(m.group(3)), int(m.group(4)))
        return d if inside else None
    m = CELL_MINGUO.match(s) or CELL_ROC3.match(s) or CELL_ROC7.match(s)
    if m:
        return minguo_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return roc_nian(s, lang)


def read(text: str | None, lang: str | None = None, era: bool = True) -> tuple[date | None, str | None]:
    """``(date, None)``; ``(None, "check_dates")`` for a date that is written but cannot be read for certain;
    ``(None, None)`` when nothing is written."""
    d = parse(text, lang, era)
    if d is not None:
        return d, None
    return None, (CHECK_DATES if _fold(text or "") else None)


__all__ = [
    "CHART_SPAN",
    "CHECK_DATES",
    "DOB_SPAN",
    "ERAS",
    "ERA_ABBR",
    "MINGUO_OFFSET",
    "PHI_SPAN",
    "era_date",
    "find",
    "minguo_date",
    "parse",
    "read",
    "roc_nian",
    "ymd",
]
