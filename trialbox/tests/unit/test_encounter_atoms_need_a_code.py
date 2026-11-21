"""G2 of the integrator's second review of the P1b run (#639, 2026-11-16), D-957: four protocols (NCT00439478,
NCT00674726, NCT01829659, NCT01855594) failed equivalence on the FHIR server's refusal of a compiled ``encounter``
atom: the model filed diagnoses as encounters ("acute appendicitis", "atrial fibrillation", "major depressive
disorder") and the CQL asked ``X.serviceType in`` a ValueSet with no code.

* A diagnosis filed as an encounter is read as a condition, as one filed as a procedure is (``domain_refiled``).
* An encounter type with no code on the box is not compiled (``logic_invalid``): a person reads it, or the notes when
  the criterion is mixed and they can settle it (D-954).

The run's own lines (public SIGIR protocols); no patient rows.
"""

from __future__ import annotations

from typing import Any

import pytest
from criteria_compiler.ir_extract import postprocess as pp
from criteria_compiler.semantics import atoms
from criteria_compiler.terminology.mapper import Terminology
from tb_contracts import LlmExtractOutput


def _one(text: str, concept: str, kind: str = "inclusion") -> Any:
    crit = {"kind": kind, "class": "structured", "text": text,
            "logic": {"domain": "encounter", "concept": concept, "quantifier": "any"},
            "concept_candidates": [{"name": concept, "domain": "encounter"}]}  # fmt: skip
    (c,) = pp.postprocess(
        "T",
        LlmExtractOutput.model_validate({"criteria": [crit]}),
        Terminology(),
        "1.0.0",
        sources=[pp.PresenceSource(text, kind, "en")],
    ).criteria
    return c


@pytest.mark.parametrize(
    ("text", "concept"),
    [("Patients with acute appendicitis", "acute appendicitis"),
     ("Other acute abdominal diseases", "acute abdominal disease"),
     ("The diagnosis of MDD consistent with DSM-IV (M.I.N.I)", "major depressive disorder")],
)  # fmt: skip
def test_a_diagnosis_filed_as_an_encounter_is_read_as_a_condition(text: str, concept: str) -> None:
    c = _one(text, concept)
    assert c.logic is not None and {a.domain for a in atoms(c.logic)} == {"condition"}, text
    assert "domain_refiled" in (c.flags or [])


@pytest.mark.parametrize(
    ("text", "concept"),
    [("Current hospitalization for COPD exacerbation", "hospitalization"),
     ("Any history of hemorrhagic stroke.", "hemorrhagic stroke")],  # not named a diagnosis: still never compiled
)  # fmt: skip
def test_an_encounter_type_with_no_code_is_not_compiled(text: str, concept: str) -> None:
    c = _one(text, concept)
    assert c.class_ == "human" and "logic_invalid" in (c.flags or [])
    assert c.logic is not None and not any(a.domain == "encounter" for a in atoms(c.logic))
