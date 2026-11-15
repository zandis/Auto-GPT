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
* ``IU/L`` against ``U/L``, except for the analytes of catalytic activity (:data:`ENZYME_ACTIVITY`, D-585), where
  the two are one unit by definition;
* a row unit when the lookup declares none.

No value is unknown to the screening engines, never a failed comparison (D-130): a unit mismatch can hold a patient for
a person to check, it can never exclude one. A row without a unit is read in the lookup's unit (the site's declared
unit, as D-149's ``unit_defaults``). Text that is no number is ``unknown_value``.
"""

from __future__ import annotations

import math
import re
import unicodedata
from typing import NamedTuple

from tb_common import labunit
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
        return (float(text), None) if math.isfinite(text) else None  # NaN and infinity are not results
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
UNIT_MISMATCH = labunit.UNIT_MISMATCH  # one spelling of the reason for the adapter and the engines (D-275)
UNKNOWN_VALUE = Reason.UNKNOWN_VALUE.value
# D-590: a result with no unit whose value cannot be one in the look-up's unit: no value, like a unit mismatch
NO_UNIT_IMPLAUSIBLE = "no_unit_implausible"

# UCUM code -> the spellings that mean exactly that unit: one table in :mod:`tb_common.labunit` (D-418), which
# the engines' scale conversions read too.
UCUM = labunit.UCUM
# NEW-STD-4 (D-585): what Japanese and Taiwanese labs print. Read here, in the feed's reader, and not added to the
# engines' table: a spelling there becomes an arm of every ruleset's compiled SQL. A mapped row is stored in its
# look-up's unit once this reader agreed, so the engines never meet these spellings from a mapped feed.
# the multiplication sign as ``x``, and the units of time written in kanji (``mL/分/1.73m2``, ``秒``, ``mm/時``)
_SPELL = str.maketrans({"×": "x", "✕": "x", "分": "min", "秒": "s", "時": "h"})
# more spellings of units the table knows, and one unit it does not: ``10*2/uL`` (white cells in Japan) agrees with
# itself only. ``G/L`` is on purpose not here: giga per litre in a blood count, grams per litre in an upper-case
# export; the site declares it per analyte (``source_unit``).
FEED_SPELLINGS: dict[str, tuple[str, ...]] = {
    "10*3/uL": ("千/uL", "千/µL", "1000/uL", "1000/µL"),  # F15 (D-809): a thousand written out
    "10*4/uL": ("x10^4/µL",),
    "10*6/uL": ("x10^6/µL",),
    "10*2/uL": ("10^2/uL", "10^2/µL", "x10^2/uL", "x10^2/µL"),
    # F15 (D-809): ``{cells}`` is a UCUM annotation, what is counted: not a unit of its own
    "/uL": ("個/uL", "個/µL", "{cells}/uL", "{cells}/µL"),
    # F15 (D-809): D-dimer in fibrinogen-equivalent units, about twice the same result in D-dimer units: its own
    # unit, agreeing only with itself, never with plain ``mg/L`` (a site whose look-up says FEU writes ``mg/L{FEU}``)
    "mg/L{FEU}": ("mg/L FEU", "mg/L(FEU)", "mg/L {FEU}", "ug/mL FEU", "µg/mL FEU", "ug/mL(FEU)", "µg/mL(FEU)"),
    # F15 (D-809): a titer's "times" (倍數): its own unit, agreeing only with itself
    "{titer}": ("倍數", "倍数", "倍"),
}
# analytes measured as catalytic activity per volume in serum or plasma (LOINC): AST, ALT, ALP, LDH, CK, γ-GT and
# lipase, each confirmed as "[Enzymatic activity/volume]" in ``catalogue/codes_checked.csv``. A code is added here
# with its catalogue row, never from memory. For these, and only these, the international unit is the enzyme unit
# by definition (1 IU = 1 U = 1 µmol of substrate a minute), so ``IU/L`` on a row and ``U/L`` in the look-up are
# one unit. An IU of insulin or of a vitamin is not an enzyme unit: every other analyte keeps them apart (D-215).
ENZYME_ACTIVITY = frozenset({"1920-8", "1742-6", "6768-6", "2532-0", "2157-6", "2324-2", "3040-3"})
_ENZYME_UNIT = {"[IU]/L": "U/L", "[IU]/mL": "U/mL", "m[IU]/mL": "mU/mL"}


def _spelled(unit: object) -> str:
    """A unit as it is looked up: NFKC, no spaces, the signs of :data:`_SPELL` in their plain form."""
    return unicodedata.normalize("NFKC", str(unit)).replace(" ", "").translate(_SPELL)


_KNOWN: dict[str, str] = {}
for _code, _spellings in (*UCUM.items(), *FEED_SPELLINGS.items()):
    for _u in (_code, *_spellings):
        _KNOWN[_spelled(_u)] = _code


_FOLDED: dict[str, set[str]] = {}
for _k, _code in _KNOWN.items():
    _FOLDED.setdefault(_k.lower(), set()).add(_code)


def ucum(unit: object) -> str | None:
    """The UCUM code a unit as written stands for, or None when :data:`UCUM` does not know it. The exact spelling
    first (NFKC, no spaces, :data:`_SPELL`); then, for a quotient only (``MG/DL``, ``U/l``: hospital exports often
    change the case), the case-folded spelling when it names one code. A bare symbol is never case-folded (``M`` is
    molar, ``m`` metre; ``S`` siemens, ``s`` second)."""
    if unit is None:
        return None
    u = _spelled(unit)
    if not u:
        return None
    if u in _KNOWN:
        return _KNOWN[u]
    folded = _FOLDED.get(u.lower(), set()) if "/" in u else set()
    return next(iter(folded)) if len(folded) == 1 else None


def _as_enzyme(code: str | None, loinc: str | None) -> str | None:
    return _ENZYME_UNIT.get(code, code) if code and loinc in ENZYME_ACTIVITY else code


def written(unit: object) -> str:
    """A unit as written, width and blanks folded, case kept (``mg`` is not ``Mg``): the key of a site's
    ``unit_spellings`` (D-590)."""
    return "".join(unicodedata.normalize("NFKC", "" if unit is None else str(unit)).split())


# D-590 (DIN-017): for a result that comes with no unit and is read in the look-up's unit (D-149), the range a
# value can have in that unit, per LOINC code: ``(UCUM unit, low, high)``. Only analytes whose other common unit
# differs by about an order of magnitude or more, so that a value in the wrong unit falls outside (creatinine
# 88 µmol/L against 0.1 to 20 mg/dL; HbA1c 0.072 or 53 mmol/mol against 3 to 20 %). The numbers are the sheet
# path's (``sitesetup.messy.ANALYTES``). A site's look-up states its own in ``plausible_low`` / ``plausible_high``
PLAUSIBLE: dict[str, tuple[str, float, float]] = {
    "2160-0": ("mg/dL", 0.1, 20.0),  # creatinine
    "3084-1": ("mg/dL", 0.5, 20.0),  # urate
    "4548-4": ("%", 3.0, 20.0),  # HbA1c (NGSP)
    "2345-7": ("mg/dL", 20.0, 800.0),  # glucose
}


def plausible_range(loinc: str | None, unit: object) -> tuple[float, float] | None:
    """The built-in range of ``loinc`` when ``unit`` is the unit the range is stated in, else None."""
    got = PLAUSIBLE.get(loinc or "")
    if got is None or ucum(unit) != ucum(got[0]):
        return None
    return got[1], got[2]


def units_agree(row_unit: object, lookup_unit: object, loinc: str | None = None) -> bool | None:
    """None when the row names no unit (the site's declared unit applies); True only when both are the same UCUM
    code (:func:`ucum`); False otherwise, a unit :data:`UCUM` lacks on either side included. Decided on the units
    alone, before and whatever the result text is. ``loinc``: the analyte, for the one rule that depends on it
    (:data:`ENZYME_ACTIVITY`: ``IU/L`` and ``U/L`` are one unit)."""
    row = "" if row_unit is None else unicodedata.normalize("NFKC", str(row_unit)).strip()
    if not row:
        return None
    mine, theirs = _as_enzyme(ucum(row), loinc), _as_enzyme(ucum(lookup_unit), loinc)
    return mine is not None and mine == theirs


class Reading(NamedTuple):
    """One lab cell read against its lookup: the value in the lookup's unit, or None and the reason."""

    value: float | None
    comparator: str | None
    reason: str | None


def read(text: object, row_unit: object, lookup_unit: object, loinc: str | None = None) -> Reading:
    """``text`` (the result as written) with the row's own unit, against the unit the lookup declares. The units are
    judged first (:func:`units_agree`, with the analyte ``loinc`` when the look-up names one): a mismatch is
    ``unit_mismatch`` whatever the text. Then the text is read by :func:`parse` only (no exponent, no ``NaN``): a
    value comes back in the lookup's unit, never converted."""
    if units_agree(row_unit, lookup_unit, loinc) is False:
        return Reading(None, None, UNIT_MISMATCH)
    got = parse(text)
    if got is None:
        return Reading(None, None, UNKNOWN_VALUE)
    return Reading(got[0], got[1], None)


# ------------------------------------------------------------------------------------- conversions (D-334)
# The adapter never converts a row's unit on its own (D-215 above): a row in another unit has no value until the
# site's lab team declares the unit the source reports (the lookup's ``source_unit`` and ``factor``). This table is
# what they check that declaration against, and what ``tools/mapping_check.py`` proposes for a unit pair it finds.
#
# Units of one kind convert by definition, whatever the analyte: each family gives how much of its first unit one
# unit is. Units are the UCUM codes of :data:`UCUM`; the tables are keyed by :func:`tb_common.labunit.key`.
SCALES = labunit.SCALES  # the families live with the engines' unit rule (D-418): one table, two readers

# Mass to substance needs the analyte (STD-002): LOINC code -> (what is weighed, g/mol, charge for meq or 0). A
# charge of 1 makes meq/L the same as mmol/L, 2 makes it half. HbA1c % (NGSP) and mmol/mol (IFCC) are not a factor
# apart (the master equation has an offset): there is no row for them, so they never convert.
MOLAR: dict[str, tuple[str, float, int]] = {
    "3084-1": ("urate", 168.11, 0),
    "2345-7": ("glucose", 180.16, 0),
    "1558-6": ("glucose", 180.16, 0),
    "1518-0": ("glucose", 180.16, 0),
    "1975-2": ("bilirubin", 584.66, 0),
    "1968-7": ("bilirubin", 584.66, 0),
    "2093-3": ("cholesterol", 386.65, 0),
    "2089-1": ("cholesterol", 386.65, 0),
    "13457-7": ("cholesterol", 386.65, 0),
    "2085-9": ("cholesterol", 386.65, 0),
    "2571-8": ("triglyceride (as triolein)", 885.7, 0),
    "3094-0": ("urea nitrogen (2 N per urea)", 28.014, 0),
    "17861-6": ("calcium", 40.078, 2),
    "2777-1": ("phosphate (as P)", 30.974, 0),
    "2601-3": ("magnesium", 24.305, 2),
    "718-7": ("hemoglobin (Fe monomer)", 16114.5, 0),
    "16362-6": ("ammonia", 17.031, 0),
    "2498-4": ("iron", 55.845, 0),
    "3024-7": ("free thyroxine", 776.87, 0),
    "2143-6": ("cortisol", 362.46, 0),
    "2986-8": ("testosterone", 288.42, 0),
    "2132-9": ("cobalamin", 1355.37, 0),
    "1989-3": ("25-hydroxyvitamin D3", 400.64, 0),
    "2951-2": ("sodium", 22.99, 1),
    "2823-3": ("potassium", 39.098, 1),
    "2075-0": ("chloride", 35.45, 1),
    "1963-8": ("bicarbonate", 61.017, 1),
}


def _close(table: dict[str, float]) -> dict[str, float]:
    """``table`` (unit key -> factor to one reference unit) with every unit of each scale family it touches."""
    out = dict(table)
    for family in SCALES.values():
        keys = {labunit.key(u): f for u, f in family.items()}
        anchor = next((k for k in keys if k in out), None)
        if anchor is not None:
            for k, f in keys.items():
                out.setdefault(k, out[anchor] * f / keys[anchor])
    return out


def _analytes() -> dict[str, dict[str, float]]:
    """LOINC code -> {unit key: factor to the analyte's reference unit}. The analytes the engines already convert
    (``tb_common.labunit.ANALYTES``: creatinine, CRP, ESR, weight, height) keep their factors, so the adapter's check
    and the engines' comparison never disagree; the others come from :data:`MOLAR`."""
    out: dict[str, dict[str, float]] = {}
    for code, (_what, grams, charge) in MOLAR.items():
        table = {labunit.key("mmol/L"): 1.0, labunit.key("g/L"): 1000.0 / grams}
        if charge:
            table[labunit.key("meq/L")] = 1.0 / charge
        out[code] = _close(table)
    for (system, code), factors in labunit.ANALYTES.items():
        if system == "http://loinc.org":
            out[code] = _close(dict(factors))
    return out


ANALYTES: dict[str, dict[str, float]] = _analytes()


def conversion(have: object, need: object, loinc: str | None = None) -> float | None:
    """The factor ``k`` that turns a value in unit ``have`` into one in ``need`` (``value * k``) for the analyte
    ``loinc``, or None when there is no tested one. Both units are read by :func:`ucum` first (a spelling it does not
    know never converts). The same unit is 1. Without an analyte only a scale family converts (g/dL to g/L); mass to
    substance needs the analyte's row."""
    h, n = ucum(have), ucum(need)
    if h is None or n is None:
        return None
    if h == n:
        return 1.0
    kh, kn = labunit.key(h), labunit.key(n)
    table = ANALYTES.get(loinc or "")
    if table and kh in table and kn in table:
        return float(f"{table[kh] / table[kn]:.10g}")
    for family in SCALES.values():
        keys = {labunit.key(u): f for u, f in family.items()}
        if kh in keys and kn in keys:
            return float(f"{keys[kh] / keys[kn]:.10g}")
    return None


# --------------------------------------------------------------------------- presence results (D-334, STD-022)
POSITIVE, NEGATIVE, UNSETTLED = "POS", "NEG", "UNK"

# One table for every site: the text as :func:`presence` folds it (NFKC, lower case, no spaces) -> the answer. A
# site's own words go in its lookup's ``answers`` column, which is read first. ``UNSETTLED`` words are read on
# purpose as unknown (a borderline or held result is for a person to read): they never settle a criterion.
PRESENCE: dict[str, str] = {
    **dict.fromkeys(
        (
            "陰性",
            "阴性",
            "(-)",
            "-",
            "−",
            "(−)",
            "neg",
            "negative",
            "non-reactive",
            "nonreactive",
            "notdetected",
            "undetected",
            "未檢出",
            "未检出",
            "未検出",
            "検出せず",
            "検出されず",
            "無反應",
            "无反应",
        ),
        NEGATIVE,
    ),
    **dict.fromkeys(
        (
            "陽性",
            "阳性",
            "(+)",
            "+",
            "++",
            "+++",
            "++++",
            "(++)",
            "(+++)",
            "(++++)",
            "1+",
            "2+",
            "3+",
            "4+",
            "(1+)",
            "(2+)",
            "(3+)",
            "(4+)",
            "pos",
            "positive",
            "reactive",
            "detected",
            "検出",
            "檢出",
            "检出",
            "有反應",
            "有反应",
        ),
        POSITIVE,
    ),
    **dict.fromkeys(
        (
            "±",
            "(±)",
            "+-",
            "+/-",
            "判定保留",
            "判定不能",
            "保留",
            "弱陽性",
            "弱阳性",
            "灰區",
            "灰区",
            "不確定",
            "不确定",
            "equivocal",
            "indeterminate",
            "borderline",
            "inconclusive",
            "weaklypositive",
            "weakpositive",
        ),
        UNSETTLED,
    ),
}
_PAREN = re.compile(r"^(?P<a>[^()]*)\((?P<b>[^()]+)\)(?P<c>[^()]*)$")


def _fold(text: object) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text)).casefold())


