"""G1 of the integrator's second review of the P1b run (#639, 2026-11-16), D-955: ``vs_resource_id`` built
``<ruleset>-<name>`` (14 + up to 60 characters); the FHIR server refuses an id over 64 with HTTP 422, and all 12 of the
run's protocols with such an id failed (none of the 63 screened had one).

* Every ValueSet id is a FHIR id, ``[A-Za-z0-9.-]{1,64}``, whatever the ruleset and the concept.
* Two different long names never share an id; the same name always gets the same one.
* An id that fitted before is unchanged (the shipped rulesets: ``build_rulesets --check``).
"""

from __future__ import annotations

import re

import pytest
from criteria_compiler.terminology.mapper import Concept, valueset, vs_name_for, vs_resource_id

FHIR_ID = re.compile(r"[A-Za-z0-9.\-]{1,64}")


@pytest.mark.parametrize("ruleset", ["SM2NCT01260883", "GZQO", "Mm2JMED-HT", "A" * 70])
@pytest.mark.parametrize(
    "concept",
    ["Histologically confirmed esophageal squamous cell carcinoma stage T2-3 Nx M0 " * 3, "x" * 200,
     "食道扁平上皮癌" * 30, "gout"],
)  # fmt: skip
def test_every_valueset_id_is_a_fhir_id(ruleset: str, concept: str) -> None:
    rid = vs_resource_id(ruleset, vs_name_for(concept))
    assert FHIR_ID.fullmatch(rid), rid
    vs = valueset(ruleset, vs_name_for(concept), concept, [Concept("http://snomed.info/sct", "1", concept)], "1.0.0")
    assert vs["id"] == rid and vs["url"].endswith("/" + rid)


def test_long_ids_are_unique_and_stable() -> None:
    a = vs_resource_id("SM2NCT01260883", "VS_" + "A" * 55 + "_ONE")
    b = vs_resource_id("SM2NCT01260883", "VS_" + "A" * 55 + "_TWO")
    assert a != b and len(a) == len(b) <= 64
    assert a == vs_resource_id("SM2NCT01260883", "VS_" + "A" * 55 + "_ONE")


def test_an_id_that_fitted_is_unchanged() -> None:
    assert vs_resource_id("GZQO", "VS_GOUT") == "GZQO-VS-GOUT"
