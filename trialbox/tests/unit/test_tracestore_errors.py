"""TRACE-ERR (D-634): the trace store's refusals are a code and a fixed sentence, never an exception's own text.
The write path takes a whole trace (model input and output): what an exception below it says must not come back."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tracestore.app import create_app
from tracestore.store import TraceAccessDenied

pytestmark = pytest.mark.nodb

LEAK = "WORDS-FROM-INSIDE-THE-TRACE-7f3a"


class Store:
    """A store that refuses, with words in the exception that must never reach a caller."""

    def count(self) -> int:
        return 0

    def write(self, trace: dict[str, Any]) -> str:
        raise ValueError(f"cannot parse {LEAK}")

    def read(self, call_id: str, **_kw: Any) -> list[dict[str, Any]]:
        raise TraceAccessDenied(f"user reading {LEAK} needs the trace:read role")

    def prune(self) -> int:
        return 0


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TB_ENV", "TEST")
    return TestClient(create_app(Store()))  # type: ignore[arg-type]


def test_a_trace_that_cannot_be_stored_is_a_code_and_a_fixed_sentence(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        r = client.post("/v1/traces", json={"tb": {}})
    assert r.status_code == 422
    assert r.json() == {"error": {"code": "trace_invalid", "message": "the trace cannot be stored as it was sent"}}
    assert LEAK not in r.text and LEAK not in caplog.text and "ValueError" in caplog.text


def test_a_read_that_is_not_allowed_is_a_code_and_a_fixed_sentence(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        r = client.get("/v1/traces/abc")
    assert r.status_code == 403
    assert r.json() == {
        "error": {"code": "trace_read_denied", "message": "a trace read needs a user, a purpose and the read role"}
    }
    assert LEAK not in r.text and LEAK not in caplog.text


def test_no_route_of_the_service_builds_an_answer_from_an_exception() -> None:
    import inspect

    import tracestore.app as app

    src = inspect.getsource(app)
    assert "str(e)" not in src and "str(exc)" not in src and "detail=" not in src
