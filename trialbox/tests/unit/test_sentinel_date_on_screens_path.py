"""P2b (lane H's trace, 2026-11-17): G8's sentinel date (D-958) on SCREEN's note-judge path too.

Three protocols of the P2b launch failed in screen judging: the judge answered "unknown" with ``quote_date``
``0000-01-01``, the client's schema check refused it (``format: date``), the correction repeated it, and the call
counted as a model that did not answer. D-958's guard ran only in the cascade's gateway judge, not on the path SCREEN
uses (``OrchestratorJudge(NoteJudge)`` -> ``tb_common.llm``). The guard now runs in ``tb_common.llm`` before the
schema reads the answer, so an "unknown" with no real date is an answer on every path. The reply below is one of the
three, as P2b stored it (SIGIR 2016, public data; the model's own words).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from orchestrator.scenarios.evaluate import NoteJudge
from tb_common.audit import AuditLog
from tb_common.llm import LlmClient, no_sentinel_date

P2B_REPLY = (
    '{\n "verdict": "unknown",\n "reason": "The excerpts describe symptoms such as productive cough and purulent '
    'sputum, but they do not state a diagnosis of a disease that is likely to require antibiotic therapy.",\n '
    '"quote": "unknown",\n "quote_date": "0000-01-01",\n "confidence": 1.0\n}'
)
EXCERPTS = [
    {"date": "2026-10-01", "note_type": "progress", "text": "Productive cough with purulent sputum.", "did": "D1"}
]


def _client(tmp_path: Path, calls: list[int]) -> LlmClient:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json={"choices": [{"message": {"content": P2B_REPLY}}], "usage": {}})

    c = LlmClient("http://x/v1", "m", audit=AuditLog(tmp_path))
    c.http = httpx.Client(transport=httpx.MockTransport(handler))
    return c


def test_screens_note_judge_takes_the_p2b_reply_as_an_answer(tmp_path: Path) -> None:
    calls: list[int] = []
    judge = NoteJudge(lake=None, llm=_client(tmp_path, calls))
    r = judge.judge_excerpts("Disease likely to require antibiotics", "Does the patient have it?", date(
        2026, 11, 1), EXCERPTS)  # fmt: skip
    assert r.predicate == "unknown" and r.quote_date is None
    assert (judge.failures, judge.calls) == (0, 1)  # an answer, not a model that did not answer
    assert calls == [1]  # no correction asked


def test_the_client_returns_the_answer_with_no_date(tmp_path: Path) -> None:
    calls: list[int] = []
    vars_: dict[str, Any] = {"criterion_text": "x", "note_question": "q", "index_date": "2026-11-01", "excerpts": []}
    res = _client(tmp_path, calls).chat_json("judge", vars_)
    assert res.data["verdict"] == "unknown" and res.data["quote_date"] is None and res.attempts == 1


def test_a_real_date_and_an_answer_without_one_are_left_alone() -> None:
    assert no_sentinel_date({"quote_date": "2026-10-01"})["quote_date"] == "2026-10-01"
    assert no_sentinel_date({"verdict": "pass"}) == {"verdict": "pass"}
    assert json.loads(P2B_REPLY)["quote_date"] == "0000-01-01"  # the fixture is the stored reply, unchanged
