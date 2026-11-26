"""Dates as a note writes them, each as an ISO interval ``[lo, hi]`` that holds the day meant (MATCH-ARCH layer (a),
rule E8: a partial date is an interval, never a guessed day).

Read from one NFKC sentence. Forms:

* Gregorian: ``2026-07-24``, ``2026/7/24``, ``2026.07.24`` (a dotted date needs the day), ``2026年7月24日`` and its
  partial forms (``2026年7月``, ``2026年``), ``Jul 24, 2026``, ``24 July 2026``, ``July 2026``, and a bare year only
  after in / since / during / from / of (``since 2019``). A run of eight digits is *not* read: it may be an identifier.
* Japanese era (wareki): ``令和6年1月10日``, ``令和元年``, ``平成31年4月``, ``令和6/1/10``, and the zero-padded
  letter form ``R06.01.10`` (never after a word, digit, ``#``, ``.``, ``/`` or ``-``). A year, month or day outside
  the era's own span is no date (``平成31年5月`` and ``令和1年4月`` do not exist); a year-only date is clipped to the
  era (``平成31年`` is 2019-01-01 to 2019-04-30). An era phrase owns its digits even when it is no date: the ``31年5月``
  of ``平成31年5月`` is never read as another calendar's date.
* Republic of China (ROC): ``民國113年1月10日`` and ``民国`` forms, ``113/01/10`` (three-digit year, zero padded), and
  without the word ``113年3月`` (three digits and a month) or ``98年3月5日`` (two or three digits and a full date). A
  year alone, or two digits and a month, is a duration as often as a date and is not read.
* Relative, only when the note's own date is given: ``3 days ago``, ``2 weeks ago``, ``3 months ago``,
  ``a year ago``, ``yesterday``, ``last month`` and the Japanese (``3か月前``, ``三ヶ月前``, ``先月``, ``昨日``) and
  Chinese (``3個月前``, ``上個月``, ``昨天``) forms. Days are exact; a week is read to the nearest half week (4 days
  either side), a month to the nearest half month (17 days), a year to the nearest half year (184 days): a
  clinician's rounding, widened by the calendar's own irregularity (a month is 28 to 31 days, a year has a leap
  day), so that the day meant is inside the interval. ``last week`` is the ISO week before the note's, ``last
  month`` and ``last year`` the calendar month or year before.
  **Without a note date a relative phrase gives nothing**: unknown carries nothing.

An impossible date (30 February) gives nothing. The era table, ``ymd`` and the ROC offset are those of
``tb_common.dates``.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta
from typing import NamedTuple

from tb_common.dates import ERA_ABBR, ERAS, MINGUO_OFFSET, ymd


class DateRef(NamedTuple):
    start: int  # character offsets in the NFKC sentence text
    end: int
    text: str
    lo: str  # ISO date, the first day the phrase can mean
    hi: str  # ISO date, the last day it can mean
    kind: str  # day | month | year | relative


LETTERS = {k: v for k, v in ERA_ABBR.items() if k in "RHST"}
_KANJI = {"一": 1, "二": 2, "兩": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_MONTHS = {
    m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)
}
_ERA_NAMES = "令和|平成|昭和|大正|明治"
_ORD = r"(?:st|nd|rd|th)?"
_MON = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?"
    r"|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
_NUMWORD = r"\d{1,3}|[一二兩两三四五六七八九十]{1,3}|an?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"
_EN_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
           "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}  # fmt: skip

_ISO = re.compile(r"(?<![\d./-])((?:19|20)\d{2})([-/.])(\d{1,2})(?:\2(\d{1,2}))?(?![\d])")
_GREG_CJK = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*年(?:\s*(\d{1,2})\s*月(?:\s*(\d{1,2})\s*日?)?)?")
_EN_DMY = re.compile(rf"(?<![\w])(\d{{1,2}}){_ORD}\s+({_MON})\.?,?\s+((?:19|20)\d{{2}})(?!\d)")
_EN_MDY = re.compile(rf"(?<![\w])({_MON})\.?\s+(?:(\d{{1,2}}){_ORD},?\s+)?((?:19|20)\d{{2}})(?!\d)")
_EN_YEAR = re.compile(r"\b(?:in|since|during|from|of)\s+((?:19|20)\d{2})\b(?![-/.]\d|\s*年)", re.I)
_ERA_WORD = re.compile(rf"({_ERA_NAMES})\s*(元|\d{{1,2}})\s*年(?:\s*(\d{{1,2}})\s*月(?:\s*(\d{{1,2}})\s*日?)?)?")
_ERA_NUM = re.compile(rf"({_ERA_NAMES})\s*(元|\d{{1,2}})([./-])(\d{{1,2}})(?:\3(\d{{1,2}}))?(?![\d/-]|\.\d)")
_ERA_LETTER = re.compile(r"(?<![\w#./-])([RHST])(\d{2})([./-])(\d{2})\3(\d{2})(?![\d/-]|\.\d)")
_ROC_WORD = re.compile(r"(?:民國|民国)\s*(\d{1,3})\s*年(?:\s*(\d{1,2})\s*月(?:\s*(\d{1,2})\s*日?)?)?")
_ROC_NUM = re.compile(r"(?<![\d./-])(1\d{2})([/.])(\d{2})\2(\d{2})(?![\d/-]|\.\d)")
_ROC_BARE = re.compile(r"(?<!\d)(\d{2,3})\s*年\s*(\d{1,2})\s*月(?:\s*(\d{1,2})\s*日)?")
_REL_EN = re.compile(rf"\b({_NUMWORD})\s+(day|week|month|year)s?\s+ago\b", re.I)
_REL_EN_WORD = re.compile(r"\b(yesterday|today|last (?:week|month|year))\b", re.I)
_REL_JA = re.compile(r"(\d+|[一二三四五六七八九十]+)\s*(日|週間|週|か月|ヵ月|ヶ月|カ月|箇月|年)\s*前")
_REL_JA_WORD = re.compile(r"一昨日|おととい|昨日|きのう|今日|本日|先週|先月|昨年|去年")
_REL_ZH = re.compile(r"(\d+|[一二兩两三四五六七八九十]+)\s*(天|日|週|周|個月|个月|年)\s*前")
_REL_ZH_WORD = re.compile(r"昨天|前天|今天|上週|上周|上個月|上个月|去年")
_WORD_OFFSET = {"yesterday": 1, "today": 0, "昨日": 1, "きのう": 1, "一昨日": 2, "おととい": 2, "今日": 0, "本日": 0,
                "昨天": 1, "前天": 2, "今天": 0}  # fmt: skip
_WORD_LAST = {"last week": "week", "先週": "week", "上週": "week", "上周": "week",
              "last month": "month", "先月": "month", "上個月": "month", "上个月": "month",
              "last year": "year", "昨年": "year", "去年": "year"}  # fmt: skip
_UNIT = {"day": "day", "日": "day", "天": "day", "week": "week", "週間": "week", "週": "week", "周": "week",
         "month": "month", "か月": "month", "ヵ月": "month", "ヶ月": "month", "カ月": "month", "箇月": "month",
         "個月": "month", "个月": "month", "year": "year", "年": "year"}  # fmt: skip


def _span(
    y: int, m: int | None, d: int | None, first: date | None = None, last: date | None = None
) -> tuple[date, date, str] | None:
    """``(lo, hi, kind)`` of a possibly partial date, clipped to ``[first, last]`` (an era); None when invalid."""
    if m is None:
        lo, hi, kind = date(y, 1, 1), date(y, 12, 31), "year"
    elif not 1 <= m <= 12:
        return None
    elif d is None:
        lo, hi, kind = date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1]), "month"
    else:
        one = ymd(y, m, d)
        if one is None:
            return None
        lo, hi, kind = one, one, "day"
    if first is not None and last is not None:
        lo, hi = max(lo, first), min(hi, last)
    return (lo, hi, kind) if lo <= hi and 1800 <= lo.year <= 2200 else None


def _int(s: str | None) -> int | None:
    return None if s is None or s == "" else int(s)


def _number(s: str) -> int | None:
    s = s.lower()
    if s.isdigit():
        return int(s)
    if s in _EN_NUM:
        return _EN_NUM[s]
    if not s or any(ch not in "十" + "".join(_KANJI) for ch in s):
        return None
    if "十" not in s:
        return _KANJI.get(s) if len(s) == 1 else None
    tens, _, ones = s.partition("十")
    t = _KANJI.get(tens, 1) if tens else 1
    o = _KANJI.get(ones, 0) if ones else 0
    return t * 10 + o if (not tens or tens in _KANJI) and (not ones or ones in _KANJI) else None


def _add_months(d: date, n: int) -> date:
    m0 = d.year * 12 + d.month - 1 + n
    y, m = divmod(m0, 12)
    return ymd(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1])) or d


def _ago(n: int, unit: str, nd: date) -> tuple[date, date]:
    if unit == "day":
        c = nd - timedelta(days=n)
        return c, c
    if unit == "week":
        c, tol = nd - timedelta(days=7 * n), 4
    elif unit == "month":
        c, tol = _add_months(nd, -n), 17
    else:
        c, tol = _add_months(nd, -12 * n), 184
    return c - timedelta(days=tol), c + timedelta(days=tol)


def _last(unit: str, nd: date) -> tuple[date, date]:
    if unit == "week":
        monday = nd - timedelta(days=nd.weekday() + 7)
        return monday, monday + timedelta(days=6)
    if unit == "month":
        first = _add_months(nd.replace(day=1), -1)
        return first, first.replace(day=calendar.monthrange(first.year, first.month)[1])
    return date(nd.year - 1, 1, 1), date(nd.year - 1, 12, 31)


def parse_note_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value[:10]):
        return ymd(int(value[:4]), int(value[5:7]), int(value[8:10]))
    return None


def dates_in(text: str, note_date: object = None) -> list[DateRef]:
    """The dates of one NFKC sentence, in text order; the longer of two overlapping readings wins."""
    nd = parse_note_date(note_date)
    cands: list[tuple[int, int, date, date, str]] = []

    def add(m: re.Match[str], got: tuple[date, date, str] | None) -> None:
        if got is not None:
            cands.append((m.start(), m.end(), got[0], got[1], got[2]))

    claims: list[tuple[int, int]] = []  # an era or 民國 phrase owns its digits even when it is no date (平成31年5月1日)

    def era(m: re.Match[str], name: str, y: str, mo: int | None, d: int | None) -> None:
        claims.append(m.span())
        base, first, last = ERAS[name]
        last = last or date.max
        n = 1 if y == "元" else int(y)
        if n >= 1:
            add(m, _span(base + n, mo, d, first, last))

    for m in _ISO.finditer(text):
        if m.group(2) != "." or m.group(4):
            add(m, _span(int(m.group(1)), int(m.group(3)), _int(m.group(4))))
    for m in _GREG_CJK.finditer(text):
        add(m, _span(int(m.group(1)), _int(m.group(2)), _int(m.group(3))))
    for m in _EN_DMY.finditer(text):
        add(m, _span(int(m.group(3)), _MONTHS[m.group(2)[:3].lower()], int(m.group(1))))
    for m in _EN_MDY.finditer(text):
        add(m, _span(int(m.group(3)), _MONTHS[m.group(1)[:3].lower()], _int(m.group(2))))
    for m in _EN_YEAR.finditer(text):
        add(m, _span(int(m.group(1)), None, None))
    for m in _ERA_WORD.finditer(text):
        era(m, m.group(1), m.group(2), _int(m.group(3)), _int(m.group(4)))
    for m in _ERA_NUM.finditer(text):
        era(m, m.group(1), m.group(2), int(m.group(4)), _int(m.group(5)))
    for m in _ERA_LETTER.finditer(text):
        era(m, LETTERS[m.group(1)], str(int(m.group(2))), int(m.group(4)), int(m.group(5)))
    for m in _ROC_WORD.finditer(text):
        claims.append(m.span())
        add(m, _span(MINGUO_OFFSET + int(m.group(1)), _int(m.group(2)), _int(m.group(3))))
    for m in _ROC_NUM.finditer(text):
        add(m, _span(MINGUO_OFFSET + int(m.group(1)), int(m.group(3)), int(m.group(4))))
    for m in _ROC_BARE.finditer(text):
        if len(m.group(1)) == 3 or m.group(3):
            add(m, _span(MINGUO_OFFSET + int(m.group(1)), int(m.group(2)), _int(m.group(3))))
    if nd is not None:
        for rx in (_REL_EN, _REL_JA, _REL_ZH):
            for m in rx.finditer(text):
                n, unit = _number(m.group(1)), _UNIT[m.group(2).lower()]
                if n:
                    lo, hi = _ago(n, unit, nd)
                    cands.append((m.start(), m.end(), lo, hi, "relative"))
        for rx in (_REL_EN_WORD, _REL_JA_WORD, _REL_ZH_WORD):
            for m in rx.finditer(text):
                w = m.group(1) if rx is _REL_EN_WORD else m.group(0)
                w = w.lower()
                lo, hi = _last(_WORD_LAST[w], nd) if w in _WORD_LAST else _ago(_WORD_OFFSET[w], "day", nd)
                cands.append((m.start(), m.end(), lo, hi, "relative"))
    cands = [c for c in cands if not any(s <= c[0] and c[1] <= e and (s, e) != (c[0], c[1]) for s, e in claims)]
    cands.sort(key=lambda c: (c[0] - c[1], c[0]))
    kept: list[tuple[int, int, date, date, str]] = []
    for c in cands:
        if all(c[1] <= k[0] or k[1] <= c[0] for k in kept):
            kept.append(c)
    kept.sort(key=lambda c: (c[0], c[1]))
    return [DateRef(s, e, text[s:e], lo.isoformat(), hi.isoformat(), kind) for s, e, lo, hi, kind in kept]
