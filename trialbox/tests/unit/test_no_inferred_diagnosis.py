"""F6 of the integrator's root-cause review of the P1b run (#639, 2026-11-16), D-985: a note exclusion decided by
inferring a diagnosis. On jmed both models agreed four times that a patient "has a history of hypertension" (or
diabetes) from a quote naming only an antihypertensive (or metformin); on sigir NCT01784523 the judge counted
findings into SLE. ``both_agree`` does not protect against a shared inference.

The SLE quote below is a SIGIR 2016 patient description (Koopman and Zuccon, CSIRO, CC BY-SA 4.0; see
``eval/criterion_ml/NOTICE.md``); the consent sentence is the one NCBI's benchmark appends to every note.

* An exclusion's "present" stands only on a verified quote that states the condition (the criterion's own words, an
  abbreviation or synonym of it, not negated, a relative's, a risk or a drug for it); one that names a drug, a value,
  findings or only a generic diagnosis word (診断, 症, "known") is an inference: unknown, to review, never a hard fail.
* The criterion is its text, never the note question, whose filler (があります) would count as the condition.
* A criterion that is a value, a drug or a procedure and names no condition is out of scope (eGFR < 30, steroids).
* An inclusion is never affected (it keeps a patient in); a quote that states the condition still excludes.

The cassette: the run's stored judge replies. jmed: JMED-Personas, synthetic, CC BY 4.0 (the patients' names
removed); sigir: public SIGIR patient descriptions.
"""

from __future__ import annotations

import pytest
from matching.cascade.judge import JudgeReply
from matching.inferred import inferred, names_condition

from tests.unit.test_safety_properties import SPAN, _ir, _run_for_map

HT, DM = "高血圧症の既往がある患者", "糖尿病の既往がある患者"
HT_Q, DM_Q = "高血圧症の既往がありますか？", "糖尿病の既往がありますか？"

INFERRED = [  # (criterion, quote): the run's replies the models agreed on, and the review called inferences
    (HT, "降圧薬としてカルシウム拮抗薬を処方されていますが、服薬は夫が管理しているため、本人の服薬意識が低くなりがちです。"),
    (HT, "アンジオテンシン受容体拮抗薬を処方されましたが、服薬は時々忘れることがあり、継続的な服薬管理が課題です。"),
    (HT, "降圧薬は服用していますが、体重管理のための食事制限や運動計画の継続が課題です。"),
    (DM, "処方された降圧薬ロサルタンとメトホルミンを服用していますが、飲み忘れが時々あり、服薬管理が課題です。"),
    ("SLE Diagnosis based on the ACR Classification Criteria > 4/11",
     "On examination she is found to have alopecia, a rash mainly distributed on the butterfly area of the face."),
    # the review of D-985's first cut: the run's replies it kept on a generic diagnosis word or a risk
    (HT, "心房細動と診断され、血圧も高めで脂質異常症があります。"),
    (HT, "数ヶ月前に健康診断で血圧が上昇していることが指摘され"),
    (HT, "血圧上昇所見（スクリーニング）と診断され、軽度の高血圧リスクがあります。"),
    ("Any illness or significant laboratory abnormality, which in the investigator's judgment would interfere with "
     "the patient's ability to comply with the protocol",
     "The patient will provide informed consent, and will comply with the trial protocol without any practical issue"),
    # a mention that does not state it
    ("History of diabetes", "known allergy to penicillin; on metformin"),
    ("History of diabetes", "denies diabetes"),
    ("History of diabetes", "no history of diabetes"),
    ("History of diabetes", "Family history: mother with diabetes"),
    ("History of diabetes", "diabetic diet; glucose 110"),
    ("History of hypertension", "Family history of hypertension; on amlodipine"),
    ("Hypertension", "prehypertension"),
    (DM, "糖尿病薬を内服"),
    (DM, "病歴: 特記なし、メトホルミン内服"),
    ("History of diabetes requiring insulin", "HbA1c 8.2%, on metformin"),
    ("History of diabetes", "服用二甲雙胍"),
]  # fmt: skip
STATED = [
    (HT, "BMI28.3の肥満と軽度の高血圧があり、内科で生活習慣指導を受けています。"),
    (DM, "併存症として高血圧と2型糖尿病があります。"),
    (DM, "高血圧と2型糖尿病という併存疾患があり、血糖・血圧は薬物で管理されています。"),
    ("History of type 2 diabetes", "Known diabetic on metformin 500 mg twice daily."),
    ("History of hypertension", "HTN on lisinopril"),
    ("Type 2 diabetes", "DM2, A1c 8"),
    ("Chronic kidney disease", "CKD stage 4"),
    ("Myocardial infarction within 6 months", "STEMI 2 months ago"),
    ("Atrial fibrillation", "AFib on apixaban"),
    ("Heart failure NYHA III-IV", "HFrEF, EF 25%"),
    ("SLE", "lupus nephritis"),
    ("Active malignancy", "metastatic adenocarcinoma of the lung"),
    ("Pregnant or breastfeeding", "currently lactating"),
    ("Prior stem cell transplant", "s/p allogeneic HSCT 2019"),
    ("妊娠中の患者", "妊娠12週"),
    ("懷孕或哺乳中", "目前懷孕12週"),
    ("心筋梗塞の既往がある患者", "AMIにてステント留置"),
    ("慢性腎臓病の患者", "CKDステージ4"),
    (HT, "併存症として高血圧症がありますが、特記すべき家族歴はありません。"),
    # a criterion in one language, the note in another (the cascade's bilingual terms table): CI's rerun test found
    # the synthetic site's gout flare read as an inference
    (
        "Acute gout flare ongoing at screening (within 14 days).",
        "目前右側第一蹠趾關節急性紅腫熱痛，診斷為急性痛風發作中。",
    ),
    ("Active tuberculosis", "肺結核治療中"),
    ("痛風の既往", "history of gout, on allopurinol"),
]
OUT_OF_SCOPE = [  # the value or the drug is what the line asks about
    ("ALT > 3x ULN", "ALT 250 U/L"),
    ("eGFR < 30 mL/min", "eGFR 22"),
    ("Use of systemic corticosteroids", "prednisone 20 mg daily"),
    ("ワルファリン服用中の患者", "ワーファリン内服中"),
]


