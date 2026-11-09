"""Messy sheets and dumps: fix what is safe, ask the rest (D-132). Pure functions, no I/O.

What sites really send (field research 2026-11-08, M5): Excel lists laid out differently by each investigator, with
a title row above the header, merged cells, full-width digits and letters, Japanese era dates (令和5年, R5.3.1,
平成31年), Taiwan's 民國 years (民國112年3月15日, 112/03/15) and NHI's 7-digit ROC dates (1120315), Excel serial
numbers, slashed dates that could be day/month or month/day, lab values in another unit, and a number column that
might be the chart number.

* **Safe fixes** are made and listed (:class:`Fix`): every one is unambiguous (an era year is one Gregorian year; a
  full-width ``７`` is ``7``; µmol/L of urate is mg/dL × 59.48).
* **Anything ambiguous** becomes a :class:`Check` with a suggested answer and nothing is guessed: until a person
  answers, the cell is left empty (a date that could be 3 April or 4 March) or the column is held back (a column that
  might be the chart number is neither stored nor used as the key).

:func:`clean` runs the whole table once; ``answers`` (``Check.key`` -> chosen option) re-runs it with the person's
choices, so the result is always a function of the file and the answers.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

# ------------------------------------------------------------------------------------------------ width
_FULL = {c: c - 0xFEE0 for c in range(0xFF01, 0xFF5F)}
_FULL[0x3000] = 0x20  # ideographic space


def half_width(text: str) -> str:
    """Full-width digits, letters and ASCII punctuation (and the ideographic space) to half-width. Kana and kanji are
    left as they are."""
    return text.translate(_FULL)


# ------------------------------------------------------------------------------------------------ results
@dataclass(frozen=True)
class Fix:
    """One safe fix that was made: ``kind`` (era, minguo, roc7, excel_serial, format, dmy, mdy, width, unit,
    merged, header_row), where, and the value before and after."""

    kind: str
    column: str
    row: int | None
    before: str
    after: str


@dataclass(frozen=True)
class Check:
    """One thing a person must decide: ``kind`` (date_order, era_boundary, two_digit_year, date_unreadable, unit,
    chart_column, sex, no_key), where, an example of the raw value, the suggested answer and the possible answers."""

    kind: str
    column: str
    row: int | None
    raw: str
    suggestion: str
    options: tuple[str, ...]

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.column}" + ("" if self.row is None else f":{self.row}")


# ------------------------------------------------------------------------------------------------ dates
ERAS: dict[str, tuple[int, date, date | None]] = {  # name -> (year offset, first day, last day)
    "令和": (2018, date(2019, 5, 1), None),
    "平成": (1988, date(1989, 1, 8), date(2019, 4, 30)),
    "昭和": (1925, date(1926, 12, 25), date(1989, 1, 7)),
    "大正": (1911, date(1912, 7, 30), date(1926, 12, 25)),
    "明治": (1867, date(1868, 10, 23), date(1912, 7, 29)),
}
ERA_ABBR = {"R": "令和", "H": "平成", "S": "昭和", "T": "大正", "M": "明治"}
_SEP = r"\s*[年./\-]\s*"
_MD = r"(\d{1,2})\s*[月./\-]\s*(\d{1,2})\s*日?"
_ERA = re.compile(rf"^(令和|平成|昭和|大正|明治|[RHSTMrhstm])\s*(元|\d{{1,2}}){_SEP}{_MD}$")
_MINGUO = re.compile(rf"^(?:民國|民国|中華民國)\s*(\d{{1,3}}){_SEP}{_MD}$")
_ROC3 = re.compile(r"^(1\d{2})[./\-](\d{1,2})[./\-](\d{1,2})$")
_ROC7 = re.compile(r"^(1\d{2})(\d{2})(\d{2})$")
_ISO = re.compile(rf"^(\d{{4}}){_SEP}{_MD}(?:[ T]\d{{1,2}}:\d{{2}}(?::\d{{2}})?)?$")
_YMD8 = re.compile(r"^((?:19|20)\d{2})(\d{2})(\d{2})$")
_DMY = re.compile(r"^(\d{1,2})[./\-](\d{1,2})[./\-](\d{4})$")
_TWO = re.compile(r"^(\d{1,2})[./\-](\d{1,2})[./\-](\d{1,2})$")
_SERIAL = re.compile(r"^(\d{5})(?:\.0+)?$")
EXCEL_EPOCH = date(1899, 12, 30)
ORDERS = ("dmy", "mdy")


@dataclass(frozen=True)
class ParsedDate:
    iso: str | None  # YYYY-MM-DD, or None (empty, ambiguous or unreadable)
    kind: str | None = None  # the fix made (None: already ISO or empty)
    problem: str | None = None  # date_order | era_boundary | two_digit_year | date_unreadable
    suggestion: str | None = None  # for era_boundary: the Gregorian reading


def _mk(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_date(raw: str, order: str | None = None, serial: bool = True) -> ParsedDate:
    """One date cell. ``order`` (``dmy`` or ``mdy``) is the person's answer for slashed day/month dates; without it
    a slashed date whose day and month could swap is not read (``date_order``)."""
    s = half_width(str(raw or "")).strip()
    if not s:
        return ParsedDate(None)
    m = _ISO.match(s)
    if m:
        d = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d is None:
            return ParsedDate(None, problem="date_unreadable")
        return ParsedDate(d.isoformat(), None if s == d.isoformat() else "format")
    m = _YMD8.match(s)
    if m:
        d = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d is not None:
            return ParsedDate(d.isoformat(), "format")
    m = _ERA.match(s)
    if m:
        era = ERA_ABBR.get(m.group(1).upper(), m.group(1))
        offset, first, last = ERAS[era]
        year = 1 if m.group(2) == "元" else int(m.group(2))
        d = _mk(offset + year, int(m.group(3)), int(m.group(4)))
        if d is None:
            return ParsedDate(None, problem="date_unreadable")
        if d < first or (last is not None and d > last):  # 平成31年5月 does not exist: the era had changed
            return ParsedDate(None, problem="era_boundary", suggestion=d.isoformat())
        return ParsedDate(d.isoformat(), "era")
    m = _MINGUO.match(s) or _ROC3.match(s)
    if m:
        d = _mk(1911 + int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return ParsedDate(d.isoformat(), "minguo") if d else ParsedDate(None, problem="date_unreadable")
    m = _ROC7.match(s)
    if m:
        d = _mk(1911 + int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d is not None:
            return ParsedDate(d.isoformat(), "roc7")
    m = _DMY.match(s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if order in ORDERS:
            d = _mk(y, b, a) if order == "dmy" else _mk(y, a, b)
            return ParsedDate(d.isoformat(), order) if d else ParsedDate(None, problem="date_unreadable")
        if a > 12 >= b:
            d = _mk(y, b, a)
            return ParsedDate(d.isoformat(), "dmy") if d else ParsedDate(None, problem="date_unreadable")
        if b > 12 >= a:
            d = _mk(y, a, b)
            return ParsedDate(d.isoformat(), "mdy") if d else ParsedDate(None, problem="date_unreadable")
        if a == b:
            d = _mk(y, a, b)
            return ParsedDate(d.isoformat(), "format") if d else ParsedDate(None, problem="date_unreadable")
        return ParsedDate(None, problem="date_order")
    if _TWO.match(s):
        return ParsedDate(None, problem="two_digit_year")
    m = _SERIAL.match(s)
    if m and serial and 20000 <= int(m.group(1)) <= 60000:
        return ParsedDate((EXCEL_EPOCH + timedelta(days=int(m.group(1)))).isoformat(), "excel_serial")
    return ParsedDate(None, problem="date_unreadable")


def infer_order(values: Sequence[str]) -> str | None:
    """The order the column's own unambiguous cells show (a first part over 12 is a day): a *suggestion* for the
    ``date_order`` check, never applied without the person's answer."""
    seen = set()
    for v in values:
        m = _DMY.match(half_width(str(v or "")).strip())
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12 >= b:
            seen.add("dmy")
        elif b > 12 >= a:
            seen.add("mdy")
    return next(iter(seen)) if len(seen) == 1 else None


