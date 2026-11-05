"""Offline checks of the public-data validation tools (TREC CT, MedTxt, hospital simulation): no network, no model."""

from __future__ import annotations

import random

import pytest

from tools import medtxt_eval, trec_ct_eval
from tools.trec_ct_eval import age_sex_filter, cluster_ci, ct_age, patient_age_sex, wilson


@pytest.mark.parametrize(
    ("text", "age", "sex"),
    [
        ("Patient is a 45-year-old man with a history of astrocytoma.", 45, "MALE"),
        ("A 32 yo woman presents with fever. She is pregnant.", 32, "FEMALE"),
        ("The patient is a 9-month-old boy with cough.", 0.75, "MALE"),
        ("Patient with chest pain.", None, None),
        ("48 M with a h/o HTN who presented with SOB.", 48, "MALE"),
        ("79 yo F with chronic hypoxemia.", 79, "FEMALE"),
    ],
)
def test_patient_age_sex(text: str, age: float | None, sex: str | None) -> None:
    a, s = patient_age_sex(text)
    assert (a if a is None else round(a, 2)) == age
    assert s == sex


def test_ct_age_units() -> None:
    assert ct_age("18 Years") == 18
    assert ct_age("6 Months") == 0.5
    assert ct_age(None) is None
    assert ct_age("N/A") is None


def test_age_sex_filter_never_blocks_on_missing_data() -> None:
    f = {"min_age": "18 Years", "max_age": "65 Years", "sex": "FEMALE"}
    assert age_sex_filter(f, "A 70-year-old woman.") == "block"
    assert age_sex_filter(f, "A 40-year-old man.") == "block"
    assert age_sex_filter(f, "A 40-year-old woman.") == "pass"
    assert age_sex_filter(f, "Patient with diabetes.") == "pass"  # age and sex unstated: no block
    assert age_sex_filter(None, "A 70-year-old woman.") == "unknown"
    # neonatal limits in weeks are often gestational age: never decided from postnatal age
    assert age_sex_filter({"min_age": "30 Weeks", "max_age": "35 Weeks", "sex": "ALL"}, "A 3-day-old girl.") == "pass"


def test_wilson_bounds() -> None:
    lo, hi = wilson(8, 79)
    assert 0.05 < lo < 0.1013 < hi < 0.19
    assert wilson(0, 0) == (0.0, 1.0)
    lo0, hi0 = wilson(0, 100)
    assert lo0 == 0.0 and 0.03 < hi0 < 0.04


def test_cluster_ci_contains_rate_and_is_seeded() -> None:
    rng = random.Random(1)
    flags = [(f"p{i % 30}", rng.random() < 0.1) for i in range(600)]
    a, b = cluster_ci(flags), cluster_ci(flags)
    k = sum(f for _, f in flags) / len(flags)
    assert a == b and a[0] <= k <= a[1]


def test_trec_note_split() -> None:
    assert trec_ct_eval.note("A 45-year-old man. He has HTN. BP 140/90.") == [
        "A 45-year-old man.",
        "He has HTN.",
        "BP 140/90.",
    ]


def test_medtxt_sentences_strip_tags() -> None:
    raw = '症例は<timex3 type="age">７０歳</timex3>，男性．\n<d certainty="negative">発熱</d>は認めなかった．'
    assert medtxt_eval.sentences(raw, "ja") == ["症例は７０歳，男性．", "発熱は認めなかった．"]
    en = 'A <d certainty="negative">fever</d> was not seen. CT was done.'
    assert medtxt_eval.sentences(en, "en") == ["A fever was not seen.", "CT was done."]


def test_medtxt_criterion_is_an_exclusion() -> None:
    p = medtxt_eval.criterion({"id": "CR:1|0", "report": "CR:1", "finding": "hemoptysis", "certainty": "positive"})
    assert p.criterion_type == "exclusion" and p.criterion == "Patients with hemoptysis."
