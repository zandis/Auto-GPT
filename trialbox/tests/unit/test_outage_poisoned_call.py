"""A call the model fails on its own is not an outage (D-659; owner's order after the deep review of 2026-11-13).

``tb_llm.outage.wait_and_retry`` sent a call again for as long as the job's outage allowance lasted. A call that
always fails with ``upstream_down`` (a 5xx that this request provokes, while the same model answers every other
call) was sent again and again: alone, it spent the job's whole allowance and stopped the job; beside answering
calls, each answer ended the outage and the call was sent again without end. Now, once the model has answered
another call since this call first failed, the call's third ``upstream_down`` from then is its own failure: raised as it is
(the caller's answer for one failed call), never charged to the job. A load refusal (``model_busy``,
``model_asleep``, ``model_unavailable``) still waits. Fake clock, no model.
"""

from __future__ import annotations

import pytest
from tb_llm import outage


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def pause(self, seconds: float) -> None:
        self.now += seconds


class Refused(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def fault_of(exc: BaseException) -> tuple[str, float | None] | None:
    return (exc.code, None) if isinstance(exc, Refused) and exc.code in outage.MODEL_FAULTS else None


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    c = Clock()
    monkeypatch.setattr(outage, "pause", c.pause)
    monkeypatch.setattr(outage, "monotonic", c)
    return c


def test_a_call_that_fails_while_the_model_answers_others_is_raised_and_charges_nothing(clock: Clock) -> None:
    budget = outage.OutageBudget(allowance=1800.0)
    tries = {"n": 0}

    def poisoned() -> str:
        tries["n"] += 1
        if tries["n"] == 2:  # between its tries, another call of the same model is answered
            outage.wait_and_retry(lambda: "ok", budget, "judge", fault_of)
        raise Refused("upstream_down")

    with pytest.raises(Refused):
        outage.wait_and_retry(poisoned, budget, "judge", fault_of)
    assert (
        tries["n"] <= 1 + outage.CALL_STRIKES + 1
    )  # given up soon after the model was seen answering, not after 1800 s
    assert clock.now < 60.0
    assert budget.spent < 60.0  # the job's allowance is not used up by one call
    assert budget.fault("judge", "upstream_down") > 1700.0  # a real outage later still has its allowance


def test_a_poisoned_call_beside_answering_calls_does_not_loop_forever(clock: Clock) -> None:
    budget = outage.OutageBudget(allowance=1800.0)
    tries = {"n": 0}

    def poisoned() -> str:
        tries["n"] += 1
        if tries["n"] > 50:
            raise AssertionError("sent again without end")
        outage.wait_and_retry(lambda: "ok", budget, "judge", fault_of)  # the model answers every other call
        raise Refused("upstream_down")

    with pytest.raises(Refused):
        outage.wait_and_retry(poisoned, budget, "judge", fault_of)


def test_a_real_outage_still_waits_and_resumes(clock: Clock) -> None:
    """No call answered meanwhile: an outage, as before (T-689)."""
    budget = outage.OutageBudget(allowance=1800.0)
    tries = {"n": 0}

    def down_then_up() -> str:
        tries["n"] += 1
        if clock.now < 120.0:
            raise Refused("upstream_down")
        return "ok"

    assert outage.wait_and_retry(down_then_up, budget, "judge", fault_of) == "ok"
    assert clock.now >= 120.0 and tries["n"] > 2


@pytest.mark.parametrize("code", ["model_busy", "model_asleep", "model_unavailable"])
def test_a_load_refusal_still_waits_while_other_calls_are_answered(clock: Clock, code: str) -> None:
    """A queue that is full for this call while others get through is load, not the call's fault (D-445)."""
    budget = outage.OutageBudget(allowance=1800.0)
    tries = {"n": 0}

    def busy_then_free() -> str:
        tries["n"] += 1
        outage.wait_and_retry(lambda: "ok", budget, "judge", fault_of)
        if tries["n"] < 4:
            raise Refused(code)
        return "ok"

    assert outage.wait_and_retry(busy_then_free, budget, "judge", fault_of) == "ok"
    assert tries["n"] == 4


def test_another_models_answers_do_not_count(clock: Clock) -> None:
    """The verifier answering says nothing about the judge's model: the judge's outage still waits."""
    budget = outage.OutageBudget(allowance=1800.0)
    tries = {"n": 0}

    def judge_down_then_up() -> str:
        tries["n"] += 1
        outage.wait_and_retry(lambda: "ok", budget, "verifier", fault_of)
        if clock.now < 60.0:
            raise Refused("upstream_down")
        return "ok"

    assert outage.wait_and_retry(judge_down_then_up, budget, "judge", fault_of) == "ok"
