"""G1 rehearsal run-a (2026-11-12): a box whose model gateway is an installed (PRODUCTION) one approved a study in a
DEV process. The approval pinned the newest judge prompt, which waits for its qualification record (D-359); the
gateway's environment refuses that version, so every note call of SCREEN was refused before it reached a model and the
job ended with "the judge model did not answer 5 calls in a row". Four things are held here:

* an approval can pin the version another environment serves (the box's gateway's), and that pin loads there;
* the harness tells the box's compiler which environment its gateway is (``tools.public_e2e.attach_models``);
* a pinned prompt the box may not use stops SCREEN before any model call, with the reason, and is never counted as a
  model that did not answer (the breaker);
* a failed canary says which threshold failed and names its first wrong cases with their reasons (OD-10).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from orchestrator import selftest
from orchestrator.clients import StepFailed
from orchestrator.scenarios import screen
from tb_common import llm as llm_mod
from tb_common.llm import LlmError, LlmPromptUnqualified, LlmResult, load_prompt
from tb_common.ruleset import Ruleset
from tb_contracts import RulesetManifest
from tb_llm import prompt_registry
from tb_llm.prompt_registry import PromptRegistryError, default_registry


def _manifest(**extra: Any) -> RulesetManifest:
    return RulesetManifest.model_validate(
        {
            "id": "PIN-G1",
            "kind": "trial",
            "title": "synthetic pin test",
            "version": "1.0.0",
            "status": "approved",
            "index_date_rule": "run_date",
            "scopes": {},
            "routing": {},
            "thresholds": {},
            "criteria": [],
            **extra,
        }
    )


# ------------------------------------------------------------------------------------------------ the approval's pin
def test_an_approval_pins_the_version_the_gateways_environment_serves() -> None:
    from criteria_compiler.service import approval_pins

    reg = default_registry()
    served = reg.served("judge", "PRODUCTION")
    out = approval_pins(_manifest(), environment="PRODUCTION")
    assert out["prompt_pins"]["judge"]["version"] == served.version
    assert out["prompt_pins"]["judge"]["sha256"] == served.sha256
    assert out["models"]["judge_prompt"] == f"judge_v{served.version}"
    # what was pinned is what a PRODUCTION gateway takes: the pinned name loads there
    assert load_prompt(out["models"]["judge_prompt"], "PRODUCTION").meta.version == served.version
    # no environment named: this process's (TB_ENV), as before
    assert approval_pins(_manifest())["prompt_pins"]["judge"]["version"] == reg.served("judge").version


def test_the_harness_names_its_gateways_environment_to_the_boxs_compiler(monkeypatch: pytest.MonkeyPatch) -> None:
    from tools.public_e2e import attach_models

    monkeypatch.setenv("TB_CANARY_GATE", "off")
    deps = SimpleNamespace(prompt_environment=None)
    services = SimpleNamespace(llm=None, verifier=None, compiler=SimpleNamespace(d=deps))
    box = SimpleNamespace(orch=SimpleNamespace(audit=object(), services=services))
    judge = SimpleNamespace(audit=None, gateway=SimpleNamespace(prompt_environment="PRODUCTION"))
    verifier = SimpleNamespace(audit=None, gateway=SimpleNamespace(prompt_environment="PRODUCTION"))
    assert attach_models(box, judge, verifier) is None
    assert deps.prompt_environment == "PRODUCTION"
    # a direct pair (no gateway) names none: the approval pins this process's served version
    deps.prompt_environment = None
    attach_models(box, SimpleNamespace(audit=None), None)
    assert deps.prompt_environment is None


# ------------------------------------------------------------------------------------------------ SCREEN, the breaker
class _Refusing:
    def get(self, *a: Any, **kw: Any) -> Any:
        raise PromptRegistryError("prompt_unqualified", "zz@9 has no qualification record: refused in PRODUCTION")


def test_an_unqualified_prompt_is_not_a_model_that_did_not_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator.jobs import NOT_DOWN, Breaker, BreakerSettings, GuardedLlm

    monkeypatch.setattr(prompt_registry, "default_registry", _Refusing)
    with pytest.raises(LlmPromptUnqualified) as exc:
        load_prompt("zz_v9", "PRODUCTION")
    assert "prompt_unqualified" in str(exc.value) and isinstance(exc.value, NOT_DOWN)

    class Client:
        def chat_json(self, prompt_id: str, variables: dict[str, Any], **kw: Any) -> Any:
            return load_prompt(prompt_id, "PRODUCTION")

    b = Breaker(BreakerSettings(failures=5, window_s=300.0))
    g = GuardedLlm(Client(), lambda: False, b, "judge")
    for _ in range(8):
        # the job stops at the call (review of 2026-11-12: it cannot succeed on a retry), and says which prompt
        with pytest.raises(StepFailed, match="prompt_unqualified") as stop:
            g.chat_json("zz_v9", {})
        assert "zz_v9" in str(stop.value) and isinstance(stop.value.__cause__, LlmPromptUnqualified)
    assert b.state == "closed" and b.failures == 0  # the request was refused; no model was down


def test_screen_stops_before_any_model_call_when_the_pinned_prompt_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    reg = default_registry()
    top = reg.entry("judge")
    rs = Ruleset(_manifest(prompt_pins=reg.pins({"judge": top.version})), [], {})
    calls: list[str] = []

    class Client:
        gateway = SimpleNamespace(prompt_environment="PRODUCTION")

        def chat_json(self, prompt_id: str, variables: dict[str, Any], **kw: Any) -> Any:
            calls.append(prompt_id)
            raise LlmError("not reached")

    seen: list[tuple[str, str | None]] = []

    def refuse(prompt_id: str, environment: str | None = None) -> Any:
        seen.append((prompt_id, environment))
        raise LlmPromptUnqualified(f"prompt {prompt_id!r} refused (prompt_unqualified): no qualification record")

    monkeypatch.setattr(screen, "load_prompt", refuse)
    ctx = SimpleNamespace(
        services=SimpleNamespace(llm=Client(), verifier=None, lake=None), job=SimpleNamespace(job_id="J1")
    )
    with pytest.raises(StepFailed) as exc:
        screen.judge_for(ctx, rs)  # type: ignore[arg-type]
    msg = str(exc.value)
    assert f"judge_v{top.version}" in msg and "prompt_unqualified" in msg and "No model was asked" in msg
    assert seen == [(f"judge_v{top.version}", "PRODUCTION")] and calls == []


def test_screen_takes_a_pinned_prompt_the_box_serves() -> None:
    reg = default_registry()
    served = reg.served("judge", "PRODUCTION")
    rs = Ruleset(_manifest(prompt_pins=reg.pins({"judge": None}, environment="PRODUCTION")), [], {})
    client = SimpleNamespace(gateway=SimpleNamespace(prompt_environment="PRODUCTION"))
    ctx = SimpleNamespace(
        services=SimpleNamespace(llm=client, verifier=None, lake=None), job=SimpleNamespace(job_id="J1")
    )
    nj = screen.judge_for(ctx, rs)  # type: ignore[arg-type]
    assert nj is not None and nj.prompt == f"judge_v{served.version}"


# ------------------------------------------------------------------------------------------------ the canary's words
class _Abstains:
    """A model that is up and answers every case "not in the note" (what the deterministic stub does)."""

    def __init__(self, model: str, misquote: bool = False) -> None:
        self.model, self.served_root, self.misquote = model, model, misquote

    def chat_json(self, prompt_id: str, variables: dict[str, Any], **kw: Any) -> LlmResult:
        data: dict[str, Any] = {"verdict": "unknown", "confidence": 0.5, "quote": None}
        if self.misquote:
            data = {"verdict": "pass", "confidence": 0.9, "quote": "This sentence is in no excerpt."}
        return LlmResult(data, "judge", 4, self.model, "local", "i", "o", 10, 5, 1)


def test_a_failed_canary_says_which_threshold_and_names_its_first_wrong_cases() -> None:
    rep = selftest.run_selftest(_Abstains("J"), _Abstains("V", misquote=True))  # type: ignore[arg-type]
    assert not rep["ok"]
    judge, verifier = rep["problems"][0], rep["problems"][1]
    assert judge.startswith("judge J failed the canary")
    # the threshold that failed, with the figures
    assert "18 of 54 correct, at least 46 needed" in judge and "54 of 54 answered" in judge
    # the first wrong cases, each with what was expected, what came back and why
    assert "en:t2dm:yes expected pass, got unknown (abstained)" in judge
    assert "expected pass, got unknown (quote_not_found)" in verifier
    wrong = rep["models"][0]["wrong"][0]
    assert wrong == {"id": "en:t2dm:yes", "expected": "pass", "got": "unknown", "reason": "abstained"}
    assert rep["models"][1]["wrong"][0]["reason"] == "quote_not_found"
    # the audit record and the gate keep the line short enough to read
    assert all(len(p) <= 400 for p in rep["problems"])


def test_a_canary_that_passes_gives_no_reason_and_a_down_model_keeps_its_error() -> None:
    cases = selftest.load_cases()

    class Good(_Abstains):
        def chat_json(self, prompt_id: str, variables: dict[str, Any], **kw: Any) -> LlmResult:
            c = next(x for x in cases if x["excerpts"] == variables["excerpts"]
                     and x["note_question"] == variables["note_question"])  # fmt: skip
            v = c["expected"]
            quote = c["excerpts"][0]["text"] if v != "unknown" else None
            return LlmResult({"verdict": v, "confidence": 0.9, "quote": quote}, "judge", 4, self.model, "local",
                             "i", "o", 10, 5, 1)  # fmt: skip

    class Down(_Abstains):
        def chat_json(self, prompt_id: str, variables: dict[str, Any], **kw: Any) -> LlmResult:
            raise LlmError("connection refused")

    assert selftest.run_selftest(Good("J"), Good("V"))["problems"] == []  # type: ignore[arg-type]
    down = selftest.run_selftest(Down("J"), None)["problems"][0]  # type: ignore[arg-type]
    assert "0 of 54 answered, at least 52 needed" in down and "connection refused" in down


def test_llm_module_keeps_the_plain_error_for_other_registry_refusals(monkeypatch: pytest.MonkeyPatch) -> None:
    class Unknown:
        def get(self, *a: Any, **kw: Any) -> Any:
            raise PromptRegistryError("prompt_unknown", "zz is not registered")

    monkeypatch.setattr(prompt_registry, "default_registry", Unknown)
    with pytest.raises(LlmError) as exc:
        llm_mod.load_prompt("zy_v8", "DEV")
    assert not isinstance(exc.value, LlmPromptUnqualified)
