from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import tb_contracts as c
from jsonschema import Draft202012Validator

SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"


@pytest.mark.parametrize("path", sorted(SCHEMAS.glob("*.schema.json")), ids=lambda p: p.name)
def test_schema_is_valid_draft_2020_12(path: Path) -> None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(doc)
    assert doc["$id"].endswith(path.name)
    assert "Schema version" in doc.get("description", "")


def test_contracts_are_up_to_date(repo_root: Path) -> None:
    out = subprocess.run(
        [sys.executable, str(repo_root / "tools" / "gen_contracts.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0, out.stderr


def test_spec_contracts_exist() -> None:
    for name in [
        "criterion_ir",
        "ruleset_manifest",
        "job",
        "feasibility_result",
        "candidate_list",
        "nav_lists",
        "screen_feedback",
        "llm_extract_output",
        "llm_judge_output",
        "settings",
    ]:
        assert (SCHEMAS / f"{name}.schema.json").exists(), name
    for model in [
        "CriterionIR",
        "RulesetManifest",
        "Job",
        "FeasibilityResult",
        "CandidateList",
        "NavLists",
        "ScreenFeedback",
        "LlmExtractOutput",
        "LlmJudgeOutput",
        "Settings",
    ]:
        assert hasattr(c, model), model


def test_ir_roundtrip_and_cross_validation() -> None:
    raw = {
        "id": "RA-BIO-INC-01",
        "ruleset": "RA-BIO",
        "text": "t",
        "kind": "inclusion",
        "class": "structured",
        "logic": {
            "op": "or",
            "args": [
                {"domain": "condition", "valueset": "VS_RA"},
                {"op": "not", "args": [{"domain": "demographic", "valueset": "NONE", "sex": "male"}]},
            ],
        },
    }
    ir = c.CriterionIR.model_validate(raw)
    assert c.schema_errors("criterion_ir", c.dump(ir)) == []
    assert c.CriterionIR.model_validate(c.dump(ir)) == ir


def test_ir_rejects_bad_id_and_extra_fields() -> None:
    base = {
        "ruleset": "X",
        "text": "t",
        "kind": "inclusion",
        "class": "human",
        "logic": {"domain": "demographic", "valueset": "NONE"},
    }
    assert c.schema_errors("criterion_ir", {**base, "id": "X-FOO-01"})
    assert c.schema_errors("criterion_ir", {**base, "id": "X-INC-01", "bogus": 1})
    assert not c.schema_errors("criterion_ir", {**base, "id": "X-INC-01"})


def test_job_schema_ulid_and_states() -> None:
    job = {
        "job_id": "01JB0000000000000000000000",
        "type": "FEAS",
        "requested_by": "a@b",
        "received_at": "2026-10-04T10:00:00+08:00",
        "state": "received",
    }
    assert not c.schema_errors("job", job)
    assert c.schema_errors("job", {**job, "state": "sleeping"})
    assert c.Job.model_validate(job).state == "received"


@pytest.mark.req("LLM-22", "MOD-4")
def test_judge_output_schema_is_strict_mode_compatible() -> None:
    """judge@3 (llm_judge_output 1.1.0): every property required, optional ones nullable, no extra keys, so
    OpenAI-style strict structured output accepts it; null and absent validate alike (``null_absent``)."""
    s = c.inline_schema("llm_judge_output")
    assert s["additionalProperties"] is False and set(s["required"]) == set(s["properties"])
    nullable = {k for k, v in s["properties"].items() if "null" in (v.get("type") or [])}
    assert nullable == {"quote", "quote_date", "reason"}  # verdict and confidence stay non-null
    assert all("type" in v for v in s["properties"].values())
    full = {"verdict": "pass", "quote": "q", "quote_date": "2026-10-01", "confidence": 0.9, "reason": "r"}
    nulls = {"verdict": "unknown", "quote": None, "quote_date": None, "confidence": 0.5, "reason": None}
    assert c.schema_errors("llm_judge_output", full) == [] and c.schema_errors("llm_judge_output", nulls) == []
    absent = {"verdict": "unknown", "confidence": 0.5}
    assert c.schema_errors("llm_judge_output", absent)  # strictly, absent is an error ...
    assert c.null_absent(s, absent) == nulls | {"reason": None}  # ... and null_absent makes it the null form
    assert c.schema_errors("llm_judge_output", c.null_absent(s, absent)) == []
    for bad in ({**nulls, "verdict": None}, {**nulls, "confidence": None}, {**full, "quote_date": "Oct 1"}):
        assert c.schema_errors("llm_judge_output", bad), bad
    assert c.null_absent(s, {"verdict": "pass"}) == {
        "verdict": "pass",
        "quote": None,
        "quote_date": None,
        "reason": None,
    }  # never invents non-nullable keys
