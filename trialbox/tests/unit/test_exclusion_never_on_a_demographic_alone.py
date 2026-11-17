"""P2b (lane H's trace of the launch, #639, 2026-11-17): an exclusion never excludes on an age or a sex alone when its
line names more.

``Sm3NCT01227499-EXC-04`` "women with pregnant or lactation" came out of ir_extract as ``class: mixed`` with the coded
logic ``sex: female`` and nothing else, its concept candidates naming pregnancy and lactation. A mixed exclusion
present in the codes excludes (D-98), so every woman was excluded at S1 with no model asked, among them a patient the
gold calls eligible. Now such a criterion is flagged ``qualifier_dropped`` and never compiled: the notes decide a mixed
one with its question, a person any other. An exclusion that is only about sex or age (no other concept named), and
an inclusion, are left as they are. Public protocol text; no patient rows.
"""

from __future__ import annotations

from typing import Any

import pytest
from criteria_compiler.ir_extract import postprocess as pp
from criteria_compiler.terminology.mapper import Terminology
from tb_contracts import LlmExtractOutput

FEMALE = {"domain": "demographic", "sex": "female"}
PREGNANCY = [
    {"domain": "demographic", "name": "sex", "synonyms": ["gender"]},
    {"domain": "observation", "name": "pregnancy", "synonyms": ["pregnant"]},
    {"domain": "observation", "name": "lactation", "synonyms": ["breastfeeding"]},
]


def _one(text: str, logic: dict[str, Any], kind: str = "exclusion", cls: str = "mixed",
         concepts: list[dict[str, Any]] | None = None, question: str | None = None) -> Any:  # fmt: skip
    crit: dict[str, Any] = {"kind": kind, "class": cls, "text": text, "logic": logic,
                            "concept_candidates": concepts or []}  # fmt: skip
    if question:
        crit["note_question"] = question
    (c,) = pp.postprocess("T", LlmExtractOutput.model_validate({"criteria": [crit]}), Terminology(), "1.0.0").criteria
    return c


def test_the_p2b_pregnancy_line_is_decided_by_the_notes_not_by_sex() -> None:
    c = _one("women with pregnant or lactation", FEMALE, concepts=PREGNANCY,
             question="Is the patient a woman who is pregnant or lactating?")  # fmt: skip
    assert c.class_ == "note" and c.note_question
    assert "qualifier_dropped" in (c.flags or [])
    assert c.logic.valueset == "NONE" and c.logic.sex is None  # the sex atom is never run on its own


def test_without_a_question_a_person_decides_it() -> None:
    c = _one("Pregnant women", FEMALE, cls="structured", concepts=PREGNANCY)
    assert c.class_ == "human" and c.human_question and "qualifier_dropped" in (c.flags or [])


@pytest.mark.parametrize(
    ("text", "logic", "concepts"),
    [
        ("Age over 75 with renal impairment", {"domain": "demographic", "age": {"min": 76}},
         [{"domain": "condition", "name": "renal impairment"}]),
        ("Males with prostate disease", {"domain": "demographic", "sex": "male"},
         [{"domain": "condition", "name": "prostate disease"}]),
        ("Women of childbearing potential not using contraception",
         {"op": "and", "args": [FEMALE, {"domain": "demographic", "age": {"max": 50}}]},
         [{"domain": "medication", "name": "contraception"}]),
    ],
)  # fmt: skip
def test_any_age_or_sex_alone_for_a_line_that_names_more_never_excludes(
    text: str, logic: dict[str, Any], concepts: list[dict[str, Any]]
) -> None:
    c = _one(text, logic, cls="structured", concepts=concepts)
    assert c.class_ == "human" and "qualifier_dropped" in (c.flags or []), text


def test_a_line_only_about_sex_or_age_stays_coded() -> None:
    c = _one("Female", FEMALE, cls="structured", concepts=[{"domain": "demographic", "name": "sex"}])
    assert c.class_ == "structured" and "qualifier_dropped" not in (c.flags or [])
    c = _one("Aged 80 or older", {"domain": "demographic", "age": {"min": 80}}, cls="structured")
    assert c.class_ == "structured" and "qualifier_dropped" not in (c.flags or [])


def test_an_inclusion_keeps_its_demographic_part() -> None:
    c = _one("Women with breast cancer", FEMALE, kind="inclusion", cls="structured",
             concepts=[{"domain": "condition", "name": "breast cancer"}])  # fmt: skip
    assert "qualifier_dropped" not in (c.flags or [])  # it excludes only men, which it should


def test_an_exclusion_whose_logic_names_the_condition_too_stays_coded() -> None:
    logic = {"op": "and", "args": [FEMALE, {"domain": "condition", "concept": "pregnancy"}]}
    c = _one("Pregnant women", logic, cls="structured", concepts=[{"domain": "condition", "name": "pregnancy"}])
    assert "qualifier_dropped" not in (c.flags or [])
