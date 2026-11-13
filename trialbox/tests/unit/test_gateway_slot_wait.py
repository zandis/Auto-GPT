"""GW-SLOTWAIT (D-627): the gateway's audit record of a call names how long the call waited for a slot. Until
here a slow run could not be told apart from the audit: a slow model server, or a queue in front of it."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from llm_stub.app import app as stub

from tests.unit.test_gateway import _records
from tests.unit.test_gateway_under_load import FRONT, _silent_gw
from tests.unit.test_model_swap import CHAT_BODY


def _calls(tmp_path: Path) -> list[dict[str, Any]]:
    return [r for r in _records(tmp_path) if str(r.get("event", "")).startswith("llm.gateway.") and "detail" in r]


def test_a_call_with_a_free_slot_waited_next_to_nothing(tmp_path: Path) -> None:
    gw = _silent_gw(tmp_path, 9)
    gw.http = TestClient(stub)
    assert gw.chat(FRONT, CHAT_BODY).status == 200
    rec = _calls(tmp_path)[-1]
    assert rec["event"] == "llm.gateway.call"
    wait = rec["detail"]["slot_wait_ms"]
    assert isinstance(wait, (int, float)) and 0 <= wait < 500


class _Clock:
    """The gateway's clock for one test: ``perf_counter`` moves only when the test moves it; the rest is the real
    ``time`` module. A bound in real milliseconds measured the machine (386 ms on a loaded runner), not the gateway."""

    def __init__(self) -> None:
        self.now = 1000.0

    def perf_counter(self) -> float:
        return self.now

    def __getattr__(self, name: str) -> Any:
        return getattr(time, name)


def test_the_time_in_the_queue_is_recorded_and_is_not_the_servers_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import gateway.core as core

    clock = _Clock()
    monkeypatch.setattr(core, "time", clock)
    gw = _silent_gw(tmp_path, 9)
    gw.http = TestClient(stub)
    lane = gw.load.get("stub")
    real = lane.acquire

    def queued(wait_s: float) -> int | None:
        clock.now += 0.25  # a quarter of a second in the queue in front of the server
        return real(wait_s)

    lane.acquire = queued  # type: ignore[method-assign]
    assert gw.chat(FRONT, CHAT_BODY).status == 200
    d = _calls(tmp_path)[-1]["detail"]
    assert d["slot_wait_ms"] == 250.0
    assert d["latency_ms"] == 0.0  # no time passed at the server: the wait is not counted as the server's time


def test_a_call_sent_away_busy_says_how_long_it_waited(tmp_path: Path) -> None:
    gw = _silent_gw(tmp_path, 9)
    gw.http = TestClient(stub)
    lane = gw.load.get("stub")
    held = [lane.acquire(0) for _ in range(lane.slots)]
    res = gw.chat(FRONT, CHAT_BODY)
    assert res.status == 503 and res.body["error"]["code"] == "model_busy"
    rec = _calls(tmp_path)[-1]
    assert rec["event"] != "llm.gateway.call"
    assert rec["detail"]["slot_wait_ms"] > 0
    for tk in held:
        assert tk is not None
        lane.release(tk)