# ------------------------------------------------------------------------------------------------ numbers, units
_NUM = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*(.*?)\s*$")
_UNITS = {
    "mg/dl": "mg/dL",
    "mg/l": "mg/L",
    "g/dl": "g/dL",
    "umol/l": "µmol/L",
    "μmol/l": "µmol/L",  # Greek mu
    "µmol/l": "µmol/L",  # micro sign
    "mmol/l": "mmol/L",
    "mmol/mol": "mmol/mol",
    "%": "%",
    "kg": "kg",
    "lb": "lb",
    "lbs": "lb",
}


def norm_unit(unit: str) -> str:
    u = half_width(str(unit or "")).strip().replace(" ", "")
    u = u.strip("()（）[]")
    return _UNITS.get(u.lower(), u)


@dataclass(frozen=True)
class Analyte:
    name: str
    unit: str  # the unit TrialBox stores
    loinc: str
    lo: float  # plausible range in ``unit`` (a value outside it is not a reason to convert, only a hint)
    hi: float
    conv: Mapping[str, Callable[[float], float]] = field(default_factory=dict)


ANALYTES: dict[str, Analyte] = {
    "urate": Analyte("urate", "mg/dL", "3084-1", 0.5, 20.0, {"µmol/L": lambda v: v / 59.48}),
    "creatinine": Analyte("creatinine", "mg/dL", "2160-0", 0.1, 20.0, {"µmol/L": lambda v: v / 88.42}),
    "hba1c": Analyte("hba1c", "%", "4548-4", 3.0, 20.0, {"mmol/mol": lambda v: v * 0.09148 + 2.152}),
    "glucose": Analyte("glucose", "mg/dL", "2345-7", 20.0, 800.0, {"mmol/L": lambda v: v * 18.016}),
    "weight": Analyte("weight", "kg", "29463-7", 1.0, 400.0, {"lb": lambda v: v * 0.45359237}),
}
_ANALYTE_WORDS: tuple[tuple[str, str], ...] = (
    (r"尿酸|uric|urate|\bs?UA\b", "urate"),
    (r"クレアチニン|肌酸酐|creatinine|\bCre?\b|\bCRE\b", "creatinine"),
    (r"HbA1c|A1c|糖化血色素|ヘモグロビンA1c", "hba1c"),
    (r"血糖|glucose|\bGLU\b", "glucose"),
    (r"体重|體重|weight", "weight"),
)


