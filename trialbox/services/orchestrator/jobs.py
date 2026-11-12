"""Snapshot pinning (T-305a, D-383, CR-063): every job reads one lake snapshot from its first lake call to its end.

Before, a scenario read ``CURRENT`` once for its report and then queried without naming a snapshot: a nightly publish
that landed mid-job moved the later queries to the new night, so one candidate list mixed two nights. Now each job's
:class:`~orchestrator.core.Ctx` hands its scenario a :class:`PinnedLake`:

* the first lake call pins ``CURRENT`` (or the job's recorded ``snapshot_date``, the pin field, for a resumed job and
  a reproducibility re-run) and records it on the job; every later query and note search names that snapshot;
* a job that never touches the lake (STATUS, HELP, APPROVE) pins nothing and is never refused;
* when it pins ``CURRENT``, the snapshot's age is checked against ``TB_LAKE_MAX_SNAPSHOT_AGE_DAYS`` (the job's run
  date, so a frozen clock decides): a stale snapshot fails the job with a plain message instead of screening on a
  lake that stopped updating days ago. A recorded pin is not checked again (a re-run of an old job must work).

T-305b (D-403): the pin is also a *hold* on the lake (``Lake.hold``, keyed by the job id): while the job runs, or
waits for an approval, its snapshot is never rebuilt under it (a site publish on ``main`` waits and is applied after;
see ``sitesetup.service``) and never pruned. The orchestrator releases the hold when the job ends
(:func:`release_hold`).

The same module holds job cancel and the SCREEN circuit breaker (T-108d, D-389; review R-39 / A-08, MR-076):

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

T-689 (D-456; scale review F-04, F-28, F-31): a job of hours must outlive a model outage and a restart of this
service.

* **wait and retry**: a call that fails because the model did not answer (:class:`tb_common.llm.LlmModelFault`: the
  gateway's ``model_busy``, ``model_unavailable``, ``model_asleep``, ``upstream_down``, an endpoint that cannot be
  reached, a 5xx without a refusal code; never a timeout and never the gateway's configuration fault
  ``upstream_failed``) is not an answer of ``unknown``. The call sleeps the gateway's ``Retry-After`` and is sent again
  (:func:`tb_llm.outage.wait_and_retry`), until the job's outage allowance is used up
  (:class:`tb_llm.outage.OutageBudget`: ``TB_LLM_OUTAGE_WAIT_S`` seconds per job over all its calls and both models,
  not per call). Then the job fails at
  once (:class:`ModelOutage`). A model fault never counts in the breaker, and the breaker's threshold is at least
  twice the calls in flight, so one blip that fails them all together cannot open it.
* **kept answers**: every answer a SCREEN or MICROBATCH job's model client gives is kept in ``orch.judge_answers``
  (:class:`KeptAnswers`) while the job is unfinished. After a restart the job runs again from its start and a call
  with the same role, snapshot, prompt and variables gets the kept answer, if the build that gave it is the build
  that answers that role in this run (the build of the role's latest live answer; unknown: nothing is replayed).
  So a list is never of two builds of one role, and each run asks at least one call per role live.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import logging
import os
import threading
import time
import weakref
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date
from typing import TYPE_CHECKING, Any

from tb_common.llm import (
    LlmError,
    LlmModelFault,
    LlmPromptTooLong,
    LlmPromptUnqualified,
    LlmResult,
    load_prompt,
)
from tb_llm.outage import ENV as OUTAGE_ENV
from tb_llm.outage import OutageBudget, OutageExhausted, wait_and_retry

from orchestrator.clients import StepFailed

if TYPE_CHECKING:
    from orchestrator.core import Ctx, Orchestrator, Services

log = logging.getLogger("orchestrator")


class PinnedLake:
    """A job's view of the lake: every query and note search on the one snapshot it pinned."""

    def __init__(
        self,
        lake: Any,
        today: Callable[[], date],
        max_age_days: int,
        pinned: str | None = None,
        on_pin: Callable[[str], None] | None = None,
        holder: str | None = None,
    ) -> None:
        self.lake = lake
        self.pinned = pinned
        self.holder = holder
        self.held = False
        self._today = today
        self._max_age = max_age_days
        self._on_pin = on_pin
        self._lock = threading.Lock()

    def pin(self) -> str | None:
        """The job's snapshot: pinned on the first call (``CURRENT``, checked for age); None while the lake has none."""
        with self._lock:
            if self.pinned is None:
                current = getattr(self.lake, "snapshot", None)  # a test's fake lake may have no CURRENT at all
                snap = current() if current is not None else None
                if not snap:
                    return None
                from lake.store import StaleSnapshotError, check_snapshot_age

                try:
                    check_snapshot_age(snap, self._today(), self._max_age)
                except StaleSnapshotError as exc:
                    raise StepFailed("running", str(exc)) from None
                self.pinned = snap
                if self._on_pin is not None:
                    self._on_pin(snap)
            if not self.held:
                self._hold(self.pinned)
            return self.pinned

    def _hold(self, snap: str) -> None:
        """Hold the pinned snapshot on the lake for this job (D-403). A lake without holds (a test's fake) or a
        snapshot that is gone (an old re-run) is said in the log, never a failure: the pin still names the snapshot."""
        hold = getattr(self.lake, "hold", None)
        self.held = True
        if hold is None or not self.holder:
            return
        try:
            hold(snap, self.holder)
        except Exception as exc:
            log.warning("job %s: lake snapshot %s not held (%s)", self.holder, snap, type(exc).__name__)

    def release(self) -> None:
        """End this job's hold (the job is done, failed or cancelled)."""
        release = getattr(self.lake, "release", None)
        if not self.held or release is None or not self.holder:
            return
        try:
            release(self.holder)
        except Exception as exc:  # a lake that is down keeps the hold until it expires (Lake.HOLD_TTL_SECONDS)
            log.warning("job %s: lake hold not released (%s)", self.holder, type(exc).__name__)
        self.held = False

    def snapshot(self) -> str | None:
        return self.pin()

    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any:
        return self.lake.query(sql, params, snapshot or self.pin())

    def chunks_search(
        self,
        pid: str,
        query: str,
        k: int = 5,
        date_from: date | None = None,
        date_to: date | None = None,
        snapshot: str | None = None,
    ) -> Any:
        return self.lake.chunks_search(pid, query, k, date_from, date_to, snapshot=snapshot or self.pin())

    def __getattr__(self, name: str) -> Any:  # put_site, rebuild and the rest: the lake itself
        return getattr(self.lake, name)


