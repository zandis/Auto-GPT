"""Where a verdict becomes a status (T-709, D-478; review 2026-11-12 ``decision.md`` AD-2, root cause R1).

A patient's status was worked out by whoever held the verdict list: the v1 ``tier``
(``orchestrator.scenarios.evaluate``), the cascade's own tiers mapped to the list's words
(``orchestrator.scenarios.screen_cascade.verdicts_of``), NAV's ``classify`` with its own ``_ok``, and CASE with no
rule at all. They differed on four rules (review M1 a to d) and two of them let one model's note answer take a
patient off a list (H1, H2). This module is the one place:

* :func:`answer_of`: what one criterion's verdict says for eligibility: ``yes``, ``no`` or ``unknown``;
* :func:`status_of`: a patient's status from the answers: ``excluded`` on a ``no``, ``review`` on an ``unknown``,
  else ``high``.

The rule of a note answer (TB-PLAN-06 §7.4, the pair and the excerpts invariants). It says ``no`` only when **all**
of these hold: the verdict is final (D-476: not given while a note answer may not exclude), a pair of two different
models gave it (``basis``; a row stored before the field is read by the rest), its confidence reaches the threshold,
and the run may exclude on notes (:class:`Policy`). Otherwise a note "not met" says ``unknown``: a person looks. A
note "met" below the threshold, or with notes left out of what the models read (T-603), says ``unknown`` too. So a
single model, a cut record or a low confidence can send a patient to review and can never take them off. An
exclusion's note "present" (its verdict ``fail``) whose quote does not state the condition (D-985) says ``unknown``.

An inclusion's note "not met" says ``unknown``, always, whatever the policy, the basis or the confidence (R22-17,
D-1069, the owner's ruling of 2026-11-22 for rc1 and the pilot): a note answer never takes a patient off a list for an
inclusion, the patient goes to review. The verdict row stays ``fail`` (a person reads "not met, from the notes"); only
its answer for the status changes. Both are the one rule of every path, :func:`matching.note_answer.note_answer_may`.
The records' answer and a person's are not changed: a coded inclusion "not met" still excludes.

The verdict of a structured criterion is T-652's table (:mod:`matching.verdict`): ``pass`` / ``fail`` / ``unknown``
by kind and predicate, with a coded ``fail`` the only one that excludes on its own.

It is pure: no lake, no model, no I/O. The policy comes from the job's decision context (D-477). T-216's "unknown
with a reason" rule for counts becomes one more field of :class:`Policy`, not a second rule.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from tb_common.verdict_word import held_back

from matching.note_answer import note_answer_may

Answer = Literal["yes", "no", "unknown"]
Basis = Literal["coded", "pair", "single", "person"]
#: the reason code of a note answer that the notes did not fit (T-603): flagged, a person looks
NOTES_OVER_BUDGET = "notes_over_budget"
TIERS = ("high", "review", "excluded")


@dataclass(frozen=True)
class Policy:
    """What a run decides with: the confidence a note answer needs, and whether a note answer may exclude on this
    run at all (D-95, D-97, D-276: a pair of two models that passed its canary; never one model)."""

    threshold: float
    note_block: bool


@dataclass(frozen=True)
class Status:
    """A patient's status: the candidate list's tier, the actions of the open criteria (in protocol order, each
    once), the number of unknown verdicts and the criteria whose answer excluded."""

    tier: str
    actions: list[str] = field(default_factory=list)
    n_unknown: int = 0
    excluded_by: list[str] = field(default_factory=list)


def is_note_answer(criterion: Any, verdict: Any) -> bool:
    """A verdict that came from the note judge (and so follows the confidence and pair rules): every ``note``
    verdict, and a ``mixed`` verdict the coded data did not settle (it carries a model confidence)."""
    if criterion.class_ == "note":
        return True
    ev = verdict.evidence
    return bool(criterion.class_ == "mixed" and ev is not None and ev.confidence is not None)


def basis_of(criterion: Any, verdict: Any, pair: bool) -> Basis | None:
    """The basis a freshly made verdict carries: ``person`` for a criterion a person decides, ``pair`` or
    ``single`` for a decided note answer (``pair``: the run's judge is two different models), ``coded`` for a
    decided answer of the records; None for an answer nobody gave (unknown)."""
    if verdict.verdict == "pending_human":
        return "person"
    if verdict.verdict not in ("pass", "fail"):
        return None
    if is_note_answer(criterion, verdict):
        return "pair" if pair else "single"
    return "coded"


def _confidence(verdict: Any) -> float:
    ev = verdict.evidence
    return float(ev.confidence) if ev is not None and ev.confidence is not None else 1.0


def _flagged(verdict: Any) -> bool:
    ev = verdict.evidence
    return ev is not None and ev.reason == NOTES_OVER_BUDGET


def _reviewed(criterion: Any, verdict: Any) -> bool:
    """The backstop of every builder and of a stored row: what this note answer may do, by the one rule of every path
    (:func:`matching.note_answer.note_answer_may`; D-1069, D-985, R22-16, R22-17), is review: an inclusion's "not met"
    with or without a quote; an exclusion's "present" with no quote, since what is not shown never excludes (#639
    7107834329 L1). A criterion that does not say its kind (a caller's stand-in) is read as before."""
    kind = getattr(criterion, "kind", None)
    if not kind:
        return False
    ev = verdict.evidence
    quote = ev.quote if ev is not None else None
    if kind == "exclusion" and verdict.verdict == "fail" and not quote:
        return True
    present = (verdict.verdict == "pass") == (kind != "exclusion")
    return note_answer_may(kind, present, quote, str(getattr(criterion, "text", "") or "")).effect == "review"


def reviews_inclusion(criterion: Any, verdict: Any) -> bool:
    """R22-17: a note "not met" on an inclusion (:func:`is_note_answer`), which the one rule sends to review with the
    reading kept. Never the records' answer, nor a person's (``basis: person``)."""
    return (
        verdict.verdict == "fail"
        and getattr(criterion, "kind", None) not in (None, "exclusion")  # an inclusion, a renewal, a documentation
        and getattr(verdict, "basis", None) != "person"
        and is_note_answer(criterion, verdict)
        and _reviewed(criterion, verdict)
    )


def fail_stands(verdict: Any, policy: Policy) -> bool:
    """Whether a note "not met" is one the run's policy lets stand: a pair's (or a caller's that states no basis),
    final, sure enough, on a run whose notes may exclude. For an exclusion that is what excludes; for an inclusion it
    is only what a sheet prints as "not met" (:func:`reviews_inclusion`: the status is review)."""
    # ``held_back`` is the one test for an answer that may not exclude (one model's, or not final): the same test
    # the pages and the sheets use. A fail that states neither basis nor ``final`` is decided by the policy alone:
    # a caller that states no basis (a tool, a test of the evaluator) and a list published before the field. A
    # stored pool row never reaches here so: MICROBATCH stamps ``final: false`` on it first (D-476 rule 3).
    sure = _confidence(verdict) >= policy.threshold
    basis = getattr(verdict, "basis", None)
    return bool(policy.note_block and sure and basis in (None, "pair") and held_back(verdict) is None)


def answer_of(criterion: Any, verdict: Any, policy: Policy) -> Answer:
    """``yes`` (fine for eligibility), ``no`` (excludes) or ``unknown`` (a person looks) for one verdict.

    A note answer that the one rule sends to review (:func:`_reviewed`: an inclusion's "not met", R22-17; an
    exclusion's "present" on a quote that does not state the condition, D-985) is ``unknown`` whatever the policy or
    the basis; the records' answer and a person's stand as they are."""
    v = verdict.verdict
    if v in ("unknown", "pending_human"):
        return "unknown"
    basis = getattr(verdict, "basis", None)
    if basis == "person" or not is_note_answer(criterion, verdict):
        # the records' answer (T-652's table made it) or a person's decision: final as it stands
        return "yes" if v == "pass" else "no"
    if v == "fail" and _reviewed(criterion, verdict):
        return "unknown"
    if v == "pass":
        sure = _confidence(verdict) >= policy.threshold
        return "yes" if sure and not _flagged(verdict) else "unknown"
    return "no" if fail_stands(verdict, policy) else "unknown"


def status_of(by_id: Mapping[str, Any], verdicts: Iterable[Any], policy: Policy) -> Status:
    """A patient's status from their verdicts. ``by_id``: the ruleset's criteria by id (``Ruleset.by_id()``).

    ``excluded``: an answer is ``no``. ``review``: no ``no`` and an answer is ``unknown`` for a reason a person can
    settle (an unknown verdict, or a note answer that is weak, flagged or not final). ``high``: every structured
    and note criterion says ``yes`` and only criteria a person decides are open."""
    actions: list[str] = []
    unknown = 0
    weak = False
    excluded_by: list[str] = []
    for v in verdicts:
        c = by_id[v.id]
        ans = answer_of(c, v, policy)
        if ans == "no":
            excluded_by.append(v.id)
            continue
        if ans == "yes":
            continue
        if v.verdict == "unknown":
            unknown += 1
        elif v.verdict in ("pass", "fail"):
            weak = True  # a note answer that may not decide: review
        if c.action:  # what a person does about the open criterion (a weak "not met" too, as the cascade listed)
            actions.append(c.action)
        elif v.verdict == "pending_human":
            # H-10: a criterion a person decides is never silent on the patient: its question (the compiler's, for a
            # line the model gave no criterion or one that would not compile), else that a person decides it
            actions.append(getattr(c, "human_question", None) or f"a person decides {c.id}")
    if excluded_by:
        tier = "excluded"
    elif unknown or weak:
        tier = "review"
    else:
        tier = "high"
    seen: set[str] = set()
    acts = [a for a in actions if not (a in seen or seen.add(a))]  # type: ignore[func-returns-value]
    return Status(tier, acts, unknown, excluded_by)
