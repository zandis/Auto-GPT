"""E-EDCB-1 (D-1043): the owner's EDC's tool answer is taken only when it says ``deidentified: true``.

D-1060 (the owner): the connector refuses any EDC tool answer whose ``deidentified`` is not exactly true, with no
opt-in for now. The answer's shape is the one #813's contract test records (``allow``, ``deidentified``,
``result``); a refused answer's body is never handed on, and the reason names no value from it.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from edc_backend import tools

TOKEN = "tool-token-for-tests"


def _client(answer: Any, status: int = 200) -> tuple[tools.ToolClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/capabilities"):
            return httpx.Response(200, json={"modules": [{"id": "trialbox"}]})
        return httpx.Response(status, json=answer)

    return tools.ToolClient("https://edc.example", TOKEN, httpx.Client(transport=httpx.MockTransport(handler))), seen


def test_an_answer_that_says_deidentified_true_is_taken() -> None:
    client, _ = _client({"allow": True, "deidentified": True, "result": "ok"})
    assert client.call("explain_field", "proj-1")["result"] == "ok"


@pytest.mark.parametrize("value", [False, None, "true", 1, "yes", [True], {"value": True}])
def test_an_answer_whose_deidentified_is_not_exactly_true_is_refused(value: Any) -> None:
    client, seen = _client({"allow": True, "deidentified": value, "result": "Chen Mei, chart 0012345"})
    with pytest.raises(tools.ToolError) as err:
        client.call("find_patient", "proj-1")
    assert "de-identified" in err.value.message
    assert "Chen" not in err.value.message and "0012345" not in err.value.message  # nothing of the body is said
    assert any(r.url.path.endswith("/tools") for r in seen)  # it was asked; its answer is what is refused


def test_an_answer_without_deidentified_is_refused() -> None:
    client, _ = _client({"allow": True, "result": "ok"})
    with pytest.raises(tools.ToolError) as err:
        client.call("summarize_queries", "proj-1")
    assert "de-identified" in err.value.message


def test_a_confirmed_write_is_held_to_the_same_rule() -> None:
    client, _ = _client({"allow": True, "deidentified": False, "result": "applied"})
    with pytest.raises(tools.ToolError):
        client.call("open_query", "proj-1", record_id="1001", confirm=True)


def test_there_is_no_switch_to_take_an_identified_answer() -> None:
    import inspect

    params = inspect.signature(tools.ToolClient.call).parameters
    assert set(params) == {"self", "tool", "project_id", "record_id", "confirm"}  # no opt-in (D-1060)
    assert not hasattr(tools, "ALLOW_IDENTIFIED")
