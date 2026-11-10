"""A judge that fails is a failure, not another model's answer (D-276; deep review LLM-002, LLM-003).

The ``patient`` route lists the judge build and then the verifier build. When the judge's server returned an error,
the gateway fell through to the next build and answered the role ``judge`` from the *verifier* build. The note judge
then asked the verifier, which confirmed its own answer: two "agreeing" answers from one model, ``failures`` 0, and a
note answer that could exclude. The install also left ``TB_GATEWAY_MODEL`` empty, so the judge named no build.

Now: (a) roles of the ``patient`` group never fall back to another alias (a route may say ``fallback: none``, and for
those roles it is always so); (b) install names the judge build on the pair profiles; (c) the note judge compares
which build served each answer, and the same build twice is ``model_down``, counted as a failure.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from gateway.app import create_app
from gateway.policy import RoutingPolicy
from orchestrator.scenarios.evaluate import NoteJudge, check_judge
from tb_common.llm import LlmClient
from tb_llm import GatewayClient

from tests.unit.test_gateway import _judge_body
from tests.unit.test_model_swap import JH, FakeVllm, _gw

ROOT = Path(__file__).resolve().parents[2]
EXCERPTS = [{"date": "2026-10-01", "note_type": "progress", "text": "q", "did": "D1"}]


class JudgeDown(FakeVllm):
    """The pair's two servers; the judge's answers HTTP 500 to every chat call, the verifier answers ``pass``."""

    def handler(self, req: httpx.Request) -> httpx.Response:
        if req.url.host == "llm-service" and req.url.path.endswith("completions"):
            self.log.append(f"{req.method} {req.url.host}{req.url.path} -> 500")
            return httpx.Response(500, json={"error": "internal server error"})
        return super().handler(req)


def test_the_patient_routes_never_fall_back_to_another_build(tmp_path: Path) -> None:
    fake = JudgeDown()
    gw = _gw(tmp_path, fake, None)
    res = gw.chat(JH, _judge_body())
    assert res.status == 502 and res.body["error"]["code"] == "upstream_failed", res.body
    assert not any("llm-verifier" in x for x in fake.log)  # the verifier build was not asked to stand in
    named = gw.chat(JH, {**_judge_body(), "model": "v-verifier"})  # the verifier, asked by name, still answers
    assert named.status == 200 and named.body["tb"]["alias"] == "v-verifier"


def test_the_routing_table_marks_the_patient_routes_and_refuses_a_fallback_for_them() -> None:
    policy = RoutingPolicy.load()
    patient = [r for r in policy.routes if r.id in ("patient", "patient-validation")]
    assert patient and all(r.fallback == "none" for r in patient)
    assert all(policy.no_fallback(r, role) for r in policy.routes for role in policy.groups["patient"])
    assert not policy.no_fallback(next(r for r in policy.routes if r.id == "mapping"), "propose_mapping")
    doc = json.loads(json.dumps(__import__("yaml").safe_load((ROOT / "models" / "routing.yaml").read_text())))
    for raw in doc["routes"]:
        if raw["id"] == "patient":
            raw["fallback"] = "any"
    with pytest.raises(ValueError, match="patient"):
        RoutingPolicy(doc)


def _client(http: Any, alias: str | None) -> LlmClient:
    return LlmClient(
        "http://unused/v1", "", gateway=GatewayClient("http://gateway/v1", "orchestrator", http=http, model=alias)
    )


def test_a_judge_error_through_the_gateway_is_a_counted_failure_never_an_agreement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reproduction: the judge's server answers HTTP 500. Before, the pair came back ``pass`` at 0.95 with
    ``failures`` 0 (the verifier build answered both roles). Now the answer is unknown and the failure counts."""
    monkeypatch.setenv("TB_STEP_ID", "step-1")
    http = TestClient(create_app(_gw(tmp_path, JudgeDown(), None)))
    nj = NoteJudge(lake=None, llm=_client(http, None), verifier=_client(http, "v-verifier"), job_id="STUDY-1")
    r = nj.judge_excerpts("Gout flare now", "Is the patient having a gout flare?", date(2026, 10, 5), EXCERPTS)
    assert r.predicate == "unknown" and r.reason == "model_down" and nj.failures >= 1, (r, nj.failures)
    assert nj.mode == "agreement"
    nj.calls = 0
    with pytest.raises(Exception, match="did not answer"):
        check_judge(nj)  # a run where the judge is down fails, instead of a list judged by the verifier alone


def test_two_answers_from_one_build_are_a_counted_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """(c) whatever the gateway does: when both answers name the same build, the judge did not answer."""
    from tb_common.llm import LlmResult

    class Build:
        gateway = None

        def __init__(self, model: str, build: str) -> None:
            self.model, self.build, self.served_root = model, build, model

        def chat_json(self, prompt_id: str, variables: dict[str, Any], **kw: Any) -> LlmResult:
            d = {"verdict": "fail", "reason": "r", "confidence": 0.95, "quote": "q", "quote_date": "2026-10-01"}
            return LlmResult(d, prompt_id, 4, self.model, "gateway", "i" * 64, "o" * 64, 1, 1, 1, self.build)

    nj = NoteJudge(lake=None, llm=Build("j", "sha256:verifier"), verifier=Build("v", "sha256:verifier"))  # type: ignore[arg-type]
    r = nj.judge_excerpts("x", "x?", date(2026, 10, 5), EXCERPTS)
    assert (r.predicate, r.reason, nj.failures, nj.same_model) == ("unknown", "model_down", 1, 1)
    ok = NoteJudge(lake=None, llm=Build("j", "sha256:judge"), verifier=Build("v", "sha256:verifier"))  # type: ignore[arg-type]
    assert ok.judge_excerpts("x", "x?", date(2026, 10, 5), EXCERPTS).predicate == "fail" and ok.failures == 0


def test_install_names_the_judge_build_on_the_pair_profiles() -> None:
    text = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    pair = text[text.index('case "$MODE:$GPU" in gpu:rtxpro6000|gpu:gb10|gpu:rtx5090)') :]
    pair = pair[: pair.index("esac")]
    assert "TB_GATEWAY_VERIFIER_MODEL=v-verifier" in pair and "TB_GATEWAY_MODEL=j-workhorse" in pair
