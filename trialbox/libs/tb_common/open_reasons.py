"""Why a criterion stayed open for the night's patients, and the "coded-complete" count (F17 5a and 5b).

An open answer (unknown, or waiting for a person) already carries a :class:`tb_common.reasons.Reason`. This module
sorts those codes into four classes and names, for each, **where the cause is**, so the page "Information still
needed" can say which site view or field to ask for:

* ``DECIDED``: ``coded``, ``note``. Not open.
* ``SITE_GAP``: the site's own data lacks what the criterion reads (no notes, no value, no record of that kind, a code
  system the site's records do not carry, an input of a score never collected). The box reads unknown, correctly;
  the page names the view (:func:`where`).
* ``PRODUCT``: a component of the box could not use what the site has (order dates, a unit spelling, a code the mapping
  does not know, a derived score, a changed rule), or an open answer that carried no reason. A defect to fix, not a
  site question. An open answer with no reason is ``no_reason``.
* ``PERSON``: a person or a model decides (the checks disagree, a quote is missing, a criterion asked at screening,
  a suspected diagnosis...). Open by design.

Every :class:`Reason` is in exactly one class (``tests/unit/test_open_reasons.py``). **Coded-complete** (F17 5b): a
patient with at least one coded yes, no no, and whose only open criteria are ``SITE_GAP``. A yes that a model or a
person gave is not a coded yes, so such a patient is not coded-complete. Reported as a count, shown as unknown, never
a tier: "high" stays "every criterion yes".

Counts only: nothing here holds a patient id.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from tb_common.reasons import Reason, code_of

NO_REASON = "no_reason"  # an open answer that carried none: a defect of the box, never a site question

DECIDED = frozenset({Reason.CODED, Reason.NOTE})
SITE_GAP = frozenset({
    Reason.NO_NOTES,  # no note feed, or none in the window
    Reason.DATA_GAP,  # no value, no record in the window
    Reason.UNKNOWN_KEPT,  # an exclusion with no value recorded
    Reason.NO_RECORD_OF_KIND,  # no coded record of that kind at all (D-914)
    Reason.CODE_SYSTEM_NOT_CARRIED,  # the site's records carry no code of the list's system (D-795)
    Reason.DERIVED_MISSING_INPUT,  # an input of the score was never recorded
})  # fmt: skip
PRODUCT = frozenset({
    Reason.UNKNOWN_CODE_SYSTEM,
    Reason.CODE_OUTSIDE_LIST,
    Reason.UNIT_MISMATCH,
    Reason.UNKNOWN_VALUE,
    Reason.ORDER_DATES_MISSING,
    Reason.DERIVED_UNIT,
    Reason.DERIVED_ADULT_ONLY,
    Reason.DERIVED_NOT_STORED,
    Reason.DERIVED_VS_DOCUMENTED,
    Reason.RULES_CHANGED,
})  # fmt: skip
PERSON = frozenset(set(Reason) - DECIDED - SITE_GAP - PRODUCT)

#: where a site-gap reason that is not about notes is looked for: the domain of the criterion's atom
VIEWS = ("condition", "observation", "medication", "procedure", "encounter", "demographic", "claim", "report")
NOTES, PRODUCT_WHERE, PERSON_WHERE, RECORDS = "notes", "product", "person", "records"
WHERES = (NOTES, *VIEWS, RECORDS, PRODUCT_WHERE, PERSON_WHERE)


def kind_of(reason: str) -> str:
    """``decided``, ``site_gap``, ``product`` or ``person`` (an unknown code, and no_reason, is ``product``)."""
    try:
        r = Reason(reason)
    except ValueError:
        return "product"
    return "decided" if r in DECIDED else "site_gap" if r in SITE_GAP else "product" if r in PRODUCT else "person"


def domain_of(criterion: Any) -> str | None:
    """The domain of the first atom of the criterion's logic, depth first."""
    stack = [criterion.logic]
    while stack:
        node = stack.pop(0)
        dom = getattr(node, "domain", None)
        if dom:
            return str(dom)
        stack = [*getattr(node, "args", ()), *stack]
    return None


def where(reason: str, criterion: Any) -> str:
    """The site view or field a reason names: ``notes`` for no notes (and any criterion the model reads); the atom's
    domain for the other site gaps (``records`` when the criterion has none); ``product`` and ``person`` otherwise."""
    kind = kind_of(reason)
    if kind == "product":
        return PRODUCT_WHERE
    if kind == "person":
        return PERSON_WHERE
    if reason == Reason.NO_NOTES.value or criterion.class_ == "note":
        return NOTES
    return domain_of(criterion) or RECORDS


