"""The pair canary gates note exclusions (TB-PLAN-03 step 2, D-117): at start, after each swap, on the Models tile."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from orchestrator import canary_gate, selftest
from orchestrator.canary_gate import GATE, Gate, gate_on, wake_cases
from orchestrator.scenarios.evaluate import effective_note_block
from tb_common.llm import LlmError, LlmResult

CASES = selftest.load_cases()


class Oracle:
    """Answers every canary case right; ``wrong`` ids the opposite way (a silent case as ``fail``)."""

    def __init__(self, model: str, wrong: set[str] | None = None, down: bool = False) -> None:
        self.model = model
        self.wrong = wrong or set()
        self.down = down

    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> LlmResult:
        if self.down:
            raise LlmError("connection refused")
        case = next(
            c
            for c in CASES
            if c["excerpts"] == variables["excerpts"] and c["note_question"] == variables["note_question"]
        )
        want = case["expected"]
        if case["id"] in self.wrong:
            want = {"pass": "fail", "fail": "pass", "unknown": "fail"}[want]
        quote = None if want == "unknown" else case["excerpts"][0]["text"][:20]
        d = {"verdict": want, "reason": "r", "confidence": 0.9, "quote": quote, "quote_date": None}
        return LlmResult(d, prompt_id, 4, self.model, "local", "i" * 64, "o" * 64, 1, 1, 1)


@pytest.fixture
def gate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Gate:
    monkeypatch.setenv("TB_CANARY_GATE", "on")
    monkeypatch.setenv("TB_NOTE_BLOCK", "both_agree")
    GATE.path = None
    GATE.configure(tmp_path)
    return GATE


def _judge() -> Any:
    return SimpleNamespace(verifier=object())


def _orch(tmp_path: Path, llm: Any, verifier: Any) -> Any:
    events: list[tuple[str, dict[str, Any]]] = []
    audit = SimpleNamespace(append=lambda ev, detail=None, **kw: events.append((ev, detail or {})))
    return SimpleNamespace(
        services=SimpleNamespace(llm=llm, verifier=verifier), data_dir=tmp_path, audit=audit, ev=events
    )


def test_the_gate_is_on_except_on_demo_and_test_boxes() -> None:
    assert gate_on({}) and gate_on({"TB_ENV": "PRODUCTION"}) and gate_on({"TB_ENV": "PILOT"})
    assert not gate_on({"TB_ENV": "DEV"}) and not gate_on({"TB_ENV": "test"})
    assert gate_on({"TB_ENV": "DEV", "TB_CANARY_GATE": "on"}) and not gate_on({"TB_CANARY_GATE": "off"})


def test_no_canary_yet_means_no_note_exclusion(gate: Gate) -> None:
    may, policy, why = effective_note_block(_judge())
    assert (may, policy) == (False, "never") and "not run" in why
    assert gate.status()["code"] == "none"


def test_a_passing_pair_canary_opens_the_gate_and_survives_a_restart(gate: Gate, tmp_path: Path) -> None:
    o = _orch(tmp_path, Oracle("J"), Oracle("V"))
    assert selftest.preflight(o, force=True)
    assert effective_note_block(_judge())[0] is True
    st = gate.status()
    assert st["code"] == "ok" and st["pair_correct"] == 54 and st["cases"] == 54 and st["at"]
    assert o.ev[-1][0] == "selftest.passed"
    fresh = Gate()
    fresh.configure(tmp_path)  # a restarted orchestrator reads <data dir>/selftest.json
    assert fresh.check()[:2] == (True, "ok")


def test_flipping_one_case_in_the_pair_closes_the_gate(gate: Gate, tmp_path: Path) -> None:
    """The done-check of TB-PLAN-03 step 2: one case both models get wrong the same way sets may_block false."""
    one = next(c["id"] for c in CASES if c["expected"] == "pass")
    o = _orch(tmp_path, Oracle("J", {one}), Oracle("V", {one}))
    assert not selftest.preflight(o, force=True)
    may, policy, why = effective_note_block(_judge())
    assert (may, policy) == (False, "never") and "failed" in why
    rep = json.loads((tmp_path / "selftest.json").read_text(encoding="utf-8"))
    assert rep["pair"]["decided_wrong"] == 1 and not rep["ok"]
    assert gate.status()["code"] == "failed"


def test_one_model_wrong_alone_keeps_the_gate_open(gate: Gate, tmp_path: Path) -> None:
    one = next(c["id"] for c in CASES if c["expected"] == "pass")
    assert selftest.preflight(_orch(tmp_path, Oracle("J", {one}), Oracle("V")), force=True)
    assert effective_note_block(_judge())[0] is True


def test_a_stale_canary_and_a_single_model_canary_close_the_gate(
    gate: Gate, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selftest.preflight(_orch(tmp_path, Oracle("J"), Oracle("V")), force=True)
    gate.at = time.time() - 40 * 3600
    assert gate.check()[1] == "stale"
    monkeypatch.setenv("TB_CANARY_MAX_AGE_H", "48")
    assert gate.check()[1] == "ok"
    selftest.preflight(_orch(tmp_path, Oracle("J"), None), force=True)
    assert gate.check()[1] == "single"


def test_a_failed_wake_check_closes_the_gate_until_the_next_pass(gate: Gate, tmp_path: Path) -> None:
    selftest.preflight(_orch(tmp_path, Oracle("J"), Oracle("V")), force=True)
    wc = wake_cases()
    assert len(wc) == 6 and {c["language"] for c in wc} == {"en", "ja", "zh-TW"}
    assert sorted(c["expected"] for c in wc) == ["fail", "fail", "pass", "pass", "unknown", "unknown"]
    probe = canary_gate.wake_probe(Oracle("J"), Oracle("V", {c["id"] for c in wc[:2]}))
    assert probe is not None
    assert probe("serving") is None
    why = probe("verifier")
    assert why and "wake check" in why
    may, _, reason = effective_note_block(_judge())
    assert not may and "wake check" in reason and gate.status()["code"] == "wake"
    selftest.preflight(_orch(tmp_path, Oracle("J"), Oracle("V")), force=True)
    assert gate.check()[1] == "ok"


def test_the_wake_check_runs_after_each_swap_of_a_screening_run(gate: Gate, tmp_path: Path) -> None:
    """two_phase's default probe is the gate's wake check: a woken verifier that answers wrongly is not used."""
    from orchestrator.twophase import two_phase

    selftest.preflight(_orch(tmp_path, Oracle("J"), Oracle("V")), force=True)
    wc = {c["id"] for c in wake_cases()}

    from dataclasses import dataclass

    @dataclass
    class J:
        """A two-model screen of one note question (the canary's first case) through the real two_phase."""

        llm: Any
        verifier: Any
        failures: int = 0

    case = CASES[0]
    variables = {k: case[k] for k in ("criterion_text", "note_question", "index_date", "excerpts")}

    def screen(j: J) -> str:
        try:
            a = j.llm.chat_json("judge", variables).data["verdict"]
            b = j.verifier.chat_json("judge", variables).data["verdict"]
        except LlmError:
            j.failures += 1
            return "unknown"
        return a if a == b else "unknown"

    swaps: list[str] = []
    out = two_phase(J(Oracle("J"), Oracle("V", wc)), screen, swaps.append, workers=1, release=lambda: None)
    assert out == "unknown" and swaps == ["serving", "verifier"]
    assert gate.status()["code"] == "wake"


def test_models_endpoint_carries_the_gate_and_run_now_starts_it(
    gate: Gate, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TB_CANARY_AT_START", "0")
    started: list[Any] = []
    monkeypatch.setattr(canary_gate, "run_canary", started.append)
    from fastapi.testclient import TestClient
    from orchestrator import app as orch_app

    fake = SimpleNamespace(services=SimpleNamespace(llm=None, verifier=None, lake=None), data_dir=tmp_path, audit=None)
    monkeypatch.setattr(orch_app, "_orch", fake)
    monkeypatch.setenv("TB_ENV", "TEST")  # no service token on a test box (D-114)
    c = TestClient(orch_app.app)
    m = c.get("/models").json()
    assert m["canary"]["gate"] == "on" and m["canary"]["code"] == "none"
    assert c.post("/models/canary").status_code == 409  # no model on this box
    fake.services.llm = Oracle("J")
    r = c.post("/models/canary")
    assert r.status_code == 200 and r.json()["started"] is True
