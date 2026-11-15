"""GW-SIGNALS (D-728): two failures that were said only in text, or not at all (lane G's findings, 2026-11-14).

* A model server that timed out under a batch call: the refusal (``upstream_failed``, never sent again) carries the
  upstream kinds as a field, ``upstream_kinds``, in its answer and in its audit record, and ``tb_llm`` gives them as
  ``GatewayRefused.upstream_kinds``. A caller decides by that field, never by the message text (D-636).
* ``GatewayClient.contexts()`` whose ``GET /v1/models`` failed: it still gives an empty map (the caller keeps its own
  default and the gateway still checks), and now logs why and keeps it in ``last_context_error``; a failure is not
  kept as an answer, so the next call asks again."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from gateway.app import create_app
from tb_llm import CallLabels, GatewayClient, GatewayRefused

from tests.unit.test_gateway import H, _judge_body
from tests.unit.test_gateway_one_role_one_model import JUDGE_HOST, _gw, _vllm

pytestmark = pytest.mark.nodb


def _refusals(tmp_path: Path) -> list[dict[str, object]]:
    out = []
    for f in sorted((tmp_path / "audit").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("event") == "llm.gateway.refuse":
                out.append(rec)
    return out


@pytest.mark.parametrize(("fault", "kinds"), [("timeout", ["timeout"]), (503, ["retried"]), ("refuse", ["retried"])])
def test_the_refusal_says_what_the_server_did_as_a_field(tmp_path: Path, fault: object, kinds: list[str]) -> None:
    http, _log = _vllm({JUDGE_HOST: fault})  # type: ignore[dict-item]
    res = _gw(tmp_path, http).chat(H(Data_Class="D3"), _judge_body())
    assert res.status == 502
    assert res.body["error"]["upstream_kinds"] == kinds, res.body
    rec = _refusals(tmp_path)[-1]
    assert rec["detail"]["upstream_kinds"] == kinds  # type: ignore[index]


def test_a_timeout_stays_upstream_failed_and_is_not_sent_again(tmp_path: Path) -> None:
    http, log = _vllm({JUDGE_HOST: "timeout"})
    res = _gw(tmp_path, http).chat(H(Data_Class="D3"), _judge_body())
    assert res.body["error"]["code"] == "upstream_failed" and log == [JUDGE_HOST]


def test_a_refusal_with_no_server_in_it_has_no_upstream_kinds(tmp_path: Path) -> None:
    http, _log = _vllm({})
    res = _gw(tmp_path, http).chat(H(Data_Class="D9"), _judge_body())  # an unknown data class: refused before
    assert res.status == 403 and "upstream_kinds" not in res.body["error"], res.body


def test_tb_llm_gives_the_kinds_to_its_caller(tmp_path: Path) -> None:
    http, _log = _vllm({JUDGE_HOST: "timeout"})
    app = TestClient(create_app(_gw(tmp_path, http)))
    h = H(Data_Class="D3")  # the gateway tests' own judge call, with its prompt's registry sha
    labels = CallLabels("D3", h["X-TB-Purpose"], h["X-TB-Study"], h["X-TB-Context-Of-Use"], h["X-TB-Role"],
                        h["X-TB-Prompt"], h["X-TB-Step"], prompt_sha=h.get("X-TB-Prompt-Sha", ""))  # fmt: skip
    client = GatewayClient("http://gateway/v1", "orchestrator", http=app)
    with pytest.raises(GatewayRefused) as exc:
        client.complete(_judge_body(), labels)
    assert exc.value.upstream_kinds == ("timeout",)


def test_a_refusal_from_an_older_gateway_gives_no_kinds() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"error": {"type": "tb_refusal", "code": "upstream_failed", "message": "x"}})

    client = GatewayClient(
        "http://gateway/v1", "orchestrator", http=httpx.Client(transport=httpx.MockTransport(handler))
    )
    labels = CallLabels("D3", "screen", "STUDY-1", "patient_screening", "judge_note", "judge_note@1", "step-1")
    with pytest.raises(GatewayRefused) as exc:
        client.complete(_judge_body(), labels)
    assert exc.value.upstream_kinds == ()


# ------------------------------------------------------------------------------------------------ contexts()
def _client(answer: object) -> tuple[GatewayClient, list[int]]:
    asked: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        asked.append(1)
        if isinstance(answer, Exception):
            raise answer
        assert isinstance(answer, httpx.Response)
        return answer

    return GatewayClient(
        "http://gateway/v1", "orchestrator", http=httpx.Client(transport=httpx.MockTransport(handler))
    ), asked


@pytest.mark.parametrize(
    ("answer", "said"),
    [
        (httpx.Response(503, json={"error": "x"}), "HTTP 503"),
        (httpx.Response(401, json={"error": "x"}), "HTTP 401"),
        (httpx.ConnectError("refused"), "ConnectError"),
        (httpx.Response(200, content=b"not json"), "not JSON"),
    ],
)
def test_a_failed_lookup_is_logged_and_kept_and_asked_again(
    answer: object, said: str, caplog: pytest.LogCaptureFixture
) -> None:
    client, asked = _client(answer)
    with caplog.at_level(logging.WARNING, logger="tb_llm.client"):
        assert client.contexts() == {}
    assert said in (client.last_context_error or "")
    assert any(said in r.getMessage() and "/v1/models" in r.getMessage() for r in caplog.records), caplog.text
    client.contexts()
    assert len(asked) == 2  # a failure is not an answer: the next call asks again


def test_a_lookup_that_answers_clears_the_error() -> None:
    client, _asked = _client(httpx.Response(200, json={"data": [{"id": "j-workhorse", "context_length": 8192}]}))
    client.last_context_error = "HTTP 503"
    assert client.contexts() == {"j-workhorse": 8192}
    assert client.last_context_error is None