@pytest.mark.parametrize(("criterion", "quote"), INFERRED)
def test_a_quote_that_states_no_diagnosis_is_an_inference(criterion: str, quote: str) -> None:
    assert inferred(quote, criterion)


@pytest.mark.parametrize(("criterion", "quote"), STATED)
def test_a_quote_that_states_the_condition_is_not(criterion: str, quote: str) -> None:
    assert not inferred(quote, criterion) and names_condition(quote, criterion)


@pytest.mark.parametrize(("criterion", "quote"), OUT_OF_SCOPE)
def test_a_criterion_that_is_a_value_or_a_drug_is_out_of_scope(criterion: str, quote: str) -> None:
    assert not inferred(quote, criterion)


def _map(kind: str, criterion: str, question: str, quote: str, affirmed: bool = True) -> object:
    c = _ir("N-EXC-09" if kind == "exclusion" else "N-INC-09", kind, "note", {"domain": "condition",
            "valueset": "VS_X"}, text=criterion, note_question=question)  # fmt: skip
    run = _run_for_map(True)
    # a pair of judge v6 that affirmed the quote (round 5, #639 7115208555): the guard is what these tests read
    reply = JudgeReply("pass", 0.95, quote, None, "from the notes", affirmed=affirmed)
    return run._map(c, reply, {**SPAN, "quote": quote}, "S3")


def test_an_exclusion_present_on_an_inference_goes_to_review_never_out() -> None:
    o = _map("exclusion", HT, HT_Q, INFERRED[0][1])
    assert o.status == "unknown" and not o.hard and o.reason.startswith("inferred")  # type: ignore[attr-defined]


def test_an_exclusion_present_on_a_stated_condition_still_excludes() -> None:
    o = _map("exclusion", HT, HT_Q, STATED[0][1])
    assert o.status == "fail" and o.hard  # type: ignore[attr-defined]
    unsaid = _map("exclusion", HT, HT_Q, STATED[0][1], affirmed=False)  # round 5: not affirmed by both models
    assert unsaid.status == "unknown" and not unsaid.hard  # type: ignore[attr-defined]


def test_the_note_question_is_not_the_condition() -> None:
    """Its filler (があります) once read as the condition: the jmed metformin reply was kept as a hard fail."""
    quote = "降圧薬、スタチン、メトホルミンを服用していますが、服薬のタイミングを時々忘れることがあります。"
    o = _map("exclusion", DM, DM_Q, quote)
    assert o.status == "unknown" and o.reason.startswith("inferred")  # type: ignore[attr-defined]


def test_an_inclusion_is_never_affected() -> None:
    o = _map("inclusion", HT, HT_Q, INFERRED[0][1])
    assert o.status == "pass"  # type: ignore[attr-defined]
