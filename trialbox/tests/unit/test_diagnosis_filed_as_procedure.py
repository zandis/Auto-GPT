"""Red of lane G's accuracy run (#639, 2026-11-15), item 4: tcga's criterion filed "invasive breast carcinoma" under
the procedure domain, so its list was searched among procedures and could never match a diagnosis.

The post-process now re-files a concept the model put under ``procedure`` whose name is a diagnosis (carcinoma,
cancer, tumour, lymphoma, disease, ...; がん, 癌, 腫瘍, 病; and no operation word such as -ectomy, resection, surgery,
手術, 切除) under ``condition``: the value set is mapped as a condition and the atom reads the diagnoses. The criterion
is flagged ``domain_refiled`` and ``needs_review``, and the compile warning names it. A real procedure stays where it
is. Synthetic extraction output.
"""

from __future__ import annotations

from typing import Any

import pytest
from criteria_compiler.ir_extract.postprocess import is_diagnosis_name, postprocess
from criteria_compiler.terminology.mapper import Terminology
from tb_contracts import LlmExtractOutput


def _crit(concept: str, domain: str) -> dict[str, Any]:
    return {"text": concept, "kind": "inclusion", "class": "structured",
            "logic": {"domain": domain, "concept": concept, "quantifier": "any"},
            "concept_candidates": [{"domain": domain, "name": concept}]}  # fmt: skip


def test_a_diagnosis_filed_as_a_procedure_is_refiled_and_flagged() -> None:
    post = postprocess(
        "TCGA",
        LlmExtractOutput.model_validate(
            {
                "criteria": [
                    _crit("invasive breast carcinoma", "procedure"),
                    _crit("mastectomy", "procedure"),
                    _crit("乳癌", "procedure"),
                    _crit("gout", "condition"),
                ]
            }
        ),
        Terminology(),
    )
    c1, c2, c3, c4 = post.criteria
    assert getattr(c1.logic, "domain", None) == "condition" and getattr(c3.logic, "domain", None) == "condition"
    assert {"domain_refiled", "needs_review"} <= set(c1.flags or []) and "domain_refiled" in (c3.flags or [])
    assert getattr(c2.logic, "domain", None) == "procedure" and "domain_refiled" not in (c2.flags or [])
    assert "domain_refiled" not in (c4.flags or [])
    assert any("TCGA-INC-01" in w and "condition" in w for w in post.warnings)


@pytest.mark.parametrize(
    ("name", "yes"),
    [("invasive breast carcinoma", True), ("non-small cell lung cancer", True), ("Hodgkin lymphoma", True),
     ("chronic kidney disease", True), ("胃がん", True), ("乳癌", True), ("脳腫瘍", True),
     ("mastectomy", False), ("tumour resection", False), ("cancer surgery", False), ("胃癌手術", False),
     ("chest x-ray", False), ("bariatric surgery", False)],
)  # fmt: skip
def test_what_counts_as_a_diagnosis_name(name: str, yes: bool) -> None:
    assert is_diagnosis_name(name) is yes
