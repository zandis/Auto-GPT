"""The order of a candidate list, "closest to eligible" (MATCH-ARCH 1(e)): a deterministic key, never a probability.

The tiers stay the only truth (``matching.decision.status_of``): this key only orders patients *inside* what the tiers
say, and it never removes anyone: a list sorted by it holds the same patients as before, and an excluded patient is
last, still there with its reasons (the owner's rule: no patient leaves the list). It carries nothing for an unknown
(an open criterion is never partial credit) and no model confidence enters it. In order:

1. the tier: ``high`` 0, ``review`` 1, ``excluded`` 2 (a coded "no" sends a patient to the last block whatever follows);
2. ``n_open``: criteria still open (unknown, or a person decides), fewest first;
3. ``open_weight``: the sum, over the open criteria, of how hard the gap is to close (:func:`open_weight`);
4. ``n_for``: criteria whose answer is "fine for eligibility" with a quote shown, most first;
5. the next appointment (none last), then the pseudonym: an operational tiebreak, then a stable order.

It is a pure function of the verdict rows (their words, reason codes and quotes): the same rows give the same key on
every run (D-82). The console reads stored rows and the matching engine reads verdict objects; both build the same
numbers and call :func:`rank_tuple`, so the order has one definition. The reliability classes of an open criterion
are a first reading of the owner's three examples (a pending or stale value, notes only, a gap in the site's own
data) and are the one place to change them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from tb_common.reasons import Reason
from tb_common.verdict_word import shown_of

TIER_RANK = {"high": 0, "review": 1, "excluded": 2}

#: the site's own data cannot answer these (no notes, no code system, no record of the kind at all): waiting does not
#: help, so an open criterion with one of these reasons weighs the most
SITE_GAP = frozenset(
    r.value
    for r in (
        Reason.NO_NOTES,
        Reason.CODE_SYSTEM_NOT_CARRIED,
        Reason.NO_RECORD_OF_KIND,
        Reason.UNKNOWN_CODE_SYSTEM,
        Reason.NOT_IN_SNAPSHOT,
    )
)
WEIGHT_VALUE, WEIGHT_NOTE, WEIGHT_SITE = 1, 2, 3

Key = tuple[int, int, int, int, bool, str, str]


def open_weight(criterion_class: str | None, reason: str | None) -> int:
    """How hard one open criterion is to close: 3 a gap in the site's data (:data:`SITE_GAP`); 2 an answer only the
    notes can give (class ``note`` or ``mixed``); 1 otherwise (a coded value that is pending or stale, or a criterion a
    person decides at the visit)."""
    if reason in SITE_GAP:
        return WEIGHT_SITE
    if criterion_class in ("note", "mixed"):
        return WEIGHT_NOTE
    return WEIGHT_VALUE


def supports(word: str, quote: str | None) -> bool:
    """Whether a verdict is evidence *for* eligibility: its word is ``pass`` (an inclusion met, or an exclusion not
    present) and it shows a quote. The count is the notes' (the ``note_fact`` rows of MATCH-ARCH 1(e) once they exist);
    a coded answer with no quote adds nothing here, its records are shown beside it."""
    return word == "pass" and bool(quote)


def rank_tuple(
    tier: str | None,
    open_weights: Iterable[int],
    n_for: int,
    next_appointment: str | None = None,
    pid: str = "",
) -> Key:
    """The key of one patient: ``(tier, n_open, open_weight, -n_for, no visit, visit, pid)``, smallest first."""
    w = list(open_weights)
    appt = str(next_appointment or "")
    return (TIER_RANK.get(str(tier), 2), len(w), sum(w), -n_for, not appt, appt, pid)


def stored_rank_key(
    tier: str | None,
    verdicts: Iterable[Mapping[str, Any]],
    classes: Mapping[str, str],
    next_appointment: str | None = None,
    pid: str = "",
) -> Key:
    """The key of a stored or published row (verdict dicts; ``classes``: criterion id to its class), with no run
    policy at hand: the word of a verdict is what :func:`tb_common.verdict_word.shown_of` says, as on every page."""
    weights: list[int] = []
    n_for = 0
    for v in verdicts:
        word, why = shown_of(v)
        ev = v.get("evidence") or {}
        if word in ("unknown", "pending_human"):
            weights.append(open_weight(classes.get(str(v.get("id"))), ev.get("reason") or why))
        if supports(word, ev.get("quote")):
            n_for += 1
    return rank_tuple(tier, weights, n_for, next_appointment, pid)


def coded_counts(verdicts: Iterable[Mapping[str, Any]], classes: Mapping[str, str]) -> tuple[int, int]:
    """``(answered, total)`` over the criteria the records answer (class ``structured``): the "coded-complete" count
    of the row header (F17 5b). It is a count to read, never a tier and never part of the key."""
    answered: set[str] = set()
    seen: set[str] = set()
    for v in verdicts:
        cid = str(v.get("id"))
        if classes.get(cid) != "structured":
            continue
        seen.add(cid)
        if shown_of(v)[0] in ("pass", "fail"):
            answered.add(cid)
    return len(answered), len(seen)
