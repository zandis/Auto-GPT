"""The unit of a plain lab comparison (D-275; review S-1, MR-002 / R-31).

A criterion such as "creatinine <= 1.5 mg/dL" names its unit (``Atom.value.unit``). Before D-275 the compiled SQL
compared the row's number with the criterion's number whatever the row's unit was: a creatinine of 90 umol/L failed
"<= 1.5 mg/dL", and an IFCC HbA1c of 53 mmol/mol met the exclusion "HbA1c > 10 %". Only the derived scores looked at
units (``tb_common.derived``, D-149).

The rule, for each observation row of a numeric comparison:

* the row's unit is the criterion's unit (both spelled as :func:`key` spells them): the number is used as it is;
* the row is one of the analytes of ``tb_common.derived.UNITS`` (creatinine, CRP, ESR, weight, height: found by the
  row's own code) and both units are in that analyte's table: the number is converted with the table's factors;
* anything else, a row with no unit included: the row has **no usable number**. It can never make a comparison TRUE
  or FALSE; the answer is unknown unless the rows that can be read settle it, and the evidence carries the reason
  ``unit_mismatch``.

A criterion with no unit (a count or a score) reads rows with no unit, or a UCUM "number" annotation, only.

There is no conversion between units of different kinds without the analyte (mg/dL to mmol/L, % to mmol/mol) and no
scale table for other analytes (g/dL to g/L, 10*4/uL to 10*9/L): those rows are unknown until someone adds a tested
factor to ``tb_common.derived.UNITS``.

The same module names the reason of a medication-duration atom that cannot be decided because an order has no end
date or no date at all (``order_dates_missing``, review S-9).
"""

from __future__ import annotations

from collections.abc import Iterable

from tb_common.derived import CODES, UNITLESS, UNITS, norm_unit
from tb_common.derived import reason_of as _derived_reason_of

UNIT_MISMATCH = "unit_mismatch"
ORDER_DATES = "order_dates_missing"
# an approved answer the current rules do not confirm (compile_sql.overlay): the least specific, reported last
RULES_CHANGED = "rules_changed"
TOKENS = (UNIT_MISMATCH, ORDER_DATES, RULES_CHANGED)  # in the order a reason is chosen

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

# (system, code) of an analyte -> {unit key: factor to the analyte's reference unit}
ANALYTES: dict[tuple[str, str], dict[str, float]] = {
    CODES[comp]: {key(u): f for u, f in factors.items()} for comp, (_target, factors) in UNITS.items()
}


# a converted value is rounded to this many decimals in every engine (review F2): 1.5 mg/dL is 132.6 umol/L, not
# 132.60000000000002, so a value equal to the bound in the other unit compares as equal. Values that are not
# converted are compared as recorded.
DIGITS = 6


def conversion(have: str, need: str, system: str | None, code: str | None) -> tuple[str, float] | None:
    """How a value in unit key ``have`` becomes one in ``need`` for the analyte ``(system, code)``: ``("*", k)`` or
    ``("/", k)``, whichever factor is the shorter decimal at 10 significant digits (88.4, 0.45359237, 10): the same
    exact number in SQL and in CQL, whose decimals stop at 8 places. None when there is no tested factor."""
    table = ANALYTES.get((system or "", code or ""))
    if not table or have not in table or need not in table or have == need:
        return None
    f = table[have] / table[need]
    mul, div = f"{f:.10g}", f"{1 / f:.10g}"
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
    return "(CASE " + " ".join(arms) + " END)"


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
    "ORDER_DATES",
    "RULES_CHANGED",
    "TOKENS",
    "UNITLESS_KEYS",
    "UNIT_MISMATCH",
    "conversion",
    "convert",
    "key",
    "key_sql",
    "reason_of",
    "value_sql",
]
