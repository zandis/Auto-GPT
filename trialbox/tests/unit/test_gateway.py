"""tb-gateway v0 (spec v4 §8.2; S1-06, S1-07): identity, labels, route refusal, audit, cache, echo, fallback.

The upstream is the deterministic ``llm_stub`` app in-process (or an ``httpx.MockTransport``), so every test is
offline and repeatable.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from gateway.app import create_app
from gateway.core import Gateway, GatewayConfig
from gateway.policy import RoutingPolicy
from guard.guard import Guard
from llm_stub.app import app as stub
from registry.registry import Registry
from tb_common.audit import AuditLog, verify
from tb_common.crypto import sha256_text
from tb_common.llm import LlmClient, load_prompt, render
from tb_common.policy.classes import Environment, Topology
from tb_contracts import inline_schema
from tb_llm import CallLabels, GatewayClient, GatewayRefused, json_schema_format
from tracestore.store import TraceStore

ROOT = Path(__file__).resolve().parents[2]
PIN = "ab" * 32  # synthetic test pin; the shipped registry has no hashes yet
JUDGE_VARS: dict[str, Any] = {
    "criterion_text": "x",
    "note_question": "Is the patient currently (ongoing) having a gout flare?",
    "index_date": "2026-10-05",
    "excerpts": [{"date": "2026-10-01", "note_type": "progress", "text": "診斷為急性痛風發作中。"}],
}


def _judge_body(variables: dict[str, Any] | None = None) -> dict[str, Any]:
    p = load_prompt("judge")
    return {
        "messages": render(p, variables or JUDGE_VARS),
        "response_format": json_schema_format("judge", inline_schema(p.meta.output_schema)),
        "max_tokens": 512,
    }


def _ir_body() -> dict[str, Any]:
    p = load_prompt("ir_extract")
    v = {"ruleset": "GZQO", "language": "en", "criteria": [{"text": "Age >= 18", "kind": "inclusion"}]}
    return {"messages": render(p, v), "response_format": json_schema_format("ir", inline_schema(p.meta.output_schema))}


def H(**over: str) -> dict[str, str]:
    h = {
        "X-TB-Caller": "orchestrator",
        "X-TB-Role": "judge",
        "X-TB-Data-Class": "D0",
        "X-TB-Purpose": "screening",
        "X-TB-Study": "STUDY-1",
        "X-TB-Step": "step-1",
        "X-TB-Context-Of-Use": "s3_note_judgement",
        "X-TB-Prompt": "judge@3",
    }
    for k, v in over.items():
        key = "X-TB-" + k.replace("_", "-")
        if v == "":
            h.pop(key, None)
        else:
            h[key] = v
    return h


def _pinned_registry(*, served: str = "j-test", sha: str | None = PIN, status: str = "champion") -> Registry:
    reg: dict[str, Any] = {
        "version": "registry-test",
        "aliases": {a: {"class": "J"} for a in ("trialbox-stub", "j-workhorse", "v-verifier", "x-external")},
        "builds": [
            {
                "build_id": "j-test-1",
                "alias": "j-workhorse",
                "status": status,
                "serving": "vllm",
                "served": {"serving": served},
                "sha256": sha,
                "licence": {"name": "test"},
                "origin": {"developer": "test"},
            },
            {
                "build_id": "v-test-1",
                "alias": "v-verifier",
                "status": "champion",
                "serving": "vllm",
                "served": {"serving": "v-test"},
                "sha256": "cd" * 32,
                "licence": {"name": "test"},
                "origin": {"developer": "test"},
            },
        ],
    }
    return Registry(reg)


def _gw(
    tmp_path: Path,
    *,
    env: Environment = Environment.TEST,
    topology: Topology = Topology.A,
    registry: Registry | None = None,
    http: httpx.Client | None = None,
    traces: TraceStore | None = None,
    confirm: Callable[[str, str, str], bool] | None = None,
) -> Gateway:
    return Gateway(
        RoutingPolicy.load(),
        registry or Registry.load(),
        AuditLog(tmp_path / "audit"),
        GatewayConfig(topology=topology, environment=env),
        http=http or TestClient(stub),
        guard=Guard("^\\d{8}$"),
        traces=traces,
        step_confirm=confirm,
        env={},
    )


def _records(tmp_path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for f in sorted((tmp_path / "audit").glob("*.jsonl")) for x in f.read_text().splitlines()]


def _mock(model: str, calls: list[str] | None = None, fail_hosts: tuple[str, ...] = ()) -> httpx.Client:
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        if calls is not None:
            calls.append(body["model"])
        if body["model"] in fail_hosts:
            return httpx.Response(500, json={"error": "down"})
        content = json.dumps({"verdict": "pass", "confidence": 0.9, "quote": "q", "quote_date": "2026-10-01"})
        return httpx.Response(
            200,
            json={
                "model": model if model != "echo" else body["model"],
                "choices": [{"message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


# ------------------------------------------------------------------------------------------------ allow + audit
@pytest.mark.req("LLM-1", "LLM-5", "MOD-6", "S1-06")
def test_allowed_call_through_stub_is_audited(tmp_path: Path) -> None:
    gw = _gw(tmp_path)
    body = _judge_body()
    res = gw.chat(H(), body)
    assert res.status == 200, res.body
    assert json.loads(res.body["choices"][0]["message"]["content"])["verdict"] == "pass"
    tb = res.body["tb"]
    assert res.body["model"] == "trialbox-stub" and tb["alias"] == "trialbox-stub"
    assert tb["build_sha"] == "unpinned:trialbox-stub-1" and tb["route_id"] == "dev-stub"
    assert res.headers["X-TB-Build-Sha"] == tb["build_sha"]
    (rec,) = _records(tmp_path)
    assert rec["event"] == "llm.gateway.call" and rec["actor"] == "orchestrator"
    assert rec["input_sha"] == sha256_text(
        json.dumps(
            {"messages": body["messages"], "response_format": body["response_format"]},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    d = rec["detail"]
    for key in ("class", "purpose", "tokens_in", "tokens_out", "latency_ms", "cost", "model_sha", "policy_version"):
        assert key in d
    assert d["class"] == "D0" and d["purpose"] == "screening" and d["tokens_out"] > 0 and d["schema_valid"] is True
    assert d["call_id"] == tb["call_id"] and rec["output_sha"]
    assert "急性痛風" not in (tmp_path / "audit").joinpath(next((tmp_path / "audit").glob("*.jsonl")).name).read_text()
    assert verify(tmp_path / "audit").ok


# ------------------------------------------------------------------------------------------------ refusals
REFUSALS: list[tuple[dict[str, str], str]] = [
    ({"Caller": "mail-gateway"}, "caller_unknown"),
    ({"Caller": ""}, "caller_unknown"),
    ({"Purpose": ""}, "header_missing"),
    ({"Data_Class": ""}, "header_missing"),
    ({"Study": ""}, "header_missing"),
    ({"Context_Of_Use": ""}, "header_missing"),
    ({"Prompt": ""}, "header_missing"),
    ({"Data_Class": "D5"}, "class_invalid"),
    ({"Caller": "criteria-compiler"}, "role_not_allowed"),
    ({"Role": "write_poetry"}, "role_unknown"),
    ({"Purpose": "marketing"}, "purpose_not_allowed"),
    ({"Data_Class": "D3"}, "step_unconfirmed"),
    ({"Data_Class": "D1"}, "class_not_allowed_in_env"),
]


@pytest.mark.req("LLM-2", "LLM-3", "LLM-48", "S1-06")
@pytest.mark.parametrize(("over", "reason"), REFUSALS)
def test_refusals_are_403_and_audited(tmp_path: Path, over: dict[str, str], reason: str) -> None:
    gw = _gw(tmp_path)
    res = gw.chat(H(**over), _judge_body())
    assert res.status == 403 and res.body["error"]["code"] == reason, res.body
    (rec,) = _records(tmp_path)
    assert rec["event"] == "llm.gateway.refuse" and rec["detail"]["reason"] == reason
    assert rec["detail"]["decision"] == "refuse" and rec["input_sha"]


@pytest.mark.req("LLM-4", "PRIV-15", "S1-06")
def test_class_route_mismatch_refused_and_audited(tmp_path: Path) -> None:
    """A D3 call asking for the external build under topology C, and a D3 call on the D0-only bake-off role."""
    calls: list[str] = []
    gw = _gw(
        tmp_path,
        env=Environment.PRODUCTION,
        topology=Topology.C,
        registry=_pinned_registry(),
        http=_mock("echo", calls),
        confirm=lambda caller, study, step: True,
    )
    gw.config = GatewayConfig(Topology.C, Environment.PRODUCTION, cloud_opt_in=True)
    r1 = gw.chat(H(Data_Class="D3"), {**_judge_body(), "model": "x-external"})
    r2 = gw.chat(H(Data_Class="D3", Caller="eval", Role="bakeoff", Purpose="evaluation"), _judge_body())
    assert (r1.status, r1.body["error"]["code"]) == (403, "class_route_mismatch")
    assert (r2.status, r2.body["error"]["code"]) == (403, "no_route")
    assert calls == []  # nothing was dispatched
    recs = _records(tmp_path)
    assert [r["detail"]["reason"] for r in recs] == ["class_route_mismatch", "no_route"]
    assert all(r["detail"]["class"] == "D3" for r in recs)


@pytest.mark.req("LLM-22", "ENG-04")
def test_schema_constrained_response_required(tmp_path: Path) -> None:
    gw = _gw(tmp_path)
    body = _judge_body()
    body.pop("response_format")
    res = gw.chat(H(), body)
    assert res.body["error"]["code"] == "schema_required"


@pytest.mark.req("LLM-15", "PRIV-29")
def test_phi_tripwire_blocks_low_class_call(tmp_path: Path) -> None:
    gw = _gw(tmp_path)
    variables = {**JUDGE_VARS, "excerpts": [{"date": "2026-10-01", "note_type": "x", "text": "身分證 A123456789"}]}
    res = gw.chat(H(), _judge_body(variables))
    assert res.status == 403 and res.body["error"]["code"] == "phi_tripwire"
    text = "".join(f.read_text() for f in (tmp_path / "audit").glob("*.jsonl"))
    assert "A123456789" not in text and "TW_NATIONAL_ID" in text


# ------------------------------------------------------------------------------------------------ registry
@pytest.mark.req("MOD-7", "S1-07")
def test_production_refuses_unpinned_and_non_champion_builds(tmp_path: Path) -> None:
    ok = lambda caller, study, step: True  # noqa: E731
    shipped = _gw(tmp_path / "a", env=Environment.PRODUCTION, http=_mock("echo"), confirm=ok)
    r = shipped.chat(H(Data_Class="D3"), _judge_body())
    assert (r.status, r.body["error"]["code"]) == (403, "no_eligible_build")  # seeds are unpinned candidates
    unpinned = _gw(
        tmp_path / "b", env=Environment.PRODUCTION, registry=_pinned_registry(sha=None), http=_mock("echo"), confirm=ok
    )
    r = unpinned.chat(H(Data_Class="D3", Step="s"), _judge_body())
    assert r.status == 200 and r.body["tb"]["alias"] == "v-verifier"  # falls to the next pinned champion
    assert _records(tmp_path / "b")[0]["detail"]["fallbacks"] == 1


@pytest.mark.req("MOD-6", "S1-07")
def test_served_model_echo_mismatch_is_refused(tmp_path: Path) -> None:
    """A stub that serves the wrong model name is detected and refused."""

    def wrong_name(req: httpx.Request) -> httpx.Response:
        inner = TestClient(stub).post(
            "/v1/chat/completions", content=req.content, headers={"X-TB-Prompt-Id": "judge", **dict(req.headers)}
        )
        payload = inner.json()
        payload["model"] = "some-other-model"
        return httpx.Response(200, json=payload)

    gw = _gw(tmp_path, http=httpx.Client(transport=httpx.MockTransport(wrong_name)))
    res = gw.chat(H(), _judge_body())
    assert res.status == 502 and res.body["error"]["code"] == "served_model_mismatch"
    (rec,) = _records(tmp_path)
    assert rec["event"] == "llm.gateway.refuse" and rec["detail"]["reason"] == "served_model_mismatch"


# ------------------------------------------------------------------------------------------------ cache, D3 path
@pytest.mark.req("LLM-41", "S1-06")
def test_response_cache_keyed_by_prompt_and_model_sha(tmp_path: Path) -> None:
    seen: list[int] = []

    def counting(req: httpx.Request) -> httpx.Response:
        seen.append(1)
        r = TestClient(stub).post("/v1/chat/completions", content=req.content, headers=dict(req.headers))
        return httpx.Response(r.status_code, json=r.json())

    gw = _gw(tmp_path, http=httpx.Client(transport=httpx.MockTransport(counting)))
    h = H(Caller="criteria-compiler", Role="extract_criteria", Purpose="protocol_ingest", Prompt="ir_extract@1")
    a = gw.chat(h, _ir_body())
    b = gw.chat(h, _ir_body())
    assert a.status == b.status == 200 and len(seen) == 1
    assert (a.body["tb"]["cache"], b.body["tb"]["cache"]) == ("miss", "hit")
    assert a.body["choices"] == b.body["choices"] and a.body["tb"]["call_id"] != b.body["tb"]["call_id"]
    gw.chat(H(), _judge_body())
    gw.chat(H(), _judge_body())
    assert len(seen) == 3  # judge is not a cacheable role
    assert [r["detail"]["cache"] for r in _records(tmp_path)] == ["miss", "hit", "miss", "miss"]


@pytest.mark.req("LLM-45", "LLM-46", "S1-08")
def test_d3_production_call_traced_redacted(tmp_path: Path) -> None:
    traces = TraceStore(tmp_path / "traces.sqlite", Guard("^\\d{8}$"))
    gw = _gw(
        tmp_path,
        env=Environment.PRODUCTION,
        registry=_pinned_registry(),
        http=_mock("j-test"),
        traces=traces,
        confirm=lambda caller, study, step: (caller, study, step) == ("orchestrator", "STUDY-1", "step-1"),
    )
    note = "患者陳志明先生，病歷號 20481234，聯絡電話 0912-345-678。目前急性痛風發作中。"
    res = gw.chat(H(Data_Class="D3"), _judge_body({**JUDGE_VARS, "excerpts": [{"date": "d", "text": note}]}))
    assert res.status == 200 and res.body["tb"]["build_sha"] == PIN and res.body["tb"]["route_id"] == "patient"
    raw = (tmp_path / "traces.sqlite").read_bytes().decode("utf-8", "ignore")
    for planted in ("陳志明", "20481234", "0912-345-678"):
        assert planted not in raw
    (t,) = traces.read(res.body["tb"]["call_id"], user="qa1", purpose="dispute review", roles=frozenset({"trace:read"}))
    assert t["attributes"]["tb.call_id"] == res.body["tb"]["call_id"] and t["attributes"]["tb.data_class"] == "D3"
    wrong_step = gw.chat(H(Data_Class="D3", Step="other"), _judge_body())
    assert wrong_step.body["error"]["code"] == "step_unconfirmed"


# ------------------------------------------------------------------------------------------------ HTTP + clients
@pytest.mark.req("LLM-7", "ENG-04", "S1-06")
def test_http_app_and_tb_llm_client(tmp_path: Path) -> None:
    gw = _gw(tmp_path)
    http = TestClient(create_app(gw))
    models = http.get("/v1/models").json()
    assert {m["id"] for m in models["data"]} >= {"trialbox-stub", "j-workhorse"}
    assert "sha" not in json.dumps(models) and "http" not in json.dumps(models)
    assert http.get("/healthz").status_code == 200 and http.get("/readyz").status_code == 200
    client = GatewayClient("http://gateway/v1", "orchestrator", http=http)
    labels = CallLabels(
        data_class="D0",
        purpose="screening",
        study_id="STUDY-1",
        context_of_use="s3_note_judgement",
        role="judge",
        prompt="judge@3",
    )
    body = _judge_body()
    out = client.chat(body["messages"], labels, response_format=body["response_format"])
    assert out.data["verdict"] == "pass" and out.alias == "trialbox-stub" and out.call_id
    with pytest.raises(GatewayRefused) as e:
        client.chat(
            body["messages"],
            CallLabels(**{**labels.__dict__, "data_class": "D3"}),
            response_format={**body["response_format"]},
        )
    assert e.value.reason == "step_unconfirmed" and e.value.status == 403
    with pytest.raises(ValueError, match="labels required"):
        client.chat(
            body["messages"], CallLabels(**{**labels.__dict__, "purpose": ""}), response_format=body["response_format"]
        )
    with pytest.raises(ValueError, match="response_format"):
        client.chat(body["messages"], labels)
    assert client.models()


@pytest.mark.req("ENG-04", "S1-06")
def test_tb_common_llm_shim_goes_through_gateway(tmp_path: Path) -> None:
    gw = _gw(tmp_path)
    client = GatewayClient("http://gateway/v1", "orchestrator", http=TestClient(create_app(gw)))
    llm = LlmClient("http://unused/v1", "unused", audit=AuditLog(tmp_path / "caller-audit"), gateway=client)
    r = llm.chat_json("judge", JUDGE_VARS, job_id="J1", data_class="D0")
    assert r.data["verdict"] == "pass" and r.target == "gateway" and r.model == "trialbox-stub"
    (rec,) = _records(tmp_path)
    assert rec["prompt_version"] == "judge@3" and rec["detail"]["study"] == "J1"
    assert rec["detail"]["context_of_use"] == "s3_note_judgement"
