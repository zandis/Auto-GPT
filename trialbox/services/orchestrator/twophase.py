"""Judge first, verifier after: two-model agreement on one GPU that holds one model at a time (survey 2026-11-07).

Both screening pipelines (v1 :func:`evaluate_patients` and the v4 cascade through ``OrchestratorJudge``) ask the
verifier right after each decided judge answer. With ``TB_MODEL_SWAP=sleep`` only one model is awake, so asking
inline would swap the GPU on every call. :func:`two_phase` runs the same screening function in rounds instead:

1. judge awake: the function runs with a :class:`MemoClient` on the judge and a :class:`DeferredVerifier`. Each
   verifier question is recorded and answered, for now, with the judge's own answer (so the run proceeds as if the
   models agreed);
2. swap to the verifier: every recorded question is answered by the real verifier, in parallel;
3. swap back to the judge and run the function again. Judge answers come from the memo (no model call), verifier
   answers from step 2, so disagreements now turn into ``unknown`` exactly as in the inline run. A disagreement can
   open a new path (the v1 full-record retry, a later cascade stage); its new questions go through steps 2-3 again.

After :data:`MAX_ROUNDS` the last run is strict: a verifier question still without an answer raises :class:`LlmError`,
which the pipelines count as a failure and turn into ``unknown`` (never an exclusion, SAFE-13). The returned result is
the last run's, so it is the inline two-model result with the same prompts and inputs; only the call order changed.

Swaps are lazy (TB-PLAN-03 step 1, D-116): the judge is woken only when a judge question has no memo answer, the
verifier only when questions are pending, and a swap to the model already awake is skipped. A run that opens no new
path after the verifier pass therefore costs one swap (judge -> verifier), and at the end the run *releases* the card
instead of swapping back: the gateway wakes the judge when the next chat or run needs it. Each real swap is followed
by an optional wake check (``probe``): a model that answers its wake questions
wrongly is not trusted for the rest of the run (its answers become errors, so ``unknown``, never an exclusion).

Without ``TB_MODEL_SWAP=sleep`` (both models resident, the GB10 and RTX PRO 6000 layouts) :func:`two_phase` simply
calls the function once with the judge as given.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields, replace
from typing import Any

import httpx
from tb_common.llm import LlmClient, LlmError, LlmResult

log = logging.getLogger(__name__)

MAX_ROUNDS = 3
COUNTERS = ("calls", "tokens_in", "tokens_out", "failures", "disagreements")


def swap_enabled(env: dict[str, str] | None = None) -> bool:
    e = os.environ if env is None else env
    return (e.get("TB_MODEL_SWAP") or "").strip().lower() == "sleep"


def _key(prompt_id: str, variables: dict[str, Any], schema: str | None) -> str:
    return json.dumps([prompt_id, schema, variables], sort_keys=True, ensure_ascii=False, default=str)


class MemoClient:
    """The judge's client, remembering every answer (or error) by prompt and variables, thread-safe."""

    def __init__(self, inner: LlmClient) -> None:
        self.inner = inner
        self.memo: dict[str, LlmResult | LlmError] = {}
        self.live_calls = 0
        self.on_live: Callable[[], None] | None = None  # wakes the judge before a call the memo cannot answer
        self.broken: str | None = None  # the judge failed its wake check: live calls fail (-> unknown)
        self._lock = threading.Lock()

    def __getattr__(self, name: str) -> Any:  # model, base_url, gateway ... of the wrapped client
        return getattr(self.inner, name)

    def lookup(self, key: str) -> LlmResult | LlmError | None:
        with self._lock:
            return self.memo.get(key)

    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> LlmResult:
        k = _key(prompt_id, variables, schema)
        hit = self.lookup(k)
        if hit is None:
            try:
                if self.on_live is not None:
                    self.on_live()
                if self.broken:
                    raise LlmError(self.broken)
                hit = self.inner.chat_json(prompt_id, variables, schema, **kw)
            except LlmError as exc:
                hit = exc
            with self._lock:
                self.memo[k] = hit
                self.live_calls += 1
        if isinstance(hit, LlmError):
            raise hit
        return hit


class DeferredVerifier:
    """Stands in for the verifier while the judge is awake (see the module docstring)."""

    def __init__(self, inner: LlmClient, judge: MemoClient) -> None:
        self.inner = inner
        self.judge = judge
        self.answers: dict[str, LlmResult | LlmError] = {}
        self.pending: dict[str, tuple[str, dict[str, Any], str | None, dict[str, Any]]] = {}
        self.strict = False
        self.live_calls = 0
        self._lock = threading.Lock()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> LlmResult:
        k = _key(prompt_id, variables, schema)
        with self._lock:
            got = self.answers.get(k)
            if got is None and not self.strict:
                self.pending.setdefault(k, (prompt_id, variables, schema, kw))
        if isinstance(got, LlmError):
            raise got
        if got is not None:
            return got
        if self.strict:
            raise LlmError("verifier answer not available after the swap rounds")
        mine = self.judge.lookup(k)  # the judge was asked the same question just before
        if isinstance(mine, LlmResult):
            return mine
        raise LlmError("deferred verifier: no judge answer to stand in for")

    def resolve(self, workers: int, broken: str | None = None) -> int:
        """Answer every pending question with the real verifier (the verifier must be awake). Returns the count.
        ``broken``: the verifier failed its wake check, so every pending question gets that error instead."""
        with self._lock:
            todo, self.pending = dict(self.pending), {}

        def one(item: tuple[str, tuple[str, dict[str, Any], str | None, dict[str, Any]]]) -> None:
            k, (pid, variables, schema, kw) = item
            try:
                if broken:
                    raise LlmError(broken)
                res: LlmResult | LlmError = self.inner.chat_json(pid, variables, schema, **kw)
            except LlmError as exc:
                res = exc
            with self._lock:
                self.answers[k] = res
                self.live_calls += 1

        with ThreadPoolExecutor(max(1, workers)) as pool:
            list(pool.map(one, todo.items()))
        return len(todo)