def pinned_services(ctx: Ctx) -> Services:
    """The job's services: the orchestrator's, with the lake pinned for this job (none when there is no lake)."""
    base = ctx.orch.services
    if base.lake is None:
        return base
    job = ctx.job

    def record(snap: str) -> None:
        if ctx.job.snapshot_date is None:
            with contextlib.suppress(ValueError):  # a snapshot not named after a night (only with the age check off)
                ctx.update(snapshot_date=date.fromisoformat(snap))

    lake = PinnedLake(
        base.lake,
        today=ctx.today,
        max_age_days=ctx.cfg.env.lake_max_snapshot_age_days,
        pinned=job.snapshot_date.isoformat() if job.snapshot_date else None,
        on_pin=record,
        holder=job.job_id,
    )
    return replace(base, lake=lake)


def release_hold(services: Services | None, holder: str | None = None) -> None:
    """End the job's lake hold (D-403): its pinned lake's, or, for a job that resumed in a new process and never
    touched the lake again, the hold the lake still keeps under the job's id."""
    lake = services.lake if services is not None else None
    if isinstance(lake, PinnedLake):
        if lake.held:
            lake.release()
            return
        lake = lake.lake
    release = getattr(lake, "release", None)
    if release is not None and holder:
        try:
            release(holder)
        except Exception as exc:
            log.warning("job %s: lake hold not released (%s)", holder, type(exc).__name__)


# ------------------------------------------------------------------------- cancel and the SCREEN breaker (T-108d)
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
        if failures > 0:
            # T-689 (F-31): the calls in flight fail together on one event; "in a row" means more than two rounds
            failures = max(failures, 2 * llm_concurrency(e))
        return cls(max(0, failures), max(1.0, window))


def llm_concurrency(env: Mapping[str, str] | None = None) -> int:
    """Model calls a screening job has in flight (``TB_SCREEN_LLM_CONCURRENCY``; compose sets it to the serving
    profile's ``--max-num-seqs``)."""
    e = os.environ if env is None else env
    try:
        return max(1, min(64, int(e.get("TB_SCREEN_LLM_CONCURRENCY") or 1)))
    except ValueError:
        return 1


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