@dataclass(frozen=True)
class Facts:
    """One patient's open criteria, each as (criterion id, reason, where), and whether the patient is coded-complete."""

    opens: tuple[tuple[str, str, str], ...]
    coded_complete: bool


def _reason(v: Any) -> str:
    ev = v.evidence
    return code_of(getattr(ev, "reason", None), v.verdict, bool(getattr(ev, "quote", None))) or NO_REASON


def _not_coded(c: Any, v: Any) -> bool:
    """An answer a model or a person gave: a note criterion, a criterion asked at screening, or a mixed one the
    model's confidence decided (``matching.decision.is_note_answer``)."""
    ev = v.evidence
    return bool(c.class_ in ("note", "human") or (c.class_ == "mixed" and ev is not None and ev.confidence is not None))


def facts_of(by_id: Mapping[str, Any], verdicts: Iterable[Any]) -> Facts:
    """The patient's :class:`Facts` from the evaluation's verdicts (``by_id``: the ruleset's criteria by id)."""
    opens: list[tuple[str, str, str]] = []
    yes = 0
    clean = True
    for v in verdicts:
        c = by_id.get(v.id)
        if c is None:
            continue
        if v.verdict == "pass":
            if _not_coded(c, v):
                clean = False
            else:
                yes += 1
        elif v.verdict == "fail":
            clean = False
        else:
            r = _reason(v)
            opens.append((v.id, r, where(r, c)))
            clean = clean and kind_of(r) == "site_gap"
    return Facts(tuple(opens), clean and yes > 0)


def tally(facts: Iterable[Facts]) -> tuple[int, list[dict[str, Any]]]:
    """The coded-complete count and the ``open_reasons`` of ``JobMetrics.prefilter`` for these patients, sorted."""
    n = 0
    c: Counter[tuple[str, str, str]] = Counter()
    for f in facts:
        n += f.coded_complete
        c.update(f.opens)
    rows = [{"criterion": k[0], "reason": k[1], "where": k[2], "count": v} for k, v in sorted(c.items())]
    return n, rows


# H-7 (REAL2): what the site must supply for an open answer. The views and fields are those of the site mapping
# template (services/adapter/mapping/tw_core/demo_his.yaml): a site copies it and changes only the names, so the site's
# IT reads its own view beside the template's (tests/unit/test_open_reasons_needs.py checks each name is one the
# template reads). Deterministic: the reason, the criterion's atoms and the ruleset's value sets, nothing else.
CODE_FIELD: dict[str, tuple[str, str]] = {
    "condition": ("diagnosis", "icd10"),
    "observation": ("lab", "local_code"),
    "medication": ("medication", "nhi_drug_code"),
    "procedure": ("procedure", "order_code"),
    "encounter": ("encounter", "dept_code"),
    "demographic": ("patient", "birth_date"),
    "claim": ("claim", "product_code"),
    "report": ("report", "exam_code"),
}
#: the vital signs the template reads from its vital view (LOINC -> field); any other observation is a lab result
LOINC = "http://loinc.org"
VITAL_FIELD = {"8302-2": "height_cm", "29463-7": "weight_kg", "8480-6": "sbp", "8462-4": "dbp"}
#: a score's inputs that are vital signs (``tb_common.derived.COMPONENTS``); every other input is a lab result row
DERIVED_VITAL = {"height": "height_cm", "weight": "weight_kg"}
LAB_VALUE, LAB_UNIT = ("lab", "result_value"), ("lab", "unit")
NOTE_TEXT, ORDER_END, BIRTH_DATE = ("note", "text"), ("medication", "end_date"), ("patient", "birth_date")
SEX = ("patient", "sex")
#: the reasons about a recorded value (none, unreadable, not usable): the value field, not the code field
_VALUE_REASONS = {
    Reason.DATA_GAP, Reason.UNKNOWN_KEPT, Reason.UNKNOWN_VALUE, Reason.DERIVED_UNIT, Reason.DERIVED_ADULT_ONLY,
    Reason.DERIVED_NOT_STORED, Reason.DERIVED_VS_DOCUMENTED, Reason.RULES_CHANGED,
}  # fmt: skip

NEEDS_TEXT = {
    "en": "The site's data needs {view}.{field} for {concept}",
    "ja": "施設データに {concept} の {view}.{field} が必要です",
    "zh-TW": "本院資料需提供 {concept} 的 {view}.{field}",
}


