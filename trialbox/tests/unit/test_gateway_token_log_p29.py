"""P-29: the gateway logs the token counts of each call (in and out) in its service log, so the model's tokens can be
measured on the box from the log as well as from the ledger. Counts only: the line holds neither the prompt nor the
answer. A call whose server gave no counts says so (``tokens_reported`` false), so a zero is never read as a count."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from llm_stub.app import app as stub
from tb_common.logging import JsonFormatter

from tests.unit.test_gateway import _records
from tests.unit.test_gateway_under_load import FRONT, _silent_gw
from tests.unit.test_model_swap import CHAT_BODY

LOGGER = "gateway.tokens"


def _server(usage: Any, seen: list[str] | None = None) -> httpx.Client:
    """The stub's answer with ``usage`` put in its place (``...`` keeps the stub's own; None drops it)."""
    inner = TestClient(stub)
    answers = [] if seen is None else seen

    def handle(request: httpx.Request) -> httpx.Response:
        got = inner.post(request.url.path, content=request.content, headers=dict(request.headers))
        body = got.json()
        answers.append(str(body["choices"][0]["message"].get("content") or ""))
        if usage is None:
            body.pop("usage", None)
        elif usage is not ...:
            body["usage"] = usage
        return httpx.Response(got.status_code, json=body)

    return httpx.Client(transport=httpx.MockTransport(handle), base_url="http://127.0.0.1:9")


def _ledger(tmp_path: Path) -> dict[str, Any]:
    calls = [r for r in _records(tmp_path) if r.get("event") == "llm.gateway.call"]
    assert len(calls) == 1
    return dict(calls[0]["detail"])


def _lines(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == LOGGER]


def test_each_call_logs_its_token_counts_and_no_text(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    gw = _silent_gw(tmp_path, 9)
    answers: list[str] = []
    gw.http = _server({"prompt_tokens": 321, "completion_tokens": 45, "total_tokens": 366}, answers)
    caplog.set_level(logging.INFO, logger=LOGGER)
    res = gw.chat(FRONT, CHAT_BODY)
    assert res.status == 200
    detail = _ledger(tmp_path)
    assert (detail["tokens_in"], detail["tokens_out"], detail["tokens_reported"]) == (321, 45, True)
    [line] = _lines(caplog)
    assert line.levelno == logging.INFO
    got = {k: getattr(line, k) for k in ("call_id", "alias", "build_id", "tokens_in", "tokens_out", "tokens_reported")}
    assert got == {
        "call_id": detail["call_id"],
        "alias": res.body["tb"]["alias"],
        "build_id": detail["build_id"],
        "tokens_in": 321,
        "tokens_out": 45,
        "tokens_reported": True,
    }
    written = JsonFormatter("gateway").format(line)
    parsed = json.loads(written)
    assert (parsed["tokens_in"], parsed["tokens_out"]) == (321, 45)  # the scrubber leaves the counts as they are
    [answer] = answers
    assert answer and answer not in written
    for message in CHAT_BODY["messages"]:
        for part in str(message["content"]).split("\n"):
            if len(part.strip()) >= 12:
                assert part.strip() not in written, part


def test_a_call_without_counts_from_its_server_says_so(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    gw = _silent_gw(tmp_path, 9)
    gw.http = _server(None)
    caplog.set_level(logging.INFO, logger=LOGGER)
    assert gw.chat(FRONT, CHAT_BODY).status == 200
    detail = _ledger(tmp_path)
    assert (detail["tokens_in"], detail["tokens_out"], detail["tokens_reported"]) == (0, 0, False)
    [line] = _lines(caplog)
    assert [getattr(line, k) for k in ("tokens_in", "tokens_out", "tokens_reported")] == [0, 0, False]


def test_the_stubs_counts_are_logged_as_estimates(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    gw = _silent_gw(tmp_path, 9)
    gw.http = _server(...)
    caplog.set_level(logging.INFO, logger=LOGGER)
    assert gw.chat(FRONT, CHAT_BODY).status == 200
    detail = _ledger(tmp_path)
    [line] = _lines(caplog)
    assert detail["tokens_in"] > 0 and vars(line)["tokens_in"] == detail["tokens_in"]
    assert vars(line)["tokens_estimated"] is True and detail["tokens_reported"] is True
