"""Card 10A-1 (review 15, finding 2.3.1; plan 10 Track A): a negated inclusion never compiles as its opposite.

The P2b launch stored two coded inclusions whose line is a negation and whose logic asks presence:
``SM3NCT00002897-INC-03`` "PRIOR CONCURRENT THERAPY: No prior chemotherapy or radiotherapy" compiled to
``any of VS_CHEMOTHERAPY`` (structured), and ``SM3NCT00256529-INC-03`` "No significant cardiopulmonary disease, or
other contraindication to EGD" the same way (mixed). An inclusion is met when its logic is true, so once the code list
loads the first would exclude every patient who never had chemotherapy, the eligible ones. The compiler rewrote a
negated exclusion's logic to the positive form and kept a negated inclusion's note question from the models, but
never compared a coded inclusion's logic with its line. Now an inclusion whose line is a negation and whose logic
asks for a concept's presence is held for a person (``negated_inclusion_presence``): it is never run, so it answers
unknown, and unknown never excludes. A negated line whose logic is already negative ("none of", ``not``), an age or
sex alone, and a positive line with a negation inside it are left as they were. Public protocol text; no patients.
"""

from __future__ import annotations

from typing import Any

import pytest
from criteria_compiler.ir_extract import postprocess as pp
from criteria_compiler.terminology.mapper import Terminology
from tb_contracts import LlmExtractOutput

FLAG = "negated_inclusion_presence"
CHEMO = {"domain": "procedure", "quantifier": "any", "concept": "chemotherapy"}  # VS_CHEMOTHERAPY once compiled
CHEMO_CAND = [{"domain": "procedure", "name": "chemotherapy"}]
_TERM: list[Terminology] = []


def _term() -> Terminology:
    """One empty terminology for the module (each takes about a second to build; the table runs hundreds of lines)."""
    if not _TERM:
        _TERM.append(Terminology())
    return _TERM[0]


def _one(text: str, logic: dict[str, Any], kind: str = "inclusion", cls: str = "structured",
         concepts: list[dict[str, Any]] | None = None, question: str | None = None) -> Any:  # fmt: skip
    crit: dict[str, Any] = {"kind": kind, "class": cls, "text": text, "logic": logic,
                            "concept_candidates": concepts if concepts is not None else CHEMO_CAND}  # fmt: skip
    if question:
        crit["note_question"] = question
    (c,) = pp.postprocess("T", LlmExtractOutput.model_validate({"criteria": [crit]}), _term(), "1.0.0").criteria
    return c


def _held(c: Any) -> None:
    assert c.class_ == "human" and c.human_question, (c.class_, c.text)
    assert FLAG in (c.flags or []), c.flags
    assert getattr(c.logic, "valueset", None) == "NONE"  # the presence logic is never run


def test_the_two_p2b_lines_are_held() -> None:
    # SM3NCT00002897-INC-03 as the launch stored it (structured)
    _held(_one("PRIOR CONCURRENT THERAPY: No prior chemotherapy or radiotherapy", CHEMO))
    # SM3NCT00256529-INC-03 (mixed, with the note question a model would answer as "has the disease")
    _held(_one("No significant cardiopulmonary disease, or other contraindication to EGD",
               {"domain": "condition", "quantifier": "any", "concept": "cardiopulmonary disease"},
               cls="mixed", concepts=[{"domain": "condition", "name": "cardiopulmonary disease"}],
               question="Does the patient have significant cardiopulmonary disease?"))  # fmt: skip