def analyte_of(text: str) -> str | None:
    t = half_width(text)
    for rx, name in _ANALYTE_WORDS:
        if re.search(rx, t, re.I):
            return name
    return None


def unit_in(text: str) -> str:
    """A unit written in a header or after a value: ``尿酸値（mg/dL）``, ``8.4 mg/dl``."""
    t = half_width(text)
    m = re.search(r"(mg/dl|mg/l|g/dl|[uμµ]mol/l|mmol/mol|mmol/l|%|\bkg\b|\blbs?\b)", t, re.I)
    return norm_unit(m.group(1)) if m else ""


def parse_number(raw: str) -> tuple[float | None, str]:
    """``(value, unit written after it)``; ``(None, "")`` when the cell is not one number."""
    s = half_width(str(raw or "")).strip().replace(",", "")
    m = _NUM.match(s)
    if not m:
        return None, ""
    rest = m.group(2)
    if rest and not unit_in(rest):
        return None, ""
    return float(m.group(1)), unit_in(rest)


def convert(analyte: str, value: float, unit: str) -> tuple[float, str, bool] | None:
    """``(value, unit, converted)`` in the analyte's stored unit, or None when the unit is not one TrialBox knows for
    this analyte (a person decides)."""
    a = ANALYTES.get(analyte)
    u = norm_unit(unit)
    if a is None:
        return (value, u, False) if u else None
    if u == a.unit:
        return value, a.unit, False
    fn = a.conv.get(u)
    if fn is None:
        return None
    return round(fn(value), 2), a.unit, True


