"""invariant: a line whose coded logic would select a different population than its text is held, never run.

Card J-R18 (D-1267; the report on #1327). Four kinds of line left the compiler coded with no flag, each run on the
wrong population:

1. an inclusion that applies to a part of the patients, coded as the sex alone ("Women of childbearing potential must
   have a negative pregnancy test" as ``female``): every man failed it. It is held for a person (``qualifier_dropped``);
2. "HIV抗体陰性の患者" coded as ``any HIV``: only HIV-positive patients met it;
3. a cessation coded as presence ("Must be off corticosteroids for 2 weeks", "refrained from smoking"): the opposite
   patients met it. (2) and (3) are held as the English "HIV-negative patients" already was
   (``negated_inclusion_presence``);
4. a line whose text qualifies its coded concept ("Uncontrolled hypertension despite three antihypertensive drugs"
   coded as ``any hypertension``): as a mixed exclusion its code alone excluded every hypertension at S1. It is
   flagged ``coded_part_qualified``: mixed, its code never settles it (``semantics.codes_settle``); structured, a
   person checks it ("Hypertension not controlled by two agents", the integrator's ruling on #639, 7127329652).

Plain lines still run unflagged. The extractions are written by hand, as the extractor would emit them (no model).
Synthetic and public protocol text; no patients.
"""

from __future__ import annotations

from typing import Any

import pytest
from criteria_compiler.ir_extract import postprocess as pp
from criteria_compiler.semantics import QUALIFIED, codes_settle
from criteria_compiler.terminology.mapper import Terminology
from tb_contracts import LlmExtractOutput

FEMALE = {"domain": "demographic", "sex": "female"}
_TERM: list[Terminology] = []


def _one(text: str, logic: dict[str, Any], kind: str = "inclusion", cls: str = "structured",
         concepts: list[dict[str, Any]] | None = None, question: str | None = None) -> Any:  # fmt: skip
    if not _TERM:
        _TERM.append(Terminology())
    crit: dict[str, Any] = {"kind": kind, "class": cls, "text": text, "logic": logic,
                            "concept_candidates": concepts or []}  # fmt: skip
    if question:
        crit["note_question"] = question
    out = pp.postprocess("T", LlmExtractOutput.model_validate({"criteria": [crit]}), _TERM[0], "1.0.0")
    (c,) = out.criteria
    return c


def _held(c: Any, flag: str) -> None:
    assert flag in (c.flags or []), (c.text, c.flags)
    assert c.class_ == "human" and c.human_question, (c.text, c.class_)
    assert c.logic.valueset == "NONE" and c.logic.sex is None and c.logic.age is None  # nothing of it is run


def _presence(concept: str, domain: str) -> dict[str, Any]:
    return {"domain": domain, "quantifier": "any", "concept": concept}


# ------------------------------------------------------------------------------- (1) a part of the patients only
PREGNANCY_TEST: list[dict[str, Any]] = [
    {"domain": "demographic", "name": "sex"},
    {"domain": "observation", "name": "pregnancy test", "synonyms": ["妊娠検査", "驗孕"]},
]


@pytest.mark.parametrize(
    "text",
    [
        "Women of childbearing potential must have a negative pregnancy test",
        "妊娠可能な女性は妊娠検査陰性であること",
        "具生育能力之女性須驗孕結果為陰性",
        "WOCBP must have a negative serum pregnancy test within 7 days",
    ],
)
@pytest.mark.parametrize("cls", ["structured", "mixed"])
def test_an_inclusion_for_a_part_of_the_patients_coded_as_sex_alone_is_held(text: str, cls: str) -> None:
    question = "Does the patient have a negative pregnancy test?" if cls == "mixed" else None
    c = _one(text, FEMALE, cls=cls, concepts=PREGNANCY_TEST, question=question)
    _held(c, "qualifier_dropped")


def test_the_reason_names_the_dropped_part() -> None:
    crit = {"kind": "inclusion", "class": "structured", "text": "Women of childbearing potential must have a negative "
            "pregnancy test", "logic": FEMALE, "concept_candidates": PREGNANCY_TEST}  # fmt: skip
    if not _TERM:
        _TERM.append(Terminology())
    out = pp.postprocess("T", LlmExtractOutput.model_validate({"criteria": [crit]}), _TERM[0], "1.0.0")
    assert any("childbearing potential" in w and "person" in w for w in out.warnings), out.warnings


# ------------------------------------------------------------------- (2) and (3) a negative result or a cessation
HIV = [{"domain": "condition", "name": "HIV", "synonyms": ["HIV抗体", "HIV infection", "人類免疫缺乏病毒"]}]
STEROID = [{"domain": "medication", "name": "corticosteroids", "synonyms": ["ステロイド", "類固醇", "steroids"]}]
SMOKING = [{"domain": "observation", "name": "smoking", "synonyms": ["tobacco use", "喫煙", "吸菸"]}]
NEGATED: list[tuple[str, str, str, list[dict[str, Any]]]] = [
    ("HIV抗体陰性の患者", "HIV", "condition", HIV),
    ("HIV-negative patients", "HIV", "condition", HIV),
    ("人類免疫缺乏病毒檢驗陰性者", "HIV", "condition", HIV),
    ("Must be off corticosteroids for 2 weeks", "corticosteroids", "medication", STEROID),
    ("ステロイドを2週間以上休薬している患者", "corticosteroids", "medication", STEROID),
    ("停用類固醇至少兩週", "corticosteroids", "medication", STEROID),
    ("停藥類固醇至少兩週者", "corticosteroids", "medication", STEROID),
    ("ステロイドの投与を中止して2週間以上経過した患者", "corticosteroids", "medication", STEROID),
    ("Corticosteroids discontinued at least 2 weeks before enrollment", "corticosteroids", "medication", STEROID),
    ("Patients who have refrained from smoking for at least 6 months", "smoking", "observation", SMOKING),
    ("Patients who have abstained from smoking for at least 6 months", "smoking", "observation", SMOKING),
]


