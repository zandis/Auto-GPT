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
    ("cancer", "Cancer ruled out last year"),
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
]


@pytest.mark.parametrize(("term", "quote"), NEGATED)
def test_a_negated_mention_is_not_a_fact(term: str, quote: str) -> None:
    assert normalise(_cond(term, quote)) is None


@pytest.mark.parametrize(("term", "quote"), KEPT)
def test_the_patients_own_mention_stands(term: str, quote: str) -> None:
    got = normalise(_cond(term, quote))
    assert got is not None and got["domain"] == "condition" and got["status"] == "proposed"


def test_a_term_the_quote_does_not_hold_is_judged_on_the_whole_quote() -> None:
    """The model's term may be its own wording ("malignant neoplasm" for 悪性腫瘍): then the quote as a whole decides,
    and a quote that is one negated clause is no fact."""
    assert normalise(_cond("malignant neoplasm", "悪性腫瘍なし")) is None
    assert normalise(_cond("malignant neoplasm", "悪性腫瘍（2018年）")) is not None
