"""The gateway under load (T-608, D-445; deep review LLM-023): slots and a breaker per endpoint.

* **Slots.** An endpoint takes at most as many calls at a time as its server runs sequences (``max_num_seqs`` of the
  serving record, else ``TB_GATEWAY_SLOTS``). An interactive call waits :data:`INTERACTIVE_SLOT_WAIT_S` for a slot,
  then gets ``model_busy``; a batch call waits within its budget.
* **Breaker.** It opens after ``failures`` failures in a row (a connection error, a batch read timeout, an HTTP 5xx
  after the retry), or when the endpoint is stalled: calls in flight, none finished for ``stall_s``, and the server
  does not answer ``GET /models`` (:meth:`LoadControl.sweep`, from a watch thread). While open nothing is sent to
  the endpoint; after ``open_s`` one call is let through (half open): its answer closes the breaker, its failure
  opens it again.

Every clock is injectable, so the tests run in milliseconds.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

SLOTS = 16  # max_num_seqs of the measured profiles (deploy/measured/serving_config.*.json)
INTERACTIVE_SLOT_WAIT_S = 0.5
BREAKER_FAILURES = 5
BREAKER_OPEN_S = 30.0
STALL_S = 40.0
WATCH_S = 5.0
PROBE_TIMEOUT_S = 3.0
# the serving record's containers and the routing table's endpoints (deploy/measured, models/routing.yaml)
RECORD_ENDPOINTS = {"judge": "serving", "verifier": "verifier"}

Clock = Callable[[], float]
Probe = Callable[[str], bool]  # endpoint name -> its server answered GET /models


def _num(env: Mapping[str, str], name: str, default: float) -> float:
    raw = (env.get(name) or "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def record_slots(path: str | Path | None) -> dict[str, int]:
    """Endpoint -> ``max_num_seqs`` from a serving record (``tb-serving-config/1``); {} when there is none."""
    if not path:
        return {}
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, int] = {}
    for srv in doc.get("servers") or [] if isinstance(doc, dict) else []:
        if not isinstance(srv, dict):
            continue
        ep = RECORD_ENDPOINTS.get(str(srv.get("container") or ""))
        n = srv.get("max_num_seqs")
        if ep and isinstance(n, int) and not isinstance(n, bool) and n > 0:
            out[ep] = n
    return out


class Breaker:
    """One endpoint's breaker (module docstring). States: ``closed``, ``open``, ``half_open``."""

    def __init__(
        self, failures: int = BREAKER_FAILURES, open_s: float = BREAKER_OPEN_S, clock: Clock = time.monotonic
    ) -> None:
        self.failures_to_open = max(1, failures)
        self.open_s = open_s
        self.clock = clock
        self.state = "closed"
        self.reason = ""
        self.failures = 0
        self.opened_at = 0.0
        self.opens = 0
        self._probe_out = False
        self._lock = threading.Lock()

    def allow(self) -> bool:
        """True when a call may be sent now; in half-open state only one call at a time."""
        with self._lock:
            if self.state == "closed":
                return True
            if self.state == "open" and self.clock() - self.opened_at >= self.open_s:
                self.state, self._probe_out = "half_open", False
            if self.state == "half_open" and not self._probe_out:
                self._probe_out = True
                return True
            return False

    def success(self) -> None:
        with self._lock:
            self.state, self.reason, self.failures, self._probe_out = "closed", "", 0, False

    def failure(self, why: str = "failures") -> None:
        with self._lock:
            self.failures += 1
            if self.state == "half_open" or self.failures >= self.failures_to_open:
                self._open(why)
            self._probe_out = False

    def cancel(self) -> None:
        """The call let through was not sent or told nothing (no slot, an interactive timeout): another may try."""
        with self._lock:
            self._probe_out = False

    def trip(self, why: str) -> None:
        with self._lock:
            if self.state != "open":
                self._open(why)

    def _open(self, why: str) -> None:
        self.state, self.reason, self.opened_at = "open", why, self.clock()
        self.opens += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"state": self.state, "reason": self.reason, "failures": self.failures, "opens": self.opens}


class Endpoint:
    """Slots, breaker and in-flight record of one endpoint."""

    def __init__(self, name: str, slots: int, breaker: Breaker, clock: Clock) -> None:
        self.name = name
        self.slots = max(1, slots)
        self._sem = threading.BoundedSemaphore(self.slots)
        self.breaker = breaker
        self.clock = clock
        self._lock = threading.Lock()
        self._inflight: dict[int, float] = {}
        self._seq = 0
        self.last_done = clock()

    def acquire(self, wait_s: float) -> int | None:
        """A slot within ``wait_s`` seconds (a ticket for :meth:`release`), else None."""
        if not self._sem.acquire(timeout=max(0.0, wait_s)):
            return None
        with self._lock:
            self._seq += 1
            self._inflight[self._seq] = self.clock()
            return self._seq

    def release(self, ticket: int) -> None:
        with self._lock:
            self._inflight.pop(ticket, None)
            self.last_done = self.clock()
        self._sem.release()

    def stalled(self, stall_s: float) -> bool:
        """Calls in flight, the oldest older than ``stall_s``, and none finished for ``stall_s``."""
        now = self.clock()
        with self._lock:
            if not self._inflight:
                return False
            oldest = min(self._inflight.values())
            return now - oldest >= stall_s and now - self.last_done >= stall_s

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            inflight = len(self._inflight)
        return {**self.breaker.snapshot(), "slots": self.slots, "in_flight": inflight}


class LoadControl:
    """Slots and breakers of every endpoint, sized from the environment (module docstring)."""

    def __init__(
        self,
        endpoints: Iterable[str],
        env: Mapping[str, str] | None = None,
        *,
        clock: Clock = time.monotonic,
        probe: Probe | None = None,
    ) -> None:
        e = os.environ if env is None else env
        self.clock = clock
        self.probe = probe
        default = int(_num(e, "TB_GATEWAY_SLOTS", SLOTS))
        sized = record_slots(e.get("TB_SERVING_RECORD"))
        failures = int(_num(e, "TB_GATEWAY_BREAKER_FAILURES", BREAKER_FAILURES))
        open_s = _num(e, "TB_GATEWAY_BREAKER_OPEN_S", BREAKER_OPEN_S)
        self.stall_s = _num(e, "TB_GATEWAY_STALL_S", STALL_S)
        self.watch_s = _num(e, "TB_GATEWAY_WATCH_S", WATCH_S)
        self.endpoints = {
            n: Endpoint(n, sized.get(n, default), Breaker(failures, open_s, clock), clock) for n in endpoints
        }

    def get(self, name: str) -> Endpoint:
        return self.endpoints[name]

    def sweep(self) -> list[str]:
        """Open the breaker of each stalled endpoint whose server does not answer the probe; the names opened."""
        opened = []
        for ep in self.endpoints.values():
            if ep.breaker.state == "open" or not ep.stalled(self.stall_s):
                continue
            alive = False
            if self.probe is not None:
                try:
                    alive = bool(self.probe(ep.name))
                except Exception:  # a probe that fails is a server that does not answer
                    alive = False
            if not alive:
                ep.breaker.trip("stalled")
                opened.append(ep.name)
        return opened

    def loop(self, stop: threading.Event) -> None:
        while not stop.wait(self.watch_s):
            self.sweep()

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {n: ep.snapshot() for n, ep in sorted(self.endpoints.items())}

    def open(self) -> list[str]:
        return sorted(n for n, ep in self.endpoints.items() if ep.breaker.state == "open")


__all__ = ["Breaker", "Endpoint", "LoadControl", "record_slots"]
