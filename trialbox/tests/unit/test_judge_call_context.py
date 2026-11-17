"""H-16 (lane H, #970's questions 1 and 2, for H-18's offline review): each judge call's own record says which stage
asked it and what it was asked, so S3 and S4 are told apart and the judged-pair key can be computed from the records.

* the cascade sets the call's context around each judge question: the stage (S3 for the judge, S4 for the second
  opinion), the context of use, the role, the patient's pseudonym, the criterion's canonical hash, the window, the
  question digest and whether it is an audit sample; outside a judge question there is none;
* ``llm.call`` writes it beside the call (``asking``) with the answer schema it was called with; a call outside such a
  question writes no ``asking``. Ids and hashes only, never the question's text.

The gateway labels of SCREEN's v1 path stay as they are (they route the call); the stage is in the call's record.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from matching.cascade.judge import JudgeReply, call_context
from tb_common.audit import AuditLog
from tb_common.llm import CALL_CONTEXT, LlmClient

from tests.judge_kit import ScriptedJudge, quoting, ruleset
from tests.unit.test_cascade_exclusion_rules import FLARE, INC, _run, lake  # noqa: F401 (the fixture)

JUDGE_VARS = {"criterion_text": "x", "note_question": "q", "index_date": "2026-01-01", "excerpts": []}


def test_the_cascade_names_the_stage_and_the_question_around_each_judge_call(lake: Any) -> None:  # noqa: F811
    seen: list[dict[str, Any] | None] = []

    def script(role: str, kw: dict[str, Any]) -> JudgeReply:
        seen.append(CALL_CONTEXT.get())
        return quoting("pass", FLARE)(role, kw)

    res = _run(lake, ruleset([INC]), ["P-HIT"], ScriptedJudge(script))
    assert res.metrics.pairs_judged == {"S3": 1, "S4": 1}
    s3, s4 = seen
    assert s3 is not None and s4 is not None
    assert (s3["stage"], s3["context_of_use"], s3["role"]) == ("S3", "s3_note_judgement", "judge")
    assert (s4["stage"], s4["context_of_use"]) == ("S4", "s4_second_opinion")
    for ctx in (s3, s4):
        assert ctx["pid"] == "P-HIT" and len(ctx["criterion_hash"]) >= 16 and len(ctx["window"]) == 2
        assert ctx["question"] and ctx["audit"] is False
        assert "Gout" not in json.dumps(ctx)  # hashes, never the criterion's or the question's text
    assert CALL_CONTEXT.get() is None  # reset after each call


def _client(tmp_path: Path) -> LlmClient:
    def handler(request: httpx.Request) -> httpx.Response:
        content = json.dumps({"verdict": "unknown", "confidence": 0.5})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {}})

    c = LlmClient("http://x/v1", "m", audit=AuditLog(tmp_path))
    c.http = httpx.Client(transport=httpx.MockTransport(handler))
    return c


def _llm_calls(tmp_path: Path) -> list[dict[str, Any]]:
    lines = [json.loads(x) for p in sorted(tmp_path.glob("*.jsonl")) for x in p.read_text("utf-8").splitlines() if x]
    return [e["detail"] for e in lines if e["event"] == "llm.call"]


def test_the_call_record_carries_the_context_and_the_schema(tmp_path: Path) -> None:
    c = _client(tmp_path)
    ctx = call_context(
        "second_opinion", "0ca5381cfa6bdf1c22961d65579f93b3", "h" * 64, ("2025-11-01", "2026-11-01"), "q"
    )
    token = CALL_CONTEXT.set(ctx)
    try:
        c.chat_json("judge", JUDGE_VARS)
    finally:
        CALL_CONTEXT.reset(token)
    c.chat_json("judge", JUDGE_VARS)  # outside a cascade question
    inside, outside = _llm_calls(tmp_path)
    assert inside["asking"] == ctx and inside["asking"]["stage"] == "S4"
    assert "schema" in inside and "asking" not in outside
