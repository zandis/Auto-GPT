"""Job cancel and the SCREEN circuit breaker (T-108d, D-389; review R-39 / A-08, MR-076).

Before, ``cancel()`` set a flag that was read only in :meth:`orchestrator.core.Ctx.state`, which a SCREEN calls
twice: the cascade ran to its end and the work was then thrown away. And a model that hangs (the container is up,
``/health`` answers, generation never returns) cost up to 600 s a call, so a night could take days to fail.

Each job's model clients (judge and verifier) are now wrapped in a :class:`GuardedLlm`:

* **cancel**: before every model call the job's cancel flag is read; a set flag raises
  :class:`~orchestrator.core.Cancelled`, so a cancelled SCREEN stops within the pair it is on (one call), and the
  orchestrator records the job as cancelled (state ``failed``, step ``cancelled``). Cancelling twice is a no-op.
* **breaker** (SCREEN jobs): ``TB_SCREEN_BREAKER_FAILURES`` model failures in a row (default 5; 0 turns it off) open
  the breaker of that model client. An open breaker fails the job at once with a plain message
  (:class:`BreakerOpen`), and every SCREEN that starts while it is open fails the same way, without a call. After
  ``TB_SCREEN_BREAKER_WINDOW_S`` seconds (default 300) one trial call goes through: an answer closes the breaker, a
  failure opens it for another window. A prompt that does not fit, or is not qualified, is not the model being down
  and does not count. The breaker is one per orchestrator and model client, shared by its jobs.

The other job types get the cancel check only. The judge's own failure count and the end-of-run share rule
(``check_failures``) are unchanged: the breaker only stops a run sooner when the model stopped answering.
"""

from __future__ import annotations

import os
import threading
import time
import weakref
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from tb_common.llm import LlmError, LlmPromptTooLong, LlmPromptUnqualified

from orchestrator.clients import StepFailed

if TYPE_CHECKING:
    from orchestrator.core import Ctx, Orchestrator, Services

BREAKER_FAILURES = 5
BREAKER_WINDOW_S = 300.0
BREAKER_JOBS = frozenset({"SCREEN"})
NOT_DOWN = (LlmPromptTooLong, LlmPromptUnqualified)  # the request, not the model


class BreakerOpen(StepFailed):
    """The model stopped answering: the run stops now instead of waiting on every pair."""


@dataclass(frozen=True)
class BreakerSettings:
    failures: int = BREAKER_FAILURES
    window_s: float = BREAKER_WINDOW_S

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> BreakerSettings:
        e = os.environ if env is None else env
        try:
            failures = int(e.get("TB_SCREEN_BREAKER_FAILURES") or BREAKER_FAILURES)
            window = float(e.get("TB_SCREEN_BREAKER_WINDOW_S") or BREAKER_WINDOW_S)
        except ValueError as exc:
            raise ValueError("TB_SCREEN_BREAKER_FAILURES and TB_SCREEN_BREAKER_WINDOW_S must be numbers") from exc
        return cls(max(0, failures), max(1.0, window))


def monotonic() -> float:
    """The breaker's clock (a test replaces it)."""
    return time.monotonic()


class Breaker:
    """Closed, open for a window, then half open for one trial call. Thread-safe (the cascade calls side by side)."""

    def __init__(self, settings: BreakerSettings, clock: Callable[[], float] | None = None) -> None:
        self.settings = settings
        self._clock = clock
        self._lock = threading.Lock()
        self.failures = 0  # in a row
        self.opened_at: float | None = None
        self._trial = False  # a half-open trial call is out

    def _now(self) -> float:
        return self._clock() if self._clock is not None else monotonic()

    @property
    def state(self) -> str:
        with self._lock:
            return self._state()

    def _state(self) -> str:
        if self.opened_at is None:
            return "closed"
        if self._now() - self.opened_at < self.settings.window_s:
            return "open"
        return "half_open"

    def allow(self) -> bool:
        """May a call go out now? An open breaker says no; a half-open one lets exactly one trial call through."""
        if self.settings.failures <= 0:
            return True
        with self._lock:
            st = self._state()
            if st == "closed":
                return True
            if st == "half_open" and not self._trial:
                self._trial = True
                return True
            return False

    def success(self) -> None:
        with self._lock:
            self.failures, self.opened_at, self._trial = 0, None, False

    def failure(self) -> None:
        if self.settings.failures <= 0:
            return
        with self._lock:
            self.failures += 1
            if self._trial or self.failures >= self.settings.failures:
                self.opened_at, self._trial = self._now(), False

    def release(self) -> None:
        """A trial call ended neither in an answer nor in a model failure: let the next call try."""
        with self._lock:
            self._trial = False

    def seconds_left(self) -> int:
        with self._lock:
            if self.opened_at is None:
                return 0
            return max(0, int(self.settings.window_s - (self._now() - self.opened_at) + 0.999))


