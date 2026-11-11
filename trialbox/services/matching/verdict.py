"""One decision table for the verdict of a structured criterion (T-652, ENG-022).

The rules below were written twice: in the v1 path (``orchestrator.scenarios.evaluate``: ``eligibility``,
``structured_verdict``) and in the v4 cascade (``matching.cascade.engine``: ``_pass``, ``_s1_coded``,
``_s1_outcome``). This module holds them once, as a table plus the overrides that turn a coded answer into
unknown. It is pure: no lake, no I/O, no import from the engines, so any engine, the compile-time equivalence gate
and the tests can use it. ``tests/unit/test_verdict_table.py`` checks that both engines give the same answer as the
table for every row (the parity property).

``outcome`` is the eligibility answer (``pass`` = fine for eligibility, ``fail`` = not eligible, ``unknown`` = a
person checks). ``hard`` means the answer excludes the patient. Unknown never excludes (D-18): an exclusion the data
cannot decide keeps the patient, an inclusion the data cannot decide keeps the patient for review. The cascade shows
a kept unknown exclusion as ``pass`` with an ``unknown_kind``; its ``hard`` is the same as here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Outcome = Literal["pass", "fail", "unknown"]
Predicate = bool | None


@dataclass(frozen=True)
class Verdict:
    outcome: Outcome
    hard: bool


PASS = Verdict("pass", False)
FAIL = Verdict("fail", True)
UNKNOWN = Verdict("unknown", False)

# (kind class, predicate) -> verdict. A kind other than ``exclusion`` (inclusion, renewal, documentation) reads as an
# inclusion: its logic must be true for the patient to be eligible.
TABLE: dict[tuple[str, Predicate], Verdict] = {
    ("inclusion", True): PASS,
    ("inclusion", False): FAIL,
    ("inclusion", None): UNKNOWN,
    ("exclusion", True): FAIL,
    ("exclusion", False): PASS,
    ("exclusion", None): UNKNOWN,  # D-18: an unknown exclusion keeps the patient
}


def kind_class(kind: str) -> str:
    return "exclusion" if kind == "exclusion" else "inclusion"


def eligibility(kind: str, predicate: Predicate) -> Outcome:
    """The table's outcome for a coded answer with nothing that overrides it."""
    return TABLE[(kind_class(kind), predicate)].outcome


def structured(
    kind: str,
    predicate: Predicate,
    *,
    code_gap: bool = False,
    proposed: bool = False,
    absent_is_unknown: bool = False,
) -> Verdict:
    """The verdict of one structured criterion.

    A null answer the engine explains (D-130 unknown code system, D-149 a score with no value) changes the reason
    shown, never the outcome, so it is not an input. ``code_gap``: a record in the window is coded in
    a system no ValueSet reads, so an inclusion's FALSE means only "not among the codes we can read" (F-10, D-130).
    ``proposed``: a proposed fact (read from a chart, not confirmed) could change the answer, so it is unknown and
    never excludes (D-135). ``absent_is_unknown``: CAS-11, an inclusion FALSE because no record exists is unknown
    (v4 semantics, a criterion that is neither a value nor an index criterion).
    """
    k = kind_class(kind)
    if predicate is not None and not isinstance(predicate, bool):
        raise TypeError(f"a structured answer is true, false or null, not {predicate!r}")
    if proposed:
        return UNKNOWN
    if k == "inclusion" and predicate is False and (code_gap or absent_is_unknown):
        return UNKNOWN
    return TABLE[(k, predicate)]


def excludes(kind: str, predicate: Predicate) -> bool:
    return TABLE[(kind_class(kind), predicate)].hard


def direction_changes(kind: str, a: Predicate, b: Predicate) -> bool:
    """True when two engines' answers for one criterion and one patient differ in a way that changes the patient's
    eligibility direction: one excludes and the other keeps, or (on an exclusion) one has decided and the other has
    not. Such a difference blocks the equivalence gate at any rate (ENG-016). The only tolerated difference is a met
    inclusion against an undecided one: both keep the patient."""
    if a == b:
        return False
    if a is not None and b is not None:
        return True
    if kind_class(kind) == "exclusion":
        return True
    return excludes(kind, a) != excludes(kind, b)
