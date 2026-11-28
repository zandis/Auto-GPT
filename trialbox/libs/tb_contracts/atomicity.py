"""The atomicity checker: an atom is one positive statement with one subject, one data kind, one concept set, one
comparison, one window with its anchor and one evaluation; polarity lives in the criterion tree, never in the atom.

:func:`check_atom` reads an atom as a plain mapping (an extractor's raw output, before any model validation, or a dumped
:class:`~tb_contracts.criterion_ir.Atom`) and returns the reasons it is not atomic, from the closed list
:data:`REASONS`; an empty list means atomic. No model, no terminology, no database.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from tb_contracts.criterion_ir import Atom, CriterionIRv3

REASONS = (
    "two_subjects",
    "two_data_kinds",
    "two_concept_sets",
    "two_comparisons",
    "two_windows",
    "two_durations",
    "two_evaluations",
    "no_concept_set",
    "negation_in_atom",
    "mixed_subject",
    "window_without_anchor",
)
# slot key -> the reason when the slot holds more than one
_SINGLE = {
    "subject": "two_subjects",
    "domain": "two_data_kinds",
    "valueset": "two_concept_sets",
    "window": "two_windows",
    "duration": "two_durations",
    "quantifier": "two_evaluations",
}
# the comparison families: an atom compares through at most one of them (a bare concept set is an existence test)
_COMPARISONS = ("value", "age", "sex", "attribute", "change", "aggregate", "lot")
_NEGATION_WORDS = {"no", "not", "non", "without", "except", "excluding", "absent", "never"}


def _dump(atom: Atom | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(atom, BaseModel):
        return atom.model_dump(mode="json", exclude_none=True)
    return dict(atom)


def _many(x: Any) -> bool:
    return isinstance(x, list) and len(x) > 1


def _comparisons(a: Mapping[str, Any]) -> int:
    n = 0
    for k in _COMPARISONS:
        v = a.get(k)
        n += len(v) if isinstance(v, list) else int(v is not None)
    derived, med = a.get("derived"), a.get("medication")
    n += int(
        isinstance(derived, Mapping) and derived.get("op") is not None
    )  # a bare calculator names what `value` compares
    return n + int(isinstance(med, Mapping) and med.get("dose") is not None)


def _negated_name(name: Any) -> bool:
    return isinstance(name, str) and bool(_NEGATION_WORDS & set(re.split(r"[^a-z0-9]+", name.lower())))


def check_atom(atom: Atom | Mapping[str, Any], subjects: Mapping[str, str] | None = None) -> list[str]:
    """The reasons ``atom`` is not atomic (sorted, each once; empty: atomic).

    ``subjects``: atom id -> subject for the other atoms of its criterion; an atom that reads another atom
    (``value_if``, an event window) of a different subject is ``mixed_subject``. Absent subject means the patient."""
    a = _dump(atom)
    out = {reason for key, reason in _SINGLE.items() if _many(a.get(key))}
    if _comparisons(a) > 1:
        out.add("two_comparisons")
    vs = a.get("valueset")
    if not vs and a.get("domain") != "demographic":
        out.add("no_concept_set")
    if a.get("quantifier") == "none" or any(_negated_name(v) for v in (vs if isinstance(vs, list) else [vs])):
        out.add("negation_in_atom")
    windows: list[Any] = a["window"] if isinstance(a.get("window"), list) else [a.get("window")]
    for w in windows:
        if not isinstance(w, Mapping) or w.get("anchor_text"):
            continue
        if w.get("anchor") is None or (w.get("anchor") == "event" and not w.get("event_atom")):
            out.add("window_without_anchor")
    own = a.get("subject") or "patient"
    if isinstance(own, list):
        own = own[0] if len(set(own)) == 1 else None
    refs = [c.get("if_atom") for c in a.get("value_if") or [] if isinstance(c, Mapping)]
    if isinstance(a.get("window"), Mapping):
        refs.append(a["window"].get("event_atom"))
    others = subjects or {}
    if own is None or any(isinstance(r, str) and r in others and others[r] != own for r in refs):
        out.add("mixed_subject")
    return sorted(out)


def check_criterion(ir: CriterionIRv3) -> dict[str, list[str]]:
    """atom id -> its reasons, for the atoms of ``ir`` that are not atomic."""
    subjects = {x.id: x.subject or "patient" for x in ir.atoms}
    found = {x.id: check_atom(x, subjects) for x in ir.atoms}
    return {k: v for k, v in found.items() if v}
