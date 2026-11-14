"""What a batch model call does when the model does not answer (T-689, D-456; scale review F-04): it waits and is
sent again, within an allowance that belongs to the job, not to the call.

A model server that restarts answers nothing for seconds to minutes; the gateway then refuses in milliseconds
(``model_unavailable``, ``Retry-After``). A batch caller that takes each refusal as its answer loses the rest of a job
of hours in one outage. :func:`wait_and_retry` sends a call again after the gateway's ``Retry-After`` (else
:data:`POLL_S`) for as long as the job's :class:`OutageBudget` lasts, then raises :class:`OutageExhausted`: the job
stops, and the pairs it did not reach are not written as ``unknown``.

The allowance is ``TB_LLM_OUTAGE_WAIT_S`` seconds per job over all its calls and every model it uses (default
:data:`WAIT_S`). The reason for the default: a model server that restarts reloads its weights in minutes, and the
one-card layout swaps two models; past half an hour a person is needed. ``0``: no wait.

An interactive role never uses this: a person is waiting, and ``model_busy`` is its answer (D-445).
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Mapping

#: the gateway's refusals that are the model's fault (an outage, a restart, a queue), not the call's. Not among
#: them, on purpose (review of T-689): ``upstream_failed``, which is the gateway's configuration fault (a 400 or 404
#: of the model server: sending it again changes nothing) and its batch read timeout (the server may still be
#: working on the call: D-445, T-608). ``upstream_down`` is a 5xx or a transport error after the gateway's own retry
MODEL_FAULTS = frozenset({"model_busy", "model_unavailable", "model_asleep", "upstream_down"})
#: D-659: the one model fault a call can cause itself: a 5xx (or a transport error) that this request provokes while
#: the same model answers the other calls. Load and state refusals (busy, asleep, unavailable) are never the call's
CALL_FAULTS = frozenset({"upstream_down"})
#: how many such faults of one call, counted once the model was seen answering other calls, make it the call's own
#: failure: more than one, as a model coming back from a restart can refuse a call a last time after it answered
#: another one (T-689's sixteen calls in flight)
CALL_STRIKES = 3
WAIT_S = 1800.0
POLL_S = 5.0  # between two tries when the gateway named no Retry-After: its own value for a busy model
ENV = "TB_LLM_OUTAGE_WAIT_S"


def allowance_s(env: Mapping[str, str] | None = None) -> float:
    e = os.environ if env is None else env
    raw = (e.get(ENV) or "").strip()
    try:
        return max(0.0, float(raw)) if raw else WAIT_S
    except ValueError as exc:
        raise ValueError(f"{ENV} must be a number of seconds") from exc


def monotonic() -> float:
    """The budget's clock (a test replaces it)."""
    return time.monotonic()


def pause(seconds: float) -> None:
    """The wait between two tries (a test replaces it)."""
    time.sleep(seconds)


class OutageExhausted(RuntimeError):
    """The model stayed down for longer than the job's allowance."""

    def __init__(self, label: str, reason: str, spent_s: float, allowance: float) -> None:
        super().__init__(
            f"the {label} model did not answer ({reason}); waited {round(spent_s)} s, the job's whole allowance "
            f"({ENV} = {round(allowance)} s)"
        )
        self.label = label
        self.reason = reason
        self.spent_s = spent_s
        self.allowance_s = allowance


