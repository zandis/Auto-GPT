"""Deep review 2026-11-13 (screening, SCR-04), family history (D-658): a relative's diagnosis in a chart is never the
patient's proposed diagnosis. "家族歴：母 乳癌" came back as the patient's C50.9, one Confirm tap from excluding them.
The guard binds the relative to the fact's own term: a relative named before the term in its clause, or a family
history heading that reaches the term within its sentence. "乳癌（2019年）、母：糖尿病" holds 母 and the patient's own
cancer: the cancer stays. Synthetic text only.
"""

from __future__ import annotations

from typing import Any

import pytest
from sitesetup.charts import normalise


def _cond(term: str, quote: str, code: str = "C50.9") -> dict[str, Any]:
    return {"domain": "condition", "term": term, "code": code, "system": "icd10cm", "value": "", "unit": "",
            "date": "", "quote": quote}  # fmt: skip


RELATIVES = [
    ("乳癌", "家族歴：母 乳癌"),
    ("胃癌", "家族歴：母 乳癌、父 胃癌"),
    ("糖尿病", "乳癌（2019年）、母：糖尿病"),
    ("大腸癌", "父が大腸癌で死亡"),
    ("高血圧", "祖母の高血圧"),
    ("痛風", "兄：痛風"),
    ("乳癌", "家族史：母親 乳癌"),
    ("糖尿病", "父親 糖尿病"),
    ("breast cancer", "Family history: mother, breast cancer"),
    ("breast cancer", "Mother had breast cancer at 52"),
    ("gout", "FH: gout in father"),
    ("diabetes", "family history of diabetes"),
    ("colon cancer", "Father: colon cancer"),
    ("胃癌", "家族歴 父 胃癌"),
    # the review's missed relatives
    ("CRC", "family hx: CRC in father"),
    ("diabetes", "Fam hx: diabetes (mother)"),
    ("diabetes", "FamHx: diabetes"),
    ("乳癌", "姐姐乳癌"),
    ("乳癌", "母親罹患乳癌"),
    ("乳癌", "母亲患乳癌"),
    ("痛风", "父亲：痛风"),
    ("痛风", "母亲 痛风"),
    ("胃癌", "患者の父 胃癌"),
    ("胃癌", "父方祖母 胃癌"),
    ("胃癌", "母方の祖父 胃癌"),
    ("痛風", "実母：痛風"),
    ("痛風", "長男：痛風"),
    ("痛風", "夫：痛風"),
    ("痛風", "妻 痛風"),
    ("gout", "Wife has gout"),
    ("gout", "Husband: gout"),
    ("gout", "Children: gout"),
    ("gout", "Sibs: gout"),
    ("breast cancer", "Sister (deceased) – breast cancer"),
    ("MI", "Uncle w/ MI"),
    ("MI", "Family history: MI in father"),
    ("DM", "Family: DM in mother"),
]

KEPT = [
    ("乳癌", "乳癌（2019年）、母：糖尿病"),
    ("乳癌", "乳癌（2019年手術）"),
    ("子宮癌", "子宮癌 2015年"),
    ("乳癌", "家族歴：特記なし。既往歴：乳癌（2019年）"),
    ("breast cancer", "breast cancer, like her mother"),
    ("gout", "Gout. Lives with her mother."),
    ("胃癌", "母乳育児歴あり、胃癌（2020年）"),
    ("hypertension", "PMH: hypertension. FH: diabetes in mother"),
    # the review's dropped own diagnoses: an own-history heading, the patient as subject, an empty family history
    ("糖尿病", "家族歴：父 高血圧 既往歴：糖尿病"),
    ("乳癌", "家族歴 母 乳癌 既往歴 乳癌"),
    ("hypertension", "Family History: Mother - HTN Past Medical History: hypertension"),
    ("胃癌", "母 胃癌の疑い→本人 胃癌"),
    ("痛風", "父：特記なし 痛風"),
    ("diabetes", "Her mother and she both have diabetes"),
    ("gout", "Patient and his father have gout"),
    ("gout", "Mother has diabetes and the patient has gout"),
    ("gout", "Lives with mother and has gout"),
    ("gout", "Diabetes in mother and gout"),
    ("高血压", "家族史：无，高血压10年"),
    ("高血圧", "家族歴：なし 高血圧（2015年〜）"),
    ("高血圧", "家族歴：特記事項なし、高血圧で内服中"),
    ("diabetes", "Family history noncontributory, diabetes on metformin"),
    ("hypertension", "FH: none Dx: hypertension"),
    ("糖尿病", "家族歴：なし 診断：糖尿病"),
    ("糖尿病", "家族史：无 现病史：糖尿病"),
    ("diabetes", "Family history positive for diabetes; personal history of diabetes"),
    ("hypercholesterolemia", "FH: familial hypercholesterolemia, on rosuvastatin"),
    # a term the quote does not hold binds no relative: the fact stays for a person
    ("breast cancer", "乳癌（2019年） 母：糖尿病"),
    ("gout", "痛風 父：高血圧"),
    ("familial hypercholesterolemia", "FH: on statin"),
]


@pytest.mark.parametrize(("term", "quote"), RELATIVES)
def test_a_relatives_diagnosis_is_not_the_patients_fact(term: str, quote: str) -> None:
    assert normalise(_cond(term, quote)) is None


@pytest.mark.parametrize(("term", "quote"), KEPT)
def test_the_patients_own_diagnosis_stands(term: str, quote: str) -> None:
    got = normalise(_cond(term, quote))
    assert got is not None and got["domain"] == "condition" and got["status"] == "proposed"
