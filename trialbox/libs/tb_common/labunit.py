"""The unit of a plain lab comparison (D-275; review S-1, MR-002 / R-31).

A criterion such as "creatinine <= 1.5 mg/dL" names its unit (``Atom.value.unit``). Before D-275 the compiled SQL
compared the row's number with the criterion's number whatever the row's unit was: a creatinine of 90 umol/L failed
"<= 1.5 mg/dL", and an IFCC HbA1c of 53 mmol/mol met the exclusion "HbA1c > 10 %". Only the derived scores looked at
units (``tb_common.derived``, D-149).

The rule, for each observation row of a numeric comparison:

* the row's unit is the criterion's unit (both spelled as :func:`key` spells them): the number is used as it is;
* the row is one of the analytes of ``tb_common.derived.UNITS`` (creatinine, CRP, ESR, weight, height: found by the
  row's own code) and both units are in that analyte's table: the number is converted with the table's factors;
* both units are of one kind (:data:`SCALES`: mass, substance or number concentration, enzyme activity,
  international units per volume): the number is converted by the definition of the units, whatever the analyte
  (``g/L`` to ``g/dL``, ``10*4/uL`` to ``10*9/L``, ``ng/mL`` to ``ug/L``; D-418, DATA-016). The spellings of
  :data:`UCUM` are the same unit (``ug/mL`` is ``mg/L``);
* anything else, a row with no unit included: the row has **no usable number**. It can never make a comparison TRUE
  or FALSE; the answer is unknown unless the rows that can be read settle it, and the evidence carries the reason
  ``unit_mismatch``.

A criterion with no unit (a count or a score) reads rows with no unit, or a UCUM "number" annotation, only.

There is no conversion between units of different kinds (mg/dL to mmol/L needs a molar mass; % to mmol/mol is an offset
apart, not a factor): those rows are unknown. ``tb_common.labvalue.MOLAR`` holds molar masses for the adapter's check
only; the engines do not use them.

The same module names the reason of a medication atom that cannot be decided because an order does not say when the
last dose was (``order_dates_missing``): no end date or no date at all (review S-9), or, for a criterion of model v3,
a therapy period that reaches the window while the record rule reads the order's date (D-1263).
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from tb_common.derived import CODES, UNITLESS, UNITS, norm_unit
from tb_common.derived import reason_of as _derived_reason_of

UNIT_MISMATCH = "unit_mismatch"
ORDER_DATES = "order_dates_missing"
# an approved answer the current rules do not confirm (compile_sql.overlay): the least specific, reported last
RULES_CHANGED = "rules_changed"
#: D-917: a condition atom's only records in the window are recorded with a status it does not count
NOT_ACTIVE = "condition_not_active"
TOKENS = (UNIT_MISMATCH, ORDER_DATES, RULES_CHANGED, NOT_ACTIVE)  # in the order a reason is chosen

_DROP = "{}[]_"


def key(unit: str | None) -> str:
    """A unit as two spellings of it compare equal: :func:`tb_common.derived.norm_unit` (NFKC, no spaces, lower
    case, ``µ`` as ``u``), ``^`` as ``*`` and no UCUM braces, brackets or underscores (``mL/min/{1.73_m2}`` and
    ``mL/min/1.73m2``, ``mm[Hg]`` and ``mmHg``, ``10^9/L`` and ``10*9/L`` are the same unit)."""
    u = norm_unit(unit).replace("^", "*")
    for ch in _DROP:
        u = u.replace(ch, "")
    return u


def key_sql(col: str) -> str:
    """The SQL twin of :func:`key` for a row's unit column (no NFKC in DuckDB: a full-width unit is not matched and
    the row is unknown)."""
    expr = f"lower(coalesce({col}, ''))"
    for old, new in ((" ", ""), ("µ", "u"), ("μ", "u"), ("^", "*"), *((ch, "") for ch in _DROP)):
        expr = f"replace({expr}, '{old}', '{new}')"
    return expr


UNITLESS_KEYS = frozenset(key(u) for u in UNITLESS)

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
    # an enzyme unit (U) and an international unit ([IU]) are kept apart in this table. The feed's reader takes them
    # as one unit for the analytes of catalytic activity only (``labvalue.ENZYME_ACTIVITY``, D-585)
    "U/L": (),
    "[IU]/L": ("IU/L",),
    "U/mL": (),
    "[IU]/mL": ("IU/mL",),
    "mU/mL": (),
    "m[IU]/mL": ("mIU/mL",),
    "m[IU]/L": ("mIU/L",),
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
    "mm": (),
    "m": (),
    "kg/m2": ("kg/m^2",),
    "mg/g{creat}": ("mg/gCr", "mg/g creatinine", "mg/gCre"),
    "{ratio}": ("ratio",),
    "1": ("{count}", "{score}"),
}

# Units of one kind convert by definition, whatever the analyte (D-334; the engines read them since D-418): each
# family gives how much of its first unit one unit is. Units are the UCUM codes of :data:`UCUM`.
SCALES: dict[str, dict[str, float]] = {
    "mass concentration": {
        "g/L": 1.0,
        "g/dL": 10.0,
        "mg/dL": 1e-2,
        "mg/L": 1e-3,
        "ug/dL": 1e-5,
        "ug/L": 1e-6,
        "ng/dL": 1e-8,
        "pg/mL": 1e-9,
    },
    "substance concentration": {"mmol/L": 1.0, "umol/L": 1e-3, "nmol/L": 1e-6, "pmol/L": 1e-9},
    "number concentration": {"10*3/uL": 1.0, "10*4/uL": 10.0, "10*6/uL": 1e3, "/uL": 1e-3},
    "enzyme activity": {"U/L": 1.0, "mU/mL": 1.0, "U/mL": 1e3},
    "international units": {"[IU]/L": 1.0, "m[IU]/mL": 1.0, "[IU]/mL": 1e3, "m[IU]/L": 1e-3, "u[IU]/mL": 1e-3},
}


def _families() -> dict[str, tuple[str, float]]:
    """unit key -> (family, how much of the family's first unit one unit is), for every code of :data:`SCALES` and
    every spelling :data:`UCUM` gives it. A key two entries would give different meanings is left out (unknown)."""
    seen: dict[str, set[tuple[str, float]]] = {}
    for family, table in SCALES.items():
        for code, factor in table.items():
            for u in (code, *UCUM.get(code, ())):
                seen.setdefault(key(u), set()).add((family, factor))
    return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}


FAMILIES: dict[str, tuple[str, float]] = _families()
# the widest factor the engines apply between two units of one kind: every engine rounds a converted value to
# :data:`DIGITS` decimals, so a factor of 1e-6 (nmol/L to mmol/L) or 1e-7 (ug/L to g/dL) could round a real value to
# 0. Such pairs stay unknown; no site reports one analyte in both.
MAX_SCALE = 1000.0


# (system, code) of an analyte -> {unit key: factor to the analyte's reference unit}
ANALYTES: dict[tuple[str, str], dict[str, float]] = {
    CODES[comp]: {key(u): f for u, f in factors.items()} for comp, (_target, factors) in UNITS.items()
}


# a converted value is rounded to this many decimals in every engine (review F2): 1.5 mg/dL is 132.6 umol/L, not
# 132.60000000000002, so a value equal to the bound in the other unit compares as equal. Values that are not
# converted are compared as recorded.
DIGITS = 6


def _plain(x: float) -> str:
    """``x`` at 10 significant digits, written without an exponent (``1e-09`` is ``0.000000001``)."""
    return format(Decimal(f"{x:.10g}"), "f")


def conversion(have: str, need: str, system: str | None, code: str | None) -> tuple[str, float] | None:
    """How a value in unit key ``have`` becomes one in ``need`` for the analyte ``(system, code)``: ``("*", k)`` or
    ``("/", k)``, whichever factor is the shorter plain decimal at 10 significant digits (88.4, 0.45359237, 10,
    1000000000 rather than 0.000000001): the same exact number in SQL and in CQL, whose decimals stop at 8 places.
    The analyte's own table first; then units of one kind (:data:`FAMILIES`, any analyte). None when there is no
    tested factor, and for the same key (used as it is)."""
    if have == need:
        return None
    table = ANALYTES.get((system or "", code or ""))
    if table and have in table and need in table:
        f = table[have] / table[need]
    elif have in FAMILIES and need in FAMILIES and FAMILIES[have][0] == FAMILIES[need][0]:
        f = FAMILIES[have][1] / FAMILIES[need][1]
        if not (1 - 1e-9) / MAX_SCALE <= f <= MAX_SCALE * (1 + 1e-9):
            return None
    else:
        return None
    mul, div = _plain(f), _plain(1 / f)
    return ("*", float(mul)) if len(mul) <= len(div) else ("/", float(div))


def convert(
    value: float | None, unit: str | None, want: str | None, system: str | None = None, code: str | None = None
) -> float | None:
    """``value`` (recorded in ``unit``) in the criterion's unit ``want``, or None when it cannot be read in it."""
    if value is None:
        return None
    have, need = key(unit), key(want)
    if need in UNITLESS_KEYS:
        return value if have in UNITLESS_KEYS else None
    if have == need:
        return value
    conv = conversion(have, need, system, code)
    if conv is None:
        return None
    op, k = conv
    return round(value * k if op == "*" else value / k, DIGITS)


def value_sql(value: str, unit: str, system: str, code: str, want: str | None) -> str:
    """The SQL twin of :func:`convert`: the row's number in the criterion's unit, or NULL."""
    have, need = key_sql(unit), key(want)
    if need in UNITLESS_KEYS:
        allowed = ", ".join("'" + k.replace("'", "''") + "'" for k in sorted(UNITLESS_KEYS))
        return f"(CASE WHEN {have} IN ({allowed}) THEN {value} END)"
    arms = [f"WHEN {have} = '{need.replace(chr(39), chr(39) * 2)}' THEN {value}"]
    for (sy, cd), table in sorted(ANALYTES.items()):
        for u in sorted(table):
            conv = conversion(u, need, sy, cd)
            if conv is not None:
                op, k = conv
                arms.append(
                    f"WHEN {system} = '{sy}' AND {code} = '{cd}' AND {have} = '{u}' "
                    f"THEN round({value} {op} {k!r}, {DIGITS})"
                )
    for u, op, k in scale_arms(need):  # after the analytes' own arms, as conversion() reads them (D-418)
        arms.append(f"WHEN {have} = '{_sql_str(u)}' THEN round({value} {op} {k!r}, {DIGITS})")
    return "(CASE " + " ".join(arms) + " END)"


def _sql_str(s: str) -> str:
    return s.replace("'", "''")


def scale_arms(need: str) -> list[tuple[str, str, float]]:
    """``(unit key, op, factor)`` for every unit of the same kind as the criterion's unit key ``need`` (D-418): the
    arms the SQL and CQL twins add after the analytes' own. Empty when ``need`` is in no family."""
    if need not in FAMILIES:
        return []
    out = []
    for u in sorted(FAMILIES):
        conv = conversion(u, need, None, None) if u != need else None
        if conv is not None:
            out.append((u, *conv))
    return out


def reason_of(items: Iterable[str]) -> tuple[str | None, list[str]]:
    """Split a criterion's evidence list into its reason code (a derived score's first, then ``unit_mismatch``,
    ``order_dates_missing``, ``rules_changed``; None when it has none) and the record references."""
    seen: set[str] = set()
    rest: list[str] = []
    for x in items:
        if x in TOKENS:
            seen.add(x)
        else:
            rest.append(x)
    code, refs = _derived_reason_of(rest)
    return code or next((t for t in TOKENS if t in seen), None), refs


__all__ = [
    "ANALYTES",
    "DIGITS",
    "FAMILIES",
    "MAX_SCALE",
    "NOT_ACTIVE",
    "ORDER_DATES",
    "RULES_CHANGED",
    "SCALES",
    "TOKENS",
    "UCUM",
    "UNITLESS_KEYS",
    "UNIT_MISMATCH",
    "conversion",
    "convert",
    "key",
    "key_sql",
    "reason_of",
    "scale_arms",
    "value_sql",
]