class OutageBudget:
    """One job's allowance of seconds spent in model outages, shared by its calls and its model clients.

    An outage of a client (``label``) starts at its first model fault and ends at its next answer; its length is
    charged when it ends, and while it lasts it counts as it grows. ``on_start(label, first refusal code)`` and
    ``on_end(label, first refusal code, seconds, "resumed" | "gave_up")`` are each called once per outage.
    Thread-safe (calls run side by side)."""

    def __init__(
        self,
        allowance: float | None = None,
        clock: Callable[[], float] | None = None,
        on_end: Callable[[str, str, float, str], None] | None = None,
        on_start: Callable[[str, str], None] | None = None,
    ) -> None:
        self.allowance_s = allowance_s() if allowance is None else allowance
        self.spent = 0.0
        self._clock = clock
        self._on_end = on_end
        self._on_start = on_start
        self._down: dict[str, tuple[float, str]] = {}  # client label -> (since, the first refusal code)
        self._answers: dict[str, int] = {}  # client label -> calls answered so far (D-659)
        self._used_up = False
        self._lock = threading.Lock()

    @property
    def waits(self) -> bool:
        return self.allowance_s > 0

    def _now(self) -> float:
        return self._clock() if self._clock is not None else monotonic()

    def fault(self, label: str, reason: str) -> float:
        """A call of ``label`` met a model fault; returns the seconds of allowance left (0 or less: used up)."""
        with self._lock:
            if self._used_up:  # the calls in flight beside the one that gave up: the same end, no new outage
                return 0.0
            now = self._now()
            started = label not in self._down
            self._down.setdefault(label, (now, reason))
            left = self.allowance_s - self.spent - sum(now - since for since, _ in self._down.values())
            self._used_up = left <= 0
        if started and left > 0 and self._on_start is not None:
            self._on_start(label, reason)  # the wait begins: said now, not only when it ends
        return left

    def _end(self, label: str, outcome: str) -> None:
        with self._lock:
            hit = self._down.pop(label, None)
            if hit is None:
                return
            waited = max(0.0, self._now() - hit[0])
            self.spent += waited
        if self._on_end is not None:
            self._on_end(label, hit[1], waited, outcome)

    def answers(self, label: str) -> int:
        """How many calls of ``label`` were answered so far (D-659: is the model answering others?)."""
        with self._lock:
            return self._answers.get(label, 0)

    def answered(self, label: str) -> None:
        with self._lock:
            self._answers[label] = self._answers.get(label, 0) + 1
        self._end(label, "resumed")

    def gave_up(self, label: str) -> None:
        self._end(label, "gave_up")


def wait_and_retry[T](
    send: Callable[[], T],
    budget: OutageBudget | None,
    label: str,
    fault_of: Callable[[BaseException], tuple[str, float | None] | None],
    before_try: Callable[[], None] | None = None,
) -> T:
    """``send()``, sent again after a wait while it fails with a model fault and ``budget`` lasts.

    ``fault_of(exc)``: ``(refusal code, Retry-After or None)`` for a model fault, None for any other error (raised
    as it is). ``before_try``: called before every wait step (a job's cancel check; it may raise). With no budget,
    or one of 0 s, a fault is raised at once.

    D-659: once the same model (``label``) has answered another call since this call first failed, the call's
    :data:`CALL_STRIKES`-th :data:`CALL_FAULTS` refusal counted from then is its own failure: raised as it is, as
    with no allowance, and never charged to the job (it used to be sent again until the job's whole allowance was
    gone, or without end beside answering calls)."""
    seen: int | None = None  # the model's answers when this call first failed
    strikes = 0
    while True:
        try:
            out = send()
        except Exception as exc:
            fault = fault_of(exc)
            if fault is None or budget is None or not budget.waits:
                raise
            reason, retry_after = fault
            if seen is None:
                seen = budget.answers(label)
            elif reason in CALL_FAULTS and budget.answers(label) > seen:
                strikes += 1
                if strikes >= CALL_STRIKES:
                    raise  # the model answers others: this call fails on its own (D-659)
            left = budget.fault(label, reason)
            if left <= 0:
                budget.gave_up(label)
                raise OutageExhausted(label, reason, budget.spent, budget.allowance_s) from exc
            delay = min(left, retry_after if retry_after else POLL_S)
            while delay > 0:  # in short steps, so a cancel is seen while the job waits
                if before_try is not None:
                    before_try()
                step = min(delay, POLL_S)
                pause(step)
                delay -= step
            continue
        if budget is not None:
            budget.answered(label)
        return out


__all__ = [
    "CALL_FAULTS",
    "CALL_STRIKES",
    "ENV",
    "MODEL_FAULTS",
    "POLL_S",
    "WAIT_S",
    "OutageBudget",
    "OutageExhausted",
    "allowance_s",
    "monotonic",
    "pause",
    "wait_and_retry",
]
