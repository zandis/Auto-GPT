"""G9 of the integrator's second review of the P1b run (#639, 2026-11-16), D-954: of sigir's 772 compiled criteria the
model classed 83 human and the compiler demoted 370 more; 111 mixed criteria that had a note question went to a person
only because their coded part could not run (``postprocess``, D-910), while ``demote_uncompilable`` keeps such a
criterion as note (D-98). That made the all-human and notes-only rulesets.

* A mixed criterion whose coded part cannot run keeps its note question: class note, flagged ``coded_part_dropped``,
  when the notes can settle it (``notes_can_decide``, from D-954's review of the run's 173 such criteria); else a
  person keeps it, flagged ``notes_cannot_decide_<why>``.
* A structured criterion, or a mixed one with no note question, still goes to a person.

Lines from the run's public SIGIR protocols; no patient rows.
"""

from __future__ import annotations

from typing import Any

import pytest
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


BAD = {"domain": "condition", "concept": "Pneumonia", "derived": "bmi"}  # a score on a condition: cannot run


def test_a_mixed_criterion_whose_coded_part_cannot_run_is_read_from_the_notes() -> None:
    c = _one("mixed", "inclusion", "Does the patient have a smoking history?", BAD, "First degree relative who smokes")
    assert c.class_ == "note" and c.note_question == "Does the patient have a smoking history?"
    assert {"coded_part_dropped", "logic_invalid", "needs_review"} <= set(c.flags or [])


@pytest.mark.parametrize(
    ("kind", "text", "question", "why"),
    [  # D-954's review: the run's lines the models would answer wider than the line, or cannot settle from notes
        ("exclusion", "No focal stroke-like symptoms", "Does the patient lack focal stroke-like symptoms?",
         "negated_question"),
        ("inclusion", "No significant cardiopulmonary disease",
         "Does the patient have significant cardiopulmonary disease?", "negated_line"),
        ("exclusion", "Women of childbearing potential not using contraception",
         "Is the patient pregnant, breastfeeding, or of childbearing potential?", "not_in_notes"),
        ("exclusion", "Patients who will refuse blood transfusions", "Will the patient refuse blood transfusions?",
         "not_in_notes"),
        ("inclusion", "Diabetes treated with oral agents such as metformin",
         "Does the patient have diabetes treated with oral agents such as metformin?", "inferred"),
        ("exclusion", "Elevated INR", "Does the patient have an elevated INR?", "inferred"),
        ("inclusion", "Positive ANA, or", "Does the patient have a positive ANA?", "fragment"),
        ("inclusion", "Patients with endometriosis will be included", "Does the patient have endometriosis?",
         "fragment"),
        ("exclusion", "Smoking history < 20 pack-years", "Does the patient have a smoking history of less than 20 "
         "pack-years?", "threshold"),
        ("exclusion", "History of neurological and medical illness",
         "Does the patient have a history of neurological or medical illness?", "broad_exclusion"),
        ("exclusion", "Right handed, normal vision and normal hearing",
         "Is the patient right-handed with normal vision and hearing?", "broad_exclusion"),
    ],
)  # fmt: skip
def test_a_question_the_notes_cannot_settle_stays_with_a_person(kind: str, text: str, question: str, why: str) -> None:
    c = _one("mixed", kind, question, BAD, text)
    assert c.class_ == "human" and f"notes_cannot_decide_{why}" in (c.flags or []), (text, c.flags)


def test_a_plain_exclusion_of_a_named_condition_is_read_from_the_notes() -> None:
    c = _one("mixed", "exclusion", "Does the patient have a history of pancreatitis?", BAD, "History of pancreatitis")
    assert c.class_ == "note" and "coded_part_dropped" in (c.flags or [])


def test_without_a_note_question_or_as_structured_it_still_goes_to_a_person() -> None:
    assert _one("mixed", "inclusion", None, BAD).class_ == "human"
    assert _one("structured", "inclusion", None, BAD).class_ == "human"


def test_a_mixed_criterion_that_runs_is_unchanged() -> None:
    c = _one("mixed", "inclusion", "Does the patient have pneumonia?", {"domain": "condition", "concept": "Pneumonia"})
    assert c.class_ == "mixed" and "coded_part_dropped" not in (c.flags or [])
