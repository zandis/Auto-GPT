"""tb_llm.GatewayClient: a JSON answer cut off at max_tokens (reasoning models) is asked again with a larger budget."""

from __future__ import annotations

import json
from typing import Any

import httpx
from tb_llm import CallLabels, GatewayClient, json_schema_format

LABELS = CallLabels(
    data_class="D0",
    purpose="screen",
    study_id="GZQO",
    context_of_use="s3_note_judgement",
    role="judge",
    prompt="judge@3",
)


def test_cut_off_json_is_asked_again_with_four_times_the_budget() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            choice = {"message": {"content": '{"verdict": "pa'}, "finish_reason": "length"}
        else:
            choice = {"message": {"content": '{"verdict": "pass"}'}, "finish_reason": "stop"}
        usage = {"prompt_tokens": 100, "completion_tokens": 1024 if len(bodies) == 1 else 300}
        return httpx.Response(200, json={"choices": [choice], "usage": usage})

    client = GatewayClient("http://gw/v1", "orchestrator", http=httpx.Client(transport=httpx.MockTransport(handler)))
    res = client.chat(
        [{"role": "user", "content": "x"}], LABELS, response_format=json_schema_format("judge", {}), max_tokens=1024
    )
    assert res.data == {"verdict": "pass"} and len(bodies) == 2
    assert bodies[1]["max_tokens"] == 4096 and bodies[1]["messages"] == bodies[0]["messages"]
    assert (res.tokens_in, res.tokens_out) == (200, 1324)  # both calls are paid for
