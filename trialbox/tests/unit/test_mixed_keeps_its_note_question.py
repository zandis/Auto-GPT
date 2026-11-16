"""G9 of the integrator's second review of the P1b run (#639, 2026-11-16), D-954: of sigir's 772 compiled criteria the
model classed 83 human and the compiler demoted 370 more; 111 mixed criteria that had a note question went to a person
only because their coded part could not run (``postprocess``, D-910), while ``demote_uncompilable`` keeps such a
criterion as note (D-98). That made the all-human and notes-only rulesets.

* A mixed criterion whose coded part cannot run keeps its note question: class note, flagged ``coded_part_dropped``;
  a negated exclusion question is still rewritten positive.
* A structured criterion, or a mixed one with no note question, still goes to a person.

Lines from the run's public SIGIR protocols; no patient rows.
"""

from __future__ import annotations

from typing import Any

from criteria_compiler.ir_extract import postprocess as pp
from criteria_compiler.terminology.mapper import Terminology
from tb_contracts import LlmExtractOutput


def _one(cls: str, kind: str, note_question: str | None, logic: dict[str, Any], text: str = "line") -> Any:
    crit: dict[str, Any] = {"kind": kind, "class": cls, "text": text, "logic": logic,
                            "concept_candidates": [{"name": "Pneumonia", "domain": "condition"}]}  # fmt: skip
    if note_question:
        crit["note_question"] = note_question
    (c,) = pp.postprocess("T", LlmExtractOutput.model_validate({"criteria": [crit]}), Terminology(), "1.0.0").criteria
    return c


BAD = {"domain": "demographic", "concept": "smoking_history", "quantifier": "none"}  # no age, no sex: cannot run


def test_a_mixed_criterion_whose_coded_part_cannot_run_is_read_from_the_notes() -> None:
    c = _one("mixed", "inclusion", "Does the patient have a smoking history?", BAD, "First degree relative who smokes")
    assert c.class_ == "note" and c.note_question == "Does the patient have a smoking history?"
    assert {"coded_part_dropped", "logic_invalid", "needs_review"} <= set(c.flags or [])


def test_a_negated_exclusion_question_is_still_made_positive() -> None:
    c = _one("mixed", "exclusion", "Does the patient have no history of pneumonia?", BAD, "History of pneumonia")
    assert c.class_ == "note" and c.note_question and " no " not in f" {c.note_question} "


def test_without_a_note_question_or_as_structured_it_still_goes_to_a_person() -> None:
    assert _one("mixed", "inclusion", None, BAD).class_ == "human"
    assert _one("structured", "inclusion", None, BAD).class_ == "human"


def test_a_mixed_criterion_that_runs_is_unchanged() -> None:
    c = _one("mixed", "inclusion", "Does the patient have pneumonia?", {"domain": "condition", "concept": "Pneumonia"})
    assert c.class_ == "mixed" and "coded_part_dropped" not in (c.flags or [])
