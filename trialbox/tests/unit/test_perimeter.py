"""T-604 (D-388; review LLM-036, LLM-037 b-d, LLM-038, LLM-043): the perimeter is checked, not a label.

* the gateway does not start in PRODUCTION on topology A when a perimeter endpoint's host is not a box address, and
  refuses every call when a name moves off the box while it runs;
* ``EGRESS_EXTRA`` cannot open the gateway to a host outside the routing table, and ``CLOUD_LLM_BASE_URL`` opens
  nothing;
* ``LlmClient.from_config`` refuses to build without a gateway in PRODUCTION;
* a job's model call carries its step (``X-TB-Step``); the gateway's reads need the service token.

Every address is synthetic: TEST-NET (203.0.113.0/24, 198.51.100.0/24) stands for "outside the box".
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient
from gateway.app import create_app
from gateway.core import Gateway, GatewayConfig
from gateway.policy import RoutingPolicy, box_address, perimeter_addresses, perimeter_problems
from registry.registry import Registry
from tb_common.audit import AuditLog
from tb_common.config import get_config
from tb_common.llm import LlmClient, LlmError
from tb_common.policy.classes import Environment, Topology
from tb_llm import CallLabels

from tools.trialbox import doctor

ROOT = Path(__file__).resolve().parents[2]
OUTSIDE = "203.0.113.5"
DNS: dict[str, list[str]] = {
    "llm-service": ["172.20.0.4"],
    "llm-verifier": ["172.20.0.5"],
    "big-server.example": [OUTSIDE],
    "lan-server.example": ["10.1.2.3"],
}


def dns(table: dict[str, list[str]]) -> Any:
    return lambda host: list(table.get(host, [host] if host[:1].isdigit() else []))


def _policy() -> RoutingPolicy:
    return RoutingPolicy.load(ROOT / "models" / "routing.yaml")


def _gateway(tmp_path: Path, env: dict[str, str], *, topology: str = "A", environment: str = "PRODUCTION") -> Gateway:
    cfg = GatewayConfig(topology=Topology(topology), environment=Environment(environment))
    return Gateway(_policy(), Registry.from_env({}), AuditLog(tmp_path / "audit"), cfg, env=env)


def _audit(tmp_path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(x)
        for f in sorted((tmp_path / "audit").glob("*.jsonl"))
        for x in f.read_text(encoding="utf-8").splitlines()
    ]


def _egress() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tb_egress_t604", ROOT / "deploy" / "egress.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tb_egress_t604"] = mod
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------------------------------------ box addresses
def test_box_addresses() -> None:
    for a in ("127.0.0.1", "10.0.0.8", "172.18.0.2", "192.168.1.9", "::1", "fd00::2"):
        assert box_address(a), a
    for a in (OUTSIDE, "198.51.100.1", "100.64.0.1", "2001:db8::1", "not-an-address"):
        assert not box_address(a), a


def test_perimeter_rows_name_each_endpoint_and_its_addresses() -> None:
    env = {"TB_EP_SERVING_URL": "http://big-server.example:8000/v1", "TB_EP_EMBED_URL": "http://127.0.0.1:8014/v1"}
    rows = {r.endpoint: r for r in perimeter_addresses(_policy(), env, "PRODUCTION", dns(DNS))}
    assert "stub" not in rows  # DEV and TEST only
    assert rows["serving"].addresses == (OUTSIDE,) and "not a box address" in rows["serving"].problem
    assert rows["verifier"].addresses == ("172.20.0.5",) and not rows["verifier"].problem
    assert rows["embed"].addresses == ("127.0.0.1",) and not rows["embed"].problem
    # a compose service name that does not resolve here is the box's own; a dotted name that does not resolve is not
    assert not perimeter_problems(_policy(), {}, "PRODUCTION", dns({}))
    gone = perimeter_problems(_policy(), {"TB_EP_SERVING_URL": "http://gone.example/v1"}, "PRODUCTION", dns({}))
    assert gone and "does not resolve" in gone[0]
    lan = {"TB_EP_SERVING_URL": "http://lan-server.example:8000/v1"}
    assert not perimeter_problems(_policy(), lan, "PRODUCTION", dns(DNS))


# ------------------------------------------------------------------------------------------------ gateway start
def test_gateway_exits_in_production_when_a_perimeter_url_is_off_the_box(tmp_path: Path) -> None:
    env = {"TB_EP_SERVING_URL": "http://big-server.example:8000/v1"}
    with pytest.raises(SystemExit, match="not on the box"):
        create_app(_gateway(tmp_path, env), resolver=dns(DNS))
    rec = [r for r in _audit(tmp_path) if r["event"] == "llm.gateway.perimeter_refused"]
    assert rec and rec[0]["detail"]["phase"] == "start" and OUTSIDE in rec[0]["detail"]["problems"][0]
    # on the box it starts; outside PRODUCTION, or on topology B (the tenant's router), the check does not apply
    assert create_app(_gateway(tmp_path, {}), resolver=dns(DNS))
    assert create_app(_gateway(tmp_path, env, environment="VALIDATION"), resolver=dns(DNS))
    assert create_app(_gateway(tmp_path, env, topology="B"), resolver=dns(DNS))


def test_gateway_re_resolves_and_refuses_when_a_name_moves_off_the_box(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    monkeypatch.setenv("TB_SERVICE_TOKEN", "synthetic-token-" + "a" * 16)
    get_config.cache_clear()
    table = dict(DNS)
    gw = _gateway(tmp_path, {"TB_PERIMETER_RECHECK_S": "0"})
    client = TestClient(create_app(gw, resolver=dns(table)))
    tok = {"X-TB-Service-Token": "synthetic-token-" + "a" * 16}
    assert client.get("/healthz").status_code == 200
    first = client.post("/v1/chat/completions", json={"messages": []}, headers={**tok, "X-TB-Caller": "nobody"})
    assert first.json()["error"]["code"] == "caller_unknown"  # the call went on to the gateway's own checks
    table["llm-service"] = [OUTSIDE]  # the name now points off the box
    res = client.post("/v1/chat/completions", json={"messages": []}, headers={**tok, "X-TB-Caller": "orchestrator"})
    assert res.status_code == 403 and res.json()["error"]["code"] == "perimeter_unverified"
    assert res.headers["X-TB-Refusal"] == "perimeter_unverified"
    assert client.get("/healthz").status_code == 503
    rec = [r for r in _audit(tmp_path) if r["event"] == "llm.gateway.perimeter_refused"]
    assert rec[-1]["detail"]["phase"] == "call" and rec[-1]["detail"]["caller"] == "orchestrator"
    # LLM-043: the gateway's reads need the token too
    assert client.get("/v1/models").status_code == 401
    assert client.get("/v1/models", headers=tok).status_code == 200
    get_config.cache_clear()


# ------------------------------------------------------------------------------------------------ egress
@pytest.mark.req("NFR-B9")
def test_egress_extra_for_the_gateway_outside_the_table_is_refused(tmp_path: Path) -> None:
    eg = _egress()
    env = {"TB_ENV": "DEV", "TB_EP_OPENROUTER_URL": "https://openrouter.example/api/v1"}
    with pytest.raises(SystemExit, match="not an open model endpoint"):
        eg.allowlist({**env, "EGRESS_EXTRA": "gateway=big-server.example:443"})
    with pytest.raises(SystemExit, match="not an open model endpoint"):  # the right host on another port
        eg.allowlist({**env, "EGRESS_EXTRA": "gateway=openrouter.example:8443"})
    with pytest.raises(SystemExit, match="not an open model endpoint"):  # the dev endpoint is closed in PRODUCTION
        eg.allowlist({**env, "TB_ENV": "PRODUCTION", "EGRESS_EXTRA": "gateway=openrouter.example:443"})
    ok = eg.allowlist({**env, "EGRESS_EXTRA": "gateway=openrouter.example:443,adapter=10.1.2.3:1433"})
    assert ("gateway", "openrouter.example", 443) in [(a.service, a.host, a.port) for a in ok]
    # `network.sh print` with both lines of the review's case exits before asking docker anything
    envf = tmp_path / "egress.env"
    envf.write_text("TB_ENV=PRODUCTION\nEGRESS_EXTRA=gateway=big-server.example:443\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="not an open model endpoint"):
        eg.main(["print", "--env", str(envf)])


def test_cloud_llm_base_url_opens_nothing() -> None:
    eg = _egress()
    env = {"TB_ENV": "DEV", "CLOUD_LLM_BASE_URL": "https://llm.example.com/v1"}
    assert "llm.example.com" not in {a.host for a in eg.allowlist(env)}
    assert "llm.example.com" in eg.model_hosts(env)  # still a model host: no other service may be given it
    with pytest.raises(SystemExit, match="model host"):
        eg.allowlist({**env, "EGRESS_EXTRA": "criteria-compiler=llm.example.com:443"})


def test_watch_applies_at_once_and_on_every_container_start() -> None:
    eg = _egress()
    calls: list[int] = []

    def apply() -> None:
        calls.append(1)
        if len(calls) == 2:
            raise SystemExit("bad EGRESS_EXTRA entry")  # reported; the watch goes on

    assert eg.watch(apply, iter(["c0ffee\n", "\n", "beef01\n"])) == 1
    assert len(calls) == 3  # the first apply, then one per start event (the blank line is not an event)


# ------------------------------------------------------------------------------------------------ the client
def test_llm_client_refuses_to_build_without_a_gateway_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_GATEWAY_URL", raising=False)
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    get_config.cache_clear()
    try:
        with pytest.raises(LlmError, match="no TB_GATEWAY_URL in PRODUCTION"):
            LlmClient.from_config(AuditLog(Path("/nonexistent-audit")))
        monkeypatch.setenv("TB_GATEWAY_URL", "http://gateway:8020/v1")
        get_config.cache_clear()
        assert LlmClient.from_config(AuditLog(Path("/nonexistent-audit"))).gateway is not None
        monkeypatch.delenv("TB_GATEWAY_URL")
        monkeypatch.setenv("TB_ENV", "DEV")
        get_config.cache_clear()
        assert LlmClient.from_config(AuditLog(Path("/nonexistent-audit"))).gateway is None  # DEV: direct is allowed
    finally:
        get_config.cache_clear()


class _Recorder:
    """A gateway client that records the labels of each call and answers a valid judge verdict."""

    def __init__(self) -> None:
        self.labels: list[CallLabels] = []

    def complete(self, body: dict[str, Any], labels: CallLabels) -> dict[str, Any]:
        self.labels.append(labels)
        content = json.dumps({"verdict": "unknown", "confidence": 0.5, "quote": None, "quote_date": None})
        return {"model": "j-workhorse", "choices": [{"message": {"content": content}, "finish_reason": "stop"}]}


@pytest.mark.req("LLM-2")
def test_a_job_call_carries_its_step(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_STEP_ID", raising=False)
    rec = _Recorder()
    llm = LlmClient("http://unused", "m", gateway=rec)
    variables = {
        "criterion_text": "Gout flare now",
        "note_question": "Is the patient currently (ongoing) having a gout flare?",
        "index_date": "2026-10-05",
        "excerpts": [{"date": "2026-10-01", "note_type": "progress", "text": "synthetic note"}],
    }
    llm.chat_json("judge", variables, job_id="JOB-1")
    assert rec.labels[-1].step_id == "JOB-1" and rec.labels[-1].headers("orchestrator")["X-TB-Step"] == "JOB-1"
    monkeypatch.setenv("TB_STEP_ID", "STEP-9")  # a step named by the environment wins
    llm.chat_json("judge", variables, job_id="JOB-1")
    assert rec.labels[-1].step_id == "STEP-9"
    llm.chat_json("judge", variables)  # no job: no step from here
    assert rec.labels[-1].step_id == "STEP-9"


# ------------------------------------------------------------------------------------------------ doctor
def test_doctor_prints_each_perimeter_address() -> None:
    def run(env: dict[str, str]) -> doctor.Check:
        inp = doctor.DoctorInputs(env=env, resolver=dns(DNS))
        return doctor.check_perimeter_addresses(inp)

    ok = run({"TB_ENV": "PRODUCTION", "TB_TOPOLOGY": "A"})
    assert ok.status == "PASS" and "serving llm-service -> 172.20.0.4" in ok.detail
    bad = {"TB_EP_SERVING_URL": "http://big-server.example:8000/v1", "TB_TOPOLOGY": "A"}
    assert run({**bad, "TB_ENV": "PRODUCTION"}).status == "FAIL"
    assert OUTSIDE in run({**bad, "TB_ENV": "PRODUCTION"}).detail
    assert run({**bad, "TB_ENV": "DEV"}).status == "WARN"
    assert doctor.check_perimeter_addresses in doctor.CHECKS