@pytest.mark.parametrize(("text", "concept", "domain", "cands"), NEGATED)
@pytest.mark.parametrize("cls", ["structured", "mixed"])
def test_a_negated_or_ceased_concept_coded_as_presence_is_held(
    text: str, concept: str, domain: str, cands: list[dict[str, Any]], cls: str
) -> None:
    question = f"Does the patient have {concept}?" if cls == "mixed" else None
    c = _one(text, _presence(concept, domain), cls=cls, concepts=cands, question=question)
    _held(c, "negated_inclusion_presence")


# ------------------------------------------------------------------------- (4) a qualifier on the coded concept
HYPERTENSION = [{"domain": "condition", "name": "hypertension", "synonyms": ["高血圧", "高血壓", "高血压"]}]
QUALIFIED_LINES = [
    "Uncontrolled hypertension despite three antihypertensive drugs",
    "Poorly controlled hypertension",
    "Refractory hypertension",
    "3剤以上の降圧薬にもかかわらずコントロール不良の高血圧",
    "使用三種降壓藥仍控制不佳的高血壓",
    "Hypertension not controlled by two agents",  # row 154 of the 10A-1 table (the integrator's ruling 7127329652)
    "高血壓且未受控制",  # row 164, the zh row of the same class
    "高血压未控制",
    "血圧のコントロールが不良な高血圧",
]


@pytest.mark.parametrize("text", QUALIFIED_LINES)
@pytest.mark.parametrize("kind", ["exclusion", "inclusion"])
def test_a_qualified_mixed_line_is_never_settled_by_its_code(text: str, kind: str) -> None:
    c = _one(text, _presence("hypertension", "condition"), kind=kind, cls="mixed", concepts=HYPERTENSION,
             question="Is the patient's hypertension uncontrolled despite treatment?")  # fmt: skip
    if c.class_ == "human":  # 高血压未控制 as an inclusion: the negation rule (未) holds it first, which is held too
        _held(c, "negated_inclusion_presence")
        return
    assert c.class_ == "mixed" and QUALIFIED in (c.flags or []), (text, c.flags)
    assert codes_settle(c) is False  # the cascade's S1 leaves it to the notes (engine: mixed and not codes_settle)


@pytest.mark.parametrize("text", QUALIFIED_LINES)
@pytest.mark.parametrize("kind", ["exclusion", "inclusion"])
def test_a_qualified_structured_line_is_held(text: str, kind: str) -> None:
    # a structured line has no notes to decide it: its code alone would run it on every hypertension
    c = _one(text, _presence("hypertension", "condition"), kind=kind, concepts=HYPERTENSION)
    _held(c, "negated_inclusion_presence" if "negated_inclusion_presence" in (c.flags or []) else QUALIFIED)


# ------------------------------------------------------------------------------------------------------ controls
def test_controls_plain_lines_still_run_unflagged() -> None:
    held = {"qualifier_dropped", "negated_inclusion_presence", QUALIFIED}
    age_sex = {"op": "and", "args": [FEMALE, {"domain": "demographic", "age": {"min": 18}}]}
    c = _one("Female patients aged 18 or older", age_sex, concepts=[{"domain": "demographic", "name": "sex"}])
    assert c.class_ == "structured" and not held & set(c.flags or [])
    assert c.logic.op == "and"
    for text, concept, kind in [("History of hypertension", "hypertension", "inclusion"),
                                ("History of hypertension", "hypertension", "exclusion"),
                                ("HIV infection", "HIV", "inclusion"), ("HIV infection", "HIV", "exclusion")]:  # fmt: skip
        cands = HYPERTENSION if concept == "hypertension" else HIV
        c = _one(text, _presence(concept, "condition"), kind=kind, concepts=cands)
        assert c.class_ == "structured" and not held & set(c.flags or []), (text, kind, c.flags)
        c = _one(text, _presence(concept, "condition"), kind=kind, cls="mixed", concepts=cands,
                 question=f"Does the patient have {concept}?")  # fmt: skip
        assert c.class_ == "mixed" and not held & set(c.flags or []), (text, kind, c.flags)
        assert codes_settle(c) is True  # an exclusion's code still settles it at S1 (D-98)


def test_controls_a_line_that_names_a_sex_with_a_condition_keeps_its_sex() -> None:
    # "Women with breast cancer" as female: men fail it, as they should (test_exclusion_never_on_a_demographic_alone)
    c = _one("Women with breast cancer", FEMALE, concepts=[{"domain": "condition", "name": "breast cancer"}])
    assert "qualifier_dropped" not in (c.flags or [])
    c = _one("Receiving off-label methotrexate", _presence("methotrexate", "medication"),
             concepts=[{"domain": "medication", "name": "methotrexate"}])  # fmt: skip
    assert "negated_inclusion_presence" not in (c.flags or []) and c.class_ == "structured"
