"""Lab result text as a number (D-142, review B-01): one reader for every input (the mapping engine for CSV, CGRD and
SS-MIX2 OBX-5, and the lake for FHIR ``valueString``).

A result such as ``"75 H"`` is the number 75 with an abnormal flag; ``"<0.3"`` and ``"0.3未満"`` are *censored*: the
true value is below 0.3, so only a comparison that holds (or fails) for every value below 0.3 can be decided. Text that
is none of these (``"検出せず"``, ``"陰性"``, ``"see note"``) is not a number: the screening engine treats it as
unknown, never as a failed comparison.

:func:`parse` returns ``(value, comparator)`` with ``comparator`` one of ``None`` (exact), ``"<"``, ``"<="``, ``">"``,
``">="`` (the FHIR ``Quantity.comparator`` codes), or ``None`` when the text is not a readable number.

:func:`read` adds the row's own unit (R-31, T-118, D-215). The lookup says which unit a site's analyte is reported
in; a row that names its own unit is checked against it, and a value is returned only when the two are **the same
unit**: the same UCUM code or one of its usual spellings (:data:`UCUM`: ``mg/dl`` is ``mg/dL``, ``µmol/L`` is
``umol/L``, ``ug/mL`` is ``mg/L``). Anything else gives **no value** and the reason ``unit_mismatch``:

* a different unit, even one a factor away (a CRP in ``mg/L`` against an ``mg/dL`` lookup is *not* divided by 10:
  the lookup may be wrong, the row may be wrong, and the site's lab team says which once, D-149);
* a unit :data:`UCUM` lacks, on either side (never converted, never assumed equal);
* a row unit when the lookup declares none.

No value is unknown to the screening engines, never a failed comparison (D-130): a unit mismatch can hold a patient for
a person to check, it can never exclude one. A row without a unit is read in the lookup's unit (the site's declared
unit, as D-149's ``unit_defaults``). Text that is no number is ``unknown_value``.
"""

from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple

from tb_common.reasons import Reason

# abnormal flags written after (or, less often, before) the number: HL7 table 0078 and the usual JP / TW marks
_FLAG = r"(?:HH|LL|H|L|N|A|AA|\*+|↑+|↓+|高|低|\(H\)|\(L\)|\[H\]|\[L\])"
_NUM = r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|[+-]?\.\d+"
_PREFIX = {"<": "<", "<=": "<=", ">": ">", ">=": ">=", "≦": "<=", "≤": "<=", "≧": ">=", "≥": ">=", "=<": "<="}
_PREFIX["=>"] = ">="
_SUFFIX = {"未満": "<", "以下": "<=", "以上": ">=", "超": ">", "より大きい": ">", "より小さい": "<"}
_RE = re.compile(
    rf"^(?:{_FLAG}\s*)?(?P<pre><=|>=|=<|=>|<|>|≦|≤|≧|≥)?\s*(?P<num>{_NUM})\s*"
    rf"(?P<suf>未満|以下|以上|超|より大きい|より小さい)?\s*(?:{_FLAG})?$"
)


def parse(text: object) -> tuple[float, str | None] | None:
    """``(value, comparator)`` for a readable result, else None. Full-width forms are folded first (NFKC)."""
    if text is None or isinstance(text, bool):
        return None
    if isinstance(text, int | float):
        return float(text), None
    s = unicodedata.normalize("NFKC", str(text)).strip()
    if not s:
        return None
    m = _RE.match(s)
    if m is None:
        return None
    pre, suf = m.group("pre"), m.group("suf")
    if pre and suf:
        return None  # "<0.3未満": two comparators, not a form anyone writes on purpose
    try:
        value = float(m.group("num").replace(",", ""))
    except ValueError:
        return None
    return value, (_PREFIX[pre] if pre else _SUFFIX[suf] if suf else None)


# ------------------------------------------------------------------------------------------------ units (R-31)
UNIT_MISMATCH = Reason.UNIT_MISMATCH.value
UNKNOWN_VALUE = Reason.UNKNOWN_VALUE.value

