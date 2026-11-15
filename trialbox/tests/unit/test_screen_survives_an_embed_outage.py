"""Red of lane G's accuracy run (#639, 2026-11-15), the SCREEN half: the embed service restarted mid-run and the job
failed at its first unanswered request, saying only "stopped answering".

Now SCREEN waits for the service to come back, as it waits for a model (T-689): a request that fails in transport (a
dropped connection, a refused one, a 5xx) is sent again after a growing wait, until ``TB_EMBED_OUTAGE_WAIT_S`` seconds
of the job are spent waiting. When it gives up, the job's sentence says how far it got (requests and sentences
embedded) and that the sentences already embedded are kept, so the request sent again starts where this one stopped.
Synthetic: a stand-in service and a fake clock.
"""

from __future__ import annotations

import httpx
import pytest
from matching.cascade.engine import CascadeError
from orchestrator.scenarios import screen_cascade as sc


class _Flaky:
    model = "e-embed-1"

    def __init__(self, fail: int, error: Exception) -> None:
        self.fail, self.error, self.calls = fail, error, 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        if self.calls <= self.fail:
            raise self.error
        return [[float(len(t)), 1.0] for t in texts]


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sc, "_VECTORS", sc._VectorCache(100))


def test_a_restart_of_the_service_is_waited_out(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock()
    inner = _Flaky(3, httpx.RemoteProtocolError("Server disconnected without sending a response."))
    served = sc._Served(inner, clock=clock.now, sleep=clock.sleep)
    assert served.embed(["a", "bb"]) == [[1.0, 1.0], [2.0, 1.0]]
    assert inner.calls == 4 and len(clock.slept) == 3 and clock.slept == sorted(clock.slept)  # growing waits


def test_giving_up_says_how_far_it_got_and_that_the_rest_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_EMBED_OUTAGE_WAIT_S", "60")
    clock = _Clock()
    inner = _Flaky(0, httpx.ConnectError("refused"))
    served = sc._Served(inner, clock=clock.now, sleep=clock.sleep)
    served.embed(["one", "two", "three"])  # answered: 1 request, 3 sentences
    inner.fail, inner.calls = 10**6, 0
    with pytest.raises(CascadeError) as err:
        served.embed(["four"])
    msg = str(err.value)
    assert "1 request" in msg and "3 sentences" in msg and "kept" in msg and "ConnectError" in msg
    assert sum(clock.slept) <= 60 + 30  # the allowance, and at most one wait past it


def test_an_answer_that_is_not_a_transport_fault_is_not_retried() -> None:
    clock = _Clock()
    inner = _Flaky(1, ValueError("bad vectors"))
    served = sc._Served(inner, clock=clock.now, sleep=clock.sleep)
    with pytest.raises(CascadeError):
        served.embed(["a"])
    assert inner.calls == 1 and clock.slept == []


def test_a_5xx_is_a_transport_fault() -> None:
    req = httpx.Request("POST", "http://embed-service:8014/embed")
    err = httpx.HTTPStatusError("503", request=req, response=httpx.Response(503, request=req))
    assert sc._transport_fault(err) and not sc._transport_fault(
        httpx.HTTPStatusError("422", request=req, response=httpx.Response(422, request=req))
    )


def test_the_allowance_is_declared() -> None:
    from tb_common.config import DECLARED

    assert "TB_EMBED_OUTAGE_WAIT_S" in DECLARED
