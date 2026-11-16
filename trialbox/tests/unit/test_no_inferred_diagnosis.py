"""F6 of the integrator's root-cause review of the P1b run (#639, 2026-11-16), D-985: a note exclusion decided by
inferring a diagnosis. On jmed both models agreed four times that a patient "has a history of hypertension" (or
diabetes) from a quote naming only an antihypertensive (or metformin); on sigir NCT01784523 the judge counted
findings into SLE. ``both_agree`` does not protect against a shared inference.

* An exclusion's "present" stands only on a verified quote that states the condition (the criterion's own words, or a
  diagnosis word); one that names a drug, a value or findings is an inference: unknown, to review, never a hard fail.
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
    ("SLE Diagnosis based on the ACR criteria",
     "On examination she is found to have alopecia, a rash mainly distributed on the butterfly area of the face."),
]  # fmt: skip
STATED = [
    (HT, "BMI28.3の肥満と軽度の高血圧があり、内科で生活習慣指導を受けています。"),
    (DM, "併存症として高血圧と2型糖尿病があります。"),
    (DM, "高血圧と2型糖尿病という併存疾患があり、血糖・血圧は薬物で管理されています。"),
    ("History of type 2 diabetes", "Known diabetic on metformin 500 mg twice daily."),
]


@pytest.mark.parametrize(("criterion", "quote"), INFERRED)
def test_a_quote_that_states_no_diagnosis_is_an_inference(criterion: str, quote: str) -> None:
    assert inferred(quote, criterion)


@pytest.mark.parametrize(("criterion", "quote"), STATED)
def test_a_quote_that_states_the_condition_is_not(criterion: str, quote: str) -> None:
    assert not inferred(quote, criterion) and (names_condition(quote, criterion) or "疾患" in quote or "Known" in quote)


def _map(kind: str, criterion: str, question: str, quote: str) -> object:
    c = _ir("N-EXC-09" if kind == "exclusion" else "N-INC-09", kind, "note", {"domain": "condition",
            "valueset": "VS_X"}, text=criterion, note_question=question)  # fmt: skip
    run = _run_for_map(True)
    return run._map(c, JudgeReply("pass", 0.95, quote, None, "from the notes"), {**SPAN, "quote": quote}, "S3")


def test_an_exclusion_present_on_an_inference_goes_to_review_never_out() -> None:
    o = _map("exclusion", HT, HT_Q, INFERRED[0][1])
    assert o.status == "unknown" and not o.hard and o.reason.startswith("inferred")  # type: ignore[attr-defined]


def test_an_exclusion_present_on_a_stated_condition_still_excludes() -> None:
    o = _map("exclusion", HT, HT_Q, STATED[0][1])
    assert o.status == "fail" and o.hard  # type: ignore[attr-defined]


def test_an_inclusion_is_never_affected() -> None:
    o = _map("inclusion", HT, HT_Q, INFERRED[0][1])
    assert o.status == "pass"  # type: ignore[attr-defined]
