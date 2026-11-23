"""The FHIR-store copy of a compiled ValueSet (``tb_common.fhir.store_valueset``): expanded already, from its own
codes, so a store with no code system loaded evaluates it; one with no code lists only a code no record carries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from criteria_compiler.terminology.mapper import Terminology, valueset
from tb_common.fhir import NO_MEMBER, FhirEvaluator, store_valueset

ROOT = Path(__file__).resolve().parents[2]
GOUT = ROOT / "rulesets/GZQO/valuesets/VS_GOUT.json"


def _codes(vs: dict[str, Any]) -> list[tuple[str, str]]:
    return [(c["system"], c["code"]) for c in vs["expansion"]["contains"]]


def test_a_shipped_value_set_is_given_expanded_from_its_own_codes() -> None:
    vs = json.loads(GOUT.read_text("utf-8"))
    out = store_valueset(vs)
    listed = [(i["system"], c["code"]) for i in vs["compose"]["include"] for c in i["concept"]]
    assert _codes(out) == listed and out["expansion"]["total"] == len(listed) > 0
    assert out["compose"] == vs["compose"] and out["url"] == vs["url"] and out["version"] == vs["version"]
    assert "expansion" not in vs  # the ruleset's own ValueSet is not changed


def test_a_value_set_with_no_code_lists_only_a_code_no_record_carries() -> None:
    res = Terminology().map("condition", "synthetic qwerty zxcv syndrome")
    assert res.method == "none" and not res.concepts
    vs = json.loads(json.dumps(valueset("SYN", "VS_UNMAPPED", "unmapped", res.concepts, "1.0.0", True)))
    out = store_valueset(vs)
    assert _codes(out) == [(NO_MEMBER["system"], NO_MEMBER["code"])]
    assert [(i["system"], c["code"]) for i in out["compose"]["include"] for c in i["concept"]] == _codes(out)
    assert NO_MEMBER["system"].startswith("https://trialbox.local/fhir/CodeSystem/")


def test_a_value_set_that_is_not_a_plain_list_is_given_as_it_is() -> None:
    filtered = {"resourceType": "ValueSet", "id": "F", "compose": {"include": [
        {"system": "http://hl7.org/fhir/sid/icd-10-cm", "filter": [{"property": "concept", "op": "is-a", "value": "M10"}]}
    ]}}  # fmt: skip
    expanded = {"resourceType": "ValueSet", "id": "E", "expansion": {"timestamp": "2026-01-01T00:00:00+00:00",
                                                                    "contains": [{"system": "s", "code": "c"}]}}  # fmt: skip
    whole = {"resourceType": "ValueSet", "id": "W", "compose": {"include": [{"system": "http://www.whocc.no/atc"}]}}
    assert store_valueset(filtered) is filtered and store_valueset(expanded) is expanded
    assert store_valueset(whole) is whole  # every code of a system: not "no code"


class Recording(FhirEvaluator):
    def __init__(self) -> None:
        super().__init__("http://fhir.invalid/fhir")
        self.sent: list[dict[str, Any]] = []

    def put(self, resource: dict[str, Any]) -> None:
        self.sent.append(resource)


def test_load_puts_the_store_copy() -> None:
    fh = Recording()
    vs = json.loads(GOUT.read_text("utf-8"))
    fh.load([{"resourceType": "Library", "id": "L"}], [vs])
    assert fh.sent[0]["id"] == vs["id"] and fh.sent[0]["expansion"]["contains"] and fh.sent[1]["id"] == "L"
