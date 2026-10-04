"""TWPAS bundle builder, validator result parsing, SUBMIT helpers and the submissions table (SPEC §9.5, §8.4)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
import tb_contracts as c
from adapter.validate.validator import Hl7Validator
from orchestrator.clients import StepFailed
from orchestrator.db import JobDB
from orchestrator.reports import twpas_bundle as tb
from orchestrator.scenarios import submit
from tb_contracts import dump

INP = tb.TwpasInput(
    pid="a" * 32,
    mrn="10000020",
    name="王小明",
    national_id="A123456789",
    gender="male",
    birth_date="1960-01-01",
    practitioner_id="P78901",
    practitioner_license="DEMO-MD-0003",
    org_id="0101090517",
    org_name="示範醫院A",
    department="ONC",
    run_date=date(2026, 10, 5),
    diagnosis_code="C34.11",
    diagnosis_date="2026-01-01",
    weight_kg=62.4,
    height_cm=168.6,
    drug_code="BC26968100",
    program_text="ONC-OSI",
    egfr_positive=True,
    egfr_date="2026-02-01",
    ecog=1,
    ecog_date="2026-09-20",
    summary="NSCLC C34.11",
)


def _by_type(bundle: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for e in bundle["entry"]:
        out.setdefault(e["resource"]["resourceType"], []).append(e["resource"])
    return out


def _refs(node: Any) -> list[str]:
    if isinstance(node, dict):
        own = [node["reference"]] if isinstance(node.get("reference"), str) else []
        return own + [r for v in node.values() for r in _refs(v)]
    if isinstance(node, list):
        return [r for v in node for r in _refs(v)]
    return []


def test_bundle_shape_and_references_resolve() -> None:
    b = tb.build(INP)
    assert b["resourceType"] == "Bundle" and b["type"] == "collection"
    assert b["meta"]["profile"][0].endswith("/Bundle-twpas")
    res = _by_type(b)
    for t in ("Claim", "Encounter", "Patient", "Practitioner", "Coverage", "MedicationRequest", "Specimen"):
        assert len(res[t]) == 1, t
    assert len(res["Organization"]) >= 2  # hospital + NHI (+ gene lab)
    full = {e["fullUrl"] for e in b["entry"]}
    local = {f"{r['resourceType']}/{r['id']}" for e in b["entry"] for r in [e["resource"]]}
    for ref in _refs(b):
        assert ref in local or ref in full, ref  # every reference resolves inside the bundle
    assert tb.structural_errors(b) == []


def test_identity_only_in_patient_and_whole_number_body_size() -> None:
    b = tb.build(INP)
    res = _by_type(b)
    pat = res["Patient"][0]
    assert {i["value"] for i in pat["identifier"]} >= {"A123456789", "10000020"}
    others = json.dumps([r for t, rs in res.items() if t != "Patient" for r in rs], ensure_ascii=False)
    assert "A123456789" not in others and "王小明" not in others
    claim = res["Claim"][0]
    values = {
        si["category"]["coding"][0]["code"]: si.get("valueQuantity", {}).get("value") for si in claim["supportingInfo"]
    }
    assert values["weight"] == 62 and values["height"] == 169  # D-65 (HTWT invariant)


def test_bundle_is_deterministic() -> None:
    assert json.dumps(tb.build(INP), sort_keys=True) == json.dumps(tb.build(INP), sort_keys=True)
    other = tb.build(replace(INP, pid="b" * 32))
    assert {e["fullUrl"] for e in other["entry"]}.isdisjoint({e["fullUrl"] for e in tb.build(INP)["entry"]})


@pytest.mark.parametrize(
    ("change", "word"),
    [
        ({"egfr_positive": None}, "gene test"),
        ({"weight_kg": None}, "weight"),
        ({"national_id": ""}, "national_id"),
        ({"practitioner_license": ""}, "practitioner_license"),
    ],
)
def test_missing_mandatory_content_raises(change: dict[str, Any], word: str) -> None:
    with pytest.raises(tb.BundleDataMissing, match=word):
        tb.build(replace(INP, **change))


def test_validator_per_file_parsing_handles_paths() -> None:
    def oo(fname: str, *sev: str) -> dict[str, Any]:
        return {
            "resource": {
                "resourceType": "OperationOutcome",
                "extension": [
                    {"url": "http://hl7.org/fhir/StructureDefinition/operationoutcome-file", "valueString": fname}
                ],
                "issue": [{"severity": s, "expression": ["Bundle.entry[0]"], "details": {"text": s}} for s in sev],
            }
        }

    doc = {
        "resourceType": "Bundle",
        "entry": [
            oo("r00000-Bundle.json", "warning", "information"),
            oo("/tmp/tbval-x/r00001-Bundle.json", "error", "fatal", "warning"),
            oo("C:\\tmp\\r00002-Bundle.json"),
        ],
    }
    res = Hl7Validator._parse(doc, 3)
    assert res.errors == 1
    assert res.per_file == {0: [], 1: ["Bundle.entry[0]: error", "Bundle.entry[0]: fatal"], 2: []}


def test_simulated_claim_response() -> None:
    b = tb.build(INP)
    cr = submit.simulated_response(b, "2026-10-05T09:00:00+08:00", "01JB0000000000000000000000")
    claim = _by_type(b)["Claim"][0]
    assert cr["resourceType"] == "ClaimResponse" and cr["outcome"] == "queued" and cr["use"] == "preauthorization"
    assert cr["request"]["reference"] == f"Claim/{claim['id']}"
    assert "DRY RUN" in cr["disposition"]


def test_post_bundle_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    replies: list[httpx.Response] = []

    def fake_post(url: str, **_: Any) -> httpx.Response:
        assert url == "https://nhi.invalid/Claim/$submit"
        return replies.pop(0)

    monkeypatch.setattr(httpx, "post", fake_post)
    cr = {"resourceType": "ClaimResponse", "outcome": "complete"}
    replies.append(httpx.Response(200, json=cr))
    assert submit.post_bundle("https://nhi.invalid/", b"{}")["outcome"] == "complete"
    replies.append(httpx.Response(200, json={"resourceType": "Bundle", "entry": [{"resource": cr}]}))
    assert submit.post_bundle("https://nhi.invalid", b"{}")["outcome"] == "complete"
    replies.append(httpx.Response(503, text="down"))
    with pytest.raises(StepFailed, match="HTTP 503"):
        submit.post_bundle("https://nhi.invalid", b"{}")
    replies.append(httpx.Response(200, json={"resourceType": "OperationOutcome"}))
    with pytest.raises(StepFailed, match="not a ClaimResponse"):
        submit.post_bundle("https://nhi.invalid", b"{}")

    def unreachable(url: str, **_: Any) -> httpx.Response:
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(httpx, "post", unreachable)
    with pytest.raises(StepFailed, match="nothing was submitted"):
        submit.post_bundle("https://nhi.invalid", b"{}")


def test_submissions_table(tmp_path: Path) -> None:
    db = JobDB(tmp_path / "jobs.sqlite")
    row = {
        "job_id": "J1",
        "ruleset": "ONC-OSI",
        "pid": "a" * 32,
        "nav_job_id": "N1",
        "bundle_sha": "s" * 64,
        "dry_run": True,
        "outcome": "queued",
        "submitted_by": "onc-dr@hospa.test",
        "submitted_at": "2026-10-05T09:00:00+08:00",
    }
    db.submission_add(row)
    db.submission_add({**row, "job_id": "J2", "dry_run": False, "outcome": "complete"})
    assert [r["job_id"] for r in db.submissions("s" * 64)] == ["J1", "J2"]
    assert [r["job_id"] for r in db.submissions("s" * 64, live_only=True)] == ["J2"]
    assert db.submissions("x" * 64) == []
    db.close()


def test_dump_keeps_required_nulls() -> None:
    """Required-but-nullable contract fields survive serialization (Precheck.passed, FunnelStep.pct)."""
    p = c.Precheck(passed=None, issues=[])
    assert dump(p) == {"passed": None, "issues": [], "validator_errors": 0}
    row = c.NavRow(pid="p", criteria=[], missing=[], precheck=p)
    data = dump(row)
    assert data["precheck"]["passed"] is None and "next_appointment" not in data
