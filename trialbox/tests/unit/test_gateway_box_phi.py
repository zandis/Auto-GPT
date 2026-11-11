"""PHI on the box (D-142, review A-01): the gateway built as an installed box builds it lets the on-box models answer the
judge, the verifier and chart facts; anything that could leave the box is still refused.

The environment is the one ``deploy/install.sh`` and ``deploy/docker-compose.yml`` give the containers: ``.env.example``
copied to ``deploy/.env``, the lines install.sh appends (``TB_ENV=PRODUCTION``, the profile; never ``TB_DATA_CLASS``),
then each service's compose ``environment:`` with ``${VAR:-default}`` resolved against that file. Only host paths
(audit, site pins, settings) point into the test's directory. The models are the in-process ``llm_stub``, which
compose aliases as both ``llm-service`` and ``llm-verifier``; the site pins are made with ``tools/pin_model.py``.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from gateway.app import create_app, from_env
from gateway.core import Gateway, GatewayConfig
from gateway.policy import Refusal, RoutingPolicy
from llm_stub.app import app as stub
from orchestrator.app import verifier_client
from registry.registry import Registry
from sitesetup import charts
from tb_common.audit import AuditLog
from tb_common.config import get_config
from tb_common.llm import LlmClient, LlmError
from tb_common.policy.classes import Environment, Topology

from tests.model_pins import promote_pins, release_registry
from tools import pin_model

ROOT = Path(__file__).resolve().parents[2]
JUDGE = "gemma-4-26b-a4b-it-spark"  # P-GB10 builds (models/registry.yaml)
VERIFIER = "qwen3.5-9b-spark"
JUDGE_VARS: dict[str, Any] = {
    "criterion_text": "Gout flare now",
    "note_question": "Is the patient currently (ongoing) having a gout flare?",
    "index_date": "2026-10-05",
    "excerpts": [{"date": "2026-10-01", "note_type": "progress", "text": "診斷為急性痛風發作中。"}],
}
CHART = "患者 山田 太郎\n生年月日 1950年4月1日\n性別 男\n診断: 痛風 (M10.9)\n2026-09-30 尿酸 8.2 mg/dL\n"


def test_install_writes_a_model_mode_the_services_accept() -> None:
    """install.sh used to write the compose profile (``gpu``) as TB_LLM_MODE, which tb_common.config refuses, and
    named no verifier build."""
    text = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    assert "TB_LLM_MODE=$MODE" not in text and 'LLM_MODE=stub; [ "$MODE" = gpu ] && LLM_MODE=vllm' in text
    # and a pair profile names its verifier build, or both_agree runs single-model
    assert "gpu:rtxpro6000|gpu:gb10|gpu:rtx5090)" in text and 'echo "TB_GATEWAY_VERIFIER_MODEL=v-verifier"' in text


def _dotenv() -> dict[str, str]:
    """deploy/.env after install.sh: .env.example plus what install appends (D-127 PRODUCTION, the GB10 profile)."""
    env: dict[str, str] = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line.strip())
        if m:
            env[m.group(1)] = m.group(2)
    env.update(TB_ENV="PRODUCTION", TB_LLM_MODE="vllm", TB_PROFILE="P-GB10", COMPOSE_PROFILES="gpu")
    env.update(TB_NOTE_BLOCK="both_agree", TB_GATEWAY_VERIFIER_MODEL="v-verifier")  # a pair profile (gb10)
    assert "TB_DATA_CLASS" not in env  # install leaves it unset: the shim labels PHI prompts D3
    return env


def _service_env(service: str, dotenv: dict[str, str]) -> dict[str, str]:
    doc = yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))
    raw = doc["services"][service]["environment"]

    def sub(v: str) -> str:
        return re.sub(r"\$\{([A-Z0-9_]+):-([^}]*)\}", lambda m: dotenv.get(m.group(1)) or m.group(2), str(v))

    return {**dotenv, **{k: sub(v) for k, v in raw.items()}}  # env_file first, environment: wins


def _weights(models: Path) -> None:
    """Synthetic weights where the gb10 compose file serves them from (deploy/models/<dir>)."""
    for name in ("gemma-4-26b-a4b-it-4bit", "qwen3.5-9b-4bit"):
        (models / name).mkdir(parents=True)
        (models / name / "model.safetensors").write_bytes(f"synthetic {name}".encode())


def _folders(models: Path) -> dict[str, Path]:
    return {JUDGE: models / "gemma-4-26b-a4b-it-4bit", VERIFIER: models / "qwen3.5-9b-4bit"}


def _pin(tmp_path: Path) -> Path:
    """The pins install.sh makes (tools/pin_model.py --install gb10, review R-01): the box's own weights, as
    candidates, then promoted to champion as a passing qualification record would (T-012b). The synthetic folders are
    the expected release of a registry copy (``tmp_path/registry.release.yaml``: give it as ``TB_REGISTRY_PATH``)."""
    out = tmp_path / "site" / "registry.site.yaml"
    _weights(tmp_path / "models")
    with pytest.MonkeyPatch.context() as mp:
        release_registry(tmp_path, _folders(tmp_path / "models"), mp)
        ok, lines = pin_model.install_pins("gb10", tmp_path / "models", out, {})
        assert ok, lines
        ok, lines = pin_model.verify_all(tmp_path / "models", out)  # install's next step (SEC-64)
        assert ok, lines
    promote_pins(out)
    return out


def test_install_pins_the_profile_pair_once_and_reports_missing_weights(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "site" / "registry.site.yaml"
    ok, lines = pin_model.install_pins("gb10", tmp_path / "models", out, {})
    assert not ok and all("routes nothing" in x for x in lines) and not out.exists()
    _weights(tmp_path / "models")
    release = release_registry(tmp_path, _folders(tmp_path / "models"), monkeypatch)
    assert pin_model.install_pins("gb10", tmp_path / "models", out, {})[0]
    again = pin_model.install_pins("gb10", tmp_path / "models", out, {})
    assert again == (True, [f"{JUDGE}: already pinned", f"{VERIFIER}: already pinned"])
    reg = Registry.from_env({"TB_REGISTRY_OVERRIDE": str(out), "TB_REGISTRY_PATH": str(release)})
    assert {reg.build(b).status.value for b in (JUDGE, VERIFIER)} == {"candidate"}  # T-012b: install pins candidate
    promote_pins(out)
    reg = Registry.from_env({"TB_REGISTRY_OVERRIDE": str(out), "TB_REGISTRY_PATH": str(release)})
    for alias, endpoint, served in (
        ("j-workhorse", "serving", "local/gemma-4-26b-a4b-nvfp4"),
        ("v-verifier", "verifier", "local/qwen3.5-9b-awq"),
    ):
        res = reg.resolve(alias, endpoint, role="judge", env=Environment.PRODUCTION)
        assert res.served_name == served  # the name compose gives vLLM (--served-model-name)
    # every profile's pair names builds of the committed registry, on the endpoint that serves them
    doc = yaml.safe_load((ROOT / "models" / "registry.yaml").read_text(encoding="utf-8"))
    known = {b["build_id"]: b for b in doc["builds"]}
    for pairs in pin_model.PROFILE_PAIRS.values():
        for build, endpoint, *_ in pairs:
            assert build in known and endpoint in (known[build].get("served") or {}), build


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    dotenv = _dotenv()
    override = _pin(tmp_path)
    host_paths = {
        "TB_AUDIT_DIR": str(tmp_path / "audit"),
        "TB_REGISTRY_OVERRIDE": str(override),
        "TB_REGISTRY_PATH": str(tmp_path / "registry.release.yaml"),  # the synthetic release (T-012b)
        "TB_SETTINGS": str(ROOT / "deploy" / "settings.example.yaml"),
        "TB_DB_URL": os.environ["TB_DB_URL"],  # the test's private trial database (trace store)
        "TB_AUDIT_WRITER": "file",  # the test's database has no audit journal (D-394): the chain in TB_AUDIT_DIR
        # install replaces the example's shared token with secrets (docker-compose.secrets.yml); one synthetic token
        "TB_SERVICE_TOKEN": secrets.token_hex(16),
    }

    def enter(service: str) -> dict[str, str]:
        env = {**_service_env(service, dotenv), **host_paths}
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        get_config.cache_clear()
        return env

    gw_env = enter("gateway")
    assert gw_env["TB_ENV"] == "PRODUCTION" and gw_env["TB_TOPOLOGY"] == "A" and gw_env["TB_TRACESTORE"] == "on"
    gw = from_env()
    gw.http = TestClient(stub)  # llm-service and llm-verifier (compose network aliases of the stub)
    app = TestClient(create_app(gw))

    orch_env = enter("orchestrator")
    assert orch_env["TB_DATA_CLASS"] == "" and orch_env["TB_SERVICE_NAME"] == "orchestrator"
    audit = AuditLog(tmp_path / "orch-audit")
    llm = LlmClient.from_config(audit)
    verifier = verifier_client(audit)
    assert llm.gateway is not None and verifier is not None and verifier.gateway is not None
    llm.gateway.http = app
    verifier.gateway.http = app
    yield gw, llm, verifier, tmp_path
    get_config.cache_clear()


def _calls(tmp_path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(x)
        for f in sorted((tmp_path / "audit").glob("*.jsonl"))
        for x in f.read_text(encoding="utf-8").splitlines()
    ]


@pytest.mark.req("LLM-2", "LLM-4")
def test_installed_box_runs_judge_verifier_and_chart_facts_on_the_box(box: Any) -> None:
    _gw, llm, verifier, tmp_path = box
    judged = llm.chat_json("judge", JUDGE_VARS)  # NoteJudge._ask passes no data class
    assert judged.data["verdict"] in ("pass", "fail", "unknown")
    checked = verifier.chat_json("judge", JUDGE_VARS)
    assert checked.data["verdict"] in ("pass", "fail", "unknown")
    facts, _dropped = charts.extract(llm, CHART, "ja")
    assert facts, "chart facts came back empty"

    recs = [r for r in _calls(tmp_path) if r["event"] == "llm.gateway.call"]
    assert [(r["detail"]["role"], r["model"]) for r in recs] == [
        ("judge", "j-workhorse"),
        ("judge", "v-verifier"),
        ("abstract_field", "j-workhorse"),
    ]
    for r in recs:
        d = r["detail"]
        assert (d["class"], d["step_basis"], d["zone"], d["route_id"]) == ("D3", "box_policy", "perimeter", "patient")
        assert d["endpoint"] in ("serving", "verifier") and d["topology"] == "A"


def _external_policy(topology: Topology, audit_dir: Path) -> Gateway:
    """The shipped policy with the external endpoint approved and on the patient route: PHI must still not go."""
    doc = yaml.safe_load((ROOT / "models" / "routing.yaml").read_text(encoding="utf-8"))
    doc["endpoints"]["external_x"]["g5_record"] = "G5-test"
    for r in doc["routes"]:
        if r["id"] == "patient":
            r["builds"] = ["x-external@external_x"]
    return Gateway(
        RoutingPolicy(doc),
        Registry.load(),
        AuditLog(audit_dir),  # replaced by the box's own audit below; never a path outside the test
        GatewayConfig(topology=topology, environment=Environment.PRODUCTION, cloud_opt_in=True),
        env={},
    )


@pytest.mark.req("LLM-2", "LLM-4", "PRIV-15")
def test_phi_never_leaves_the_box_by_this_policy(box: Any, tmp_path: Path) -> None:
    gw, llm, _verifier, _ = box
    # the route lists only an external endpoint: refused before anything is sent (may_reach, then the box policy)
    ext = _external_policy(Topology.A, tmp_path / "ext-audit")
    ext.audit = gw.audit
    llm.gateway.http = TestClient(create_app(ext))
    with pytest.raises(LlmError, match="class_route_mismatch|step_unconfirmed"):
        llm.chat_json("judge", JUDGE_VARS)
    # a cloud tenant (B) or a hybrid box (C): the box policy does not apply, LLM-2 alone decides
    for topology in (Topology.B, Topology.C):
        gw.config = GatewayConfig(topology=topology, environment=Environment.PRODUCTION)
        llm.gateway.http = TestClient(create_app(gw))
        with pytest.raises(LlmError, match="step_unconfirmed"):
            llm.chat_json("judge", JUDGE_VARS)
    # D4 is never allowed by the box policy
    gw.config = GatewayConfig(topology=Topology.A, environment=Environment.PRODUCTION)
    llm.gateway.http = TestClient(create_app(gw))
    with pytest.raises(LlmError, match="step_unconfirmed"):
        llm.chat_json("judge", JUDGE_VARS, data_class="D4")
    # a caller the policy does not list (the evaluation harness)
    headers = {
        "X-TB-Caller": "eval",
        "X-TB-Data-Class": "D3",
        "X-TB-Purpose": "evaluation",
        "X-TB-Study": "S",
        "X-TB-Context-Of-Use": "s3_note_judgement",
        "X-TB-Role": "judge",
        "X-TB-Prompt": "judge@4",
    }
    res = gw.chat(headers, {"messages": [{"role": "user", "content": "x"}]})
    assert res.status == 403 and res.body["error"]["code"] == "step_unconfirmed"


@pytest.mark.parametrize(
    "box_policy",
    [
        {"topologies": ["A", "B"], "environments": ["PRODUCTION"], "classes": ["D3"], "callers": ["orchestrator"]},
        {"topologies": ["A"], "environments": ["PRODUCTION"], "classes": ["D3", "D4"], "callers": ["orchestrator"]},
        {"topologies": ["A"], "environments": ["PRODUCTION"], "classes": ["D3"], "callers": ["nobody"]},
    ],
)
def test_the_box_policy_cannot_be_widened(box_policy: dict[str, Any]) -> None:
    doc = yaml.safe_load((ROOT / "models" / "routing.yaml").read_text(encoding="utf-8"))
    assert doc["phi_on_box"]["topologies"] == ["A"] and doc["phi_on_box"]["classes"] == ["D3"]
    with pytest.raises(ValueError, match="phi_on_box"):
        RoutingPolicy({**doc, "phi_on_box": box_policy})


SERVED = {"llm-service": "local/gemma-4-26b-a4b-nvfp4", "llm-verifier": "local/qwen3.5-9b-awq"}


def _strict(seen: list[tuple[str, str, int]]) -> Any:
    """vLLM as the box serves it (the rehearsal's stand-in, tests/rehearsal/vllm_standin.py): each host answers only
    its own ``--served-model-name`` (404 otherwise) and only ``/v1/chat/completions``; the content is the stub's."""
    inner = TestClient(stub)
    app = FastAPI()

    @app.post("/{path:path}")
    async def chat(path: str, request: Request) -> JSONResponse:
        body = await request.json()
        host = request.headers.get("host", "").split(":")[0]
        model = str(body.get("model"))
        if path != "v1/chat/completions" or SERVED.get(host) != model:
            seen.append((host, model, 404))
            return JSONResponse({"object": "error", "message": f"The model `{model}` does not exist.",
                                 "type": "NotFoundError", "code": 404}, status_code=404)  # fmt: skip
        hdr = {k: v for k, v in request.headers.items() if k.lower().startswith("x-tb-")}
        r = inner.post("/v1/chat/completions", json=body, headers=hdr)
        seen.append((host, model, r.status_code))
        out = r.json()
        out["model"] = model  # vLLM echoes its served name
        return JSONResponse(out, status_code=r.status_code)

    return app


@pytest.mark.req("LLM-2", "LLM-4")
def test_installed_box_drafts_edc_notes_through_the_gateway(box: Any) -> None:
    """EDC prefill (D-160) on an installed box: the note item goes through the gateway (prompt crf_prefill, role
    abstract_field, purpose data_entry) to the box's own judge build. The rehearsal of 2026-11-10 got a 409 for every
    draft: the routing policy did not list the purpose data_entry, the gateway refused (purpose_not_allowed), and
    the orchestrator answered a bare 500 that the console showed as 409 with no code."""
    from edc.store import EdcError

    from tests import edc_kit as k

    gw, llm, _verifier, tmp_path = box
    seen: list[tuple[str, str, int]] = []
    gw.http = TestClient(_strict(seen))
    svc, _, _ = k.service(tmp_path, llm=llm)
    k.ready(svc)
    d = {r["item"]: r for r in svc.build(k.STUDY, k.RECORD, k.PID, "", k.VISIT_DATE, "crc")}
    assert d["tophus"]["state"] == "drafted" and d["tophus"]["value"] == "1"
    assert d["tophus"]["citation"]["kind"] == "note" and d["tophus"]["citation"]["quote"] == "Tophus on the right ear."
    assert d["brthdat"]["value"] == "1960-05-01" and d["urate"]["value"] == "8.4"
    assert seen and all(s == ("llm-service", SERVED["llm-service"], 200) for s in seen), seen
    recs = [r for r in _calls(tmp_path) if r["event"] == "llm.gateway.call"]
    assert recs and all(r["detail"]["role"] == "abstract_field" and r["model"] == "j-workhorse" for r in recs)
    for r in recs:
        dt = r["detail"]
        assert (dt["class"], dt["step_basis"], dt["zone"], dt["route_id"]) == (
            "D3",
            "box_policy",
            "perimeter",
            "patient",
        )

    # a refusal is a coded EDC error (never a bare 500), audited, and nothing new is drafted
    doc = yaml.safe_load((ROOT / "models" / "routing.yaml").read_text(encoding="utf-8"))
    doc["callers"]["orchestrator"]["purposes"].remove("data_entry")
    gw.policy = RoutingPolicy(doc)
    before = svc.store.drafts(k.STUDY, k.RECORD)
    with pytest.raises(EdcError) as e:
        svc.build(k.STUDY, k.RECORD, k.PID, "", "2026-11-06", "crc")
    assert e.value.code == "edc.model" and e.value.status == 502 and "purpose_not_allowed" in e.value.message
    assert svc.store.drafts(k.STUDY, k.RECORD) == before


def test_every_v1_prompt_has_a_caller_the_policy_allows() -> None:
    """Each prompt the tb_common.llm shim labels (libs/tb_llm/v1_roles.yaml) has a role and a purpose some caller may
    ask for; crf_prefill's purpose data_entry was on no caller (rehearsal of 2026-11-10)."""
    policy = RoutingPolicy.load()
    labels = yaml.safe_load((ROOT / "libs" / "tb_llm" / "v1_roles.yaml").read_text(encoding="utf-8"))
    for prompt, lab in labels.items():
        ok = []
        for caller in policy.callers:
            try:
                policy.check_caller(caller, lab["role"], lab["purpose"])
            except Refusal:  # this caller may not
                continue
            ok.append(caller)
        assert ok, f"{prompt}: no caller may use role {lab['role']} with purpose {lab['purpose']}"
    policy.check_caller("orchestrator", labels["crf_prefill"]["role"], labels["crf_prefill"]["purpose"])
