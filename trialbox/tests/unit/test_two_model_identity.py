"""A note answer excludes only when two DIFFERENT models agree (D-276; safety review S-2).

Before, a verifier that was the judge's own model (the same endpoint and name, ``LLM_VERIFIER_MODEL`` left to its
default, or the judge's alias named again) was accepted: ``effective_note_block`` said ``both_agree``, the "verifier"
repeated the judge at temperature 0, the pair canary passed, and one model alone excluded patients. Now the pair is
checked where it is configured (``same_model``: the run falls back to never-exclude, start-up audits it, the doctor
fails), where it answers (``combine``: two answers served under one model name are ``unknown`` / ``same_model``),
and in the canary (a pair that is one model does not pass).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from orchestrator import canary_gate, selftest
from orchestrator.scenarios.evaluate import NoteJudge, effective_note_block
from tb_common.llm import LlmClient, LlmResult
from tb_common.pair import Vote, combine, same_model, served_keys
from tb_llm import GatewayClient

from tools.trialbox import doctor

CASES = selftest.load_cases()


@pytest.fixture(autouse=True)
def _policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_NOTE_BLOCK", "both_agree")
    monkeypatch.setenv("TB_CANARY_GATE", "off")


def _direct(url: str, model: str, models: list[dict[str, Any]] | None = None) -> LlmClient:
    """A direct client; ``models`` is what its endpoint's ``/models`` lists (None: the endpoint has no such page)."""
    c = LlmClient(url, model)

    def handler(req: httpx.Request) -> httpx.Response:
        if models is None:
            return httpx.Response(404)
        return httpx.Response(200, json={"object": "list", "data": models})

    c.http = httpx.Client(transport=httpx.MockTransport(handler))
    return c


def _gateway(url: str, alias: str | None) -> LlmClient:
    return LlmClient("http://llm-service:8000/v1", "", gateway=GatewayClient(url, "orchestrator", model=alias))


def _block(llm: Any, verifier: Any) -> tuple[bool, str, str]:
    return effective_note_block(NoteJudge(lake=None, llm=llm, verifier=verifier))


# ------------------------------------------------------------------------------------------------ configured pair
GEMMA = [{"id": "local/gemma-4-26b-a4b-nvfp4", "root": "/models/gemma-4-26b-a4b-it-4bit"}]
QWEN = [{"id": "local/qwen3.5-9b-awq", "root": "/models/qwen3.5-9b-4bit"}]


def test_two_differently_named_models_may_exclude() -> None:
    j = _direct("http://llm-service:8000/v1", "local/gemma-4-26b-a4b-nvfp4", GEMMA)
    v = _direct("http://llm-verifier:8000/v1", "local/qwen3.5-9b-awq", QWEN)
    assert same_model(j, v) is None
    assert _block(j, v)[:2] == (True, "both_agree")
    assert (
        same_model(_gateway("http://gateway:8020/v1", None), _gateway("http://gateway:8020/v1", "v-verifier")) is None
    )


@pytest.mark.parametrize(
    ("judge", "verifier", "says"),
    [
        # the review's trigger: LLM_VERIFIER_BASE_URL = the judge's URL, no LLM_VERIFIER_MODEL
        (("http://llm-service:8000/v1", "qwen"), ("http://llm-service:8000/v1", "qwen"), "both are the model qwen"),
        # one served name behind two URLs is still one model; case, a trailing slash and spaces do not make two
        (("http://a:8000/v1", "local/Gemma-4"), ("http://b:8000/v1/", " local/gemma-4 "), "both are the model"),
        (("http://a:8000/v1", "qwen"), ("http://a:8000/v1", ""), "a model has no name"),
    ],
)
def test_one_model_configured_twice_falls_back_to_never_exclude(judge: Any, verifier: Any, says: str) -> None:
    j, v = _direct(*judge), _direct(*verifier)
    assert says in (same_model(j, v) or "")
    may, policy, why = _block(j, v)
    assert (may, policy) == (False, "never") and "not a second model" in why and "single model" in why


def test_the_judges_own_client_and_the_judges_own_alias_are_one_model() -> None:
    j = _direct("http://llm-service:8000/v1", "qwen")
    assert _block(j, j)[:2] == (False, "never")
    gw = "http://gateway:8020/v1"
    for a, b in ((None, None), ("j-workhorse", "J-Workhorse"), ("v-verifier", "v-verifier")):
        why = same_model(_gateway(gw, a), _gateway(gw + "/", b))
        assert why and "same gateway" in why, (a, b)
        assert _block(_gateway(gw, a), _gateway(gw, b))[:2] == (False, "never")