def unit_suggestion(analyte: str, value: float) -> str:
    """For an unknown or missing unit: the analyte's unit when the value is plausible in it, else leave it out."""
    a = ANALYTES.get(analyte)
    return a.unit if a is not None and a.lo <= value <= a.hi else "drop"


# ------------------------------------------------------------------------------------------------ layout
Grid = list[list[str]]
Merged = Sequence[tuple[int, int, int, int]]  # (first row, first col, last row, last col), 0-based, inclusive


def _col(c: int) -> str:
    out = ""
    c += 1
    while c:
        c, r = divmod(c - 1, 26)
        out = chr(65 + r) + out
    return out


def unmerge(grid: Grid, merged: Merged) -> tuple[Grid, list[Fix]]:
    """Every cell of a merged range gets the range's value (Excel keeps it in the first cell only)."""
    out = [list(r) for r in grid]
    fixes: list[Fix] = []
    for r1, c1, r2, c2 in merged:
        if r1 >= len(out):
            continue
        val = out[r1][c1] if c1 < len(out[r1]) else ""
        for r in range(r1, min(r2, len(out) - 1) + 1):
            row = out[r]
            while len(row) <= c2:
                row.append("")
            for c in range(c1, c2 + 1):
                row[c] = val
        fixes.append(Fix("merged", f"{_col(c1)}{r1 + 1}:{_col(c2)}{r2 + 1}", r1 + 1, "", str(val)[:60]))
    return out, fixes


def _datelike(s: str) -> bool:
    p = parse_date(s, serial=False)
    return p.iso is not None or p.problem in ("date_order", "two_digit_year", "era_boundary")


def find_header(grid: Grid, look: int = 10) -> int:
    """The header row: the first of the first ``look`` rows with at least two cells that are words (not numbers or
    dates), followed by a data row. Rows above it (a title, a date of printing) are skipped and listed."""
    for i, row in enumerate(grid[:look]):
        cells = [half_width(str(c)).strip() for c in row if str(c or "").strip()]
        if len(cells) < 2 or len(set(cells)) < 2:
            continue
        words = [c for c in cells if parse_number(c)[0] is None and not _datelike(c)]
        if len(words) >= max(2, int(0.6 * len(cells))) and i + 1 < len(grid):
            return i
    return 0


# ------------------------------------------------------------------------------------------------ columns
ROLES = (
    "chart_no",  # the hospital's chart number: turned into the pseudonym, never stored
    "birth_date",
    "sex",
    "diagnosis",  # a diagnosis as written (a local code until mapped once for the site)
    "diagnosis_code",  # the hospital's own diagnosis code
    "lab",  # a lab value; the analyte from the header or the lab_code column
    "lab_code",
    "lab_unit",
    "date",  # the visit / test / prescription date of the row
    "drug_code",
    "drug_name",
    "ignore",
)
IDENTIFIER = re.compile(
    r"(?i)^(name|patient.?name|full.?name|first.?name|last.?name|kana|phone|tel|mobile|e-?mail|address|postcode|zip|"
    r"氏名|患者名|名前|カナ|フリガナ|電話|住所|郵便番号|姓名|病人姓名|電話號碼|地址|身分證|身份證|マイナンバー)"
)
_ROLE_WORDS: tuple[tuple[str, str], ...] = (
    (r"カルテ|病歷號|病历号|病歷|chart|\bMRN\b|患者番号|患者ID|patient.?(no|id)", "chart_no"),
    (r"生年月日|出生|birth|DOB", "birth_date"),
    (r"性別|sex|gender", "sex"),
    (r"病名コード|診断コード|ICD|診斷碼|diag.*code|dx.?code", "diagnosis_code"),
    (r"病名|診断|診斷|diagnos|\bdx\b", "diagnosis"),
    (r"検査コード|検査項目コード|lab.?code|檢驗代碼|JLAC", "lab_code"),
    (r"単位|單位|unit", "lab_unit"),
    (r"薬剤コード|藥品代碼|drug.?code|YJ|ATC", "drug_code"),
    (r"薬剤名|薬剤|藥品|drug|medic", "drug_name"),
    (r"検査値|結果値|檢驗值|result|value", "lab"),
    (r"受診日|検査日|処方日|日付|日期|就診|date|visit", "date"),
)
_CHART_HEAD = re.compile(r"(?i)(^id$|^no\.?$|番号|編號|号码|號碼|\bID\b)")
_CHART_VAL = re.compile(r"^\d{6,10}$")


