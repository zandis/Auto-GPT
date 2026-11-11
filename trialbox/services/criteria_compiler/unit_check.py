"""The unit of a lab criterion, checked when the protocol is compiled (D-418, T-619c; D-275 open point 3).

A plain lab comparison is made in the criterion's unit (D-275): a result in another unit is converted only when
``tb_common.labunit`` has a factor, and is otherwise unknown with the reason ``unit_mismatch``. Two criteria the
extraction can produce are therefore unknown for almost every patient, silently:

* **no unit** (``creatinine <= 1.5``): only results recorded with no unit are read, and a lab result always has one;
* **a unit the analyte is not reported in and cannot be converted from** (``glucose < 7.0 mmol/L`` where the
  catalogue reports glucose in mg/dL): mass and substance never convert in screening.

The compiler flags both for the reviewer (``value_unit_missing``, ``value_unit_unconvertible``, with
``needs_review``) and says which unit the analyte is reported in. It never changes the criterion: the reviewer
adds or changes the unit, or accepts it (a count, a site that reports in that unit).

The expected unit of an analyte is the catalogue's ``unit_ucum`` for its LOINC code (``catalogue/items.csv``). A
UCUM annotation alone (``{score}``, ``{ratio}``, ``{INR}``) is a plain number, so such an analyte is never flagged
for having no unit; an analyte the catalogue does not list is not checked.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from tb_common import catalogue, labunit
from tb_contracts import Atom

LOINC = "http://loinc.org"
MISSING = "value_unit_missing"
UNCONVERTIBLE = "value_unit_unconvertible"
_ANNOTATION = re.compile(r"^(\{[^{}]*\}|1)?$")  # no unit, "1", or a UCUM annotation only: a plain number


def is_number_unit(unit: str | None) -> bool:
    """True for a unit that says "a plain number": none, ``1``, or a UCUM annotation such as ``{score}``."""
    u = (unit or "").strip()
    return bool(_ANNOTATION.match(u)) or labunit.key(u) in labunit.UNITLESS_KEYS


def expected_units(codes: Iterable[tuple[str, str]], folder: Path | None = None) -> dict[str, str]:
    """LOINC code -> the unit the catalogue says it is reported in, for the codes of a value set that have one."""
    wanted = {code for system, code in codes if system == LOINC}
    if not wanted:
        return {}
    return {it.loinc: it.unit for it in catalogue.items(folder) if it.loinc in wanted and it.unit}


def valueset_codes(vs: dict[str, Any] | None) -> list[tuple[str, str]]:
    """The ``(system, code)`` pairs of a FHIR ValueSet's ``compose.include``."""
    out: list[tuple[str, str]] = []
    for inc in ((vs or {}).get("compose") or {}).get("include") or []:
        for c in inc.get("concept") or []:
            out.append((str(inc.get("system") or ""), str(c.get("code") or "")))
    return out


def check(atom: Atom, vs: dict[str, Any] | None, folder: Path | None = None) -> tuple[str, str] | None:
    """``(flag, message)`` for a numeric lab atom whose unit would leave its results unknown, else None."""
    v = atom.value
    if atom.domain != "observation" or atom.derived is not None or v is None or v.op in (None, "in"):
        return None
    if getattr(v, "ref", None) is not None:  # a multiple of the reference range: no unit to compare
        return None
    units = expected_units(valueset_codes(vs), folder)
    real = {code: u for code, u in sorted(units.items()) if not is_number_unit(u)}
    if not real:
        return None
    named = ", ".join(sorted(set(real.values())))
    if is_number_unit(v.unit):
        return MISSING, (
            f"the number has no unit, but the result is reported in {named}: every result with a unit will be "
            f"unknown (D-275); add the unit"
        )
    lost = sorted({u for code, u in real.items() if labunit.convert(1.0, u, v.unit, LOINC, code) is None})
    if lost:
        return UNCONVERTIBLE, (
            f"the unit {v.unit} cannot be converted from {', '.join(lost)}, the unit the result is usually reported "
            f"in: such results will be unknown (D-275); check the unit"
        )
    return None


__all__ = ["MISSING", "UNCONVERTIBLE", "check", "expected_units", "is_number_unit", "valueset_codes"]