class GatewaySwap:
    """Asks tb-gateway to wake one model and sleep the other (``POST /v1/serving/activate``)."""

    def __init__(self, gateway_url: str, caller: str, http: httpx.Client | None = None) -> None:
        self.url = gateway_url.rstrip("/")
        self.caller = caller
        self.http = http or httpx.Client(timeout=600.0)

    @classmethod
    def from_env(cls) -> GatewaySwap | None:
        url = os.environ.get("TB_GATEWAY_URL")
        if not (url and swap_enabled()):
            return None
        return cls(url, os.environ.get("TB_SERVICE_NAME") or "orchestrator")

    def use(self, endpoint: str) -> None:
        """Wake ``endpoint`` and hold the card for this run (D-116)."""
        try:
            r = self.http.post(
                f"{self.url}/serving/activate",
                json={"endpoint": endpoint, "hold": True},
                headers={"X-TB-Caller": self.caller},
            )
        except httpx.HTTPError as exc:
            raise LlmError(f"model swap to {endpoint} failed: {type(exc).__name__}") from exc
        if r.status_code >= 400:
            raise LlmError(f"model swap to {endpoint} failed: HTTP {r.status_code} {r.text[:200]}")

    def release(self) -> None:
        """Let go of the card; the gateway wakes the judge when the next call needs it. Never raises: a release that
        fails only means the hold lapses on its own (``TB_SWAP_HOLD_S``)."""
        try:
            self.http.post(f"{self.url}/serving/release", headers={"X-TB-Caller": self.caller})
        except httpx.HTTPError as exc:
            log.warning("model swap release failed: %s", type(exc).__name__)


Swap = Callable[[str], None]
Probe = Callable[[str], str | None]  # endpoint just woken -> None when its wake check passed, else why not


class Gpu:
    """Which model this run last woke; skips a swap to the model already awake and runs the wake check after each
    real one. ``swaps`` counts the real swaps (the first wake of a run included when it changed the model)."""

    def __init__(self, swap: Swap, probe: Probe | None = None) -> None:
        self.swap = swap
        self.probe = probe
        self.awake: str | None = None
        self.swaps = 0
        self.broken: dict[str, str] = {}  # endpoint -> why it failed its wake check (kept for the rest of the run)
        self._lock = threading.Lock()

    def use(self, endpoint: str) -> None:
        with self._lock:
            if self.awake == endpoint:
                return
            self.swap(endpoint)
            first, self.awake = self.awake is None, endpoint
            if not first:
                self.swaps += 1
            if self.probe is not None and endpoint not in self.broken:
                why = self.probe(endpoint)
                if why:
                    self.broken[endpoint] = why
                    log.error("%s failed its wake check, its answers are not used this run: %s", endpoint, why)


def two_phase[J, R](
    judge: J,
    run: Callable[[J], R],
    swap: Swap | None = None,
    *,
    workers: int | None = None,
    release: Callable[[], None] | None = None,
    probe: Probe | None = None,
) -> R:
    """Run ``run(judge)`` with the verifier deferred to after the judge pass when the GPU is time-shared.

    ``judge`` is a :class:`NoteJudge` or ``OrchestratorJudge`` (anything with ``llm``, ``verifier`` and the
    :data:`COUNTERS` fields); its counters end up as those of the final round. ``swap`` (and ``release``) default to
    :meth:`GatewaySwap.from_env`; ``None`` there (no swap configured) means one plain run.
    ``probe``: the wake check run after each real swap."""
    if swap is None:
        gs = GatewaySwap.from_env()
        if gs is not None:
            swap, release = gs.use, release or gs.release
    if swap is None or judge is None or getattr(judge, "verifier", None) is None:
        return run(judge)
    n = workers or int(os.environ.get("TB_SCREEN_WORKERS") or 4)
    gpu = Gpu(swap, probe)
    memo = MemoClient(judge.llm)  # type: ignore[attr-defined]
    dv = DeferredVerifier(judge.verifier, memo)  # type: ignore[attr-defined]

    def wake_judge() -> None:
        gpu.use("serving")
        memo.broken = gpu.broken.get("serving")

    memo.on_live = wake_judge
    names = {f.name for f in fields(judge)}  # type: ignore[arg-type]
    reset = {c: 0 for c in COUNTERS if c in names}
    out: R
    j: J = judge
    try:
        for rnd in range(1, MAX_ROUNDS + 1):
            dv.strict = rnd == MAX_ROUNDS
            j = replace(judge, llm=memo, verifier=dv, **reset)  # type: ignore[type-var]
            out = run(j)
            if not dv.pending or dv.strict:  # strict rounds record nothing
                break
            gpu.use("verifier")
            asked = dv.resolve(n, broken=gpu.broken.get("verifier"))
            log.info("two_phase round %d: %d verifier questions answered", rnd, asked)
    finally:
        if release is not None:
            release()  # the gateway wakes the judge for the next chat or run (no swap back here)
    log.info("two_phase: %d swap(s), wake checks failed: %s", gpu.swaps, sorted(gpu.broken) or "none")
    for c in reset:
        setattr(judge, c, getattr(j, c))
    return out


__all__ = ["MAX_ROUNDS", "DeferredVerifier", "GatewaySwap", "Gpu", "MemoClient", "swap_enabled", "two_phase"]
