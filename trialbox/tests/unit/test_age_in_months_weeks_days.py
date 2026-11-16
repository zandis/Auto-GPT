"""F3 of the integrator's root-cause review of the P1b run (#639, 2026-11-16), D-947: NCT01260883 INC-01 "2-18 months"
came out of ir_extract as age 2 to 18 (years, with a stray sex female), mixed, no flag; EXC-05 "<36 weeks gestation"
as ``age.max 36`` on a condition atom. The age is complete years (D-442).

* A criterion whose age the line writes in months, weeks or days (か月, ヵ月, 週, 日齢, 個月, 个月, 天 too) is never
  compiled, flagged ``age_unit_not_years``: a mixed one keeps its note question and the notes decide, any other goes
  to a person.
* An age in years beside a duration in months ("18 or older ... for 12 months") is left alone.

Public protocol text; no patient rows.
"""

from __future__ import annotations

from typing import Any

import pytest
from criteria_compiler.ir_extract import postprocess as pp
from criteria_compiler.terminology.mapper import Terminology
from tb_contracts import LlmExtractOutput


def _one(text: str, logic: dict[str, Any], kind: str = "inclusion", cls: str = "structured",
         concepts: list[dict[str, str]] | None = None) -> Any:  # fmt: skip
    crit = {"kind": kind, "class": cls, "text": text, "logic": logic, "concept_candidates": concepts or []}
    if cls == "mixed":
        crit["note_question"] = "Is the patient within the age range?"
    (c,) = pp.postprocess("T", LlmExtractOutput.model_validate({"criteria": [crit]}), Terminology(), "1.0.0").criteria
    return c


def test_p1b_nct01260883_inc01_2_to_18_months_is_not_runnable() -> None:
    c = _one("Infants aged 2-18 months", {"op": "and", "args": [
        {"domain": "demographic", "age": {"min": 2, "max": 18}}, {"domain": "demographic", "sex": "female"}]},
        cls="mixed")  # fmt: skip
    assert c.class_ == "note" and c.note_question  # never compiled; its note question is kept (D-98)
    assert {"age_unit_not_years", "needs_review"} <= set(c.flags or [])


def test_p1b_nct01260883_exc05_36_weeks_gestation_is_not_runnable() -> None:
    c = _one("Born at <36 weeks gestation", {"domain": "condition", "concept": "Preterm birth", "age": {"max": 36}},
             kind="exclusion", concepts=[{"name": "Preterm birth", "domain": "condition"}])  # fmt: skip
    assert c.class_ == "human" and "age_unit_not_years" in (c.flags or [])


@pytest.mark.parametrize(
    ("text", "age"),
    [("生後6か月以上", {"min": 6}), ("6ヶ月から24ヶ月", {"min": 6, "max": 24}), ("出生後28日以内", {"max": 28}),
     ("年齡6個月以上", {"min": 6}), ("Age 6 weeks or older", {"min": 6}), ("aged 30 days to 2 years", {"min": 30}),
     # adversarial review of D-947: spellings, words, compound ages, rounded and strict bounds
     ("6〜24ヵ月", {"min": 6, "max": 24}), ("2歳6ヵ月以上", {"min": 2}), ("6个月以上", {"min": 6}),
     ("6-month-old infants", {"min": 6}), ("six months or older", {"min": 6}), ("1 year 6 months or older", {"min": 1}),
     ("aged 6 months - 17 years", {"min": 0, "max": 17}), ("生後6カ月以上", {"min": 6}), ("28日齢", {"min": 28}),
     ("Born at <36 weeks gestation", {"max": 35}), ("6 mths", {"min": 6}), ("between 6 and 24 months", {"min": 6})],
)  # fmt: skip
def test_an_age_in_months_weeks_or_days_goes_to_a_person(text: str, age: dict[str, float]) -> None:
    c = _one(text, {"domain": "demographic", "age": age})
    assert c.class_ == "human" and "age_unit_not_years" in (c.flags or []), text


@pytest.mark.parametrize(
    ("text", "age"),
    [("Aged 18 or older, able to attend for 12 months", {"min": 18}), ("18歳以上", {"min": 18}),
     ("Age 2 to 17 years", {"min": 2, "max": 17}),
     # the review's false positives: a duration beside an age in years, a date, "weekly"
     ("Aged 18 or older; contraception for 18 months", {"min": 18}), ("Aged 18-75; 18 days washout", {"min": 18}),
     ("Age 18 to 65 years, HbA1c within 18 weeks", {"min": 18, "max": 65}), ("年齡20歲以上，20天內", {"min": 20}),
     ("age 1 to 17 years; within 1 month of screening", {"min": 1, "max": 17}),
     ("aged 65 years or older, 65 days post-op", {"min": 65}), ("20歳以上 2026年1月20日", {"min": 20}),
     ("16 weekly", {"min": 16}), ("18歳以上（同意取得日）", {"min": 18})],
)  # fmt: skip
def test_an_age_in_years_is_left_alone(text: str, age: dict[str, float]) -> None:
    c = _one(text, {"domain": "demographic", "age": age})
    assert c.class_ == "structured" and "age_unit_not_years" not in (c.flags or []), text
