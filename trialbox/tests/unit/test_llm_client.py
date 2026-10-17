from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from llm_stub.app import app as stub
from tb_common.audit import AuditLog, verify
from tb_common.llm import LlmClient, LlmSchemaError, load_prompt
from tb_common.phi_guard import scan, variables_text


def _client(tmp_path: Path, **kw: Any) -> LlmClient:
    c = LlmClient("http://stub/v1", "stub", audit=AuditLog(tmp_path), **kw)
    c.http = TestClient(stub)
    return c


def test_prompts_have_front_matter() -> None:
    for pid in ("ir_extract", "concept_map", "ie_locate", "judge", "draft_doc"):
        p = load_prompt(pid)
        assert p.meta.output_schema and p.system and p.user
    assert load_prompt("judge").meta.phi is True and load_prompt("judge").meta.model_class == "local"


def test_judge_through_stub_and_audit(tmp_path: Path) -> None:
    c = _client(tmp_path)
    r = c.chat_json(
        "judge",
        {
            "criterion_text": "x",
            "note_question": "Is the patient currently (ongoing) having a gout flare?",
            "index_date": "2026-10-05",
            "excerpts": [
                {
                    "date": "2026-10-01",
                    "note_type": "progress",
                    "text": "目前右側第一蹠趾關節急性紅腫熱痛，診斷為急性痛風發作中。",
                }
            ],
        },
    )
    assert r.data["verdict"] == "pass" and r.target == "local"
    assert verify(tmp_path).ok
    line = json.loads(next(tmp_path.glob("*.jsonl")).read_text().splitlines()[0])
    assert line["event"] == "llm.call" and line["prompt_version"] == "judge_v3"


def test_cloud_routing_requires_service_flag_and_clearance(tmp_path: Path) -> None:
    c = _client(tmp_path, cloud_base_url="http://cloud/v1", cloud_enabled=True, service_name="criteria-compiler")
    meta = load_prompt("ir_extract").meta
    variables = {"ruleset": "GZQO", "language": "en", "criteria": [{"text": "Age >= 18", "kind": "inclusion"}]}
    assert c._target(meta, variables, None) == "local"
    clear = scan(variables_text(variables)).clearance
    assert c._target(meta, variables, clear) == "cloud"
    other = {**variables, "criteria": [{"text": "Age >= 18 years", "kind": "inclusion"}]}
    assert c._target(meta, other, clear) == "local"  # clearance bound to exactly these variables
    c.service_name = "orchestrator"
    assert c._target(meta, variables, clear) == "local"
    assert c._target(load_prompt("judge").meta, variables, clear) == "local"  # PHI prompts never go to cloud
    # MRN at the start of a criteria line: a JSON dump would hide it behind "\n", the variables text does not
    assert scan(variables_text({"criteria": [{"text": "see\nA1234567 chart"}]}), r"^A\d{7}$").hit


def test_compiler_cloud_call_goes_to_cloud(tmp_path: Path) -> None:
    """End to end through chat_json: a clean ir_extract call from criteria-compiler with cloud enabled reaches the
    cloud endpoint (the clearance used to be computed over other text than the check, so it never did)."""
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url.host))
        out = {"criteria": [{"text": "Age >= 18", "kind": "inclusion", "class": "human", "concept_candidates": []}]}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(out)}}], "usage": {}})

    c = _client(tmp_path, cloud_base_url="http://cloud/v1", cloud_enabled=True, service_name="criteria-compiler")
    c.http = httpx.Client(transport=httpx.MockTransport(handler))
    variables = {"ruleset": "GZQO", "language": "en", "criteria": [{"text": "Age >= 18", "kind": "inclusion"}]}
    guard = scan(variables_text(variables))
    res = c.chat_json("ir_extract", variables, job_id="J1", clearance=guard.clearance, phi_guard_hit=guard.hit)
    assert res.target == "cloud" and seen == ["cloud"]


class _Flaky(httpx.MockTransport):
    pass


def test_schema_violation_retry_then_error(tmp_path: Path) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        bad = len(calls) == 1
        content = json.dumps({"verdict": "maybe"} if bad else {"verdict": "unknown", "confidence": 0.5})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {}})

    c = LlmClient("http://x/v1", "m", audit=AuditLog(tmp_path))
    c.http = httpx.Client(transport=httpx.MockTransport(handler))
    r = c.chat_json("judge", {"criterion_text": "x", "note_question": "q", "index_date": "2026-01-01", "excerpts": []})
    assert r.attempts == 2 and r.data["verdict"] == "unknown"

    def always_bad(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

    c.http = httpx.Client(transport=httpx.MockTransport(always_bad))
    with pytest.raises(LlmSchemaError):
        c.chat_json("judge", {"criterion_text": "x", "note_question": "q", "index_date": "2026-01-01", "excerpts": []})
