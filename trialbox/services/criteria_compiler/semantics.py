"""Shared, engine-independent interpretation of Criterion IR atoms (used by both the CQL and the SQL generator).

Normative semantics (DECISIONS D-17):

* Window ``[I + from_days, I + to_days]`` on the local calendar date of the event, inclusive; missing ``from_days`` =
  unbounded past, missing ``to_days`` = index date. Derived atoms default to their DEFAULT_WINDOW_DAYS.
* Code-presence atoms (``condition``, ``medication`` without duration, ``procedure``, ``encounter``, ``claim``,
  ``report``, ``observation`` without ``value``) are never null.
* ``observation`` with ``value``: null when no matching observation is in the window; ``latest`` compares the most
  recent observation (ties broken by resource id); ``any``/``all``/``none``/``count>=`` over all matching ones.
  A number is compared in the criterion's unit (``value.unit``): a row in another unit is converted when
  ``tb_common.labunit`` has a factor for that analyte, or when both units are of one kind (g/L and g/dL, D-418), and
  otherwise (a row with no unit included) has no usable number, like a text result: it never makes the comparison
  true or false (D-275).
* ``demographic``: age = complete years at the index date; null when the birth date is missing or the gender is
  not ``male`` / ``female`` (missing, ``other``, ``unknown``; D-275).
* ``derived``: computed from the latest components in the window; null when a component is missing; without
  ``value`` the atom is true when computable.
* ``medication`` with ``duration``: validity periods clipped to the window, merged when the gap <= ``gap_days``,
  longest island in days (inclusive) compared with ``min_days``. Null when the dated periods do not reach
  ``min_days`` and a matching order has no end date (it began on or before the window's end) or no date at all:
  its length is not known (D-275). An order with no end date still counts one day towards the dated periods.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from tb_common.derived import COMPONENTS, DEFAULT_WINDOW_DAYS
from tb_contracts import Atom, BoolExpr, CriterionIR

UNBOUNDED_PAST = "1900-01-01"


class CompileError(ValueError):
    """IR that cannot be compiled deterministically (blocks the ruleset; flagged needs_review)."""


class UnknownValueSet(CompileError, KeyError):
    """B14 (D-502): IR naming a value set that no concept candidate defined (a model answer can). A
    :class:`CompileError`, so the criterion goes to a person and the rest compiles; still a ``KeyError`` for any caller
    that caught one."""

    def __str__(self) -> str:  # KeyError would quote the message
        return str(self.args[0]) if self.args else ""


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
        lo, hi = (atom.age.min, atom.age.max) if atom.age is not None else (None, None)
        if (lo is not None and lo < 0) or (hi is not None and hi < 0):  # D-914
            raise CompileError("an age bound below 0")
        if lo is not None and hi is not None and lo > hi:  # D-914: matched by no one ("80 to 18")
            raise CompileError(f"age range {lo} to {hi} is reversed")
        # D-946 (F2 of P1b, NCT01260883 "0.17 years"): the age is complete years (D-442), so a bound of 0.17 is met by
        # no one under 1 and 1.5 by no one under 2; a person reads it (months are not compared)
        for b in (lo, hi):  # review: NaN and infinity are refused too (int() raised past every CompileError catch)
            if b is not None and not (math.isfinite(float(b)) and float(b).is_integer()):
                raise CompileError(f"age bound {b!r} is not a whole number of years; the age is counted in years")
        return Kind.DEMOGRAPHIC
    if atom.derived is not None:
        if atom.domain != "observation":
            raise CompileError("derived values are observation atoms")
        # G5 of the P1b review (D-956, NCT01187901): a derived name that does not exist, with value.op "in", reached
        # the CQL as ``(None in { })`` and failed the translator. A derived value is a known score, compared as a number
        if atom.derived not in COMPONENTS:
            raise CompileError(f"derived value {atom.derived!r} is not one this box computes ({', '.join(COMPONENTS)})")
        if atom.value is not None:  # none: "computable" (TRUE when the score can be computed, D-149)
            if atom.value.op == "in":
                raise CompileError(
                    f"derived value {atom.derived} is a number: 'in' a list of codes does not compare it"
                )
            check_value(atom)
        return Kind.DERIVED
    if atom.duration is not None:
        if atom.domain != "medication" or atom.duration.min_days is None:
            raise CompileError("duration requires domain=medication and min_days")
        if atom.duration.min_days <= 0:  # D-914 (lane G, case 10): "within 3 months" as at least -90 days, met by all
            raise CompileError(f"duration of at least {atom.duration.min_days} days is met by everyone; a time limit "
                               f"is a window, a duration a positive number of days")  # fmt: skip
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


FILTERED = ("structured", "mixed")  # classes whose logic is compiled to CQL/SQL (D-32, D-98)
JUDGED = ("note", "mixed")  # classes whose note_question goes to the model


def demographic_alone(logic: Atom | BoolExpr | None) -> bool:
    """Whether a criterion's coded logic is an age or a sex and nothing else: every atom demographic, none naming a
    ValueSet or a derived value (P2b: an exclusion that compiled to this while its line named more lost its
    qualifier; a mixed inclusion that compiled to this was met on its age alone, card 10A-2)."""
    if logic is None:
        return False
    got = atoms(logic)
    return bool(got) and all(
        a.domain == "demographic" and a.valueset in ("NONE", "", None) and not a.derived and (a.sex or a.age)
        for a in got
    )


def codes_settle(c: CriterionIR) -> bool:
    """Whether a ``mixed`` criterion's coded part, when true, settles the line without its note question (D-98).
    Card 10A-2 (review 15, P2b: 6 of 81 mixed inclusions): an inclusion whose coded part is only an age or a sex
    ("18 years or older with a diagnosis of FAP", "women with a negative pregnancy test" kept as ``female``) is not
    met on that part: the notes decide the rest, and with no answer from them the line stays unknown, never met and
    never excluded. An exclusion keeps D-98 (the compiler's ``qualifier_dropped`` rule keeps an age-or-sex-alone
    exclusion from running)."""
    return not (c.class_ == "mixed" and c.kind == "inclusion" and demographic_alone(c.logic))


def class_split(criteria: list[CriterionIR]) -> dict[str, int]:
    """How many active (not rejected) inclusion/exclusion criteria each class checks (D-101)."""
    out = {"structured": 0, "mixed": 0, "note": 0, "human": 0}
    for c in criteria:
        if c.kind in ("inclusion", "exclusion") and not (c.review and c.review.status == "rejected"):
            out[c.class_] = out.get(c.class_, 0) + 1
    return out


def human_heavy(split: dict[str, int]) -> bool:
    """True when at least half of the criteria are left to a person: the box would do little of the screening."""
    n = sum(split.values())
    return n > 0 and split.get("human", 0) * 2 >= n


def compiled(criteria: list[CriterionIR]) -> list[CriterionIR]:
    """Class ``structured`` and ``mixed`` criteria are compiled to CQL/SQL (note/human are judged or asked; D-32).
    A mixed criterion's compiled part is a pre-check: it decides the patient when the coded data can, and the note
    judge decides the rest (D-98)."""
    return [c for c in criteria if c.class_ in FILTERED]


def fmt_num(x: float) -> str:
    """Render a number literal identically for CQL and SQL (integers without a decimal point)."""
    if float(x).is_integer():
        return str(int(x))
    return repr(float(x))


def ident(crit_id: str) -> str:
    """SQL-safe identifier fragment for a criterion id."""
    return crit_id.replace("-", "_")
