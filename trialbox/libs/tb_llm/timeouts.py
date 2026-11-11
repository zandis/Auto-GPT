"""One timeout budget across the three layers of a model call (T-608, D-445; deep review LLM-023).

A caller (``tb_llm``, ``tb_common.llm``) → ``tb-gateway`` → a model server. Each layer waits longer than the one
below it, so the gateway always answers before its caller gives up and never works on a call nobody waits for:

* gateway to model: connect :data:`CONNECT_S`, read :data:`UPSTREAM_READ_S` for a batch role (an interactive role
  has the gateway's 30 s chat limit);
* one call inside the gateway: :data:`CALL_BUDGET_S`, shared by its retry and any fallback;
* caller to gateway: connect :data:`CONNECT_S`, read :data:`CALLER_TIMEOUT_S`.

A caller sends a request once more only when the connection failed or dropped (:func:`dropped`), never after a read
timeout: the gateway may still be working on it. The same body goes again, so the same role and build (T-601).
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping

import httpx

CONNECT_S = 5.0
UPSTREAM_READ_S = 180.0
CALL_BUDGET_S = 210.0
CALLER_TIMEOUT_S = 240.0
RETRY_DELAY_S = 0.5


def caller_timeout(env: Mapping[str, str] | None = None) -> httpx.Timeout:
    """The caller's limit: ``TB_LLM_TIMEOUT_S`` (read, default :data:`CALLER_TIMEOUT_S`), connect :data:`CONNECT_S`."""
    e = os.environ if env is None else env
    raw = (e.get("TB_LLM_TIMEOUT_S") or "").strip()
    try:
        read = float(raw) if raw else CALLER_TIMEOUT_S
    except ValueError:
        read = CALLER_TIMEOUT_S
    return httpx.Timeout(read, connect=min(CONNECT_S, read))


def dropped(exc: BaseException) -> bool:
    """True for a connection that failed or dropped before an answer: worth one more try. A read, write or pool
    timeout is not (the far side may still be working on the request)."""
    if isinstance(exc, httpx.ConnectTimeout):
        return True
    if isinstance(exc, httpx.TimeoutException):
        return False
    return isinstance(exc, httpx.ConnectError | httpx.RemoteProtocolError | httpx.ReadError | httpx.WriteError)


def once_more[T](send: Callable[[], T], delay_s: float | None = None) -> T:
    """``send()``, and once more after ``delay_s`` (default :data:`RETRY_DELAY_S`) when the connection dropped
    (:func:`dropped`)."""
    try:
        return send()
    except httpx.HTTPError as exc:
        if not dropped(exc):
            raise
    wait = RETRY_DELAY_S if delay_s is None else delay_s
    if wait > 0:
        time.sleep(wait)
    return send()


__all__ = [
    "CALLER_TIMEOUT_S",
    "CALL_BUDGET_S",
    "CONNECT_S",
    "RETRY_DELAY_S",
    "UPSTREAM_READ_S",
    "caller_timeout",
    "dropped",
    "once_more",
]
