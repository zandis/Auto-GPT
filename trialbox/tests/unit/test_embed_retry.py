"""T-701 (F-15 of the 2026-11-11 scale review), D-944: one failed batch in a thousand stopped a lake rebuild. The
embed service's client now sends a batch again when the service did not answer it for a reason of its own (no
connection, a timeout, a 5xx, a 429), after waits of 2, 5 and 15 s; a refusal of the request (a 4xx) raises at once,
and so does the fourth failure. The rebuild logs its progress. The GPU half (the rtxpro6000 profile reports cuda)
waits for the hardware.

A scripted service (httpx's mock transport); no model.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from embed_service.embedder import DIM, HttpEmbedder


def _embedder(script: list[Any]) -> tuple[HttpEmbedder, list[float], list[int]]:
    calls: list[int] = []
    waits: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        step = script[min(len(calls), len(script) - 1)]
        calls.append(1)
        if isinstance(step, Exception):
            raise step
        if step != 200:
            return httpx.Response(step, json={"detail": "x"})
        n = len(__import__("json").loads(request.content)["texts"])
        return httpx.Response(200, json={"model": "m", "dim": DIM, "vectors": [[0.0] * DIM] * n})

    e = HttpEmbedder("http://embed", sleep=waits.append)
    e.client = httpx.Client(transport=httpx.MockTransport(handler))
    return e, waits, calls


def test_a_batch_the_service_did_not_answer_is_sent_again() -> None:
    e, waits, calls = _embedder([503, httpx.ConnectError("refused"), 200])
    assert len(e.embed(["a", "b"])) == 2
    assert waits == [2.0, 5.0] and len(calls) == 3 and e.retried == 2


@pytest.mark.parametrize("status", [400, 401, 403, 422])
def test_a_refused_request_raises_at_once(status: int) -> None:
    e, waits, calls = _embedder([status])
    with pytest.raises(httpx.HTTPStatusError):
        e.embed(["a"])
    assert waits == [] and len(calls) == 1


def test_the_fourth_failure_raises() -> None:
    e, waits, calls = _embedder([500])
    with pytest.raises(httpx.HTTPStatusError):
        e.embed(["a"])
    assert waits == [2.0, 5.0, 15.0] and len(calls) == 4


def test_a_busy_service_is_waited_for() -> None:
    e, waits, _ = _embedder([429, 200])
    assert e.embed(["a"]) and waits == [2.0]
