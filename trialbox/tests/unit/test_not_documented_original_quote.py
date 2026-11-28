"""An unsure answer that quoted the note is "abstained", never "not documented in the notes" (BENCH-2 §2).

``unknown_carries_nothing`` (INT-S-C) clears the quote of every unknown; ``not_documented`` must read the quote as the
model gave it (whitespace alone is no quote), on each path that clears it: the generic client, the cascade's gateway
judge and the note judge's ``postprocess``.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from matching.cascade.judge import GatewayJudge
from matching.note_answer import not_documented
from orchestrator.scenarios.evaluate import postprocess
from tb_common.llm import LlmClient

from tests.unit.test_judge_sentinel_date import KW, _Client

EXCERPTS = [{"did": "D1", "text": "Routine visit. Blood pressure stable.", "date": "2026-01-10"}]
QUOTES = [("Blood pressure stable.", True), ("  \n", False), (None, False)]


def _reply(quote: str | None) -> dict[str, Any]:
    return {"verdict": "unknown", "reason": "r", "confidence": 0.0, "quote": quote, "quote_date": None}


@pytest.mark.parametrize(
    ("kind", "quote", "quoted", "want"),
    [("exclusion", None, False, True), ("exclusion", "  ", False, True), ("exclusion", None, True, False),
     ("exclusion", "x", False, False), ("inclusion", None, False, False)],
)  # fmt: skip
def test_the_label_reads_the_original_quote(kind: str, quote: str | None, quoted: bool, want: bool) -> None:
    assert not_documented(kind, "abstained", quote, quoted) is want


@pytest.mark.parametrize(("quote", "want"), QUOTES)
def test_the_generic_client_records_that_the_unknown_quoted(quote: str | None, want: bool) -> None:
    class Http:
        def post(self, url: str, **kw: Any) -> httpx.Response:
            msg = {"content": json.dumps(_reply(quote))}
            body = {"choices": [{"message": msg, "finish_reason": "stop"}], "model": "m"}
            return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    llm = LlmClient("http://stub/v1", "m")
    llm.http = Http()  # type: ignore[assignment]
    vs = {"criterion_text": "c", "note_question": "q", "index_date": "2026-10-05", "excerpts": []}
    res = llm.chat_json("judge", vs)
    assert res.data["quote"] is None and res.quoted is want


@pytest.mark.parametrize(("quote", "want"), QUOTES)
def test_the_gateway_judge_records_that_the_unknown_quoted(quote: str | None, want: bool) -> None:
    r = GatewayJudge(_Client(_reply(quote))).judge(**KW)
    assert r.quote is None and r.quoted is want


@pytest.mark.parametrize(("quote", "want"), QUOTES)
def test_postprocess_records_that_the_unknown_quoted(quote: str | None, want: bool) -> None:
    r = postprocess(_reply(quote), EXCERPTS)
    assert r.quote is None and r.quoted is want
    assert postprocess(_reply(None), EXCERPTS, quoted=True).quoted  # the client's own record is kept
