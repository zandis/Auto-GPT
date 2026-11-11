"""T-108d (D-389): a cancelled SCREEN stops within one pair; the SCREEN circuit breaker opens after N model failures
in a row and closes after its window. Fake services, synthetic jobs, no model."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Literal

import pytest
from orchestrator import jobs
from orchestrator.core import Ctx, Orchestrator, Outcome, Services
from orchestrator.db import JobDB
from orchestrator.jobs import Breaker, BreakerSettings, GuardedLlm
from tb_common.audit import AuditLog
from tb_common.config import Config, load_env, load_settings
from tb_common.llm import LlmError, LlmPromptTooLong
from tb_common.objstore import FsStore
from tb_contracts import JobCreate, SendRequest, SendResult

ROOT = Path(__file__).resolve().parents[2]
PAIRS = 40


class FakeMail:
    def send(self, req: SendRequest) -> SendResult:
        return SendResult(message_id="<1@t>", sent_to=req.to, encrypted=bool(req.encrypt))


class FakeLlm:
    """Answers, or fails every call (a wedged model), and can run a hook on the n-th call."""

    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail
        self.on_call: Any = None
        self.model = "judge-model"

    def chat_json(self, prompt_id: str, variables: dict[str, Any], **kw: Any) -> dict[str, Any]:
        self.calls += 1
        if self.on_call is not None:
            self.on_call(self.calls)
        if self.fail:
            raise LlmError("timed out")
        return {"predicate": "pass"}


def screen_like(ctx: Ctx) -> Outcome:
    """A SCREEN stand-in: one model call per pair; an unanswered pair stays unknown, as the note judge does."""
    ctx.state("running")
    llm = ctx.services.llm
    assert llm is not None
    unknown = 0
    for i in range(PAIRS):
        try:
            llm.chat_json("judge", {"pair": i}, job_id=ctx.job.job_id)
        except LlmError:
            unknown += 1
    ctx.state("reporting")
    return Outcome(summary_md=f"{PAIRS} pairs, {unknown} unknown")


@pytest.fixture
def make(tmp_path: Path) -> Any:
    def build(llm: Any, verifier: Any = None) -> Orchestrator:
        cfg = Config(
            env=load_env(dotenv=tmp_path / "x.env", environ={}),
            settings=load_settings(ROOT / "deploy/settings.example.yaml"),
        )
        services = Services(lake=None, parser=None, compiler=None, mail=FakeMail(), llm=llm, verifier=verifier)  # type: ignore[arg-type]
        return Orchestrator(
            cfg,
            JobDB(),
            FsStore(tmp_path / "obj"),
            AuditLog(tmp_path / "audit"),
            services,
            {"SCREEN": screen_like, "NAV": screen_like},
            tmp_path / "rulesets",
            tmp_path,
            today=lambda: date(2026, 10, 5),
            workers=0,
            async_notify=False,
        )

    return build


def _job(orch: Orchestrator, kind: Literal["SCREEN", "NAV"] = "SCREEN") -> str:
    return orch.create(JobCreate(type=kind, ruleset="GZQO", requested_by="crc1@hospa.test")).job_id


def _transitions(tmp_path: Path, job_id: str) -> list[tuple[str, str]]:
    import json

    out = []
    for f in sorted((tmp_path / "audit").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            ev = json.loads(line)
            if ev.get("event") == "job.state" and ev.get("job_id") == job_id:
                out.append((ev["detail"]["from"], ev["detail"]["to"]))
    return out


# ------------------------------------------------------------------------------------------------------- cancel
def test_cancel_stops_a_running_screen_within_one_pair(make: Any) -> None:
    llm = FakeLlm()
    orch = make(llm)
    job_id = _job(orch)
    llm.on_call = lambda n: orch.cancel(job_id, "admin@hospa.test") if n == 3 else None  # the admin presses Cancel
    orch.drain()
    job = orch.db.get(job_id)
    assert job is not None and job.state == "failed" and job.error is not None and job.error.step == "cancelled"
    assert llm.calls == 3  # the pair in flight finished; no further model call
    assert job.state != "done"


def test_cancel_is_idempotent(make: Any, tmp_path: Path) -> None:
    orch = make(FakeLlm())
    job_id = _job(orch)
    first = orch.cancel(job_id, "admin@hospa.test")
    second = orch.cancel(job_id, "admin@hospa.test")
    assert first.state == second.state == "failed" and second.error is not None and second.error.step == "cancelled"
    orch.drain()  # the worker finds nothing to run
    assert orch.db.get(job_id).state == "failed"
    assert [t for t in _transitions(tmp_path, job_id) if t[1] == "failed"] == [("received", "failed")]
    done = _job(orch)
    orch.drain()
    assert orch.cancel(done, "admin@hospa.test").state == "done"  # a finished job stays finished


def test_cancel_reaches_other_job_types_too(make: Any) -> None:
    llm = FakeLlm()
    orch = make(llm)
    job_id = _job(orch, "NAV")
    llm.on_call = lambda n: orch.cancel(job_id, "admin@hospa.test") if n == 1 else None
    orch.drain()
    assert orch.db.get(job_id).error.step == "cancelled" and llm.calls == 1


# ------------------------------------------------------------------------------------------------------ breaker
class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_breaker_opens_after_n_failures_and_closes_after_the_window() -> None:
    clock = Clock()
    b = Breaker(BreakerSettings(failures=3, window_s=60), clock)
    for _ in range(2):
        assert b.allow()
        b.failure()
    assert b.state == "closed" and b.allow()
    b.success()  # an answer resets the run of failures
    for _ in range(3):
        assert b.allow()
        b.failure()
    assert b.state == "open" and not b.allow() and b.seconds_left() == 60
    clock.t += 59
    assert not b.allow()
    clock.t += 1
    assert b.state == "half_open"
    assert b.allow() and not b.allow()  # one trial call, not two
    b.failure()  # the trial failed: open for another window
    assert b.state == "open" and not b.allow()
    clock.t += 60
    assert b.allow()
    b.success()
    assert b.state == "closed" and b.allow() and b.allow()


def test_breaker_off_and_settings() -> None:
    off = Breaker(BreakerSettings(failures=0, window_s=60))
    for _ in range(20):
        off.failure()
    assert off.allow() and off.state == "closed"
    s = BreakerSettings.from_env({"TB_SCREEN_BREAKER_FAILURES": "7", "TB_SCREEN_BREAKER_WINDOW_S": "30"})
    assert (s.failures, s.window_s) == (7, 30.0)
    assert BreakerSettings.from_env({}) == BreakerSettings(5, 300.0)
    with pytest.raises(ValueError, match="numbers"):
        BreakerSettings.from_env({"TB_SCREEN_BREAKER_FAILURES": "many"})


def test_a_prompt_that_does_not_fit_is_not_a_model_failure() -> None:
    class TooLong:
        def chat_json(self, *a: Any, **k: Any) -> Any:
            raise LlmPromptTooLong("too long")

    b = Breaker(BreakerSettings(failures=2, window_s=60))
    g = GuardedLlm(TooLong(), lambda: False, b, "judge")
    for _ in range(5):
        with pytest.raises(LlmPromptTooLong):
            g.chat_json("judge", {})
    assert b.state == "closed" and b.failures == 0


def test_screen_fails_fast_on_a_wedged_model_and_runs_again_after_the_window(
    make: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock()
    monkeypatch.setattr(jobs, "monotonic", clock)
    monkeypatch.setenv("TB_SCREEN_BREAKER_FAILURES", "3")
    monkeypatch.setenv("TB_SCREEN_BREAKER_WINDOW_S", "120")
    llm = FakeLlm(fail=True)
    orch = make(llm)
    first = _job(orch)
    orch.drain()
    job = orch.db.get(first)
    assert job.state == "failed" and "did not answer 3 calls in a row" in job.error.message
    assert llm.calls == 3  # not PAIRS: the run stopped at the third failure

    second = _job(orch)  # within the window: fails without a model call
    orch.drain()
    assert orch.db.get(second).state == "failed" and llm.calls == 3

    clock.t += 120
    llm.fail = False  # the model is back
    third = _job(orch)
    orch.drain()
    assert orch.db.get(third).state == "done" and llm.calls == 3 + PAIRS


def test_other_job_types_have_no_breaker(make: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_SCREEN_BREAKER_FAILURES", "2")
    llm = FakeLlm(fail=True)
    orch = make(llm)
    job_id = _job(orch, "NAV")
    orch.drain()
    assert orch.db.get(job_id).state == "done" and llm.calls == PAIRS  # NAV keeps its own share rule


def test_one_wrapper_per_client_keeps_the_same_model_check(make: Any) -> None:
    llm = FakeLlm()
    orch = make(llm, verifier=llm)  # a "verifier" that is the judge's own client
    seen: dict[str, Any] = {}

    def look(ctx: Ctx) -> Outcome:
        seen["llm"], seen["verifier"] = ctx.services.llm, ctx.services.verifier
        return Outcome(summary_md="ok")

    orch.scenarios["SCREEN"] = look
    _job(orch)
    orch.drain()
    assert isinstance(seen["llm"], GuardedLlm) and seen["llm"] is seen["verifier"]
    assert seen["llm"].model == "judge-model"  # the wrapped client's attributes show through
