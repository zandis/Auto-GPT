"""Red of lane G's master run (#639, 2026-11-16), D-915: on a real box the canary at orchestrator start met the model
servers still loading ("gateway refused judge: upstream_down", 0 of 54 answered), was recorded as a failure, and the
gate stayed shut (tcga BRCA: 0 of 450 excluded, ``note_block_code`` "failed") until someone ran a canary by hand.

* A canary that could not reach a model (every call a model fault) did not run: nothing is recorded over the last
  result, the gate says ``waiting``, the console says it waits for the models, doctor warns (not red).
* The canary at start asks again with backoff until a model answers; the night gate asks again on a later tick.
* Still fail-closed: without a passing result no note answer excludes. A model that answers wrongly, or errors for
  a reason of its own call, is a failure as before.

The 54 shipped canary cases; scripted models; no gateway.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from orchestrator import canary_gate, scheduler, selftest
from orchestrator.canary_gate import GATE, Gate
from orchestrator.scenarios.evaluate import NOTE_BLOCK_CODES, effective_note_block
from tb_common import metrics
from tb_common.llm import LlmError, LlmModelFault

from tests.unit.test_canary_gate import CASES, Oracle, _judge, _orch


class Loading(Oracle):
    """A model whose server is not up for its first ``down_for`` canaries (54 calls each)."""

    def __init__(self, model: str, down_for: int = 1, fault: type[LlmError] = LlmModelFault) -> None:
        super().__init__(model)
        self.calls = 0
        self.down_for = down_for
        self.fault = fault

    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> Any:
        self.calls += 1
        if self.calls <= self.down_for * len(CASES):
            if self.fault is LlmModelFault:
                raise LlmModelFault("gateway refused judge: upstream_down", "upstream_down")
            raise self.fault("the answer was not JSON")
        return super().chat_json(prompt_id, variables, schema, **kw)


@pytest.fixture
def gate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Gate:
    monkeypatch.setenv("TB_CANARY_GATE", "on")
    monkeypatch.setenv("TB_NOTE_BLOCK", "both_agree")
    monkeypatch.delenv("TB_MODEL_SWAP", raising=False)
    monkeypatch.delenv("TB_GATEWAY_URL", raising=False)
    GATE.path = None
    GATE.configure(tmp_path)
    return GATE


def test_a_canary_that_meets_the_models_down_is_waiting_not_failed(gate: Gate, tmp_path: Path) -> None:
    o = _orch(tmp_path, Loading("J"), Loading("V"))
    assert selftest.preflight(o, force=True) is False
    assert not (tmp_path / "selftest.json").exists()  # nothing recorded over the last result
    assert [e for e, _ in o.ev] == ["selftest.unreached"]
    assert o.ev[0][1]["unreached"] == ["judge", "verifier"]
    st = gate.status()
    assert st["code"] == "waiting" and st["allows_block"] is False and st["waiting"]["tries"] == 1
    may, policy, why = effective_note_block(_judge())
    assert (may, policy) == (False, "never") and "waiting for the models" in why and "upstream_down" in why
    check = metrics.check_canary(st)
    assert check.level == metrics.WARN and "waiting" in check.text
    assert "waiting" in NOTE_BLOCK_CODES
    # the models come up: the next canary runs and opens the gate
    assert selftest.preflight(o, force=True) is True
    assert gate.status()["code"] == "ok" and gate.status()["waiting"] is None
    assert json.loads((tmp_path / "selftest.json").read_text(encoding="utf-8"))["ok"] is True


def test_one_model_down_is_waiting_too(gate: Gate, tmp_path: Path) -> None:
    rep = selftest.run_selftest(Oracle("J"), Loading("V"))  # type: ignore[arg-type]
    assert not rep["ok"] and rep["reached"] is False and rep["unreached"] == ["verifier"]
    assert any("verifier V could not be reached" in p for p in rep["problems"])


def test_a_passing_result_stands_while_waiting_and_a_failed_one_shows_waiting(gate: Gate, tmp_path: Path) -> None:
    assert selftest.preflight(_orch(tmp_path, Oracle("J"), Oracle("V")), force=True)
    assert selftest.preflight(_orch(tmp_path, Loading("J"), Loading("V")), force=True) is False
    assert gate.check()[:2] == (True, "ok")  # the pair was checked; a restart of its servers does not undo that
    one = next(c["id"] for c in CASES if c["expected"] == "pass")
    assert not selftest.preflight(_orch(tmp_path, Oracle("J", {one}), Oracle("V", {one})), force=True)
    assert gate.check()[1] == "failed"
    assert selftest.preflight(_orch(tmp_path, Loading("J"), Loading("V")), force=True) is False
    assert gate.check()[:2] == (False, "waiting")  # still shut: the last real result is a failure


def test_a_model_that_answers_badly_is_still_a_failure(gate: Gate, tmp_path: Path) -> None:
    o = _orch(tmp_path, Loading("J", fault=LlmError), Loading("V", fault=LlmError))
    assert selftest.preflight(o, force=True) is False
    assert gate.check()[1] == "failed" and o.ev[-1][0] == "selftest.failed"
    assert json.loads((tmp_path / "selftest.json").read_text(encoding="utf-8"))["reached"] is True


def test_the_canary_at_start_asks_again_with_backoff_until_the_models_answer(
    gate: Gate, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TB_CANARY_RETRY_S", "10")
    monkeypatch.setenv("TB_CANARY_RETRY_MAX_S", "25")
    o = _orch(tmp_path, Loading("J", down_for=4), Loading("V", down_for=4))
    slept: list[float] = []
    rep = canary_gate.canary_until_reached(o, sleep=slept.append)
    assert slept == [10, 20, 25, 25]  # doubling, capped
    assert rep is not None and rep["ok"] and gate.check()[:2] == (True, "ok")
    assert [e for e, _ in o.ev] == ["selftest.unreached"] * 4 + ["selftest.passed"]


def test_the_night_gate_asks_again_on_a_later_tick(gate: Gate, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_CANARY_RETRY_S", "60")
    o = _orch(tmp_path, Loading("J"), Loading("V"))
    o.cfg = None  # unused: the day is given
    now = [1000.0]
    scheduler._gate.clear()
    scheduler._unreached.clear()
    day = "2026-11-16"
    assert scheduler.night_gate(o, day, clock=lambda: now[0]) is False
    assert day not in scheduler._gate  # not kept for the night
    now[0] += 30
    assert scheduler.night_gate(o, day, clock=lambda: now[0]) is False and len(o.ev) == 1  # too soon: not asked
    now[0] += 31
    assert scheduler.night_gate(o, day, clock=lambda: now[0]) is True  # the models are up: it ran and passed
    assert [e for e, _ in o.ev] == ["selftest.unreached", "selftest.passed"] and scheduler._gate[day] is True