def guess_role(header: str) -> str:
    h = half_width(header)
    if analyte_of(h) and not re.search(r"コード|code|代碼", h, re.I):
        return "lab"
    for rx, role in _ROLE_WORDS:
        if re.search(rx, h, re.I):
            return role
    return "ignore"


def chart_like(header: str, values: Sequence[str]) -> bool:
    """A column that might hold chart numbers: an ID-like header, or mostly unique 6-10 digit numbers."""
    vals = [half_width(str(v)).strip() for v in values if str(v or "").strip()]
    if _CHART_HEAD.search(half_width(header)):
        return True
    if len(vals) < 2:
        return False
    digits = [v for v in vals if _CHART_VAL.match(v)]
    return len(digits) >= 0.8 * len(vals) and len(set(digits)) >= 0.8 * len(digits)


_SEX = {
    "男": "male",
    "男性": "male",
    "m": "male",
    "male": "male",
    "女": "female",
    "女性": "female",
    "f": "female",
    "female": "female",
}


# ------------------------------------------------------------------------------------------------ the table
@dataclass
class Record:
    row: int  # the row as Excel numbers it
    key: str  # the chart number as written (half-width): the caller turns it into the pseudonym at once
    values: dict[str, str]  # column -> cleaned value (dates ISO, numbers in the stored unit)
    units: dict[str, str] = field(default_factory=dict)  # lab column -> stored unit
    analytes: dict[str, str] = field(default_factory=dict)  # lab column -> analyte


@dataclass
class Cleaned:
    head: list[str]
    roles: dict[str, str]  # column -> role (identifier columns are not here)
    records: list[Record]
    fixes: list[Fix]
    checks: list[Check]
    dropped: list[str]  # identifier columns left out (names, phones ...)
    held: list[str]  # columns held back until a person answers (might be a chart number)
    header_row: int  # 1-based


