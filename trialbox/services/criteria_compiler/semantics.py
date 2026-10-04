"""Shared, engine-independent interpretation of Criterion IR atoms (used by both the CQL and the SQL generator).

Normative semantics (DECISIONS D-17):

* Window ``[I + from_days, I + to_days]`` on the local calendar date of the event, inclusive; missing ``from_days`` =
  unbounded past, missing ``to_days`` = index date. Derived atoms default to their DEFAULT_WINDOW_DAYS.
* Code-presence atoms (``condition``, ``medication`` without duration, ``procedure``, ``encounter``, ``claim``,
  ``report``, ``observation`` without ``value``) are never null.
* ``observation`` with ``value``: null when no matching observation is in the window; ``latest`` compares the most
  recent observation (ties broken by resource id); ``any``/``all``/``none``/``count>=`` over all matching ones.
* ``demographic``: age = complete years at the index date; null when birth date / gender is missing.
* ``derived``: computed from the latest components in the window; null when a component is missing; without
  ``value`` the atom is true when computable.
* ``medication`` with ``duration``: validity periods clipped to the window, merged when the gap <= ``gap_days``,
  longest island in days (inclusive) compared with ``min_days``; never null.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from tb_common.derived import DEFAULT_WINDOW_DAYS
from tb_contracts import Atom, BoolExpr, CriterionIR

UNBOUNDED_PAST = "1900-01-01"


class CompileError(ValueError):
    """IR that cannot be compiled deterministically (blocks the ruleset; flagged needs_review)."""


class Kind(StrEnum):
    PRESENCE = "presence"  # exists/count/none over coded events (never null)
    OBS_VALUE = "obs_value"  # observation value comparison (null when no observation)
    DEMOGRAPHIC = "demographic"
    DERIVED = "derived"
    MED_DURATION = "med_duration"


@dataclass(frozen=True)
class Window:
    from_days: int | None
    to_days: int


def window(atom: Atom) -> Window:
    if atom.derived and atom.window is None:
        return Window(-DEFAULT_WINDOW_DAYS[atom.derived], 0)
    if atom.window is None:
        return Window(None, 0)
    if atom.window.anchor not in (None, "index"):
        raise CompileError("window anchor 'event' is not supported in v1.0 (use index-relative windows)")
    to_days = 0 if atom.window.to_days is None else atom.window.to_days
    if atom.window.from_days is not None and atom.window.from_days > to_days:
        raise CompileError(f"empty window [{atom.window.from_days}, {to_days}]")
    return Window(atom.window.from_days, to_days)


def kind(atom: Atom) -> Kind:
    if atom.domain == "demographic":
        if atom.age is None and atom.sex is None:
            raise CompileError("demographic atom needs age and/or sex")
        return Kind.DEMOGRAPHIC
    if atom.derived is not None:
        if atom.domain != "observation":
            raise CompileError("derived values are observation atoms")
        return Kind.DERIVED
    if atom.duration is not None:
        if atom.domain != "medication" or atom.duration.min_days is None:
            raise CompileError("duration requires domain=medication and min_days")
        return Kind.MED_DURATION
    if atom.value is not None:
        if atom.domain != "observation":
            raise CompileError(f"value comparison is only supported for observations (got {atom.domain})")
        check_value(atom)
        return Kind.OBS_VALUE
    if atom.quantifier in ("latest", "all"):
        raise CompileError(f"quantifier {atom.quantifier} requires a value comparison")
    if atom.quantifier == "count>=" and atom.count is None:
        raise CompileError("count>= requires count")
    if atom.valueset in ("", "NONE"):
        raise CompileError(f"{atom.domain} atom needs a ValueSet")
    return Kind.PRESENCE


def check_value(atom: Atom) -> None:
    v = atom.value
    assert v is not None
    if v.op is None:
        raise CompileError("value.op is required")
    if v.op == "in":
        if not v.codes:
            raise CompileError("value op 'in' requires codes")
    elif v.op == "between":
        if v.num is None or v.num2 is None:
            raise CompileError("value op 'between' requires num and num2")
    elif v.num is None:
        raise CompileError(f"value op {v.op!r} requires num")
    if atom.quantifier == "count>=" and atom.count is None:
        raise CompileError("count>= requires count")


def atoms(expr: Atom | BoolExpr) -> list[Atom]:
    if isinstance(expr, Atom):
        return [expr]
    out: list[Atom] = []
    for a in expr.args:
        out.extend(atoms(a))
    return out


def check_bool(expr: Atom | BoolExpr) -> None:
    if isinstance(expr, BoolExpr):
        if expr.op == "not" and len(expr.args) != 1:
            raise CompileError("'not' takes exactly one argument")
        for a in expr.args:
            check_bool(a)


def compiled(criteria: list[CriterionIR]) -> list[CriterionIR]:
    """Only class=structured criteria are compiled to CQL/SQL (note/human are judged or asked; D-32)."""
    return [c for c in criteria if c.class_ == "structured"]


def fmt_num(x: float) -> str:
    """Render a number literal identically for CQL and SQL (integers without a decimal point)."""
    if float(x).is_integer():
        return str(int(x))
    return repr(float(x))


def ident(crit_id: str) -> str:
    """SQL-safe identifier fragment for a criterion id."""
    return crit_id.replace("-", "_")
