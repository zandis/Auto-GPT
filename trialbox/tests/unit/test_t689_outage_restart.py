"""T-689 (D-456; scale review F-04, F-16, F-28, F-31, G1-2, G1-3): a screening job outlives a model outage and a
restart of the orchestrator, and its budgets come from the population.

The three acceptance tests of the card's row, at a small size (the nightly scale gate runs them at 50,000 patients):

* a gateway stand-in that answers 502 and then 503 for 40 s inside a run of note checks: no ``model_down``;
* three restarts of the orchestrator: the model work does not start at 0 (kept answers are replayed);
* 5,000 pairs of 2,500 tokens with ``max_pairs=20000``: none unprocessed.

Fake services, a fake clock, synthetic excerpts, no model."""

from __future__ import annotations

import contextlib
import json
import threading
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
from orchestrator import jobs
from orchestrator.clients import StepFailed
from orchestrator.core import Ctx, Orchestrator, Outcome, Services
from orchestrator.db import JobDB
from orchestrator.scenarios.evaluate import NoteJudge
from tb_common.audit import AuditLog
from tb_common.config import Config, load_env, load_settings
from tb_common.llm import LlmClient, LlmError, LlmResult
from tb_common.objstore import FsStore
from tb_contracts import JobCreate, SendRequest, SendResult
from tb_llm import GatewayClient

try:
    from tb_llm import outage
except ImportError:  # the code before T-689
    outage = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[2]
EXCERPT = [{"date": "2026-10-01", "note_type": "progress", "text": "No history of stroke.", "did": "d1"}]


class FakeMail:
    def __init__(self) -> None:
        self.sent: list[SendRequest] = []

    def send(self, req: SendRequest) -> SendResult:
        self.sent.append(req)
        return SendResult(message_id=f"<{len(self.sent)}@t>", sent_to=req.to, encrypted=bool(req.encrypt))


class Clock:
    """The test's time: the wait between two tries moves it, the gateway stand-in reads it."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept = 0.0
        self._lock = threading.Lock()

    def __call__(self) -> float:
        return self.now

    def pause(self, seconds: float) -> None:
        with self._lock:
            self.now += seconds
            self.slept += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    c = Clock()
    monkeypatch.setattr(jobs, "monotonic", c)
    if outage is not None:  # unchanged code has no wait: the tests then fail on what they assert
        monkeypatch.setattr(outage, "pause", c.pause)
        monkeypatch.setattr(outage, "monotonic", c)
    return c


class Gateway:
    """A tb-gateway stand-in: answers every judge call, except during an outage, where (as the real one does) the
    first five calls get 502 ``upstream_failed`` and the rest 503 ``model_unavailable`` with ``Retry-After: 30``."""

    def __init__(self, clock: Clock, *outages: tuple[int, float]) -> None:
        self.clock = clock
        self.outages = list(outages)  # (after this many answers, for this many seconds)
        self.down_until: float | None = None
        self.answered = 0
        self.refused: list[str] = []
        self._in_outage = 0
        self._lock = threading.Lock()

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if req.method == "GET":  # /v1/models: no context recorded
            return httpx.Response(200, json={"data": []})
        with self._lock:
            return self._post()

    def _post(self) -> httpx.Response:
        if self.outages and self.answered == self.outages[0][0]:
            self.down_until = self.clock.now + self.outages.pop(0)[1]
            self._in_outage = 0
        if self.down_until is not None and self.clock.now < self.down_until:
            code, status = ("upstream_failed", 502) if self._in_outage < 5 else ("model_unavailable", 503)
            self._in_outage += 1
            self.refused.append(code)
            headers = {"Retry-After": "30"} if status == 503 else {}
            body = {"error": {"type": "tb_refusal", "code": code, "message": "the model server did not answer"}}
            return httpx.Response(status, json=body, headers=headers)
        self.answered += 1
        content = json.dumps({"verdict": "unknown", "confidence": 0.5, "quote": None, "quote_date": None})
        return httpx.Response(
            200,
            json={
                "model": "judge-a",
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10},
                "tb": {
                    "alias": "j-workhorse",
                    "call_id": "c",
                    "expected_alias": "j-workhorse",
                    "fallbacks": 0,
                    "build_sha": "b1",
                },
            },
        )

    def client(self) -> LlmClient:
        gc = GatewayClient("http://gateway/v1", "orchestrator", http=httpx.Client(transport=httpx.MockTransport(self)))
        return LlmClient("", "judge-a", service_name="orchestrator", gateway=gc)


def screen_of(pairs: int, seen: dict[str, Any]) -> Any:
    """A SCREEN stand-in: ``pairs`` note checks through the real note judge and the job's guarded model client."""

    def scenario(ctx: Ctx) -> Outcome:
        ctx.state("running")
        llm = ctx.services.llm
        assert llm is not None
        judge = NoteJudge(lake=None, llm=llm, job_id=ctx.job.job_id)
        seen["judge"] = judge
        reasons: list[str] = []
        seen["reasons"] = reasons
        for i in range(pairs):
            r = judge.judge_excerpts(f"criterion {i}", f"question {i}?", date(2026, 10, 5), EXCERPT)
            reasons.append(str(r.reason))
        ctx.metrics(llm_calls=judge.calls, tokens_in=judge.tokens_in)
        ctx.state("reporting")
        return Outcome(summary_md=f"{pairs} pairs")

    return scenario