# ------------------------------------------------------------------------- restarts (T-689, D-456; review F-28)
# restarts of this service one job may survive (TB_JOB_MAX_RESTARTS). The reason: the restart may be the job's own
# doing (an out-of-memory kill), and without a count the box loops on it; three covers an update and two faults
MAX_RESTARTS = 3


def max_restarts(env: Mapping[str, str] | None = None) -> int:
    e = os.environ if env is None else env
    raw = (e.get("TB_JOB_MAX_RESTARTS") or "").strip()
    try:
        return max(0, int(raw)) if raw else MAX_RESTARTS
    except ValueError as exc:
        raise ValueError("TB_JOB_MAX_RESTARTS must be a whole number") from exc


# ------------------------------------------------------------------------- outages and kept answers (T-689, D-456)
REPLAY_JOBS = frozenset({"SCREEN", "MICROBATCH"})


class ModelOutage(StepFailed):
    """The model stayed down for longer than the job's outage allowance (:mod:`tb_llm.outage`): the job stops,
    nothing is written as ``unknown`` for the pairs it did not reach."""


def _model_fault(exc: BaseException) -> tuple[str, float | None] | None:
    return (exc.reason, exc.retry_after) if isinstance(exc, LlmModelFault) else None


class KeptAnswers:
    """The answers one job's model clients gave, in ``orch.judge_answers`` (T-689, D-456): written as they arrive,
    read back when the job runs again after a restart. Only :class:`tb_common.llm.LlmResult` answers are kept,
    never an error. The key names the client's role, the job's pinned snapshot, the prompt (id and file sha, so an
    update that changes the prompt between two starts replays nothing stale) and the variables.

    **The build** (review of T-689): a kept answer stands in only when its ``build_sha`` is the build that answers
    its role in this run, which is the build of the role's latest live answer here. Until a role has answered live
    in this run, or when the client names no build (a direct endpoint), nothing of that role is replayed. An update
    that changes the routed build between two starts therefore replays nothing of the old build, and its kept
    answers are replaced as the new build answers."""

    def __init__(self, db: Any, job_id: str, snapshot: Callable[[], str], now: Callable[[], str]) -> None:
        self._db = db
        self.job_id = job_id
        self._snapshot = snapshot
        self._now = now
        self.replayed = 0
        self._build: dict[str, str] = {}  # role -> the build of its latest live answer in this run
        self._lock = threading.Lock()

    def key(self, label: str, inner: Any, prompt_id: str, variables: Any, schema: str | None) -> str | None:
        try:
            env = getattr(inner, "_prompt_env", None) or getattr(
                getattr(inner, "gateway", None), "prompt_environment", None
            )
            sha = load_prompt(prompt_id, env).sha256
            body = json.dumps(
                [label, self._snapshot(), prompt_id, sha, schema, variables],
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            )
        except Exception:  # a prompt that cannot be loaded, variables that cannot be written: asked live, not kept
            return None
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def get(self, key: str, label: str) -> LlmResult | None:
        with self._lock:
            build = self._build.get(label)
        if not build:  # the role has not answered live in this run, or names no build: asked live
            return None
        raw = self._db.answer_get(self.job_id, key)
        if raw is None:
            return None
        try:
            out = LlmResult(**json.loads(raw))
        except (TypeError, ValueError):  # written by another build of the code: asked again
            return None
        if out.build_sha != build:  # another build of the model said it: asked again
            return None
        with self._lock:
            self.replayed += 1
        return out

    def put(self, key: str, result: Any, label: str) -> None:
        if not isinstance(result, LlmResult):
            return
        with self._lock:
            self._build[label] = result.build_sha
        try:
            raw = json.dumps(dataclasses.asdict(result), ensure_ascii=False)
        except (TypeError, ValueError):
            return
        other = False  # a kept answer of another build gives way; one of the same build stays (the first)
        old = self._db.answer_get(self.job_id, key)
        if old is not None:
            try:
                other = json.loads(old).get("build_sha") != result.build_sha
            except (TypeError, ValueError, AttributeError):
                other = True
        self._db.answer_put(self.job_id, key, raw, self._now(), replace=other)


