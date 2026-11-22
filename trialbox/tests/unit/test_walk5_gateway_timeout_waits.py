"""Walk step 5 (2026-11-22): the gateway's own timeout is not "the model did not answer".

On the bench's screening night with the shipped pair on one 32 GB card the run stopped on "The model did not answer
34 of 84 note checks" while every call the model server logged was HTTP 200: the gateway's time for a call (its read
limit, or its call budget with the wait for a slot) ran out, it refused the call as ``upstream_failed`` with the
upstream kind ``timeout`` (D-728), and the note judge counted that as the model's failure, sent once. The same client
with no gateway in front answered all 2,360 note checks.

The rule (``tb_llm.outage.refusal_fault``): such a refusal is waited for and sent again within the job's outage
allowance, as a busy model is; a call that keeps timing out while the model answers the others fails on its own after
``CALL_STRIKES``; the rest of ``upstream_failed`` (a 400 or 404, a malformed answer, no kind) stays final.

The refusal is the gateway's own body (``gateway/core.py``: ``Refusal(code, text, status=502, upstream_kinds=...)``).
Fake services, a fake clock, synthetic excerpts, no model."""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pytest
from orchestrator import jobs
from tb_common.llm import LlmAnswerTimeout, LlmClient, LlmError, LlmModelFault, LlmUpstreamFailed
from tb_llm import GatewayClient, GatewayRefused, json_schema_format
from tb_llm.outage import ANSWER_TIMEOUT, CALL_STRIKES, POLL_S, OutageBudget, refusal_fault, wait_and_retry

from tests.unit.test_t689_outage_restart import EXCERPT, Clock, Gateway, _job, clock, make, screen_of

__all__ = ["clock", "make"]  # the fixtures of the T-689 harness, used here by name

VARIABLES = {"criterion_text": "x", "note_question": "x?", "index_date": "2026-10-05", "excerpts": EXCERPT}


def _timeout_refusal(kinds: list[str] | None = None) -> httpx.Response:
    kinds = ["timeout"] if kinds is None else kinds
    """The gateway's refusal when its time for the call ran out: 502, ``upstream_failed``, the kinds as a field."""
    error: dict[str, Any] = {
        "type": "tb_refusal",
        "code": "upstream_failed",
        "message": "llm-judge: ReadTimeout",
        "call_id": "01JTIMEOUT",
    }
    if kinds:
        error["upstream_kinds"] = kinds
    return httpx.Response(502, json={"error": error})


class SlowGateway(Gateway):
    """The T-689 stand-in, where the calls numbered in ``slow`` run out of the gateway's time."""

    def __init__(self, clock: Clock, slow: set[int], kinds: list[str] | None = None) -> None:
        super().__init__(clock)
        self.slow = slow
        self.kinds = ["timeout"] if kinds is None else kinds

    def _post(self) -> httpx.Response:
        if self.posts + 1 in self.slow:
            self.posts += 1
            self.refused.append("upstream_failed")
            return _timeout_refusal(self.kinds)
        return super()._post()


class StuckGateway(Gateway):
    """The 3rd pair's call runs out of the gateway's time ``limit`` times; every other call is answered."""

    def __init__(self, clock: Clock, limit: int = 50) -> None:
        super().__init__(clock)
        self.stuck = 0
        self.limit = limit

    def _post(self) -> httpx.Response:
        if self.answered == 2 and self.stuck < self.limit:
            self.stuck += 1
            self.posts += 1
            self.refused.append("upstream_failed")
            return _timeout_refusal()
        return super()._post()


def test_the_rule_reads_the_kinds_never_the_text() -> None:
    assert refusal_fault("upstream_failed", ("timeout",)) == ANSWER_TIMEOUT
    assert refusal_fault("upstream_failed", ("timeout", "timeout")) == ANSWER_TIMEOUT
    assert refusal_fault("upstream_failed", ()) is None  # a 400 or 404 of the server: final (T-689 review)
    assert refusal_fault("upstream_failed", ("timeout", "other")) is None  # not only time
    assert refusal_fault("upstream_failed", ("retried",)) is None
    assert refusal_fault("model_busy", ()) == "model_busy"
    assert refusal_fault("phi_tripwire", ("timeout",)) is None


def test_a_gateway_timeout_is_a_model_fault_and_still_a_part_given_up_on() -> None:
    gc = GatewayClient("http://gateway/v1", "orchestrator", http=httpx.Client(transport=httpx.MockTransport(_post)))
    llm = LlmClient("", "m", service_name="orchestrator", gateway=gc)
    with pytest.raises(LlmError) as err:
        llm.chat_json("judge", VARIABLES, job_id="J1")
    assert isinstance(err.value, LlmModelFault) and err.value.reason == ANSWER_TIMEOUT
    assert isinstance(err.value, LlmUpstreamFailed)  # the compiler still asks a slow part again in halves (G4)


def _post(req: httpx.Request) -> httpx.Response:
    if req.method == "GET":
        return httpx.Response(200, json={"data": []})
    return _timeout_refusal()


def test_a_gateway_timeout_is_sent_again_and_answered(clock: Clock) -> None:
    gw = SlowGateway(clock, {1})
    budget = OutageBudget(1800.0, clock=clock)
    res = wait_and_retry(
        lambda: gw.client().chat_json("judge", VARIABLES, job_id="J1"), budget, "judge", jobs._model_fault
    )
    assert res.data["verdict"] == "unknown" and gw.posts == 2 and gw.refused == ["upstream_failed"]


