"""Deep review 2026-11-13 (screening, SCR-04), negation (D-657): a chart's negated mention never becomes the patient's
proposed diagnosis. "悪性腫瘍なし" read as C80.1 waited for one Confirm tap to exclude the patient. The guard binds the
negation to the fact's own term in its own clause, so a negated neighbour ("糖尿病なし、高血圧あり") and a word that
only looks negative ("非小細胞肺癌", "無症候性") leave the fact standing. Synthetic text only.
"""

from __future__ import annotations

from typing import Any

import pytest
from sitesetup.charts import normalise


def _cond(term: str, quote: str, code: str = "C80.1") -> dict[str, Any]:
    return {"domain": "condition", "term": term, "code": code, "system": "icd10cm", "value": "", "unit": "",
            "date": "", "quote": quote}  # fmt: skip


NEGATED = [
    ("悪性腫瘍", "悪性腫瘍なし"),
    ("悪性腫瘍", "悪性腫瘍：なし"),
    ("悪性腫瘍", "既往歴：悪性腫瘍 無し"),
    ("高血圧", "高血圧（－）"),
    ("高血圧", "高血圧(-)"),
    ("高血圧", "高血圧の既往なし"),
    ("糖尿病", "糖尿病は認めず"),
    ("悪性腫瘍", "悪性腫瘍は否定的"),
    ("肝炎", "B型肝炎 陰性"),
    ("hypertension", "No history of hypertension"),
    ("gout", "Patient denies gout."),
    ("malignancy", "negative for malignancy"),
    ("cancer", "Cancer ruled out."),
    ("糖尿病", "糖尿病（なし）"),
    ("悪性腫瘍", "悪性腫瘍は特になし"),
    ("高血圧", "高血圧ではない"),
    ("高血圧", "高血圧はありません"),
    ("高血圧", "高血圧を認めない"),
    ("高血圧", "高血圧は認められない"),
    ("高血圧", "高血圧は無い"),
    ("高血圧", "高血圧はなかった"),
    ("悪性腫瘍", "悪性腫瘍無"),
    ("悪性腫瘍", "悪性腫瘍の既往無"),
    ("diabetes", "diabetes - no"),
    ("痛風", "痛風(ｰ)"),
    ("malignancy", "no known malignancy"),
    ("diabetes", "no hypertension or diabetes"),
    ("diabetes", "denies hypertension or diabetes"),
    ("糖尿病", "否認高血壓及糖尿病"),
    ("diabetes", "no-diabetes"),
    ("gout", "not gout"),
    ("gout", "Gout absent"),
    ("gout", "free of gout"),
    ("gout", "never had gout"),
    ("hypertension", "no hypertension, no diabetes"),
    ("高血壓", "否認高血壓"),
    ("糖尿病", "無糖尿病"),
    ("糖尿病", "沒有糖尿病"),
    ("痛風", "未見痛風發作"),
]

KEPT = [
    ("乳癌", "乳癌（2019年手術）"),
    ("非小細胞肺癌", "非小細胞肺癌 stage IV"),
    ("肺癌", "非小細胞肺癌 stage IV"),
    ("高尿酸血症", "無症候性高尿酸血症"),
    ("高血圧", "糖尿病なし、高血圧あり"),
    ("gout", "gout, no tophi"),
    ("hypertension", "hypertension; denies chest pain"),
    ("痛風", "痛風発作あり。腎結石なし"),
    ("gout", "Gout flare in March"),
    ("breast cancer", "breast cancer, no recurrence"),
    # the review's missed exclusions: a cue that does not end its clause, or a word that only starts like one
    ("高血圧", "高血圧ないし糖尿病"),
    ("高血圧", "高血圧 ない時もある"),
    ("糖尿病", "糖尿病がないとは言えない"),
    ("高血圧", "高血圧なし→あり"),
    ("痛風", "痛風(-)→(+)"),
    ("痛風", "痛風否定できず"),
    ("痛風", "痛風は否定できない"),
    ("痛風", "痛風なしではない"),
    ("diabetes", "diabetes negative urine glucose"),
    ("肝炎", "C型肝炎 陰性化 (SVR)"),
    ("gout", "no chest pain and gout"),
]


@pytest.mark.parametrize(("term", "quote"), NEGATED)
def test_a_negated_mention_is_not_a_fact(term: str, quote: str) -> None:
    assert normalise(_cond(term, quote)) is None


@pytest.mark.parametrize(("term", "quote"), KEPT)
def test_the_patients_own_mention_stands(term: str, quote: str) -> None:
    got = normalise(_cond(term, quote))
    assert got is not None and got["domain"] == "condition" and got["status"] == "proposed"


@pytest.mark.parametrize(
    ("term", "quote"),
    [
        ("malignant neoplasm", "悪性腫瘍なし"),
        ("breast cancer", "乳癌術後 再発なし"),
        ("diabetes", "糖尿病あり 高血圧なし"),
        ("2型糖尿病", "Type 2 DM on metformin. HTN: none. Cancer: なし"),
        ("痛風", "Gout confirmed. Malignancy (-)"),
    ],
)
def test_a_term_the_quote_does_not_hold_is_kept_for_a_person(term: str, quote: str) -> None:
    """The model's term may be its own wording or language. Without the term in the quote nothing binds a negation to
    the fact, so the fact stays proposed and a person reads the quote (review of D-657: dropping it lost real
    diagnoses)."""
    assert normalise(_cond(term, quote)) is not None