def clean(
    grid: Grid,
    merged: Merged = (),
    roles: Mapping[str, str] | None = None,
    answers: Mapping[str, str] | None = None,
) -> Cleaned:
    """Clean one sheet: unmerge, find the header, map columns, fix what is safe, list the rest. ``roles`` maps a
    header to a role (:data:`ROLES`); a header not given gets :func:`guess_role`. ``answers`` maps
    :attr:`Check.key` to the chosen option."""
    answers = dict(answers or {})
    orig, _ = unmerge([["" if c is None else str(c) for c in r] for r in grid], merged)
    grid = [[half_width(str(c)) if c is not None else "" for c in r] for r in grid]
    grid, fixes = unmerge(grid, merged)
    hi = find_header(grid)
    if hi > 0:
        title = " ".join(str(c).strip() for r in grid[:hi] for c in r if str(c).strip())[:80]
        fixes.append(Fix("header_row", "", hi + 1, title, f"row {hi + 1}"))
    head: list[str] = []
    for i, h in enumerate(grid[hi] if grid else []):
        name = str(h).strip() or f"column {_col(i)}"
        while name in head:
            name += "'"
        head.append(name)
    body = [(hi + 2 + k, r) for k, r in enumerate(grid[hi + 1 :]) if any(str(c).strip() for c in r)]
    col = {h: [str(r[i]).strip() if i < len(r) else "" for _, r in body] for i, h in enumerate(head)}
    given = dict(roles or {})
    out_roles: dict[str, str] = {}
    dropped: list[str] = []
    held: list[str] = []
    checks: list[Check] = []
    for h in head:
        if IDENTIFIER.match(h) and given.get(h) != "chart_no":
            dropped.append(h)
            continue
        out_roles[h] = given.get(h) or guess_role(h)
    if "chart_no" not in out_roles.values():
        for h in head:  # no chart-number column named: one that looks like it is asked about, never assumed
            if h not in out_roles or out_roles[h] in ("lab", "date", "birth_date"):
                continue
            if chart_like(h, col[h]):  # its values are never shown: they may be chart numbers
                ck = Check("chart_column", h, None, "…", "chart_no", ("chart_no", "keep", "drop"))
                a = answers.get(ck.key)
                if a == "chart_no":
                    out_roles[h] = "chart_no"
                    break
                if a == "drop":
                    dropped.append(h)
                    del out_roles[h]
                elif a != "keep":
                    held.append(h)
                    del out_roles[h]
                    checks.append(ck)
    else:  # another number column beside the named chart number that also looks like one is asked about too
        for h in head:
            if out_roles.get(h) in (None, "chart_no", "lab", "date", "birth_date"):
                continue
            if chart_like(h, col[h]):
                ck = Check("chart_column", h, None, "…", "drop", ("chart_no", "keep", "drop"))
                a = answers.get(ck.key)
                if a == "keep":
                    continue
                if a != "drop":
                    checks.append(ck)
                    held.append(h)
                else:
                    dropped.append(h)
                del out_roles[h]
    key_col = next((h for h, r in out_roles.items() if r == "chart_no"), None)
    unit_col = next((h for h, r in out_roles.items() if r == "lab_unit"), None)
    code_col = next((h for h, r in out_roles.items() if r == "lab_code"), None)
    # one date-order question per column, with the column's own evidence as the suggestion
    order: dict[str, str | None] = {}
    for h, r in out_roles.items():
        if r in ("date", "birth_date"):
            ck = Check("date_order", h, None, "", infer_order(col[h]) or "mdy", ORDERS)
            order[h] = answers.get(ck.key) if answers.get(ck.key) in ORDERS else None
    asked: set[str] = set()
    records: list[Record] = []
    for rown, raw in body:
        vals = {h: (str(raw[i]).strip() if i < len(raw) else "") for i, h in enumerate(head)}
        src = orig[rown - 1]
        ovals = {h: (str(src[i]).strip() if i < len(src) else "") for i, h in enumerate(head)}
        key = vals.get(key_col, "").strip() if key_col else ""
        if not key:
            ck = Check("no_key", key_col or "", rown, "", "drop", ("drop",))
            if ck.key not in answers:
                checks.append(ck)
            continue
        rec = Record(rown, key, {})
        for h, role in out_roles.items():
            v, ov = vals.get(h, ""), ovals.get(h, "")
            if role in ("chart_no", "ignore", "lab_unit") or not v:
                continue
            if role in ("date", "birth_date"):
                _date_cell(rec, h, v, ov, order.get(h), col[h], answers, asked, fixes, checks)
            elif role == "sex":
                sx = _SEX.get(v.strip().lower())
                ck = Check("sex", h, rown, v, "drop", ("male", "female", "drop"))
                a = sx or answers.get(ck.key)
                if a in ("male", "female"):
                    rec.values[h] = a
                elif a is None:
                    checks.append(ck)
            elif role == "lab":
                _lab_cell(rec, h, v, ov, vals, code_col, unit_col, answers, asked, fixes, checks)
            else:
                rec.values[h] = re.sub(r"\s+", " ", v).strip()
                if ov != v:  # full-width digits or letters rewritten (never in a key or identifier column)
                    fixes.append(Fix("width", h, rown, ov[:40], rec.values[h][:40]))
        records.append(rec)
    return Cleaned(head, out_roles, records, fixes, checks, dropped, held, hi + 1)