@pytest.fixture
def make(tmp_path: Path) -> Any:
    def build(llm: Any, scenario: Any) -> Orchestrator:
        cfg = Config(
            env=load_env(dotenv=tmp_path / "x.env", environ={}),
            settings=load_settings(ROOT / "deploy/settings.example.yaml"),
        )
        services = Services(lake=None, parser=None, compiler=None, mail=FakeMail(), llm=llm, verifier=None)  # type: ignore[arg-type]
        return Orchestrator(
            cfg,
            JobDB(),
            FsStore(tmp_path / "obj"),
            AuditLog(tmp_path / "audit"),
            services,
            {"SCREEN": scenario},
            tmp_path / "rulesets",
            tmp_path,
            today=lambda: date(2026, 10, 5),
            workers=0,
            async_notify=False,
        )

    return build


def _job(orch: Orchestrator) -> str:
    return orch.create(JobCreate(type="SCREEN", ruleset="GZQO", requested_by="crc1@hospa.test")).job_id


def _events(tmp_path: Path, name: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted((tmp_path / "audit").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            ev = json.loads(line)
            if ev.get("event") == name:
                out.append(ev)
    return out


# ------------------------------------------------------------------------------------------- outage (F-04, G1-3)
PAIRS = 300


def test_an_outage_of_40_s_inside_a_screen_loses_no_pair(make: Any, clock: Clock, tmp_path: Path) -> None:
    """Acceptance 1: the stand-in answers 502 / 503 for 40 s from call 100. No pair is ``model_down``; the job
    waited about the outage's length and went on."""
    gw = Gateway(clock, (99, 40.0))
    seen: dict[str, Any] = {}
    orch = make(gw.client(), screen_of(PAIRS, seen))
    job_id = _job(orch)
    orch.drain()
    job = orch.db.get(job_id)
    assert job is not None and job.state == "done", job.error
    assert gw.refused, "the outage happened"
    assert seen["reasons"].count("model_down") == 0
    assert seen["judge"].failures == 0 and seen["judge"].calls == PAIRS == gw.answered
    assert 40.0 <= clock.slept <= 40.0 + 30.0  # the outage, and at most one Retry-After more
    (ev,) = _events(tmp_path, "llm.outage")
    assert ev["job_id"] == job_id and ev["detail"]["outcome"] == "resumed" and ev["detail"]["model"] == "judge"
    assert ev["detail"]["reason"] == "upstream_failed" and ev["detail"]["waited_s"] >= 40.0


def test_a_model_that_stays_down_fails_the_job_after_its_allowance(
    make: Any, clock: Clock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wait is bounded per job: after ``TB_LLM_OUTAGE_WAIT_S`` the job fails at once and says why; the pairs it
    did not reach are not written ``model_down``."""
    monkeypatch.setenv("TB_LLM_OUTAGE_WAIT_S", "90")
    gw = Gateway(clock, (10, 10_000.0))
    seen: dict[str, Any] = {}
    orch = make(gw.client(), screen_of(PAIRS, seen))
    job_id = _job(orch)
    orch.drain()
    job = orch.db.get(job_id)
    assert job is not None and job.state == "failed" and job.error is not None
    assert job.error.step == "running" and "TB_LLM_OUTAGE_WAIT_S" in job.error.message
    assert "judge model did not answer" in job.error.message
    assert seen["reasons"].count("model_down") == 0 and len(seen["reasons"]) == 10 == gw.answered
    assert 90.0 <= clock.slept <= 90.0 + 30.0
    (ev,) = _events(tmp_path, "llm.outage")
    assert ev["detail"]["outcome"] == "gave_up"


def test_two_outages_share_one_allowance(make: Any, clock: Clock, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bounded per job, not per call or per outage: two outages of 60 s do not fit an allowance of 100 s."""
    monkeypatch.setenv("TB_LLM_OUTAGE_WAIT_S", "100")
    gw = Gateway(clock, (4, 60.0), (20, 60.0))
    seen: dict[str, Any] = {}
    orch = make(gw.client(), screen_of(40, seen))
    job_id = _job(orch)
    orch.drain()
    job = orch.db.get(job_id)
    assert job is not None and job.state == "failed" and job.error is not None
    assert "TB_LLM_OUTAGE_WAIT_S" in job.error.message and gw.answered == 20
    assert seen["reasons"].count("model_down") == 0


def test_no_wait_when_the_allowance_is_zero(make: Any, clock: Clock, monkeypatch: pytest.MonkeyPatch) -> None:
    """``TB_LLM_OUTAGE_WAIT_S=0`` is the behaviour before T-689: a fault is a failure at once (and the breaker
    counts it)."""
    monkeypatch.setenv("TB_LLM_OUTAGE_WAIT_S", "0")
    monkeypatch.setenv("TB_SCREEN_BREAKER_FAILURES", "0")
    gw = Gateway(clock, (4, 10_000.0))
    seen: dict[str, Any] = {}
    orch = make(gw.client(), screen_of(20, seen))
    _job(orch)
    orch.drain()
    assert clock.slept == 0 and seen["reasons"].count("model_down") == 16


def test_cancel_is_seen_while_the_job_waits(make: Any, clock: Clock, monkeypatch: pytest.MonkeyPatch) -> None:
    gw = Gateway(clock, (2, 10_000.0))
    seen: dict[str, Any] = {}
    orch = make(gw.client(), screen_of(20, seen))
    job_id = _job(orch)

    def pause_then_cancel(seconds: float) -> None:
        clock.pause(seconds)
        orch.cancel(job_id, "admin@hospa.test")

    monkeypatch.setattr(outage, "pause", pause_then_cancel)
    orch.drain()
    job = orch.db.get(job_id)
    assert job is not None and job.state == "failed" and job.error is not None and job.error.step == "cancelled"
    assert clock.slept <= 5.0


def test_a_model_fault_is_told_from_a_refusal_of_the_request(clock: Clock) -> None:
    from tb_common.llm import LlmModelFault
    from tb_llm import GatewayRefused
    from tb_llm.client import CallLabels, json_schema_format

    def refusing(code: str, status: int, headers: dict[str, str]) -> GatewayClient:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(status, json={"error": {"type": "tb_refusal", "code": code}}, headers=headers)

        return GatewayClient(
            "http://gateway/v1", "orchestrator", http=httpx.Client(transport=httpx.MockTransport(handler))
        )

    labels = CallLabels("D3", "screening", "S", "s3_note_judgement", "judge", "judge@4", "step")
    body = {"messages": [], "response_format": json_schema_format("judge", {"type": "object"})}
    with pytest.raises(GatewayRefused) as busy:
        refusing("model_unavailable", 503, {"Retry-After": "30"}).complete(body, labels)
    assert busy.value.retry_after == 30.0  # F-04: it was never read
    variables = {"criterion_text": "x", "note_question": "x?", "index_date": "2026-10-05", "excerpts": EXCERPT}
    for code, status, headers, fault in (
        ("model_unavailable", 503, {"Retry-After": "30"}, True),
        ("model_busy", 503, {"Retry-After": "5"}, True),
        ("model_asleep", 503, {}, True),
        ("upstream_failed", 502, {}, True),
        ("phi_tripwire", 403, {}, False),
        ("no_route", 403, {}, False),
    ):
        llm = LlmClient("", "m", service_name="orchestrator", gateway=refusing(code, status, headers))
        with pytest.raises(LlmError) as err:
            llm.chat_json("judge", variables, job_id="J1")
        assert isinstance(err.value, LlmModelFault) is fault, code
        if fault:
            assert err.value.reason == code  # type: ignore[attr-defined]
            assert err.value.retry_after == (float(headers["Retry-After"]) if headers else None)  # type: ignore[attr-defined]

    def unreachable(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    gc = GatewayClient(
        "http://gateway/v1", "orchestrator", http=httpx.Client(transport=httpx.MockTransport(unreachable))
    )
    with pytest.raises(LlmModelFault) as down:
        LlmClient("", "m", service_name="orchestrator", gateway=gc).chat_json("judge", variables, job_id="J1")
    assert down.value.reason == "unreachable"


# ------------------------------------------------------------------------------------------- breaker (F-31)
def test_the_breaker_threshold_is_at_least_two_rounds_of_calls_in_flight() -> None:
    from orchestrator.jobs import BreakerSettings

    assert BreakerSettings.from_env({"TB_SCREEN_LLM_CONCURRENCY": "16"}).failures == 32
    assert (
        BreakerSettings.from_env({"TB_SCREEN_BREAKER_FAILURES": "50", "TB_SCREEN_LLM_CONCURRENCY": "16"}).failures == 50
    )
    assert BreakerSettings.from_env({}).failures == 5
    assert (
        BreakerSettings.from_env({"TB_SCREEN_BREAKER_FAILURES": "0", "TB_SCREEN_LLM_CONCURRENCY": "16"}).failures == 0
    )


def test_an_outage_never_opens_the_breaker(make: Any, clock: Clock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_SCREEN_BREAKER_FAILURES", "2")
    gw = Gateway(clock, (4, 40.0))
    seen: dict[str, Any] = {}
    orch = make(gw.client(), screen_of(30, seen))
    job_id = _job(orch)
    orch.drain()
    job = orch.db.get(job_id)
    assert job is not None and job.state == "done", job.error
    assert len(gw.refused) > 2


# ------------------------------------------------------------------------------------------- the share (G1-3)
class Scripted:
    """A model client that answers, and fails (not a model fault: an unusable answer) the calls ``bad`` names."""

    gateway = None
    model = "judge-a"

    def __init__(self, bad: Any) -> None:
        self.bad = bad
        self.calls = 0
        self.kill_at = 0

    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> LlmResult:
        self.calls += 1
        if self.kill_at and self.calls == self.kill_at:
            raise Killed
        if self.bad(self.calls):
            raise LlmError("answer outside its schema twice")
        data = {"verdict": "unknown", "confidence": 0.5, "quote": None, "quote_date": None}
        return LlmResult(data, "judge", 4, "judge-a", "local", "in", f"out{self.calls:04d}", 100, 10, 1, "sha", "b1")


class Killed(BaseException):
    """The process dies here: nothing after this line of the job runs (no failure handling, no clean-up)."""


def _judge(llm: Any, in_flight: int) -> NoteJudge:
    return NoteJudge(lake=None, llm=llm, job_id="J1", in_flight=in_flight)


def test_the_failure_share_stops_the_job_while_it_runs() -> None:
    """G1-3: every check fails from call 61 on. With 4 calls in flight the rule applies from 80 checks: the job
    stops there, not after all 300."""
    llm = Scripted(lambda n: n > 60)
    judge = _judge(llm, in_flight=4)
    with pytest.raises(StepFailed) as stop:
        for i in range(300):
            judge.judge_excerpts(f"c{i}", "q?", date(2026, 10, 5), EXCERPT)
    assert llm.calls == 80 and "20 of 80 note checks so far" in stop.value.message


def test_one_round_of_failures_in_flight_never_stops_the_job() -> None:
    """F-31: 8 failures together (two full rounds of 4 calls in flight), even as the first calls, do not stop it."""
    llm = Scripted(lambda n: n <= 8)
    judge = _judge(llm, in_flight=4)
    for i in range(300):
        judge.judge_excerpts(f"c{i}", "q?", date(2026, 10, 5), EXCERPT)
    assert judge.failures == 8 and judge.calls == 292


def test_without_calls_in_flight_the_share_is_checked_at_the_end_only() -> None:
    from orchestrator.scenarios.evaluate import check_judge

    llm = Scripted(lambda n: n > 60)
    judge = _judge(llm, in_flight=0)
    for i in range(100):
        judge.judge_excerpts(f"c{i}", "q?", date(2026, 10, 5), EXCERPT)
    with pytest.raises(StepFailed):
        check_judge(judge)


# ------------------------------------------------------------------------------------------- restarts (F-28, G1-2)
RESTART_PAIRS = 40


def _restart(make: Any, llm: Scripted, seen: dict[str, Any], kill_at: int) -> Orchestrator:
    """A new orchestrator process on the same database: it finds the interrupted job and runs it again."""
    llm.calls, llm.kill_at = 0, kill_at
    orch: Orchestrator = make(llm, screen_of(RESTART_PAIRS, seen))
    orch.start()
    return orch


def test_three_restarts_do_not_start_the_model_work_at_zero(make: Any, tmp_path: Path) -> None:
    """Acceptance 2: the orchestrator dies three times inside one job. Each run asks the model only for the pairs no
    earlier run had answered; the finished job counts every pair once, and its kept answers are gone."""
    llm = Scripted(lambda n: False)
    seen: dict[str, Any] = {}
    orch = make(llm, screen_of(RESTART_PAIRS, seen))
    job_id = _job(orch)
    llm.kill_at = 11  # dies on its 11th call: 10 answers
    with pytest.raises(Killed):
        orch.drain()
    assert orch.db.answer_count(job_id) == 10
    live = [10]
    for kept in (10, 20, 30):
        orch = _restart(make, llm, seen, kill_at=11)
        with pytest.raises(Killed) if kept < 30 else contextlib.nullcontext():
            orch.drain()
        live.append(llm.calls - (1 if kept < 30 else 0))
        if kept < 30:
            assert orch.db.answer_count(job_id) == kept + 10  # nothing kept is asked again
            assert seen["judge"].calls == kept + 10  # the run's own counter did not start at 0
    assert live == [10, 10, 10, 10] and sum(live) == RESTART_PAIRS  # every pair asked exactly once
    job = orch.db.get(job_id)
    assert job is not None and job.state == "done", job.error
    assert job.metrics is not None and job.metrics.llm_calls == RESTART_PAIRS
    assert orch.db.restarts(job_id) == 3 and orch.db.answer_count(job_id) == 0
    requeued = [e["detail"] for e in _events(tmp_path, "job.requeued")]
    assert [(d["restarts"], d["kept_answers"]) for d in requeued] == [(1, 10), (2, 20), (3, 30)]


def test_one_restart_too_many_fails_the_job_with_a_message(
    make: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-28: a job that is interrupted again and again (it may be what kills the box) is not run for ever."""
    monkeypatch.setenv("TB_JOB_MAX_RESTARTS", "2")
    llm = Scripted(lambda n: False)
    seen: dict[str, Any] = {}
    orch = make(llm, screen_of(RESTART_PAIRS, seen))
    job_id = _job(orch)
    llm.kill_at = 6
    with pytest.raises(Killed):
        orch.drain()
    for _ in range(2):
        orch = _restart(make, llm, seen, kill_at=6)
        with pytest.raises(Killed):
            orch.drain()
    orch = _restart(make, llm, seen, kill_at=6)
    orch.drain()  # nothing to run: the third restart did not queue it
    assert llm.calls == 0
    job = orch.db.get(job_id)
    assert job is not None and job.state == "failed" and job.error is not None
    assert "restart of the box 3 times" in job.error.message and "TB_JOB_MAX_RESTARTS = 2" in job.error.message
    assert orch.db.answer_count(job_id) == 0  # the kept answers went with the job
    mail = orch.services.mail
    assert isinstance(mail, FakeMail) and any("failed" in m.subject.lower() for m in mail.sent)
    assert _events(tmp_path, "job.requeued")[-1]["detail"]["gave_up"] == 1


def test_kept_answers_go_when_the_job_ends_in_any_state(make: Any) -> None:
    for bad, state in ((lambda n: False, "done"), (lambda n: n > 20, "failed")):
        llm = Scripted(bad)
        seen: dict[str, Any] = {}

        def scenario(ctx: Ctx, seen: dict[str, Any] = seen) -> Outcome:
            out: Outcome = screen_of(RESTART_PAIRS, seen)(ctx)
            assert ctx.orch.db.answer_count(ctx.job.job_id) > 0  # kept while the job runs
            if seen["judge"].failures:
                raise StepFailed("judging", "the model did not answer")
            return out

        orch = make(llm, scenario)
        job_id = _job(orch)
        orch.drain()
        job = orch.db.get(job_id)
        assert job is not None and job.state == state
        assert orch.db.answer_count(job_id) == 0


def test_kept_answers_of_finished_and_missing_jobs_are_swept_at_start(make: Any) -> None:
    llm = Scripted(lambda n: False)
    orch = make(llm, screen_of(5, {}))
    done = _job(orch)
    orch.drain()
    orch.db.answer_put(done, "k", "{}", "2026-10-05T00:00:00")  # left behind by a process that died after the end
    orch.db.answer_put("NOJOB", "k", "{}", "2026-10-05T00:00:00")
    waiting = _job(orch)
    orch.db.answer_put(waiting, "k", "{}", "2026-10-05T00:00:00")
    make(llm, screen_of(5, {})).start()
    assert (orch.db.answer_count(done), orch.db.answer_count("NOJOB"), orch.db.answer_count(waiting)) == (0, 0, 1)


def test_the_key_names_role_snapshot_prompt_and_variables_and_the_first_answer_stays(make: Any) -> None:
    from orchestrator.jobs import KeptAnswers

    orch = make(Scripted(lambda n: False), screen_of(1, {}))
    snap = ["2026-10-04"]
    kept = KeptAnswers(orch.db, "J1", lambda: snap[0], lambda: "2026-10-05T00:00:00")
    inner = Scripted(lambda n: False)
    v = {"criterion_text": "x", "excerpts": EXCERPT}
    k = kept.key("judge", inner, "judge", v, None)
    assert k is not None and k == kept.key("judge", inner, "judge", dict(reversed(list(v.items()))), None)
    assert k != kept.key("verifier", inner, "judge", v, None)
    assert k != kept.key("judge", inner, "judge", {**v, "criterion_text": "y"}, None)
    snap[0] = "2026-10-05"
    assert k != kept.key("judge", inner, "judge", v, None)  # another night's notes: another question
    assert kept.key("judge", inner, "no_such_prompt", v, None) is None  # asked live, not kept
    first, second = inner.chat_json("judge", v), inner.chat_json("judge", v)
    kept.put(k, first)
    kept.put(k, second)  # two calls with one key in flight together
    kept.put(k, {"not": "a result"})
    got = kept.get(k)
    assert got == first and got != second and kept.replayed == 1
    assert KeptAnswers(orch.db, "J2", lambda: snap[0], lambda: "").get(k) is None  # never another job's answer
    orch.db.answer_put("J3", "k", '{"written": "by another build"}', "t")
    assert KeptAnswers(orch.db, "J3", lambda: "", lambda: "").get("k") is None


# ------------------------------------------------------------------------------------------- budgets (F-16)
@pytest.mark.nodb
def test_5000_pairs_of_2500_tokens_fit_a_budget_of_20000_pairs() -> None:
    """Acceptance 3: the hidden 10,000,000-token budget stopped this at pair 3,572 under the pair budget's name."""
    from matching.cascade import CascadeConfig
    from matching.cascade.engine import EXCERPT_TOKENS, budget_stop

    cfg = CascadeConfig(study_id="S", run_date=date(2026, 10, 5), max_llm_items=20000)
    assert cfg.max_tokens is None
    cost = 300 + EXCERPT_TOKENS
    assert cost == 2800
    items = tokens = 0
    unprocessed = 0
    for _ in range(5000):
        if budget_stop(cfg, items, tokens, cost):
            unprocessed += 1
        else:
            items, tokens = items + 1, tokens + cost
    assert unprocessed == 0 and items == 5000


@pytest.mark.nodb
def test_the_budget_that_stops_a_run_is_named() -> None:
    from dataclasses import replace

    from matching.cascade import CascadeConfig
    from matching.cascade.engine import budget_stop

    cfg = CascadeConfig(study_id="S", run_date=date(2026, 10, 5), max_llm_items=3)
    assert budget_stop(cfg, 2, 0, 2800) == "" and budget_stop(cfg, 3, 0, 2800) == "pairs"
    capped = replace(cfg, max_llm_items=20000, max_tokens=10_000_000)
    assert budget_stop(capped, 3571, 3571 * 2800, 2800) == "tokens"
    assert budget_stop(replace(cfg, max_llm_items=None), 10**9, 10**12, 2800) == ""  # no budget: the population's


@pytest.mark.nodb
def test_screen_budget_defaults_to_the_population() -> None:
    from orchestrator.scenarios.screen_cascade import max_pairs_of

    assert max_pairs_of({}, {}) is None  # no fixed 20,000: the population's own pairs
    assert max_pairs_of({}, {"TB_SCREEN_MAX_PAIRS": "700"}) == 700
    assert max_pairs_of({"max_pairs": "50000"}, {"TB_SCREEN_MAX_PAIRS": "700"}) == 50000


def test_sixteen_calls_in_flight_wait_through_one_outage_together(clock: Clock) -> None:
    """Two at once, and more: the calls in flight share the job's one allowance and one outage; each is answered."""
    from concurrent.futures import ThreadPoolExecutor

    from orchestrator.jobs import GuardedLlm
    from tb_llm.outage import OutageBudget

    gw = Gateway(clock, (40, 40.0))
    ended: list[tuple[str, str, float, str]] = []
    budget = OutageBudget(1800.0, on_end=lambda *a: ended.append(a))
    llm = GuardedLlm(gw.client(), lambda: False, None, "judge", budget)
    variables = {"criterion_text": "x", "note_question": "x?", "index_date": "2026-10-05", "excerpts": EXCERPT}
    with ThreadPoolExecutor(max_workers=16) as ex:
        got = list(ex.map(lambda i: llm.chat_json("judge", {**variables, "criterion_text": f"c{i}"}), range(200)))
    assert len(got) == 200 == gw.answered and gw.refused
    # every thread's pause moves the one test clock, so the seconds are bounded by what was paused in all, not by
    # the outage's own length
    assert ended and all(e[3] == "resumed" for e in ended) and 0 < budget.spent <= clock.slept


def test_the_cascades_own_judge_waits_through_an_outage_too(clock: Clock) -> None:
    """The judge the scale gate runs (``matching.cascade.judge.GatewayJudge`` straight on ``tb_llm``): its check
    ``screen.outage_no_unknown`` counts the refusals this judge records. None is recorded for an outage it outlives."""
    from matching.cascade.judge import GatewayJudge
    from tb_llm.outage import OutageBudget, OutageExhausted

    kw: dict[str, Any] = {
        "role": "judge",
        "criterion_text": "x",
        "note_question": "stroke?",
        "index_date": date(2026, 10, 5),
        "excerpts": EXCERPT,
        "study_id": "S-1",
        "data_class": "D0",
        "step_id": "s",
        "purpose": "screening",
    }

    def judge_on(gw: Gateway, allowance: float | None = None) -> GatewayJudge:
        gc = GatewayClient("http://gateway/v1", "orchestrator", http=httpx.Client(transport=httpx.MockTransport(gw)))
        return GatewayJudge(gc, outage=None if allowance is None else OutageBudget(allowance))

    gw = Gateway(clock, (14, 5.0))  # the gate's own case: 5 s of 502 lost 60 of 74 judge calls
    judge = judge_on(gw)
    replies = [judge.judge(**kw) for _ in range(74)]
    assert gw.refused and judge.refusals == [] and all(r.refused is None for r in replies)
    assert judge.calls == 74 == gw.answered
    down = judge_on(Gateway(clock, (3, 10_000.0)), allowance=60.0)
    with pytest.raises(OutageExhausted):
        for _ in range(10):
            down.judge(**kw)
    assert down.refusals == []  # the run stops; nothing is written as refused for the pairs it did not reach
    content = judge_on(Gateway(clock))  # a refusal of the request is still its answer, at once
    content.client.http = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(403, json={"error": {"type": "tb_refusal", "code": "phi_tripwire"}})
        )
    )
    slept = clock.slept
    assert content.judge(**kw).refused == "phi_tripwire" and clock.slept == slept