def test_the_night_of_step_5_is_judged_not_stopped(make: Any, clock: Clock) -> None:
    """A third of the calls of a 30-pair screen run out of the gateway's time once: every pair is answered on its
    resend, none is "did not answer", and the job ends."""
    seen: dict[str, Any] = {}
    gw = SlowGateway(clock, {2, 5, 8, 11, 14, 17, 20, 23, 26, 29})
    orch = make(gw.client(), screen_of(30, seen))
    job_id = _job(orch)
    orch.drain()
    job = orch.db.get(job_id)
    assert job is not None and job.state == "done", job.error
    assert seen["judge"].failures == 0 and "model_down" not in seen["reasons"], seen["reasons"]
    assert gw.refused.count("upstream_failed") == 10 and gw.answered == 30


def test_a_call_stuck_for_a_while_is_waited_for_and_answered(make: Any, clock: Clock) -> None:
    """One call runs out of the gateway's time 50 times in a row with nothing else answered meanwhile (a stalled card):
    an outage, waited out inside the allowance; the call is then answered and nobody is "did not answer"."""
    seen: dict[str, Any] = {}
    gw = StuckGateway(clock)
    orch = make(gw.client(), screen_of(30, seen))
    job_id = _job(orch)
    orch.drain()
    job = orch.db.get(job_id)
    assert job is not None and job.state == "done", job.error
    assert seen["judge"].failures == 0 and gw.stuck == 50 and gw.answered == 30


def test_a_timeout_that_outlasts_the_allowance_stops_the_job_and_says_so(make: Any, clock: Clock) -> None:
    """Every call runs out of the gateway's time, for longer than the job's allowance: the job stops with the outage
    message that names the cause and the allowance; it is never a list in which the pairs are silently unknown."""
    seen: dict[str, Any] = {}
    gw = StuckGateway(clock, limit=10**6)
    orch = make(gw.client(), screen_of(30, seen))
    job_id = _job(orch)
    orch.drain()
    job = orch.db.get(job_id)
    assert job is not None and job.state == "failed" and job.error is not None
    assert ANSWER_TIMEOUT in job.error.message and "allowance" in job.error.message, job.error.message


def test_a_call_that_keeps_timing_out_while_the_model_answers_others_fails_on_its_own(clock: Clock) -> None:
    """D-659's strikes: the model answers other calls between this call's timeouts, so after ``CALL_STRIKES`` the
    call fails on its own (one unknown) instead of waiting the night away on one call."""
    budget = OutageBudget(1800.0, clock=clock)
    tries = {"n": 0}

    def send() -> Any:
        tries["n"] += 1
        budget.answered("judge")  # another call of the same model was answered meanwhile
        raise LlmAnswerTimeout("gateway refused judge: upstream_failed (timeout)", ANSWER_TIMEOUT)

    with pytest.raises(LlmAnswerTimeout):
        wait_and_retry(send, budget, "judge", jobs._model_fault)
    assert tries["n"] == CALL_STRIKES + 1 and budget.spent == POLL_S  # only the first fault was an outage


def test_a_refusal_with_no_timeout_kind_is_still_final(clock: Clock) -> None:
    """The ruling of T-689's review stands for a configuration fault: ``upstream_failed`` with no kind, sent once."""
    gw = SlowGateway(clock, {1}, kinds=[])
    budget = OutageBudget(1800.0, clock=clock)
    with pytest.raises(LlmError) as err:
        wait_and_retry(
            lambda: gw.client().chat_json("judge", VARIABLES, job_id="J1"), budget, "judge", jobs._model_fault
        )
    assert not isinstance(err.value, LlmModelFault) and gw.posts == 1 and clock.slept == 0


def test_the_cascade_judge_reads_the_same_rule(clock: Clock) -> None:
    """The cascade's own gateway judge waits for the same refusal (one rule, both judges)."""
    from matching.cascade.judge import GatewayJudge

    gw = SlowGateway(clock, {1})
    gc = GatewayClient("http://gateway/v1", "orchestrator", http=httpx.Client(transport=httpx.MockTransport(gw)))
    judge = GatewayJudge(client=gc, outage=OutageBudget(1800.0, clock=clock))
    reply = judge.judge(
        role="judge",
        criterion_text="x",
        note_question="x?",
        index_date=date(2026, 10, 5),
        excerpts=EXCERPT,
        study_id="S",
        data_class="D3",
        step_id="step",
        purpose="screening",
    )
    assert not reply.refused and gw.posts == 2, reply


def test_the_refusal_class_is_the_clients() -> None:
    """``GatewayRefused`` carries the kinds the rule reads (D-728)."""
    gc = GatewayClient("http://gateway/v1", "orchestrator", http=httpx.Client(transport=httpx.MockTransport(_post)))
    with pytest.raises(GatewayRefused) as err:
        gc.complete({"messages": [], "response_format": json_schema_format("judge", {"type": "object"})}, _labels())
    assert err.value.reason == "upstream_failed" and err.value.upstream_kinds == ("timeout",)


def _labels() -> Any:
    from tb_llm import CallLabels

    return CallLabels("D3", "screening", "S", "s3_note_judgement", "judge", "judge@5", "step")