class GuardedLlm:
    """A job's view of one model client: the cancel check before each call and, for SCREEN, the breaker."""

    def __init__(
        self,
        inner: Any,
        should_stop: Callable[[], bool],
        breaker: Breaker | None,
        label: str,
    ) -> None:
        self.inner = inner
        self._should_stop = should_stop
        self._breaker = breaker
        self._label = label

    def __getattr__(self, name: str) -> Any:  # model, base_url, gateway, text_budget ... of the wrapped client
        return getattr(self.inner, name)

    def _call(self, fn: Callable[..., Any], *args: Any, **kw: Any) -> Any:
        if self._should_stop():
            from orchestrator.core import Cancelled

            raise Cancelled("cancelled")
        b = self._breaker
        if b is not None and not b.allow():
            raise BreakerOpen(
                "running",
                f"The {self._label} model did not answer {b.settings.failures} calls in a row, so screening stopped "
                f"instead of waiting on every patient. Nothing was sent. Check the model service (RUNBOOK §4); the "
                f"next run tries again in {b.seconds_left()} s.",
            )
        try:
            out = fn(*args, **kw)
        except NOT_DOWN:
            if b is not None:
                b.release()
            raise
        except LlmError:
            if b is not None:
                b.failure()
            raise
        except BaseException:
            if b is not None:
                b.release()
            raise
        if b is not None:
            b.success()
        return out

    def chat_json(self, *args: Any, **kw: Any) -> Any:
        return self._call(self.inner.chat_json, *args, **kw)


_BREAKERS: weakref.WeakKeyDictionary[Any, dict[int, Breaker]] = weakref.WeakKeyDictionary()
_BREAKERS_LOCK = threading.Lock()


def breaker_for(orch: Orchestrator, client: Any, settings: BreakerSettings | None = None) -> Breaker:
    """The orchestrator's breaker of one model client (created on first use, shared by the jobs)."""
    with _BREAKERS_LOCK:
        per = _BREAKERS.setdefault(orch, {})
        if id(client) not in per:
            per[id(client)] = Breaker(settings or BreakerSettings.from_env())
        return per[id(client)]


def cancel_requested(ctx: Ctx) -> Callable[[], bool]:
    job_id = ctx.job.job_id
    return lambda: ctx.orch.db.cancel_requested(job_id)


def guarded_services(ctx: Ctx, base: Services) -> Services:
    """``base`` with the job's model clients guarded. One wrapper per client object, so a verifier that is the
    judge's own client stays the same object (the two-model check of ``tb_common.pair.same_model`` still sees it)."""
    if base.llm is None and base.verifier is None:
        return base
    stop = cancel_requested(ctx)
    screen = ctx.job.type in BREAKER_JOBS
    wrapped: dict[int, GuardedLlm] = {}

    def guard(client: Any, label: str) -> Any:
        if client is None:
            return None
        if id(client) not in wrapped:
            b = breaker_for(ctx.orch, client) if screen else None
            wrapped[id(client)] = GuardedLlm(client, stop, b, label)
        return wrapped[id(client)]

    return replace(base, llm=guard(base.llm, "judge"), verifier=guard(base.verifier, "verifier"))
