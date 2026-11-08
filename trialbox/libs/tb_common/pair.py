"""The two-model rule, in one place (TB-PLAN-03 step 3, D-118).

Both screening paths (the v1 ``NoteJudge`` that NAV, MICROBATCH and CASE run, and the v4 cascade that SCREEN runs,
through ``OrchestratorJudge``) and the cascade's own ``AgreementJudge`` (offline tools) decide a note answer with
:func:`combine`. Before D-118 each carried its own copy, so the path SCREEN ran was not the one the tests covered
(Fable review 2026-11-08, finding 4).

The rule:

1. the judge's answer stands alone when no verifier is configured (the note-block policy then never lets it exclude,
   ``effective_note_block``);
2. an undecided judge answer (``unknown``) is not put to the verifier;
3. a verifier that did not answer, whose quote is not in the notes, or that gives another verdict turns the answer
   into ``unknown`` with the matching :class:`~tb_common.reasons.Reason`, never an exclusion;
4. when both agree the answer is as sure as the less sure model (``min`` of the confidences);
5. a decided answer below :data:`~tb_common.reasons.MIN_CONFIDENCE` is not used: ``unknown`` / ``low_confidence``.
"""

from __future__ import annotations

from dataclasses import dataclass

from tb_common.reasons import MIN_CONFIDENCE, Reason

DECIDED = ("pass", "fail")


@dataclass(frozen=True)
class Vote:
    """One model's answer after its quote was checked: ``reason`` is a :class:`Reason` code (``quote_not_found``
    when the quote did not verify, ``model_down`` when the model did not answer)."""

    verdict: str  # pass | fail | unknown
    confidence: float
    reason: str | None = None


@dataclass(frozen=True)
class Decision:
    verdict: str
    confidence: float
    reason: str | None
    disagreement: bool = False  # the verifier did not confirm a decided judge answer
    failure: bool = False  # the verifier did not answer


def needs_verifier(first: Vote) -> bool:
    return first.verdict in DECIDED


def floor(v: Vote, minimum: float = MIN_CONFIDENCE) -> Decision:
    if v.verdict in DECIDED and v.confidence < minimum:
        return Decision("unknown", 0.0, Reason.LOW_CONFIDENCE.value)
    return Decision(v.verdict, v.confidence, v.reason)


def combine(first: Vote, second: Vote | None, minimum: float = MIN_CONFIDENCE) -> Decision:
    """The pair's answer (see the module docstring). ``second`` is ``None`` when there is no verifier or the judge
    did not decide."""
    if second is None or not needs_verifier(first):
        return floor(first, minimum)
    if second.reason == Reason.MODEL_DOWN.value:
        return Decision("unknown", 0.0, Reason.MODEL_DOWN.value, failure=True)
    if second.reason == Reason.QUOTE_NOT_FOUND.value:
        return Decision("unknown", 0.0, Reason.VERIFIER_QUOTE_MISSING.value, disagreement=True)
    if second.verdict != first.verdict:
        return Decision("unknown", 0.0, Reason.DISAGREE.value, disagreement=True)
    return floor(Vote(first.verdict, min(first.confidence, second.confidence), first.reason), minimum)


__all__ = ["DECIDED", "Decision", "Vote", "combine", "floor", "needs_verifier"]