def _date_cell(
    rec: Record,
    h: str,
    v: str,
    ov: str,
    order: str | None,
    column: Sequence[str],
    answers: Mapping[str, str],
    asked: set[str],
    fixes: list[Fix],
    checks: list[Check],
) -> None:
    p = parse_date(v, order)
    if p.iso:
        rec.values[h] = p.iso
        if p.kind or ov != v:
            fixes.append(Fix(p.kind or "width", h, rec.row, ov, p.iso))
        return
    if p.problem is None:
        return
    if p.problem == "date_order":
        ck = Check("date_order", h, None, v, infer_order(column) or "mdy", ORDERS)
    elif p.problem == "era_boundary":
        ck = Check("era_boundary", h, rec.row, v, p.suggestion or "drop", (p.suggestion or "", "drop"))
    else:
        ck = Check(p.problem, h, rec.row, v, "drop", ("drop",))
    a = answers.get(ck.key)
    if p.problem == "era_boundary" and a and a != "drop":
        rec.values[h] = a
        fixes.append(Fix("era", h, rec.row, ov, a))
    elif a is None and ck.key not in asked:
        asked.add(ck.key)
        checks.append(ck)


def _lab_cell(
    rec: Record,
    h: str,
    v: str,
    ov: str,
    vals: Mapping[str, str],
    code_col: str | None,
    unit_col: str | None,
    answers: Mapping[str, str],
    asked: set[str],
    fixes: list[Fix],
    checks: list[Check],
) -> None:
    num, cell_unit = parse_number(v)
    if num is None:
        return
    analyte = analyte_of(h) or (analyte_of(vals.get(code_col, "")) if code_col else None) or ""
    unit = cell_unit or (norm_unit(vals.get(unit_col, "")) if unit_col else "") or unit_in(h)
    conv = convert(analyte, num, unit) if unit else None
    if conv is None:  # a unit TrialBox does not know for this test (or none at all): a person decides
        known = ANALYTES[analyte].unit if analyte in ANALYTES else ""
        ck = Check(
            "unit",
            f"{h}|{unit or '-'}",
            None,
            unit or "",
            unit_suggestion(analyte, num),
            tuple(o for o in (known, "drop") if o),
        )
        a = answers.get(ck.key)
        if a and a != "drop":
            rec.values[h], rec.units[h], rec.analytes[h] = f"{num:g}", a, analyte
            fixes.append(Fix("unit", h, rec.row, f"{ov} {unit}".strip(), f"{num:g} {a}"))
        elif a is None and ck.key not in asked:
            asked.add(ck.key)
            checks.append(ck)
        return
    value, stored, converted = conv
    rec.values[h], rec.units[h], rec.analytes[h] = f"{value:g}", stored, analyte
    if converted:
        fixes.append(Fix("unit", h, rec.row, f"{ov} {unit}".strip(), f"{value:g} {stored}"))
    elif ov != v:
        fixes.append(Fix("width", h, rec.row, ov, f"{value:g}"))


def summarise(fixes: Sequence[Fix], examples: int = 3) -> list[dict[str, object]]:
    """Fixes grouped by kind and column: ``{kind, column, n, examples: [[before, after], ...]}``."""
    groups: dict[tuple[str, str], list[Fix]] = {}
    for f in fixes:
        groups.setdefault((f.kind, f.column), []).append(f)
    return [
        {"kind": k, "column": c, "n": len(v), "examples": [[f.before, f.after] for f in v[:examples]]}
        for (k, c), v in sorted(groups.items())
    ]