class GuardedLlm:
    """A job's view of one model client: the cancel check before each call, the wait on a model outage, the kept
    answers of a screening job and, for SCREEN, the breaker."""

    def __init__(
        self,
        inner: Any,
        should_stop: Callable[[], bool],
        breaker: Breaker | None,
        label: str,
        outage: OutageBudget | None = None,
        answers: KeptAnswers | None = None,
    ) -> None:
        self.inner = inner
        self._should_stop = should_stop
        self._breaker = breaker
        self._label = label
        self._outage = outage
        self._answers = answers

    def __getattr__(self, name: str) -> Any:  # model, base_url, gateway, text_budget ... of the wrapped client
        return getattr(self.inner, name)

    def _check_stop(self) -> None:
        if self._should_stop():
            from orchestrator.core import Cancelled

            raise Cancelled("cancelled")

    def _call(self, fn: Callable[..., Any], *args: Any, **kw: Any) -> Any:
        """``fn``, sent again after a wait while the model does not answer and the job's allowance lasts."""
        waiting = self._outage is not None and self._outage.waits
        try:
            return wait_and_retry(
                lambda: self._once(fn, waiting, *args, **kw), self._outage, self._label, _model_fault, self._check_stop
            )
        except OutageExhausted as exc:
            raise ModelOutage(
                "running",
                f"The {exc.label} model did not answer ({exc.reason}) and this job has waited "
                f"{round(exc.spent_s)} s for it, its whole allowance ({OUTAGE_ENV} = {round(exc.allowance_s)} s), so "
                f"the job stopped. Nothing was sent. Check the model service (RUNBOOK §4) and send the request again "
                f"when the model is back.",
            ) from exc

    def _once(self, fn: Callable[..., Any], waiting: bool, *args: Any, **kw: Any) -> Any:
        self._check_stop()
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
        except LlmPromptUnqualified as exc:
            # the gateway (or the registry) refuses this prompt version as unqualified (D-359): the next call is
            # refused with the same words, so the job stops here. It is not a model failure (the breaker), and a job
            # that went on would ask every pair and end as "the model did not answer" (review of 2026-11-12).
            if b is not None:
                b.release()
            prompt = str(args[0]) if args and isinstance(args[0], str) else "a prompt"
            raise StepFailed(
                "running",
                f"The {self._label} model's gateway refused {prompt} as unqualified (prompt_unqualified: {exc}), "
                f"and it refuses every further call the same way, so the job stopped at the first one. No model "
                f"was asked and nothing was sent. The model service is not the cause: this box does not serve that "
                f"prompt version. Approve the study again on this box (it then pins the served version), or install "
                f"the prompt's qualification record.",
            ) from exc
        except NOT_DOWN:
            if b is not None:
                b.release()
            raise
        except LlmModelFault:
            if b is not None:
                if waiting:  # T-689: the job waits for the model; an outage is not a failure in a row
                    b.release()
                else:
                    b.failure()
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
        key = None
        if self._answers is not None and len(args) >= 2:
            schema = args[2] if len(args) > 2 else kw.get("schema")
            key = self._answers.key(self._label, self.inner, str(args[0]), args[1], schema)
        if key is not None and self._answers is not None:
            self._check_stop()
            kept = self._answers.get(key, self._label)
            if kept is not None:
                return kept
        out = self._call(self.inner.chat_json, *args, **kw)
        if key is not None and self._answers is not None:
            self._answers.put(key, out, self._label)
        return out


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
    job_id = ctx.job.job_id

    def outage_ended(label: str, reason: str, waited: float, outcome: str) -> None:
        ctx.orch.audit.append(
            "llm.outage",
            job_id=job_id,
            detail={"model": label, "reason": reason, "waited_s": round(waited, 1), "outcome": outcome},
        )

    def outage_started(label: str, reason: str) -> None:
        # review of T-689: the person who looks at a job that only says "running" finds why in the audit
        ctx.orch.audit.append(
            "llm.outage",
            job_id=job_id,
            detail={"model": label, "reason": reason, "waited_s": 0.0, "outcome": "waiting"},
        )

    outage = OutageBudget(on_end=outage_ended, on_start=outage_started)
    answers = None
    if ctx.job.type in REPLAY_JOBS:
        answers = KeptAnswers(
            ctx.orch.db,
            job_id,
            lambda: ctx.job.snapshot_date.isoformat() if ctx.job.snapshot_date else "",
            lambda: ctx.orch._now().isoformat(),
        )

    def guard(client: Any, label: str) -> Any:
        if client is None:
            return None
        if id(client) not in wrapped:
            b = breaker_for(ctx.orch, client) if screen else None
            wrapped[id(client)] = GuardedLlm(client, stop, b, label, outage, answers)
        return wrapped[id(client)]

    return replace(base, llm=guard(base.llm, "judge"), verifier=guard(base.verifier, "verifier"))