# the negated forms of a line in the three languages the compiler takes; each leads (en, zh-TW) or ends (ja) the line
NEGATED_LINES = [
    "No prior chemotherapy",
    "no previous chemotherapy",
    "NO PRIOR CHEMOTHERAPY.",
    "PRIOR CONCURRENT THERAPY: No prior chemotherapy or radiotherapy",
    "- No history of chemotherapy",
    "1. Not previously treated with chemotherapy",
    "Never received chemotherapy",
    "Without prior chemotherapy",
    "Absence of prior chemotherapy",
    "Free of prior chemotherapy for 5 years",
    "None of the following: chemotherapy, radiotherapy",
    "Lack of prior chemotherapy",
    "Chemotherapy-naive",
    "Chemotherapy naïve patients",
    "Patients with no prior chemotherapy",
    "Subjects without prior chemotherapy",
    "Patients who have not received chemotherapy",
    "Participants who have never received chemotherapy",
    "Must not have received chemotherapy",
    "Has not had chemotherapy",
    "化学療法歴なし",
    "化学療法の治療歴がない",
    "化学療法の既往がないこと",
    "化学療法の既往のない患者",
    "化学療法を受けていない",
    "化学療法を受けたことがない者",
    "前治療として化学療法を認めない。",
    "化学療法を受けていません",
    "化学療法未施行",
    "化学療法歴無し",
    "無化學治療病史",
    "沒有接受過化學治療",
    "未曾接受化學治療",
    "未接受過化學治療",
    "從未接受化學治療",
    "不曾接受化學治療",
    "病人無化學治療病史",
    "患者未曾接受化學治療",
    # forms an adversarial review found missed by the first version of the rule
    "Patient has not received chemotherapy",
    "Patients must not have received prior chemotherapy",
    "Female patients who are not on chemotherapy",
    "Patients that haven't received chemotherapy",
    "The patient has no history of chemotherapy",
    "Prior chemotherapy not allowed",
    "Chemotherapy is not permitted",
    "Prior chemotherapy - none",
    "Previously untreated",
    "Must be chemotherapy-naive",
    "Treatment-naïve for HCC",
    "化学療法治療歴なし（ただし術後補助療法は除く）",
    "化学療法を受けていない（6ヶ月以内）",
    "化学療法歴が無い",
    "化学療法未施行例",
    "化学療法ナイーブ",
    "過去未曾接受化學治療",
    "先前未接受化學治療",
    "之前沒有接受過化學治療",
    "病患未曾接受化學治療",
    "參與者未曾接受化學治療",
    "不得曾接受化學治療",
]
# shapes of logic that ask presence: the atom itself, in an and/or beside an age, or twice negated
PRESENCE = [
    CHEMO,
    {**CHEMO, "quantifier": "all"},
    {"op": "and", "args": [{"domain": "demographic", "age": {"min": 18}}, CHEMO]},
    {"op": "or", "args": [CHEMO, {**CHEMO, "quantifier": "none"}]},
    {"op": "not", "args": [{"op": "not", "args": [CHEMO]}]},
]


@pytest.mark.parametrize("cls", ["structured", "mixed"])
@pytest.mark.parametrize("logic", PRESENCE)
@pytest.mark.parametrize("text", NEGATED_LINES)
def test_property_a_negated_inclusion_with_presence_logic_is_never_run(
    text: str, logic: dict[str, Any], cls: str
) -> None:
    q = "Has the patient received chemotherapy?" if cls == "mixed" else None
    _held(_one(text, logic, cls=cls, question=q))


ABSENCE = [
    {**CHEMO, "quantifier": "none"},
    {"op": "not", "args": [CHEMO]},
    {"op": "and", "args": [{"domain": "demographic", "age": {"min": 18}}, {**CHEMO, "quantifier": "none"}]},
]


@pytest.mark.parametrize("logic", ABSENCE)
@pytest.mark.parametrize("text", NEGATED_LINES)
def test_property_a_negated_inclusion_already_negative_is_kept(text: str, logic: dict[str, Any]) -> None:
    c = _one(text, logic)
    assert c.class_ == "structured" and FLAG not in (c.flags or []), (text, c.class_, c.flags)