# UCUM code -> the spellings that mean exactly that unit (no factor: a spelling, or a unit equal to it by definition,
# ug/mL = mg/L). A unit not listed here is unknown: it is never converted and never taken as equal to another.
UCUM: dict[str, tuple[str, ...]] = {
    "mg/dL": ("mg/dl", "mg/100mL", "mg%"),
    "mg/L": ("mg/l", "ug/mL", "ug/ml", "µg/mL", "μg/mL"),
    "g/dL": ("g/dl", "g/100mL"),
    "g/L": ("g/l", "mg/mL", "mg/ml"),
    "ug/dL": ("ug/dl", "µg/dL", "μg/dL"),
    "ug/L": ("ug/l", "µg/L", "μg/L", "ng/mL", "ng/ml"),
    "ng/dL": ("ng/dl",),
    "pg/mL": ("pg/ml", "ng/L", "ng/l"),
    "umol/L": ("µmol/L", "μmol/L", "umol/l", "µmol/l", "μmol/l"),
    "mmol/L": ("mmol/l",),
    "mmol/mol": (),
    "nmol/L": ("nmol/l",),
    "pmol/L": ("pmol/l",),
    "meq/L": ("mEq/L", "mEq/l", "meq/l"),
    "%": ("percent",),
    # an enzyme unit (U) and an international unit ([IU]) are kept apart: labs often use them alike, but a person
    # says so for the site once, the table does not
    "U/L": (),
    "[IU]/L": ("IU/L",),
    "U/mL": (),
    "[IU]/mL": ("IU/mL",),
    "mU/mL": (),
    "m[IU]/mL": ("mIU/mL",),
    "uU/mL": ("µU/mL", "μU/mL"),
    "u[IU]/mL": ("uIU/mL", "µIU/mL", "μIU/mL"),
    "10*3/uL": ("10^3/uL", "10^3/µL", "x10^3/uL", "x10^3/µL", "10*9/L", "10^9/L", "x10^9/L", "/nL", "K/uL"),
    "10*6/uL": ("10^6/uL", "10^6/µL", "x10^6/uL", "10*12/L", "10^12/L", "x10^12/L", "M/uL"),
    "10*4/uL": ("10^4/uL", "10^4/µL", "x10^4/uL", "万/uL", "万/µL"),
    "/uL": ("/µL", "/ul", "cells/uL"),
    "fL": ("fl",),
    "pg": (),
    "s": ("sec",),
    "mm/h": ("mm/hr", "mm/(1.h)", "mm/1h"),
    "mL/min/{1.73_m2}": ("mL/min/1.73m2", "ml/min/1.73m2", "mL/min/1.73 m2", "mL/min/1.73m^2"),
    "mm[Hg]": ("mmHg",),
    "kg": (),
    "g": (),
    "cm": (),
    "m": (),
    "kg/m2": ("kg/m^2",),
    "mg/g{creat}": ("mg/gCr", "mg/g creatinine", "mg/gCre"),
    "{ratio}": ("ratio",),
    "1": ("{count}", "{score}"),
}
_KNOWN: dict[str, str] = {}
for _code, _spellings in UCUM.items():
    for _u in (_code, *_spellings):
        _KNOWN[unicodedata.normalize("NFKC", _u).replace(" ", "")] = _code


_FOLDED: dict[str, set[str]] = {}
for _k, _code in _KNOWN.items():
    _FOLDED.setdefault(_k.lower(), set()).add(_code)


def ucum(unit: object) -> str | None:
    """The UCUM code a unit as written stands for, or None when :data:`UCUM` does not know it. The exact spelling
    first (NFKC, no spaces); then, for a quotient only (``MG/DL``, ``U/l``: hospital exports often change the case),
    the case-folded spelling when it names one code. A bare symbol is never case-folded (``M`` is molar, ``m`` metre;
    ``S`` siemens, ``s`` second)."""
    if unit is None:
        return None
    u = unicodedata.normalize("NFKC", str(unit)).replace(" ", "")
    if not u:
        return None
    if u in _KNOWN:
        return _KNOWN[u]
    folded = _FOLDED.get(u.lower(), set()) if "/" in u else set()
    return next(iter(folded)) if len(folded) == 1 else None


class Reading(NamedTuple):
    """One lab cell read against its lookup: the value in the lookup's unit, or None and the reason."""

    value: float | None
    comparator: str | None
    reason: str | None


def read(text: object, row_unit: object, lookup_unit: object) -> Reading:
    """``text`` (the result as written) with the row's own unit, against the unit the lookup declares. A value comes
    back only in the lookup's unit and only when no conversion is needed; see the module docstring for the rules."""
    got = parse(text)
    if got is None:
        return Reading(None, None, UNKNOWN_VALUE)
    row = "" if row_unit is None else unicodedata.normalize("NFKC", str(row_unit)).strip()
    if not row:
        return Reading(got[0], got[1], None)  # the row says nothing: the site's declared unit
    mine, theirs = ucum(row), ucum(lookup_unit)
    if mine is None or theirs is None or mine != theirs:
        return Reading(None, None, UNIT_MISMATCH)
    return Reading(got[0], got[1], None)
