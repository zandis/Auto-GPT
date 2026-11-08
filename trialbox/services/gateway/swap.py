"""Time-share one GPU between the judge and the verifier with vLLM sleep mode (one RTX 5090; survey 2026-11-07).

On a 32 GB card the two 4-bit models do not fit side by side with useful KV cache (35 GiB measured on 2026-11-06), so
``TB_MODEL_SWAP=sleep`` keeps one awake at a time. Both vLLM servers run with ``--enable-sleep-mode`` (and
``VLLM_SERVER_DEV_MODE=1``, which exposes ``/sleep``, ``/wake_up`` and ``/is_sleeping``). Level-1 sleep moves the
weights to host memory and drops the KV cache; waking copies them back in seconds, not the minutes of a cold start.

Only the gateway reaches the model servers (LLM-1, model-net), so the swap lives here and callers ask for it through
``POST /v1/serving/activate``. The gateway also uses the state on the request path: a call routed to the endpoint
that is asleep is not sent; an interactive role (front-desk chat) gets ``model_busy`` at once instead of waiting.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Mapping
from typing import Any

import httpx

SWAPPABLE = ("serving", "verifier")  # routing.yaml endpoints of the judge (J) and verifier (V) builds


class SwapError(RuntimeError):
    pass


def server_root(url: str) -> str:
    """vLLM's admin endpoints sit at the server root, the OpenAI API under ``/v1``."""
    u = url.rstrip("/")
    return u[: -len("/v1")] if u.endswith("/v1") else u


class ModelSwap:
    def __init__(
        self,
        urls: Mapping[str, str],
        *,
        http: httpx.Client | None = None,
        wake_timeout_s: float = 300.0,
        poll_s: float = 1.0,
        sleep_level: int = 1,
    ) -> None:
        self.urls = {k: server_root(v) for k, v in urls.items() if v}
        self.http = http or httpx.Client(timeout=120.0)
        self.wake_timeout_s = wake_timeout_s
        self.poll_s = poll_s
        self.sleep_level = sleep_level
        self.active: str | None = None  # None until the first activate: state unknown, nothing is held back
        self.swaps = 0
        self.last_swap_s = 0.0
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls, endpoint_urls: Mapping[str, str], env: Mapping[str, str] | None = None) -> ModelSwap | None:
        e = os.environ if env is None else env
        if (e.get("TB_MODEL_SWAP") or "").strip().lower() != "sleep":
            return None
        return cls(
            {k: endpoint_urls.get(k, "") for k in SWAPPABLE},
            wake_timeout_s=float(e.get("TB_SWAP_WAKE_TIMEOUT_S") or 300),
        )

    def awake(self, endpoint: str) -> bool:
        """False only for a swappable endpoint known to be asleep."""
        return endpoint not in self.urls or self.active is None or self.active == endpoint

    def status(self) -> dict[str, Any]:
        return {"swap": "sleep", "active": self.active, "swaps": self.swaps, "last_swap_s": self.last_swap_s}

    def activate(self, endpoint: str) -> dict[str, Any]:
        if endpoint not in self.urls:
            raise SwapError(f"{endpoint!r} is not a swappable endpoint ({', '.join(sorted(self.urls))})")
        with self._lock:
            if self.active == endpoint:
                return self.status()
            t0 = time.perf_counter()
            self.active = "-"  # mid-swap: neither endpoint takes calls
            try:
                for other in self.urls:
                    if other != endpoint:
                        self._post(other, f"/sleep?level={self.sleep_level}")
                self._post(endpoint, "/wake_up")
                self._wait_awake(endpoint)
            except SwapError:
                self.active = None  # unknown again; the next activate retries both steps
                raise
            self.active = endpoint
            self.swaps += 1
            self.last_swap_s = round(time.perf_counter() - t0, 2)
            return self.status()

    def _post(self, endpoint: str, path: str) -> None:
        try:
            r = self.http.post(self.urls[endpoint] + path)
        except httpx.HTTPError as exc:
            raise SwapError(f"{endpoint}{path}: {type(exc).__name__}") from exc
        if r.status_code >= 400:
            raise SwapError(
                f"{endpoint}{path}: HTTP {r.status_code} (is the server started with --enable-sleep-mode"
                " and VLLM_SERVER_DEV_MODE=1?)"
            )

    def _wait_awake(self, endpoint: str) -> None:
        deadline = time.monotonic() + self.wake_timeout_s
        while True:
            try:
                r = self.http.get(self.urls[endpoint] + "/is_sleeping")
                if r.status_code < 400 and not bool(r.json().get("is_sleeping")):
                    return
            except (httpx.HTTPError, ValueError):
                pass
            if time.monotonic() > deadline:
                raise SwapError(f"{endpoint} did not wake within {self.wake_timeout_s:.0f}s")
            time.sleep(self.poll_s)


__all__ = ["SWAPPABLE", "ModelSwap", "SwapError", "server_root"]
