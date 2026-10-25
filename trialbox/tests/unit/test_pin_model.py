"""Site model pinning (spec v4 §8.4; S1-07, SEC-63, SEC-64): weight manifest -> registry sha256 -> site override, and
the gateway path that uses it (the on-box build is reachable only once pinned, and only when asked for).

Every model directory here is synthetic: a few bytes named like weight files, never a real model.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient
from gateway.app import create_app
from gateway.core import Gateway, GatewayConfig
from gateway.policy import RoutingPolicy
from guard.guard import Guard
from llm_stub.app import app as stub
from registry.registry import DEFAULT_PATH, Registry, RegistryError, apply_override
from tb_common.audit import AuditLog
from tb_common.policy.classes import Environment, Topology

from tools import pin_model
from tools.trialbox import doctor

BUILD = "qwen3.5-35b-a3b-candidate"
SERVED = "qwen3.5-35b-a3b-q4"


def _model_dir(root: Path, payload: bytes = b"synthetic-weights") -> Path:
    d = root / "model"
    (d / "sub").mkdir(parents=True)
    (d / "model-00001-of-00002.safetensors").write_bytes(payload)
    (d / "sub" / "model-00002-of-00002.safetensors").write_bytes(b"more")
    (d / "config.json").write_text('{"architectures": ["Synthetic"]}', encoding="utf-8")
    (d / ".cache").mkdir()
    (d / ".cache" / "lock").write_text("ignored", encoding="utf-8")
    return d


def _pin(tmp_path: Path, **kw: Any) -> tuple[pin_model.Manifest, Path]:
    return pin_model.pin(BUILD, _model_dir(tmp_path), served_name=SERVED, out=tmp_path / "site" / "o.yaml", **kw)


@pytest.mark.req("S1-07", "SEC-63")
def test_manifest_is_sha256sum_of_visible_files_and_the_pin_is_its_digest(tmp_path: Path) -> None:
    d = _model_dir(tmp_path)
    m = pin_model.weight_manifest(d)
    lines = m.text.splitlines()
    assert [ln.split("  ", 1)[1] for ln in lines] == [
        "config.json",
        "model-00001-of-00002.safetensors",
        "sub/model-00002-of-00002.safetensors",
    ]  # sorted by path, hidden files left out
    assert lines[1].split("  ")[0] == hashlib.sha256(b"synthetic-weights").hexdigest()
    assert m.sha256 == hashlib.sha256(m.text.encode()).hexdigest() and m.files == 3
    assert pin_model.weight_manifest(d) == m  # deterministic


@pytest.mark.req("SEC-63")
@pytest.mark.parametrize("bad", ["pytorch_model.bin", "modeling_custom.py", "weights.pt"])
def test_pickle_weights_and_code_are_refused(tmp_path: Path, bad: str) -> None:
    d = _model_dir(tmp_path)
    (d / bad).write_bytes(b"x")
    with pytest.raises(pin_model.PinError, match="refused file types"):
        pin_model.weight_manifest(d)


@pytest.mark.req("SEC-63")
def test_a_directory_without_safetensors_or_gguf_is_refused(tmp_path: Path) -> None:
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "config.json").write_text("{}", encoding="utf-8")
    with pytest.raises(pin_model.PinError, match="no .safetensors or .gguf"):
        pin_model.weight_manifest(tmp_path / "m")


@pytest.mark.req("S1-07", "MOD-7")
def test_pin_writes_a_site_override_and_the_build_resolves_only_with_it(tmp_path: Path) -> None:
    committed = DEFAULT_PATH.read_text(encoding="utf-8")
    m, out = _pin(tmp_path)
    assert DEFAULT_PATH.read_text(encoding="utf-8") == committed  # the committed registry is never written
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert doc["builds"][BUILD]["sha256"] == m.sha256 and doc["builds"][BUILD]["served"] == {"serving": SERVED}
    assert (out.parent / "manifests" / f"{BUILD}.sha256").read_text(encoding="utf-8") == m.text

    base = Registry.load()
    with pytest.raises(RegistryError) as e:
        base.resolve("j-workhorse", "serving", role="judge", env=Environment.TEST)
    assert e.value.reason == "build_unpinned"

    reg = Registry.load(DEFAULT_PATH, out)
    assert reg.version.startswith(base.version + "+site.")
    res = reg.resolve("j-workhorse", "serving", role="judge", env=Environment.TEST)
    assert res.build.build_id == BUILD and res.build.sha256 == m.sha256 and res.served_name == SERVED
    assert reg.build(BUILD).weights["files"] == 3
    with pytest.raises(RegistryError):  # other builds stay unpinned
        reg.resolve("v-verifier", "serving", role="judge", env=Environment.TEST)
    with pytest.raises(RegistryError) as e:  # a pinned candidate is not a production champion
        reg.resolve("j-workhorse", "serving", role="judge", env=Environment.PRODUCTION)
    assert e.value.reason == "no_eligible_build"


@pytest.mark.req("S1-07", "MOD-7")
def test_champion_pin_resolves_in_production_and_other_pins_are_kept(tmp_path: Path) -> None:
    _, out = _pin(tmp_path, status="champion")
    other = tmp_path / "other"
    other.mkdir()
    (other / "w.gguf").write_bytes(b"g")
    pin_model.pin("gpt-oss-120b-candidate", other, served_name="v-local", out=out)
    reg = Registry.load(DEFAULT_PATH, out)
    assert reg.resolve("j-workhorse", "serving", role="judge", env=Environment.PRODUCTION).build.build_id == BUILD
    assert reg.resolve("v-verifier", "serving", role="judge", env=Environment.TEST).served_name == "v-local"


@pytest.mark.req("S1-07")
@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"kind": "other", "builds": {}}, "kind"),
        ({"kind": "registry-site-override", "builds": {"nope": {"sha256": "ab" * 32}}}, "unknown build"),
        ({"kind": "registry-site-override", "builds": {BUILD: {"alias": "v-verifier"}}}, "may not set"),
        ({"kind": "registry-site-override", "builds": {BUILD: {"sha256": "XYZ"}}}, "lowercase hex"),
        ({"kind": "registry-site-override", "builds": {BUILD: {"status": "blessed"}}}, "blessed"),
    ],
)
def test_override_cannot_add_builds_or_change_identity(override: dict[str, Any], message: str) -> None:
    doc = yaml.safe_load(DEFAULT_PATH.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match=message):
        apply_override(doc, override)


@pytest.mark.req("SEC-64")
def test_verify_detects_one_changed_byte(tmp_path: Path) -> None:
    _, out = _pin(tmp_path)
    d = tmp_path / "model"
    assert pin_model.verify(BUILD, d, out)[0]
    (d / "model-00001-of-00002.safetensors").write_bytes(b"synthetic-weightz")
    good, msg = pin_model.verify(BUILD, d, out)
    assert not good and "changed since the pin" in msg
    assert pin_model.main(["--build", BUILD, "--model-dir", str(d), "--out", str(out), "--verify"]) == 1


@pytest.mark.req("S1-07")
def test_cli_refuses_the_stub_unknown_builds_and_a_missing_served_name(tmp_path: Path) -> None:
    d = _model_dir(tmp_path)
    out = tmp_path / "o.yaml"
    assert pin_model.main(
        ["--build", "trialbox-stub-1", "--model-dir", str(d), "--out", str(out), "--served-name", "x"]
    )
    assert pin_model.main(["--build", "nope", "--model-dir", str(d), "--out", str(out), "--served-name", "x"]) == 2
    assert pin_model.main(["--build", BUILD, "--model-dir", str(d), "--out", str(out)]) == 2
    assert not out.exists()
    assert pin_model.main(["--build", BUILD, "--model-dir", str(d), "--out", str(out), "--served-name", SERVED]) == 0


# ------------------------------------------------------------------------------------------------ gateway path
def _serving(calls: list[str]) -> httpx.Client:
    """Stub app for the stub endpoint; a fake on-box server (reports its served name) for the serving endpoint."""
    stub_client = TestClient(stub)

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        calls.append(f"{req.url.host}:{body['model']}")
        if req.url.host == "llm-stub":
            r = stub_client.post("/v1/chat/completions", json=body, headers=dict(req.headers))
            return httpx.Response(r.status_code, json=r.json())
        content = json.dumps({"verdict": "pass", "confidence": 0.9, "quote": "q", "quote_date": "2026-10-01"})
        return httpx.Response(
            200,
            json={
                "model": SERVED,
                "choices": [{"message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def _gateway(tmp_path: Path, registry: Registry, calls: list[str]) -> Gateway:
    return Gateway(
        RoutingPolicy.load(),
        registry,
        AuditLog(tmp_path / "audit"),
        GatewayConfig(topology=Topology.A, environment=Environment.TEST),
        http=_serving(calls),
        guard=Guard(None),
        env={},
    )


def _judge(model: str | None) -> tuple[dict[str, str], dict[str, Any]]:
    from tb_common.llm import load_prompt, render
    from tb_contracts import inline_schema
    from tb_llm import CallLabels, json_schema_format

    p = load_prompt("judge")
    v = {"criterion_text": "x", "note_question": "q?", "index_date": "2026-10-05", "excerpts": []}
    body: dict[str, Any] = {
        "messages": render(p, v),
        "response_format": json_schema_format("judge", inline_schema(p.meta.output_schema)),
    }
    if model:
        body["model"] = model
    labels = CallLabels("D0", "feasibility", "GZQO", "s3_note_judgement", "judge", f"judge@{p.meta.version}")
    return labels.headers("orchestrator"), body


@pytest.mark.req("S1-06", "S1-07", "LLM-1")
def test_gateway_routes_to_the_pinned_on_box_build_only_when_named_and_pinned(tmp_path: Path) -> None:
    calls: list[str] = []
    _, out = _pin(tmp_path)
    pinned = Registry.load(DEFAULT_PATH, out)
    gw = _gateway(tmp_path, pinned, calls)

    res = gw.chat(*_judge(None))  # route default: the stub
    assert res.status == 200 and res.body["tb"]["alias"] == "trialbox-stub" and res.body["tb"]["route_id"] == "dev-stub"

    res = gw.chat(*_judge("j-workhorse"))  # named and pinned: the on-box build, with its sha in the record
    assert res.status == 200, res.body
    assert res.body["tb"]["build_sha"] == pinned.build(BUILD).sha256 and res.body["tb"]["build_id"] == BUILD
    assert calls[-1] == f"llm-service:{SERVED}"

    gw2 = _gateway(tmp_path / "unpinned", Registry.load(), calls)  # the committed registry: refused, not the stub
    res = gw2.chat(*_judge("j-workhorse"))
    assert res.status == 403 and res.body["error"]["code"] == "build_unpinned"


@pytest.mark.req("S1-06", "ENG-04")
def test_client_default_model_is_sent_unless_the_call_names_one() -> None:
    from tb_llm import CallLabels, GatewayClient

    seen: list[Any] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content).get("model"))
        return httpx.Response(200, json={"model": "m", "choices": [{"message": {"content": "{}"}}]})

    _, body = _judge(None)
    labels = CallLabels("D0", "feasibility", "GZQO", "s3_note_judgement", "judge", "judge@3")
    c = GatewayClient("http://gw/v1", "orchestrator", http=httpx.Client(transport=httpx.MockTransport(handler)))
    c.complete(body, labels)
    c.model = "j-workhorse"
    c.complete(body, labels)
    c.complete({**body, "model": "v-verifier"}, labels)
    assert seen == [None, "j-workhorse", "v-verifier"] and "model" not in body


# ------------------------------------------------------------------------------------------------ doctor
@pytest.mark.req("S1-16")
def test_doctor_reports_site_pins(tmp_path: Path) -> None:
    env = {"TB_ENV": "TEST", "TB_REGISTRY_OVERRIDE": str(tmp_path / "missing.yaml")}
    c = next(x for x in doctor.run(doctor.DoctorInputs(env=env)) if x.name == "registry_pins")
    assert c.status == "WARN" and "no model build pinned" in c.detail

    _, out = _pin(tmp_path)
    env["TB_REGISTRY_OVERRIDE"] = str(out)
    c = next(x for x in doctor.run(doctor.DoctorInputs(env=env)) if x.name == "registry_pins")
    assert c.status == "PASS" and BUILD in c.detail
    c = next(
        x for x in doctor.run(doctor.DoctorInputs(env={**env, "TB_ENV": "PRODUCTION"})) if x.name == "registry_pins"
    )
    assert c.status == "WARN" and "champion" in c.detail

    out.write_text("kind: registry-site-override\nbuilds: {nope: {sha256: null}}\n", encoding="utf-8")
    checks = doctor.run(doctor.DoctorInputs(env=env))
    assert next(x for x in checks if x.name == "registry_pins").status == "FAIL" and not doctor.ok(checks)


# ------------------------------------------------------------------------------------------------ remote modes
@pytest.mark.req("S1-13", "ENG-16")
def test_judge_public_live_mode_runs_through_a_gateway_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Live mode against a gateway in front of the stub: the stub abstains with a valid label, so the floors hold."""
    import tb_llm

    from tools.trialbox import eval as tb_eval

    calls: list[str] = []
    app_client = TestClient(create_app(_gateway(tmp_path, Registry.load(), calls)))
    real = tb_llm.GatewayClient

    def factory(url: str, caller: str, *, model: str | None = None, **_: Any) -> Any:
        assert url == "http://gateway.test/v1"
        return real("http://testserver/v1", caller, http=app_client, model=model)

    monkeypatch.setattr(tb_llm, "GatewayClient", factory)
    monkeypatch.setenv("TB_GATEWAY_URL", "http://gateway.test/v1")
    monkeypatch.setenv("TB_EVAL_LIMIT", "12")
    result = tb_eval.run_judge_public(tmp_path, tb_eval.load_suite("judge_public"))
    assert result["passed"] is True, result
    assert result["gateway"]["mode"] == "live" and result["gateway"]["refused"] == 0
    assert result["metrics"]["n"] == 12 and result["metrics"]["valid_rate"] == 1.0
    assert result["gateway"]["builds"] == ["trialbox-stub:unpinned:trialbox-stub-1"]

    monkeypatch.setenv("TB_GATEWAY_EXPECT_SHA", "ab" * 32)  # answers from another build fail the run
    assert tb_eval.run_judge_public(tmp_path, tb_eval.load_suite("judge_public"))["passed"] is False


@pytest.mark.req("S1-06")
def test_cascade_e2e_uses_the_gateway_url_when_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tools import cascade_e2e

    monkeypatch.delenv("TB_GATEWAY_URL", raising=False)
    assert cascade_e2e.gateway_client(tmp_path).mode == "in-process"
    monkeypatch.setenv("TB_GATEWAY_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("TB_GATEWAY_MODEL", "j-workhorse")
    c = cascade_e2e.gateway_client(tmp_path)
    assert c.summary() == {
        "mode": "remote",
        "url": "http://127.0.0.1:1/v1",
        "model": "j-workhorse",
        "calls": 0,
        "builds": {},
    }
