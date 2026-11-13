"""An answer still cut off after the retry is no answer (lane G's run C: 1 of 64 guided answers outside the schema).

``tb_llm.GatewayClient.chat`` asks once more, with a larger ``max_tokens``, when a JSON answer comes back with
``finish_reason: length``. What comes back the second time is taken as it is. These tests drive that end to end
through the cascade's gateway judge (``matching.cascade.judge.GatewayJudge``) with a fake gateway, on the note of
the wrong exclusion of run C ("病人否認下列病史：… 肺結核"): a reply cut twice never yields "met" or "not met",
whatever verdict its cut text begins with; with a verifier beside it the pair's answer is unknown too; and when no
larger budget fits the context, the one cut reply is no answer either.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import httpx
import pytest
from matching.cascade.judge import AgreementJudge, GatewayJudge, JudgeReply
from tb_llm import GatewayClient

NOTE = "【過去病史】\n高血壓。\n病人否認下列病史：\n肺結核。\nB型肝炎。"
EXCERPTS = [{"date": "2026-06-01", "note_type": "discharge", "text": NOTE, "did": "d1"}]
WHOLE = {"verdict": "pass", "reason": "肺結核 is listed", "quote": "肺結核。", "quote_date": "2026-06-01",
         "confidence": 0.97}  # fmt: skip
# a cut answer, as a model server returns it at the token limit: the text of the object up to some character
CUTS = [
    '{"verdict": "pass", "reason": "The note lists 肺結核 under the past history, so the patient',
    '{"verdict": "fail", "reason": "病人否認',
    '{"verdict": "pass", "reason": "x", "quote": "肺結核。", "quote_date": "2026-06-01", "confidence": 0.9',
    '{"verdict": "pass"',
    "",
]


def _gateway(replies: list[tuple[str, str]], context: int | None = None) -> tuple[GatewayClient, list[dict[str, Any]]]:
    """A gateway that answers the chat calls with ``replies`` (content, finish_reason) in turn; ``context``: what
    ``GET /v1/models`` says of the answering alias."""
    sent: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "j-workhorse", "context_length": context}]})
        sent.append(json.loads(req.content))
        content, finish = replies[min(len(sent), len(replies)) - 1]
        return httpx.Response(200, json={
            "model": "x",
            "choices": [{"message": {"content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            "tb": {"alias": "j-workhorse", "call_id": f"c{len(sent)}", "expected_alias": "j-workhorse", "fallbacks": 0},
        })  # fmt: skip

    return GatewayClient(
        "http://gw/v1", "orchestrator", http=httpx.Client(transport=httpx.MockTransport(handler))
    ), sent


def _ask(judge: Any, role: str = "judge") -> JudgeReply:
    reply: JudgeReply = judge.judge(
        role=role, criterion_text="Active or past tuberculosis",
        note_question="Does the patient have active tuberculosis or a history of tuberculosis?",
        index_date=date(2026, 6, 30), excerpts=EXCERPTS, study_id="GZQO", data_class="D3", step_id="s", purpose="screen",
    )  # fmt: skip
    return reply


@pytest.mark.parametrize("cut", CUTS)
def test_a_reply_cut_twice_is_unknown_whatever_its_cut_text_says(cut: str) -> None:
    client, sent = _gateway([(cut, "length"), (cut, "length")])
    judge = GatewayJudge(client)
    r = _ask(judge)
    assert len(sent) == 2 and sent[1]["max_tokens"] > sent[0]["max_tokens"]  # asked again, with room
    assert (r.verdict, r.refused, r.confidence, r.quote) == ("unknown", "schema_invalid", 0.0, None)
    assert judge.refusals == ["schema_invalid"]


def test_the_retry_that_finishes_is_the_answer() -> None:
    """The other side, so the test above cannot pass on a judge that answers unknown to everything."""
    client, sent = _gateway([(CUTS[0], "length"), (json.dumps(WHOLE, ensure_ascii=False), "stop")])
    r = _ask(GatewayJudge(client))
    assert len(sent) == 2 and (r.verdict, r.quote, r.refused) == ("pass", "肺結核。", None)


def test_with_no_room_for_a_retry_the_one_cut_reply_is_unknown() -> None:
    client, sent = _gateway([(CUTS[0], "length")], context=1200)  # the prompt leaves no larger answer budget
    r = _ask(GatewayJudge(client))
    assert len(sent) == 1 and (r.verdict, r.refused) == ("unknown", "schema_invalid")


@pytest.mark.parametrize("cut_side", ["primary", "verifier"])
def test_a_pair_with_one_model_cut_twice_never_decides(cut_side: str) -> None:
    whole = [(json.dumps(WHOLE, ensure_ascii=False), "stop")]
    cut = [(CUTS[0], "length"), (CUTS[0], "length")]
    primary, _ = _gateway(cut if cut_side == "primary" else whole)
    verifier, asked = _gateway(cut if cut_side == "verifier" else whole)
    r = _ask(AgreementJudge(GatewayJudge(primary), GatewayJudge(verifier)))
    assert r.verdict == "unknown"
    assert len(asked) == (0 if cut_side == "primary" else 2)  # a cut primary is not put to the verifier
