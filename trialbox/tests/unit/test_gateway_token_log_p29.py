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
from tb_common.llm import load_prompt, render
from tb_common.logging import JsonFormatter

from tests.unit.test_gateway import _records
from tests.unit.test_gateway_under_load import FRONT, _silent_gw
from tests.unit.test_model_swap import CHAT_BODY

LOGGER = "gateway.tokens"


def _server(usage: Any, seen: list[str] | None = None, answer: str | None = None) -> httpx.Client:
    """The stub's answer with ``usage`` put in its place (``...`` keeps the stub's own; None drops it) and, with
    ``answer``, that text as the model's answer."""
    inner = TestClient(stub)
    answers = [] if seen is None else seen

    def handle(request: httpx.Request) -> httpx.Response:
        got = inner.post(request.url.path, content=request.content, headers=dict(request.headers))
        body = got.json()
        if answer is not None:
            body["choices"][0]["message"]["content"] = answer
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


#: synthetic markers (letters only: the log scrubber masks digit runs and identifiers, not these)
SHORT_ASKED = "Wqxjz"  # five characters, alone on a line of the user's message
LONG_ASKED = "the plover counted seventeen teal on the far shore"
SHORT_ANSWER = "Qzkvw"
#: a three-line answer in the classify_intent schema, one line holding a short marker
ANSWER = '{"type": "ASK", "language": "en",\n "question": "Qzkvw",\n "scope": "kestrel-heron-bittern"}'


def _body(text: str) -> dict[str, Any]:
    """CHAT_BODY with the user's text replaced (the registered template, rendered; D-300)."""
    return {
        **CHAT_BODY,
        "messages": render(
            load_prompt("classify_intent_v1"),
            {"text": text, "attachments": [], "today": "2026-11-10", "language": "en"},
        ),
    }


def _leaks(line: logging.LogRecord, markers: tuple[str, ...], answer: str) -> list[str]:
    """What of the prompt or the answer a log line holds: in the written text, in the parsed record's values and in
    the record's own attributes."""
    written = JsonFormatter("gateway").format(line)
    values = " ".join(str(v) for v in json.loads(written).values())
    attrs = " ".join(str(v) for v in vars(line).values())
    found = [m for m in markers if any(m in where for where in (written, values, attrs))]
    if json.dumps(answer)[1:-1] in written or answer in attrs:
        found.append("the whole answer")
    return found


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


def test_the_log_line_holds_no_word_of_the_prompt_or_the_answer(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    gw = _silent_gw(tmp_path, 9)
    gw.http = _server({"prompt_tokens": 12, "completion_tokens": 7}, answer=ANSWER)
    caplog.set_level(logging.INFO, logger=LOGGER)
    res = gw.chat(FRONT, _body(f"how many patients for study X?\n{SHORT_ASKED}\n{LONG_ASKED}"))
    assert res.status == 200 and res.body["choices"][0]["message"]["content"] == ANSWER
    [line] = _lines(caplog)
    assert _leaks(line, (SHORT_ASKED, LONG_ASKED, SHORT_ANSWER), ANSWER) == []


def test_the_leak_check_sees_a_short_id_and_a_multi_line_answer() -> None:
    """The check above can fail: a record that carries the short marker, or the multi-line answer, is caught."""
    planted = logging.LogRecord(LOGGER, logging.INFO, __file__, 1, "call %s", ("x",), None)
    planted.note = f"asked {SHORT_ASKED}"
    assert _leaks(planted, (SHORT_ASKED, LONG_ASKED, SHORT_ANSWER), ANSWER) == [SHORT_ASKED]
    answered = logging.LogRecord(LOGGER, logging.INFO, __file__, 1, "said %s", (ANSWER,), None)
    found = _leaks(answered, (SHORT_ASKED, LONG_ASKED, SHORT_ANSWER), ANSWER)
    assert SHORT_ANSWER in found and "the whole answer" in found


@pytest.mark.parametrize(
    "usage",
    [{"prompt_tokens": "unknown", "completion_tokens": 45}, {"prompt_tokens": [1], "completion_tokens": 45}, "n/a"],
)
def test_a_count_that_is_not_a_number_does_not_fail_the_call(
    usage: Any, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    gw = _silent_gw(tmp_path, 9)
    gw.http = _server(usage, answer=ANSWER)
    caplog.set_level(logging.INFO, logger=LOGGER)
    res = gw.chat(FRONT, CHAT_BODY)
    assert res.status == 200 and res.body["choices"][0]["message"]["content"] == ANSWER
    detail = _ledger(tmp_path)
    assert detail["tokens_in"] == 0 and detail["tokens_reported"] is False
    [line] = _lines(caplog)
    assert vars(line)["tokens_in"] == 0 and vars(line)["tokens_reported"] is False


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