def test_two_served_names_of_one_vllm_are_one_model_on_any_url() -> None:
    """vLLM can serve one set of weights under several names (``--served-model-name a b``); ``/models`` gives each
    the same ``root``. Two URLs can reach that one server (a host name and an IP). Two roots are two models."""
    one = [{"id": "judge", "root": "/models/gemma-4"}, {"id": "verifier", "root": "/models/gemma-4"}]
    two = [{"id": "judge", "root": "/models/gemma-4"}, {"id": "verifier", "root": "/models/qwen3.5"}]
    for vurl in ("http://vllm:8000/v1", "http://10.0.0.5:8000/v1"):  # review F-02: not only textually equal URLs
        j, v = _direct("http://vllm:8000/v1", "judge", one), _direct(vurl, "verifier", one)
        assert "same weights" in (same_model(j, v) or "")
        assert _block(j, v)[:2] == (False, "never")
        assert same_model(_direct("http://vllm:8000/v1", "judge", two), _direct(vurl, "verifier", two)) is None


@pytest.mark.parametrize(
    ("models", "why"),
    [
        (None, "does not say which weights"),  # no /models (404)
        ("down", "does not say which weights"),  # /models errors or times out
        ([{"id": "judge"}, {"id": "verifier"}], "does not say which weights"),  # listed, no root
        ([{"id": "something-else", "root": "/m"}], "does not say which weights"),  # name not listed (llama.cpp)
    ],
)
def test_a_direct_pair_whose_weights_cannot_be_told_is_one_model(models: Any, why: str) -> None:
    """Fail closed (review F-02; this test used to assert the opposite: "no /models: names decide"). When the box
    cannot tell which weights each endpoint serves, a note answer may not exclude."""
    if models == "down":
        j = LlmClient("http://vllm:8000/v1", "judge")
        v = LlmClient("http://other:8000/v1", "verifier")

        def boom(req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("scripted time-out")

        j.http = v.http = httpx.Client(transport=httpx.MockTransport(boom))
    else:
        j, v = _direct("http://vllm:8000/v1", "judge", models), _direct("http://other:8000/v1", "verifier", models)
    assert why in (same_model(j, v) or "")
    may, policy, reason = _block(j, v)
    assert (may, policy) == (False, "never") and "not a second model" in reason


def test_a_gateway_judge_with_no_alias_gets_the_default_build(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review F-03: a judge that names no alias gets the gateway's default build; a verifier naming that build is the
    judge again. A judge through the gateway and a verifier straight to an endpoint cannot be compared."""
    gw = "http://gateway:8020/v1"
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    assert "j-workhorse" in (same_model(_gateway(gw, None), _gateway(gw, "j-workhorse")) or "")
    assert same_model(_gateway(gw, None), _gateway(gw, "v-verifier")) is None
    monkeypatch.setenv("TB_ENV", "TEST")
    assert "trialbox-stub" in (same_model(_gateway(gw, None), _gateway(gw, "trialbox-stub")) or "")
    assert same_model(_gateway(gw, None), _gateway(gw, "stub-verifier")) is None
    mixed = same_model(_gateway(gw, None), _direct("http://v:8000/v1", "verifier", QWEN))
    assert mixed and "cannot be told apart" in mixed


# ------------------------------------------------------------------------------------------------ the answers
def test_two_answers_served_under_one_name_are_unknown_not_an_agreement() -> None:
    a = Vote("fail", 0.9, None, served_keys("local/Gemma-4"))
    d = combine(a, Vote("fail", 0.9, None, served_keys(" local/gemma-4")))
    # the judge did not really answer: model_down, counted as a failure (review LLM-002)
    assert (d.verdict, d.reason, d.same_model, d.failure) == ("unknown", "model_down", True, True)
    ok = combine(a, Vote("fail", 0.8, None, served_keys("local/qwen3.5")))
    assert (ok.verdict, ok.confidence, ok.same_model) == ("fail", 0.8, False)
    # through the gateway: one build (the same weights digest) under two served names is one model too
    one_build = combine(
        Vote("fail", 0.9, None, served_keys("name-a", "sha256:abc")),
        Vote("fail", 0.9, None, served_keys("name-b", "SHA256:ABC")),
    )
    assert one_build.reason == "model_down" and one_build.failure
    assert served_keys("", "") == () and served_keys("x") == ("name:x",)
    assert combine(Vote("fail", 0.9), Vote("fail", 0.9)).verdict == "fail"  # no name known: the configured check rules


# ------------------------------------------------------------------------------------------------ canary, start-up
class Oracle:
    """Answers every canary case right, under the served name ``served``."""

    gateway = None

    def __init__(self, model: str, served: str | None = None, base_url: str | None = None) -> None:
        self.model, self.served = model, served or model
        self.served_root = self.served  # the weights it is served from (``tb_common.pair.served_root``)
        self.base_url = base_url or f"http://{model}/v1"

    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> LlmResult:
        case = next(
            c
            for c in CASES
            if c["excerpts"] == variables["excerpts"] and c["note_question"] == variables["note_question"]
        )
        want = case["expected"]
        quote = None if want == "unknown" else case["excerpts"][0]["text"][:20]
        d = {"verdict": want, "reason": "r", "confidence": 0.9, "quote": quote, "quote_date": None}
        return LlmResult(d, prompt_id, 4, self.served, "local", "i" * 64, "o" * 64, 1, 1, 1)


def test_a_pair_that_is_one_model_does_not_pass_the_canary() -> None:
    """The pair canary compared answers, not models: one correct model asked twice agreed with itself and passed."""
    ok = selftest.run_selftest(Oracle("J"), Oracle("V"))  # type: ignore[arg-type]
    assert ok["ok"] and "same_model" not in ok["pair"]
    for verifier in (Oracle("J", base_url="http://other/v1"), Oracle("V", served="J")):  # configured; as served
        rep = selftest.run_selftest(Oracle("J"), verifier)  # type: ignore[arg-type]
        assert not rep["ok"] and rep["pair"]["same_model"]
        assert any("not a second model" in p for p in rep["problems"])
        assert rep["pair"]["correct"] == 54  # the answers alone would have passed


def _orch(tmp_path: Path, llm: Any, verifier: Any) -> Any:
    events: list[tuple[str, dict[str, Any]]] = []
    audit = SimpleNamespace(append=lambda ev, detail=None, **kw: events.append((ev, detail or {})))
    services = SimpleNamespace(llm=llm, verifier=verifier)
    return SimpleNamespace(services=services, data_dir=tmp_path, audit=audit, ev=events)


def test_start_up_reports_and_audits_a_verifier_that_is_the_judge(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(canary_gate, "GATE", canary_gate.Gate())  # this test's own gate, not the process's
    j = _direct("http://llm-service:8000/v1", "qwen", [{"id": "qwen", "root": "/models/qwen"}])
    good = _orch(tmp_path, j, _direct("http://llm-verifier:8000/v1", "gemma", [{"id": "gemma", "root": "/models/g"}]))
    assert canary_gate.check_pair(good) is None and good.ev == []
    bad = _orch(tmp_path, j, _direct("http://llm-service:8000/v1", "qwen"))
    with caplog.at_level("ERROR"):
        canary_gate.startup(bad)  # the gate is off on this box: the check runs all the same
    assert [e for e, _ in bad.ev] == ["llm.pair.same_model"]
    detail = bad.ev[0][1]
    assert detail["judge"] == detail["verifier"] == "qwen" and detail["note_block"] == "never"
    assert any("FAIL" in r.getMessage() and "not a second model" in r.getMessage() for r in caplog.records)
    assert canary_gate.check_pair(_orch(tmp_path, j, None)) is None  # one model: the doctor and the run say so


# ------------------------------------------------------------------------------------------------ doctor
def _note_block(env: dict[str, str]) -> doctor.Check:
    checks = doctor.run(doctor.DoctorInputs(env={"TB_TOPOLOGY": "A", **env}))
    return next(c for c in checks if c.name == "note_block")


@pytest.mark.parametrize(
    "env",
    [
        {"LLM_VERIFIER_BASE_URL": "http://llm-service:8000/v1", "LLM_MODEL": "qwen"},  # the review's trigger
        {"LLM_VERIFIER_BASE_URL": "http://x:8000/v1", "LLM_MODEL": "qwen", "LLM_VERIFIER_MODEL": "QWEN "},
        {"TB_GATEWAY_URL": "http://gw/v1", "TB_GATEWAY_MODEL": "j-workhorse", "TB_GATEWAY_VERIFIER_MODEL": "j-workhorse"},
        {"TB_GATEWAY_URL": "http://gw/v1", "TB_GATEWAY_VERIFIER_MODEL": "j-workhorse"},  # the judge's default build
    ],
)  # fmt: skip
@pytest.mark.parametrize("tb_env", ["TEST", "PRODUCTION"])
def test_doctor_fails_a_verifier_that_is_the_judge(env: dict[str, str], tb_env: str) -> None:
    if "LLM_VERIFIER_BASE_URL" not in env and tb_env == "TEST":
        env = {**env, "TB_GATEWAY_VERIFIER_MODEL": env.get("TB_GATEWAY_MODEL") or "trialbox-stub"}
    c = _note_block({**env, "TB_ENV": tb_env})
    assert c.status == "FAIL" and "not a second model" in c.detail


def test_doctor_passes_two_named_models() -> None:
    gw = {"TB_GATEWAY_URL": "http://gw/v1", "TB_ENV": "PRODUCTION", "TB_GATEWAY_VERIFIER_MODEL": "v-verifier"}
    assert _note_block(gw).status == "PASS"
    assert _note_block({**gw, "TB_ENV": "TEST", "TB_GATEWAY_VERIFIER_MODEL": "stub-verifier"}).status == "PASS"
    direct = {"LLM_VERIFIER_BASE_URL": "http://v:8000/v1", "LLM_MODEL": "gemma", "LLM_VERIFIER_MODEL": "qwen"}
    assert _note_block({**direct, "TB_ENV": "TEST"}).status == "PASS"


def test_doctor_fails_a_direct_pair_in_production_it_cannot_confirm() -> None:
    """Review F-02: on the direct path which weights each endpoint serves is known only at start (``/models``), so
    the doctor cannot confirm two models: FAIL in VALIDATION and PRODUCTION, where the gateway build is the way."""
    direct = {"LLM_VERIFIER_BASE_URL": "http://v:8000/v1", "LLM_MODEL": "gemma", "LLM_VERIFIER_MODEL": "qwen"}
    for env in ("VALIDATION", "PRODUCTION"):
        c = _note_block({**direct, "TB_ENV": env})
        assert c.status == "FAIL" and "gateway verifier build" in c.detail
    mixed = {"TB_GATEWAY_URL": "http://gw/v1", "LLM_VERIFIER_BASE_URL": "http://v:8000/v1", "LLM_VERIFIER_MODEL": "q"}
    c = _note_block({**mixed, "TB_ENV": "TEST"})
    assert c.status == "FAIL" and "not a second model" in c.detail


# ------------------------------------------------------------------------------------------------ the stub box
def test_through_the_gateway_one_build_asked_twice_is_one_model_and_the_stub_box_names_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stub box used to name ``trialbox-stub`` as the verifier while the judge got the same build by default.
    Nothing in the configuration is equal (no alias against an alias), so only the answers show it: one build."""
    from fastapi.testclient import TestClient
    from gateway.app import create_app

    from tests.unit.test_gateway import JUDGE_VARS, _gw

    monkeypatch.setenv("TB_DATA_CLASS", "D0")  # the stub box judges synthetic notes (deploy/poc.sh)
    http = TestClient(create_app(_gw(tmp_path)))

    def client(alias: str | None) -> LlmClient:
        gw = GatewayClient("http://gateway/v1", "orchestrator", http=http, model=alias)
        return LlmClient("http://unused/v1", "", gateway=gw)

    def ask(verifier_alias: str) -> tuple[Any, NoteJudge]:
        nj = NoteJudge(lake=None, llm=client(None), verifier=client(verifier_alias))
        ex = [{**e, "did": "D1"} for e in JUDGE_VARS["excerpts"]]
        return nj.judge_excerpts("Gout flare now", JUDGE_VARS["note_question"], date(2026, 10, 5), ex), nj

    old, nj = ask("trialbox-stub")
    assert (old.predicate, old.reason, nj.same_model, nj.failures) == ("unknown", "model_down", 1, 1)
    new, nj = ask("stub-verifier")  # deploy/poc.sh: the registry's second stub build, its own served name
    assert (new.predicate, new.reason, nj.same_model) == ("pass", "note", 0)
    assert new.model == "trialbox-stub" and new.build_sha == "unpinned:trialbox-stub-1"


# ------------------------------------------------------------------------------------------------ consent
def test_consent_is_not_checked_by_the_judge_itself() -> None:
    """Review F-04: the consent explainer's second-model check marked statements "ok" whatever the verifier was. A
    verifier that is the judge again checks nothing: the statements are unverified, and the refusal is audited."""
    from orchestrator.scenarios import consent

    events: list[tuple[str, dict[str, Any]]] = []
    j = _direct("http://llm-service:8000/v1", "qwen", [{"id": "qwen", "root": "/models/qwen"}])

    def ctx(verifier: Any) -> Any:
        audit = SimpleNamespace(append=lambda ev, detail=None, **kw: events.append((ev, detail or {})))
        return SimpleNamespace(
            services=SimpleNamespace(llm=j, verifier=verifier),
            orch=SimpleNamespace(audit=audit),
            job=SimpleNamespace(job_id="J1"),
        )

    other = _direct("http://llm-verifier:8000/v1", "gemma", [{"id": "gemma", "root": "/models/gemma"}])
    assert consent.models(ctx(other)).verifier is other and events == []  # control: a second model checks
    again = _direct("http://llm-verifier:8000/v1", "qwen", [{"id": "qwen", "root": "/models/qwen"}])
    assert consent.models(ctx(again)).verifier is None
    assert [e for e, _ in events] == ["llm.pair.same_model"] and events[0][1]["step"] == "consent"
