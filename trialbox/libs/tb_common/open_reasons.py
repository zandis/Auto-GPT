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