def presence(text: object) -> str | None:
    """A qualitative result as :data:`POSITIVE`, :data:`NEGATIVE` or :data:`UNSETTLED`, in Japanese, Chinese or
    English (``陰性``, ``(-)``, ``未檢出``, ``Non-reactive``, ``陽性(+)``, ``2+``, ``判定保留``); None when the
    table does not know the text. A word with its sign in brackets (``陰性(-)``, ``(+)陽性``) reads as the two
    agree; when they disagree (``陰性(+)``) the result is unsettled."""
    if text is None or isinstance(text, bool):
        return None
    s = _fold(text)
    if not s:
        return None
    if s in PRESENCE:
        return PRESENCE[s]
    m = _PAREN.match(s)
    if m is None or (m.group("a") and m.group("c")):
        return None
    word = PRESENCE.get(m.group("a") or m.group("c"))
    sign = PRESENCE.get(f"({m.group('b')})") or PRESENCE.get(m.group("b"))
    if word is None or sign is None:
        return None
    return word if word == sign else UNSETTLED


def answer_key(text: object, answers: dict[str, str]) -> str | None:
    """The key of the lookup's ``answers`` a coded result reads as: the site's own word first (upper case, as the
    lookup is written), then :func:`presence`. None when neither reads it, or when it is unsettled."""
    s = str(text).strip().upper()
    if s in answers:
        return s
    word = presence(text)
    return word if word in (POSITIVE, NEGATIVE) and word in answers else None
