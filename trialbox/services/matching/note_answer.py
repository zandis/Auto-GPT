"""What a note answer may do (D-1069, the owner's ruling 1 of 2026-11-22; D-985): the one rule every path reads.

A note answer is two models' reading of the notes, decided (``pass`` / ``fail``) and resting on a verified quote.
What it may then do to a patient is said here once, for the cascade (``engine._map``), the older evaluator
(``evaluate.note_verdict``) and the status rule's backstop over a stored row (``decision.answer_of``):

* an answer that keeps the patient (an inclusion met, an exclusion's condition absent): ``keeps``;
* an exclusion's "condition present" on a quote that does not state the condition (a negated, a relative's, a
  rule-out, a suspected condition, a drug or a value for it; :func:`matching.inferred.inferred`): ``review``, a
  person looks (D-985, R22-16);
* an exclusion's "condition present" on a quote that states it: ``excludes``.

``excludes`` is what the answer may do, not what it does: the run's own rules then decide whether this answer is
one that may exclude (two different models, sure enough, final, notes allowed to exclude: ``decision.fail_stands``
and the cascade's ``note_block``). Never a coded answer's nor a person's: those do not come here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from matching.inferred import inferred, sentence_of

Effect = Literal["keeps", "review", "excludes"]

#: the reason of an exclusion "present" on a quote that does not state the condition (the cascade's wording, D-985)
INFERRED_REASON = "inferred: the quote does not state the condition; review"


@dataclass(frozen=True)
class NoteEffect:
    """What one note answer may do, and the reason when it is review."""

    effect: Effect
    reason: str = ""


def note_answer_may(
    kind: str, condition_present: bool, quote: str | None, criterion: str, sentence: str = ""
) -> NoteEffect:
    """What a decided note answer may do to the patient.

    ``kind``: the criterion's (``inclusion`` / ``exclusion``). ``condition_present``: the models' answer to the
    criterion's question (``pass`` of the judge). ``quote``: the verified quote it rests on. ``criterion``: the
    criterion's text, never its note question. ``sentence``: the record's sentence the quote was verified in, when the
    caller has it (a quote may be a fragment of it)."""
    eligible = condition_present if kind == "inclusion" else not condition_present
    if eligible:
        return NoteEffect("keeps")
    if kind == "exclusion" and inferred(str(quote or ""), str(criterion or ""), sentence):
        return NoteEffect("review", INFERRED_REASON)
    return NoteEffect("excludes")


__all__ = ["INFERRED_REASON", "Effect", "NoteEffect", "note_answer_may", "sentence_of"]