def named_sources() -> list[tuple[str, str]]:
    """Every (view, field) :func:`needs` can name."""
    out = [*CODE_FIELD.values(), LAB_VALUE, LAB_UNIT, NOTE_TEXT, ORDER_END, BIRTH_DATE, SEX]
    out += [("vital", f) for f in (*VITAL_FIELD.values(), *DERIVED_VITAL.values())]
    return sorted(set(out))


def _atoms(node: Any) -> list[Any]:
    """The criterion's atoms, depth first."""
    if getattr(node, "domain", None):
        return [node]
    return [a for arg in getattr(node, "args", None) or () for a in _atoms(arg)]


def _loinc_codes(valueset: str | None, valuesets: Mapping[str, Any] | None) -> set[str]:
    """The value set's LOINC codes (a site's local code that reads like one is not one)."""
    vs = (valuesets or {}).get(valueset or "") or {}
    includes = (vs.get("compose") or {}).get("include") or []
    return {str(c.get("code")) for i in includes if i.get("system") == LOINC for c in i.get("concept") or []}


def _pick(r: Reason, atoms: list[Any]) -> Any:
    """The atom the reason is about: a medication with a duration for missing order dates, the scored atom for a
    score's reason, a valued atom for a value reason, else the first atom."""
    if r is Reason.ORDER_DATES_MISSING:
        return next((a for a in atoms if a.domain == "medication" and getattr(a, "duration", None)), atoms[0])
    if r.value.startswith("derived_"):
        return next((a for a in atoms if getattr(a, "derived", None)), atoms[0])
    if r in _VALUE_REASONS:
        return next((a for a in atoms if getattr(a, "value", None) is not None), atoms[0])
    return atoms[0]


def needs(reason: str | None, criterion: Any, valuesets: Mapping[str, Any] | None = None) -> dict[str, str] | None:
    """``{"view", "field", "concept"}``: what the site must supply for an open answer with this engine reason (the
    engine's own string or a code; ``derived_missing_input:<input>`` names the input). None for a decided answer and
    for one a person or a model decides (:data:`PERSON`), except no notes (the note feed)."""
    try:
        r = Reason(code_of(reason) or "")
    except ValueError:
        return None
    if r in DECIDED or (r in PERSON and r is not Reason.NO_NOTES):
        return None
    atoms = _atoms(criterion.logic)
    if r is Reason.NO_NOTES or criterion.class_ == "note" or not atoms:
        return {"view": NOTE_TEXT[0], "field": NOTE_TEXT[1], "concept": str(criterion.id)}
    a = _pick(r, atoms)
    concept = str(a.valueset)
    if r is Reason.ORDER_DATES_MISSING:
        view, field = ORDER_END
    elif r is Reason.UNIT_MISMATCH:
        view, field = LAB_UNIT
    elif r is Reason.DERIVED_ADULT_ONLY and getattr(a, "derived", None):
        concept, (view, field) = str(a.derived), BIRTH_DATE  # an adult equation: the age decides whether it applies
    elif r.value.startswith("derived_") and getattr(a, "derived", None):
        from tb_common.derived import COMPONENTS

        part = str(reason or "").partition(":")[2].strip()
        inputs = [part] if part else list(COMPONENTS.get(str(a.derived), ()))  # no input named: every input
        concept = f"{a.derived}: {', '.join(inputs)}" if inputs else str(a.derived)
        if r is Reason.DERIVED_UNIT and part and part not in DERIVED_VITAL:
            view, field = LAB_UNIT  # the input's unit is what the formula cannot use
        elif inputs and all(i in DERIVED_VITAL for i in inputs):
            view, field = "vital", ", ".join(DERIVED_VITAL[i] for i in inputs)
        else:
            view, field = LAB_VALUE
    elif a.domain == "observation" and (vital := VITAL_FIELD.keys() & _loinc_codes(a.valueset, valuesets)):
        view, field = "vital", VITAL_FIELD[min(vital)]
    elif a.domain == "observation" and r in _VALUE_REASONS:
        view, field = LAB_VALUE
    elif a.domain == "demographic":
        (view, field), concept = (SEX, "sex") if getattr(a, "sex", None) else (BIRTH_DATE, "age")
    else:
        view, field = CODE_FIELD[a.domain]
    return {"view": view, "field": field, "concept": concept}


def needs_text(need: Mapping[str, str] | None, lang: str = "en") -> str:
    """The need as one sentence in the page language (English for another language); empty for none."""
    if not need:
        return ""
    tpl = NEEDS_TEXT.get(lang) or NEEDS_TEXT.get(lang.split("-", maxsplit=1)[0]) or NEEDS_TEXT["en"]
    return tpl.format(**need)
