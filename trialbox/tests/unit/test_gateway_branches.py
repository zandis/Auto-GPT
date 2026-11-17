"""The gateway's branches the suite did not reach (D-976): the content of a message in parts, the schema check, the stall
probe.

The nightly's branch coverage of ``services/gateway/core.py`` was 87.37 % against its floor of 89.16 % (run
43912198355, 2026-11-16). These are the branches no test walked: a message whose content is a list of parts, a schema
check with no schema, a broken answer or a valid one, and the stall probe's answers (no endpoint, no URL, a server
that answers, one that fails, one that is not there). No floor is changed.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from gateway.core import Gateway, _content_text, _schema_ok
from gateway.policy import RoutingPolicy
from registry.registry import Registry
from tb_common.audit import AuditLog

SCHEMA = {
    "json_schema": {
        "schema": {
            "type": "object",
            "properties": {"verdict": {"type": "string"}},
            "required": ["verdict"],
            "additionalProperties": False,
        }
    }
}


def test_a_message_in_parts_is_read_part_by_part() -> None:
    msgs = [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": [{"type": "text", "text": "part one"}, "not a part", {"type": "image_url"}]},
        "not a message",
        {"role": "user"},
    ]
    assert _content_text(msgs) == "rules\npart one\n"
    assert _content_text("not a list") == ""


def test_the_schema_check() -> None:
    assert _schema_ok('{"verdict": "met"}', SCHEMA) is True
    assert _schema_ok('{"verdict": 3}', SCHEMA) is False
    assert _schema_ok("not json", SCHEMA) is False
    assert _schema_ok('{"verdict": "met"}', {"type": "json_object"}) is None  # no schema to check against
    assert _schema_ok('{"verdict": "met"}', None) is None


def _gw(tmp_path: Path, handler: object, env: dict[str, str] | None = None) -> Gateway:
    gw = Gateway(RoutingPolicy.load(), Registry.load(), AuditLog(tmp_path / "audit"), env=env or {})
    gw.http = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    return gw


def test_the_probe_with_nothing_to_ask_is_not_a_stall(tmp_path: Path) -> None:
    def never(req: httpx.Request) -> httpx.Response:
        raise AssertionError(f"asked {req.url}")

    gw = _gw(tmp_path, never)
    assert gw._probe("no-such-endpoint") is True
    assert gw._probe("external_x") is True  # an endpoint with no URL set


def test_the_probe_reads_the_servers_answer(tmp_path: Path) -> None:
    seen: list[tuple[str, str]] = []
    answer = {"code": 200}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((str(req.url), req.headers.get("Authorization", "")))
        return httpx.Response(answer["code"], content=json.dumps({"data": []}).encode())

    gw = _gw(tmp_path, handler)
    assert gw._probe("stub") is True
    assert seen[-1] == ("http://llm-stub:8000/v1/models", "")  # no key for an endpoint that has none
    answer["code"] = 503
    assert gw._probe("stub") is False
    answer["code"] = 404
    assert gw._probe("stub") is True  # it answered: not stalled, whatever it said


def test_the_probe_sends_the_endpoints_key(tmp_path: Path) -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.headers.get("Authorization", ""))
        return httpx.Response(200)

    gw = _gw(tmp_path, handler, env={"TB_LLM_API_KEY": "probe-key-0123456789"})
    assert gw._probe("serving") is True
    assert seen == ["Bearer probe-key-0123456789"]


def test_a_server_that_is_not_there_is_a_stall(tmp_path: Path) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=req)

    assert _gw(tmp_path, handler)._probe("stub") is False


# ------------------------------------------------------------------------------------------------ refusals (D-976)
def test_an_empty_message_list_is_refused(tmp_path: Path) -> None:
    from tests.unit.test_gateway import H, _judge_body
    from tests.unit.test_gateway import _gw as _stub_gw

    res = _stub_gw(tmp_path).chat(H(), {**_judge_body(), "messages": []})
    assert res.status != 200 and res.headers["X-TB-Refusal"] == "request_invalid"


def test_a_model_not_on_the_route_is_refused(tmp_path: Path) -> None:
    from tests.unit.test_gateway import H, _judge_body
    from tests.unit.test_gateway import _gw as _stub_gw

    res = _stub_gw(tmp_path).chat(H(), {**_judge_body(), "model": "no-such-model"})
    assert res.status != 200 and res.headers["X-TB-Refusal"] == "class_route_mismatch"


def test_release_without_a_swap_says_it_is_off(tmp_path: Path) -> None:
    gw = _gw(tmp_path, lambda req: httpx.Response(200))
    assert gw.swap is None
    res = gw.release("on-demand")
    assert res.status == 200 and res.body == {"swap": "off", "active": None}


def test_an_answer_that_is_not_a_chat_completion_is_upstream_failed(tmp_path: Path) -> None:
    """A model server's 200 whose body is not a chat completion: refused, and the message names the endpoint only."""
    from tests.unit.test_gateway import H, _judge_body
    from tests.unit.test_gateway import _gw as _stub_gw

    for body in (b"not json", b'{"choices": []}', b'{"no": "choices"}'):
        bad = httpx.Client(transport=httpx.MockTransport(lambda req, b=body: httpx.Response(200, content=b)))
        res = _stub_gw(tmp_path, http=bad).chat(H(), _judge_body())
        assert res.status == 502 and res.headers["X-TB-Refusal"] == "upstream_failed"
        assert res.body["error"]["message"] == "stub: malformed response"
