"""One-GPU robustness (survey 2026-11-07): the gateway's model swap, the chat time limit, judge-then-verifier rounds,
the nightly canary and the weight re-check at install. Offline: every model server is an ``httpx.MockTransport``."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from channels.base import ClassifiedIntent
from fastapi.testclient import TestClient
from gateway.app import create_app
from gateway.core import Gateway, GatewayConfig
from gateway.policy import RoutingPolicy
from gateway.swap import ModelSwap, SwapError, server_root
from guard.guard import Guard
from orchestrator import selftest
from orchestrator.twophase import DeferredVerifier, MemoClient, two_phase
from tb_common.audit import AuditLog
from tb_common.llm import LlmError, LlmResult, load_prompt, render
from tb_common.policy.classes import Environment

from tests.unit.test_gateway import H, _judge_body, _pinned_registry
from tools import pin_model

# ------------------------------------------------------------------------------------------------ fake vLLM pair


class FakeVllm:
    """Two vLLM servers in sleep mode on one card: a call to a sleeping one fails like the real server would."""

    def __init__(self, slow: float = 0.0) -> None:
        self.sleeping = {"llm-service": False, "llm-verifier": False}
        self.log: list[str] = []
        self.slow = slow

    def handler(self, req: httpx.Request) -> httpx.Response:
        host, path = req.url.host, req.url.path
        self.log.append(f"{req.method} {host}{path}")
        if path == "/sleep":
            self.sleeping[host] = True
            return httpx.Response(200)
        if path == "/wake_up":
            self.sleeping[host] = False
            return httpx.Response(200)
        if path == "/is_sleeping":
            return httpx.Response(200, json={"is_sleeping": self.sleeping[host]})
        if self.slow:
            raise httpx.ReadTimeout("slow", request=req)
        if self.sleeping[host]:
            return httpx.Response(500, json={"error": "model is sleeping"})
        content = json.dumps({"verdict": "pass", "confidence": 0.9, "quote": "q", "quote_date": "2026-10-01"})
        served = "j-test" if host == "llm-service" else "v-test"
        return httpx.Response(
            200,
            json={
                "model": served,
                "choices": [{"message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


URLS = {"serving": "http://llm-service:8000/v1", "verifier": "http://llm-verifier:8000/v1"}


def _swap(fake: FakeVllm) -> ModelSwap:
    return ModelSwap(URLS, http=fake.client(), wake_timeout_s=2, poll_s=0.01)


def _gw(tmp_path: Path, fake: FakeVllm, swap: ModelSwap | None) -> Gateway:
    return Gateway(
        RoutingPolicy.load(),
        _pinned_registry(),
        AuditLog(tmp_path / "audit"),
        GatewayConfig(environment=Environment.PRODUCTION),
        http=fake.client(),
        guard=Guard("^\\d{8}$"),
        step_confirm=lambda caller, study, step: True,
        env={},
        swap=swap,
    )


JH = H(Data_Class="D3")  # a screening judge call (production routes: j-workhorse@serving, then v-verifier@verifier)


def test_server_root_strips_the_openai_suffix() -> None:
    assert server_root("http://llm-service:8000/v1/") == "http://llm-service:8000"
    assert server_root("http://x:1") == "http://x:1"


@pytest.mark.req("LLM-1")
def test_activate_sleeps_the_other_model_then_wakes_and_waits() -> None:
    fake = FakeVllm()
    sw = _swap(fake)
    assert sw.awake("serving") and sw.awake("verifier")  # state unknown: nothing is held back
    st = sw.activate("verifier")
    assert st["active"] == "verifier" and fake.sleeping == {"llm-service": True, "llm-verifier": False}
    assert fake.log[:2] == ["POST llm-service/sleep", "POST llm-verifier/wake_up"]
    assert not sw.awake("serving") and sw.awake("verifier") and sw.awake("embed")
    n = len(fake.log)
    sw.activate("verifier")  # already awake: no calls
    assert len(fake.log) == n
    sw.activate("serving")
    assert fake.sleeping == {"llm-service": False, "llm-verifier": True} and sw.swaps == 2
    with pytest.raises(SwapError):
        sw.activate("embed")


def test_a_failed_swap_leaves_the_state_unknown() -> None:
    def down(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    sw = ModelSwap(URLS, http=httpx.Client(transport=httpx.MockTransport(down)), wake_timeout_s=0.05, poll_s=0.01)
    with pytest.raises(SwapError, match="enable-sleep-mode"):
        sw.activate("serving")
    assert sw.active is None


def test_swap_is_off_unless_configured() -> None:
    assert ModelSwap.from_env(URLS, {}) is None
    sw = ModelSwap.from_env(URLS, {"TB_MODEL_SWAP": "sleep"})
    assert sw is not None and set(sw.urls) == {"serving", "verifier"}


@pytest.mark.req("LLM-1", "LLM-5")
def test_gateway_does_not_send_to_a_sleeping_model_and_chat_gets_busy(tmp_path: Path) -> None:
    fake = FakeVllm()
    sw = _swap(fake)
    gw = _gw(tmp_path, fake, sw)
    sw.activate("verifier", hold=True)  # night: a screening run holds the card for its verifier pass
    res = gw.chat(JH, _judge_body())  # a judge call while the judge sleeps
    assert res.status == 503 and res.body["error"]["code"] == "model_asleep"
    assert not any(x.endswith("/chat/completions") for x in fake.log)  # not sent, and no fallback to the verifier
    sw.activate("serving")
    ok = gw.chat(JH, _judge_body())
    assert ok.status == 200 and ok.body["tb"]["alias"] == "j-workhorse"


def test_a_released_card_wakes_the_judge_on_demand(tmp_path: Path) -> None:
    """D-116: the run ends on the verifier and releases; the next judge call wakes the judge (no swap back)."""
    fake = FakeVllm()
    sw = _swap(fake)
    gw = _gw(tmp_path, fake, sw)
    sw.activate("verifier", hold=True)
    assert sw.held
    sw.release()
    assert not sw.held and sw.active == "verifier"
    ok = gw.chat(JH, _judge_body())
    assert ok.status == 200 and sw.active == "serving" and sw.on_demand == 1
    assert fake.sleeping == {"llm-service": False, "llm-verifier": True}


def test_a_hold_lapses_and_batch_calls_keep_it_alive(tmp_path: Path) -> None:
    fake = FakeVllm()
    sw = ModelSwap(URLS, http=fake.client(), wake_timeout_s=2, poll_s=0.01, hold_s=0.05)
    gw = _gw(tmp_path, fake, sw)
    sw.activate("verifier", hold=True)
    import time as _t

    _t.sleep(0.03)
    sw.touch()  # a verifier call during the pass
    _t.sleep(0.03)
    assert sw.held  # 0.06 s after the start, kept alive by the call
    _t.sleep(0.06)
    assert not sw.held  # the orchestrator died mid-run: the hold lapses, chat can wake the judge again
    assert gw.chat(CHAT_H, CHAT_BODY).status == 200


def test_interactive_roles_are_marked_in_the_routing_table() -> None:
    roles = RoutingPolicy.load().roles
    assert {r for r, v in roles.items() if v.get("interactive")} == {
        "classify_intent",
        "frontdesk_converse",
        "ops_explain",
    }


@pytest.mark.req("LLM-1")
def test_interactive_timeout_becomes_model_busy_and_batch_keeps_its_error(tmp_path: Path) -> None:
    fake = FakeVllm(slow=1)
    gw = _gw(tmp_path, fake, None)
    assert gw.interactive_timeout_s == 30.0
    batch = gw.chat(JH, _judge_body())
    assert batch.status == 502 and "ReadTimeout" in batch.body["error"]["message"]
    chat = gw.chat(CHAT_H, CHAT_BODY)
    assert chat.status == 503 and chat.body["error"]["code"] == "model_busy", chat.body
    assert "try again" in chat.body["error"]["message"]


CHAT_H = H(
    Data_Class="D3",
    Caller="converse-native",
    Role="classify_intent",
    Purpose="intake",
    Study="none",
    Step="",
    Context_Of_Use="intake_classify",
    Prompt="classify_intent@1",
)
CHAT_BODY = {
    # the registered template of classify_intent rendered, and its schema (D-300: the gateway refuses others)
    "messages": render(
        load_prompt("classify_intent_v1"),
        {"text": "how many patients for study X?", "attachments": [], "today": "2026-11-10", "language": "en"},
    ),
    "response_format": {
        "type": "json_schema",
        "json_schema": {"name": "x", "schema": ClassifiedIntent.model_json_schema()},
    },
}


def test_activate_endpoint_needs_a_judge_caller(tmp_path: Path) -> None:
    fake = FakeVllm()
    gw = _gw(tmp_path, fake, _swap(fake))
    c = TestClient(create_app(gw))
    assert (
        c.post("/v1/serving/activate", json={"endpoint": "verifier"}, headers={"X-TB-Caller": "hermes"}).status_code
        == 403
    )
    r = c.post("/v1/serving/activate", json={"endpoint": "verifier"}, headers={"X-TB-Caller": "orchestrator"})
    assert r.status_code == 200 and r.json()["active"] == "verifier"
    assert c.get("/v1/serving/status").json()["active"] == "verifier"
    assert c.post("/v1/serving/activate", json={}, headers={"X-TB-Caller": "orchestrator"}).status_code == 400
    held = c.post(
        "/v1/serving/activate", json={"endpoint": "verifier", "hold": True}, headers={"X-TB-Caller": "orchestrator"}
    )
    assert held.json()["held"] is True
    assert c.post("/v1/serving/release", headers={"X-TB-Caller": "hermes"}).status_code == 403
    rel = c.post("/v1/serving/release", headers={"X-TB-Caller": "orchestrator"})
    assert rel.status_code == 200 and rel.json()["held"] is False and rel.json()["active"] == "verifier"
    off = TestClient(create_app(_gw(tmp_path, fake, None)))
    assert off.post("/v1/serving/activate", json={"endpoint": "verifier"}).json() == {"swap": "off", "active": None}


# ------------------------------------------------------------------------------------------------ two_phase rounds


def _res(verdict: str, model: str) -> LlmResult:
    return LlmResult({"verdict": verdict}, "judge", 4, model, "local", "i", "o" + verdict, 10, 5, 1)


class FakeClient:
    """A model that answers from a table keyed by the question; counts its calls; fails when asleep."""

    def __init__(self, name: str, answers: dict[str, str], awake: dict[str, bool]) -> None:
        self.model = name
        self.answers = answers
        self.awake = awake
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> LlmResult:
        if not self.awake[self.model]:
            raise LlmError(f"{self.model} is asleep")
        q = variables["q"]
        with self._lock:
            self.calls.append(q)
        return _res(self.answers[q], self.model)


@dataclass
class ToyJudge:
    """The shape two_phase needs: llm, verifier and the counters (as NoteJudge / OrchestratorJudge)."""

    llm: Any
    verifier: Any
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    failures: int = 0
    disagreements: int = 0

    def ask(self, q: str) -> str:
        try:
            a = str(self.llm.chat_json("judge", {"q": q}).data["verdict"])
        except LlmError:
            self.failures += 1
            return "unknown"
        self.calls += 1
        if a not in ("pass", "fail"):
            return a
        try:
            b = str(self.verifier.chat_json("judge", {"q": q}).data["verdict"])
        except LlmError:
            self.failures += 1
            return "unknown"
        self.calls += 1
        if a == b:
            return a
        self.disagreements += 1
        return "unknown"


def screen(j: ToyJudge) -> dict[str, str]:
    """A screening run with a retry path that opens only after a disagreement (like the v1 full-record retry)."""
    out = {q: j.ask(q) for q in ("q1", "q2", "q3")}
    if out["q2"] == "unknown":
        out["q2-full"] = j.ask("q2-full")
    return out


def _pair() -> tuple[FakeClient, FakeClient, dict[str, bool], list[str]]:
    awake = {"J": True, "V": True}
    judge = FakeClient("J", {"q1": "pass", "q2": "fail", "q3": "unknown", "q2-full": "fail"}, awake)
    verifier = FakeClient("V", {"q1": "pass", "q2": "pass", "q3": "pass", "q2-full": "fail"}, awake)
    return judge, verifier, awake, []


def test_two_phase_equals_the_inline_two_model_run_with_one_model_awake_at_a_time() -> None:
    jc, vc, awake, swaps = _pair()
    inline = screen(ToyJudge(jc, vc))
    inline_calls = (len(jc.calls), len(vc.calls))
    jc.calls.clear()
    vc.calls.clear()

    def swap(endpoint: str) -> None:
        swaps.append(endpoint)
        awake["J"], awake["V"] = endpoint == "serving", endpoint == "verifier"

    released: list[bool] = []
    tj = ToyJudge(jc, vc)
    phased = two_phase(tj, screen, swap, workers=2, release=lambda: released.append(True))
    assert phased == inline == {"q1": "pass", "q2": "unknown", "q3": "unknown", "q2-full": "fail"}
    assert (len(jc.calls), len(vc.calls)) == inline_calls == (4, 3)  # every question asked once per model
    assert sorted(vc.calls) == ["q1", "q2", "q2-full"]
    # round 1: judge, verifier (q1, q2); round 2 opens the retry q2-full: judge again (new question), verifier again
    assert swaps == ["serving", "verifier", "serving", "verifier"]
    assert released == [True] and awake == {"J": False, "V": True}  # no swap back: the gateway wakes on demand
    assert tj.disagreements == 1 and tj.failures == 0 and tj.calls == 7


def test_a_run_without_a_new_path_costs_one_swap_and_releases_the_card() -> None:
    """TB-PLAN-03 step 1 (D-116): judge batch -> sleep -> verifier batch; the merge round is answered from memory."""
    jc, vc, awake, swaps = _pair()

    def swap(endpoint: str) -> None:
        swaps.append(endpoint)
        awake["J"], awake["V"] = endpoint == "serving", endpoint == "verifier"

    def no_retry(j: ToyJudge) -> dict[str, str]:
        return {q: j.ask(q) for q in ("q1", "q2", "q3")}

    released: list[bool] = []
    out = two_phase(ToyJudge(jc, vc), no_retry, swap, workers=2, release=lambda: released.append(True))
    assert out == {"q1": "pass", "q2": "unknown", "q3": "unknown"}
    assert swaps == ["serving", "verifier"] and released == [True]
    assert sorted(jc.calls) == ["q1", "q2", "q3"]  # the merge round asked the judge nothing


def test_a_run_with_no_note_question_swaps_nothing() -> None:
    jc, vc, _, swaps = _pair()
    assert two_phase(ToyJudge(jc, vc), lambda j: "filters only", swaps.append, release=lambda: None) == "filters only"
    assert swaps == []


def test_a_model_failing_its_wake_check_is_not_trusted_for_the_run() -> None:
    """A woken model that answers its wake questions wrongly: its answers become errors, so unknown, not exclusions."""
    jc, vc, awake, swaps = _pair()

    def swap(endpoint: str) -> None:
        swaps.append(endpoint)
        awake["J"], awake["V"] = endpoint == "serving", endpoint == "verifier"

    def probe(endpoint: str) -> str | None:
        return "wake check: 2 wrong" if endpoint == "verifier" else None

    tj = ToyJudge(jc, vc)
    out = two_phase(tj, screen, swap, workers=2, probe=probe)
    assert out["q1"] == "unknown" and "fail" not in out.values()  # the verifier's answers were not used
    assert vc.calls == []  # not even asked
    assert tj.failures >= 1


def test_two_phase_is_one_plain_run_without_a_swap_or_verifier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_MODEL_SWAP", raising=False)
    jc, vc, _, _ = _pair()
    assert two_phase(ToyJudge(jc, vc), screen) == screen(ToyJudge(jc, vc))
    seen: list[str] = []
    assert two_phase(ToyJudge(jc, None), lambda j: "ran", seen.append) == "ran" and seen == []


def test_strict_last_round_turns_a_missing_answer_into_unknown_not_an_exclusion() -> None:
    jc, vc, _, _ = _pair()
    memo = MemoClient(jc)  # type: ignore[arg-type]
    dv = DeferredVerifier(vc, memo)  # type: ignore[arg-type]
    dv.strict = True
    memo.chat_json("judge", {"q": "q2"})
    with pytest.raises(LlmError, match="not available"):
        dv.chat_json("judge", {"q": "q2"})
    assert dv.pending == {}


def test_memo_replays_judge_errors_without_a_second_call() -> None:
    jc, _, awake, _ = _pair()
    awake["J"] = False
    memo = MemoClient(jc)  # type: ignore[arg-type]
    for _ in range(2):
        with pytest.raises(LlmError):
            memo.chat_json("judge", {"q": "q1"})
    assert memo.live_calls == 1 and memo.model == "J"


# ------------------------------------------------------------------------------------------------ canary


class CanaryModel:
    def __init__(self, model: str, flip: int = 0, down: bool = False) -> None:
        self.model = model
        self.served_root = model  # its own weights (tb_common.pair.served_root, D-276)
        self.flip = flip
        self.down = down

    def chat_json(self, prompt_id: str, variables: dict[str, Any], **kw: Any) -> LlmResult:
        if self.down:
            raise LlmError("connection refused")
        case = next(
            c
            for c in CASES
            if c["note_question"] == variables["note_question"] and c["excerpts"] == variables["excerpts"]
        )
        v = case["expected"]
        if self.flip and v in ("pass", "fail"):
            self.flip -= 1
            v = "fail" if v == "pass" else "pass"
        quote = case["excerpts"][0]["text"] if v != "unknown" else None
        return LlmResult(
            {"verdict": v, "confidence": 0.9, "quote": quote}, "judge", 4, self.model, "local", "i", "o", 10, 5, 1
        )


CASES = selftest.load_cases()


def test_canary_set_is_54_balanced_cases_in_three_languages() -> None:
    assert len(CASES) == 54 and len({c["id"] for c in CASES}) == 54
    for lang in ("en", "ja", "zh-TW"):
        exp = [c["expected"] for c in CASES if c["language"] == lang]
        assert exp.count("pass") == exp.count("fail") == 6 and exp.count("unknown") == 6


def test_canary_passes_a_good_pair_and_leaves_the_judge_awake() -> None:
    swaps: list[str] = []
    rep = selftest.run_selftest(CanaryModel("J"), CanaryModel("V"), swaps.append)  # type: ignore[arg-type]
    assert rep["ok"], rep
    assert [m["correct"] for m in rep["models"]] == [54, 54]
    assert swaps == ["serving", "verifier", "serving"]


def test_canary_fails_on_two_flips_or_a_model_that_is_down() -> None:
    rep = selftest.run_selftest(CanaryModel("J"), CanaryModel("V", flip=2))  # type: ignore[arg-type]
    assert not rep["ok"] and rep["models"][1]["flips"] == 2 and "verifier V failed" in rep["problems"][0]
    one = selftest.run_selftest(CanaryModel("J", flip=1), None)  # type: ignore[arg-type]
    assert one["ok"]  # a single flip is tolerated, and a judge-only box checks the judge only
    down = selftest.run_selftest(CanaryModel("J", down=True), None)  # type: ignore[arg-type]
    assert not down["ok"] and down["models"][0]["answered"] == 0
    assert not selftest.run_selftest(None, None)["ok"]


def test_a_failed_canary_holds_the_night_jobs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator import scheduler

    monkeypatch.delenv("TB_MODEL_SWAP", raising=False)
    events: list[str] = []

    class Orch:
        data_dir = tmp_path
        audit = type("A", (), {"append": staticmethod(lambda ev, **kw: events.append(ev))})()
        services = type("S", (), {"llm": CanaryModel("J", down=True), "verifier": None})()

    scheduler._gate.clear()
    assert scheduler.night_gate(Orch(), "2026-11-08") is False  # type: ignore[arg-type]
    assert scheduler.night_gate(Orch(), "2026-11-08") is False and events == ["selftest.failed"]  # type: ignore[arg-type]
    assert json.loads((tmp_path / "selftest.json").read_text())["ok"] is False
    monkeypatch.setenv("TB_SELFTEST", "off")
    assert scheduler.night_gate(Orch(), "2026-11-09") is True  # type: ignore[arg-type]


# ------------------------------------------------------------------------------------------------ weight re-check


@pytest.mark.req("SEC-64")
def test_verify_all_checks_every_pin_and_refuses_an_empty_override(tmp_path: Path) -> None:
    from tests.unit.test_pin_model import BUILD, SERVED, _model_dir

    models = tmp_path / "models"
    d = _model_dir(models)
    out = tmp_path / "site" / "o.yaml"
    assert pin_model.verify_all(models, out) == (False, [f"nothing is pinned in {out}"])
    pin_model.pin(BUILD, d, served_name=SERVED, out=out, trust_first_use=True)
    assert pin_model.main(["--verify-all", str(models), "--out", str(out)]) == 0
    (d / "model-00001-of-00002.safetensors").write_bytes(b"tampered")
    good, lines = pin_model.verify_all(models, out)
    assert not good and "changed since the pin" in lines[0]
    d.rename(models / "gone")
    good, lines = pin_model.verify_all(models, out)
    assert not good and "missing" in lines[0]
    assert pin_model.main(["--verify-all", str(models), "--out", str(out)]) == 1


def test_compose_pins_the_tested_vllm_release_and_sleep_mode() -> None:
    root = Path(__file__).resolve().parents[2]
    for f in ("deploy/docker-compose.yml", "deploy/docker-compose.rtx5090.yml"):
        text = (root / f).read_text(encoding="utf-8")
        assert (
            "vllm/vllm-openai:v0.32.0" in text and "v0.11.0" not in text and "- --guided-decoding-backend" not in text
        )
    r5090 = (root / "deploy/docker-compose.rtx5090.yml").read_text(encoding="utf-8")
    assert r5090.count("--enable-sleep-mode") == 2 and 'VLLM_SERVER_DEV_MODE: "1"' in r5090
    assert "enable_thinking" in r5090 and 'TB_MODEL_SWAP: "${TB_MODEL_SWAP:-sleep}"' in r5090


def test_chat_during_the_verifier_pass_is_told_busy_at_once(tmp_path: Path) -> None:
    fake = FakeVllm()
    sw = _swap(fake)
    gw = _gw(tmp_path, fake, sw)
    sw.activate("verifier", hold=True)
    res = gw.chat(CHAT_H, CHAT_BODY)
    assert res.status == 503 and res.body["error"]["code"] == "model_busy"


def test_native_engine_reports_a_busy_model() -> None:
    from datetime import date

    from channels.native.engine import EngineBusy, NativeEngine
    from tb_llm import GatewayRefused

    class BusyGateway:
        def chat(self, *a: Any, **kw: Any) -> Any:
            raise GatewayRefused("model_busy", 503, "busy")

    eng = NativeEngine(BusyGateway(), today=lambda: date(2026, 11, 7))  # type: ignore[arg-type]
    with pytest.raises(EngineBusy):
        eng.classify("患者は何人ですか？", (), "ja", "D3")