# positive lines with a negation inside them, all from the stored launch set or written as it writes: they keep their
# logic (each asks a concept that is present; the negation qualifies it)
POSITIVE_LINES = [
    "Histologically confirmed adenocarcinoma, not amenable to surgery",
    "Subjects meeting full criteria for the diagnosis of current Major Depressive Disorder (MDD) without psychotic "
    "features",
    "Anovulatory patients who did not conceive after a minimum of three ovulatory cycles",
    "Patients with cutaneous leg ulcers due to diabetes mellitus, not healing after 4 weeks",
    "Non-small cell lung cancer",
    "Noninvasive breast cancer",
    "Notable history of chemotherapy",
    "非小細胞肺癌",
    "未満18歳の化学療法歴のある患者",
    "化学療法歴のある患者（転移なし）",
    "未滿75歲且曾接受化學治療",
    "非小細胞肺癌の患者で化学療法を受けたもの",
]


@pytest.mark.parametrize("text", POSITIVE_LINES)
def test_a_positive_line_with_a_negation_inside_is_kept(text: str) -> None:
    c = _one(text, CHEMO)
    assert c.class_ == "structured" and FLAG not in (c.flags or []), (text, c.class_, c.flags)


@pytest.mark.parametrize(
    "text",
    ["Patients must not be pregnant", "Non-pregnant, non-lactating women", "Nonsmoker", "妊娠中ではない女性",
     "未懷孕", "非懷孕", "受試者未懷孕"],
)  # fmt: skip
def test_property_not_pregnant_never_runs_as_pregnant(text: str) -> None:
    """ "Not pregnant" coded as "any of pregnancy" would exclude every woman who is not pregnant."""
    preg = {"domain": "condition", "quantifier": "any", "concept": "pregnancy"}
    _held(_one(text, preg, concepts=[{"domain": "condition", "name": "pregnancy"}]))


def test_a_negated_mixed_line_is_held_before_another_rule_hands_it_to_the_notes() -> None:
    """The age-at-onset rule hands a mixed line to the notes; a negated inclusion must not get there first."""
    logic = {**CHEMO, "age": {"max": 18}}
    c = _one("No chemotherapy before age 18", logic, cls="mixed",
             question="Did the patient receive chemotherapy before age 18?")  # fmt: skip
    _held(c)


def test_a_line_led_by_a_negated_subject_is_held_even_when_its_concept_is_present() -> None:
    """The cost the rule accepts: "Nonsmokers with asthma" asks asthma, yet its lead is a negation, so a person looks
    at it. Holding a line costs a look; missing a negated one would exclude the patients it should keep."""
    asthma = {"domain": "condition", "quantifier": "any", "concept": "asthma"}
    _held(_one("Nonsmokers with asthma", asthma, concepts=[{"domain": "condition", "name": "asthma"}]))


def test_an_age_or_sex_alone_and_an_exclusion_are_not_this_rule() -> None:
    age = _one("No younger than 18 years", {"domain": "demographic", "age": {"min": 18}}, concepts=[])
    assert age.class_ == "structured" and FLAG not in (age.flags or [])
    exc = _one("No prior chemotherapy", CHEMO, kind="exclusion")  # an exclusion's own rules decide it, not this one
    assert FLAG not in (exc.flags or [])


def test_the_reason_is_said_to_the_reviewer() -> None:
    post = pp.postprocess("T", LlmExtractOutput.model_validate({"criteria": [
        {"kind": "inclusion", "class": "structured", "text": "No prior chemotherapy", "logic": CHEMO,
         "concept_candidates": CHEMO_CAND}]}), _term(), "1.0.0")  # fmt: skip
    assert any("T-INC-01" in w and "negat" in w and "person" in w for w in post.warnings), post.warnings


def test_held_it_answers_unknown_and_never_excludes() -> None:
    """Unknown never excludes: the held line is neither compiled for S1 nor asked of a model; it reaches the engine
    as a person's question, which never excludes (``test_safety_properties.py``, P1's tier table: a human
    criterion)."""
    from criteria_compiler.semantics import FILTERED, JUDGED
    from tb_contracts import Atom

    c = _one("No prior chemotherapy", CHEMO)
    assert c.class_ == "human" and c.class_ not in FILTERED and c.class_ not in JUDGED
    assert isinstance(c.logic, Atom) and c.logic.domain == "demographic" and c.logic.valueset == "NONE"
    assert c.logic.age is None and c.logic.sex is None
