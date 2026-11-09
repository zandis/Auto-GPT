"""One served name per model on every path (the first complete run, 2026-11-09).

The installed box's gateway sends the pinned served name as each request's ``model``. vLLM answers 404 to any name it
was not started with (``--served-model-name``). The run's card served ``local/gemma-4-26b-a4b-nvfp4`` and
``local/qwen3.5-9b-awq``, as the measured record says; ``pin_model --install`` pinned the compose defaults
``gemma-4-26b-a4b-it`` and ``qwen3.5-9b``. Every model call of the run was then refused (502 upstream_failed:
"serving: HTTP 404; verifier: HTTP 404"). These tests hold the names together and replay that call path against a
vLLM stand-in behind the VM's nginx layout (``/judge/v1``, ``/verifier/v1``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient
from llm_stub.app import app as stub
from orchestrator.selftest import load_cases, model_name, run_selftest
from registry.registry import Registry
from tb_common.llm import LlmClient, LlmError
from tb_common.policy.classes import Environment

from tools import complete_run, pin_model, scenarios

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = {g: ROOT / "deploy" / f"docker-compose.{g}.yml" for g in ("rtxpro6000", "gb10", "rtx5090")}
COMPOSE["rtx4090"] = COMPOSE["rtx5090"]  # the 24 GB card runs the 5090 file with the verifier scaled to 0
JUDGE_URL, VERIFIER_URL = "http://127.0.0.1:8080/judge/v1", "http://127.0.0.1:8080/verifier/v1"
JUDGE_VARS: dict[str, Any] = {
    "criterion_text": "Gout flare now",
    "note_question": "Is the patient currently (ongoing) having a gout flare?",
    "index_date": "2026-10-05",
    "excerpts": [{"date": "2026-10-01", "note_type": "progress", "text": "診斷為急性痛風發作中。"}],
}


def _compose_default(path: Path, var: str) -> str:
    m = re.search(r"--served-model-name=\$\{" + var + r":-([^}]+)\}", path.read_text(encoding="utf-8"))
    assert m, (path.name, var)
    return m.group(1)


def test_every_path_serves_and_pins_the_same_two_names() -> None:
    names = {"serving": pin_model.JUDGE_SERVED, "verifier": pin_model.VERIFIER_SERVED}
    # what install pins = what each profile's compose file serves
    for gpu, pairs in pin_model.PROFILE_PAIRS.items():
        for _build, endpoint, _dv, _dd, name_var, name_default in pairs:
            assert name_default == names[endpoint], (gpu, endpoint)
            assert _compose_default(COMPOSE[gpu], name_var) == name_default, (gpu, name_var)
    # = what the measured serving records name (install requires one)
    for rec in sorted((ROOT / "deploy" / "measured").glob("serving_config.*.json")):
        served = {s["role"]: s["served_model_name"] for s in json.loads(rec.read_text(encoding="utf-8"))["servers"]}
        assert served == {"judge": names["serving"], "verifier": names["verifier"]}, rec.name
    # = what the cloud complete run starts vLLM with, and what the run's direct clients ask for
    vm = (ROOT / "deploy" / "gcp" / "complete-run-vm.sh").read_text(encoding="utf-8")
    assert f"start judge $J {names['serving']} " in vm and f"start verifier $V {names['verifier']} " in vm
    assert (names["serving"], names["verifier"]) == (complete_run.JUDGE, complete_run.VERIFIER)


def _weights(models: Path) -> None:
    for d in ("gemma-4-26b-a4b-it-4bit", "qwen3.5-9b-4bit"):
        (models / d).mkdir(parents=True, exist_ok=True)
        (models / d / "model.safetensors").write_bytes(f"synthetic {d}".encode())


def test_install_moves_an_old_pin_to_the_served_name_and_keeps_the_weights_pin(tmp_path: Path) -> None:
    """A box pinned before the names were joined (served ``gemma-4-26b-a4b-it``): install again renames, never
    re-hashes, and a site's own JUDGE_MODEL (deploy/.env, which compose reads too) still wins."""
    out = tmp_path / "site" / "registry.site.yaml"
    _weights(tmp_path / "models")
    old = {"JUDGE_MODEL": "gemma-4-26b-a4b-it", "VERIFIER_MODEL": "qwen3.5-9b"}
    assert pin_model.install_pins("rtxpro6000", tmp_path / "models", out, old)[0]
    before = yaml.safe_load(out.read_text(encoding="utf-8"))["builds"]
    ok, lines = pin_model.install_pins("rtxpro6000", tmp_path / "models", out, {})
    assert ok and all("served name on" in x and "(was 'gemma-4-26b-a4b-it')" in lines[0] for x in lines), lines
    after = yaml.safe_load(out.read_text(encoding="utf-8"))["builds"]
    reg = Registry.from_env({"TB_REGISTRY_OVERRIDE": str(out)})
    for alias, endpoint, build, served in (
        ("j-workhorse", "serving", "gemma-4-26b-a4b-it-rtxpro6000", pin_model.JUDGE_SERVED),
        ("v-verifier", "verifier", "qwen3.5-9b-rtxpro6000", pin_model.VERIFIER_SERVED),
    ):
        assert after[build]["sha256"] == before[build]["sha256"] and after[build]["weights"] == before[build]["weights"]
        assert reg.resolve(alias, endpoint, role="judge", env=Environment.PRODUCTION).served_name == served
    assert pin_model.install_pins("rtxpro6000", tmp_path / "models", out, {})[1][0].endswith("already pinned")
    pin_model.install_pins("rtxpro6000", tmp_path / "models", out, {"JUDGE_MODEL": "site/judge"})
    assert yaml.safe_load(out.read_text(encoding="utf-8"))["builds"]["gemma-4-26b-a4b-it-rtxpro6000"]["served"] == {
        "serving": "site/judge"
    }
    with pytest.raises(pin_model.PinError):
        pin_model.set_served("qwen3.5-9b-spark", "verifier", "x", out)  # not pinned here


# ---------------------------------------------------------------------- the run's call path against a vLLM stand-in
class _Vllm:
    """The VM's two vLLM servers behind nginx: ``/judge/...`` and ``/verifier/...``; each answers only the name it was
    started with and 404s anything else, as vLLM does ("The model `x` does not exist.")."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, str, int]] = []
        self.inner = TestClient(stub)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        served = {
            "/judge/v1/chat/completions": pin_model.JUDGE_SERVED,
            "/verifier/v1/chat/completions": pin_model.VERIFIER_SERVED,
        }.get(request.url.path)
        if served is None or body.get("model") != served:
            self.seen.append((request.url.path, str(body.get("model")), 404))
            return httpx.Response(404, json={"object": "error", "message": f"The model `{body.get('model')}` does "
                                             "not exist.", "type": "NotFoundError", "code": 404})  # fmt: skip
        hdr = {k: v for k, v in request.headers.items() if k.lower().startswith("x-tb-")}
        r = self.inner.post("/v1/chat/completions", json=body, headers=hdr)
        self.seen.append((request.url.path, served, r.status_code))
        return httpx.Response(r.status_code, content=r.content, headers={"content-type": "application/json"})


@pytest.fixture
def no_data_class(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_DATA_CLASS", raising=False)  # as install leaves it: a PHI prompt is D3 (D-142)


def _client(env: dict[str, str], vllm: _Vllm, alias: str = "") -> LlmClient:
    c = LlmClient(
        "http://unused/v1", "", gateway=scenarios.gateway_client(env, httpx.Client(transport=httpx.MockTransport(vllm)))
    )
    if alias:
        c.gateway.model = alias
    return c


def test_the_installed_gateway_reaches_both_servers_by_their_served_names(tmp_path: Path, no_data_class: None) -> None:
    """complete_run --model pair with explicit URLs: the harness installs the box as install.sh does (pins the compose
    defaults) and routes through the gateway; judge, chart facts and the verifier are answered, none is a 404."""
    env = scenarios.installed_env(tmp_path / "audit", JUDGE_URL, VERIFIER_URL)
    vllm = _Vllm()
    judge, verifier = _client(env, vllm), _client(env, vllm, "v-verifier")
    assert judge.chat_json("judge", JUDGE_VARS, job_id="t").data
    assert judge.chat_json("chart_facts", {"text": "診断：痛風", "language": "ja", "language_name": "Japanese"},
                           job_id="t").data  # fmt: skip
    assert verifier.chat_json("judge", JUDGE_VARS, job_id="t").data
    assert [s for s in vllm.seen if s[2] != 200] == []
    assert {s[0] for s in vllm.seen} == {"/judge/v1/chat/completions", "/verifier/v1/chat/completions"}
    rep = run_selftest(judge, verifier)
    assert [m["model"] for m in rep["models"]] == ["(the gateway's build)", "v-verifier"]
    assert all(m["answered"] == m["cases"] for m in rep["models"]), rep["problems"]


def test_a_pin_with_a_name_the_server_does_not_serve_is_a_named_404(tmp_path: Path, no_data_class: None) -> None:
    """The first run's state, replayed: the pins name what the card does not serve. The refusal now says which name
    was sent, and the canary names the model and the error instead of an empty name."""
    _weights(tmp_path / "models")
    site = tmp_path / "site" / "registry.site.yaml"
    old = {"JUDGE_MODEL": "gemma-4-26b-a4b-it", "VERIFIER_MODEL": "qwen3.5-9b"}
    assert pin_model.install_pins("rtxpro6000", tmp_path / "models", site, old)[0]
    env = scenarios.installed_env(tmp_path / "audit", JUDGE_URL, VERIFIER_URL)
    assert env["TB_REGISTRY_OVERRIDE"] == str(site)
    vllm = _Vllm()
    judge = _client(env, vllm)
    with pytest.raises(LlmError):
        judge.chat_json("judge", JUDGE_VARS, job_id="t")
    assert {s[2] for s in vllm.seen} == {404}
    audit = "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "audit").glob("*.jsonl"))
    assert "HTTP 404 (model 'gemma-4-26b-a4b-it' not served there?)" in audit
    rep = run_selftest(judge, None, cases=load_cases()[:2])
    assert rep["problems"][0].startswith("judge (the gateway's build) failed the canary (0 of 2 answered; ")


def test_the_canary_names_a_gateway_client() -> None:
    class Gw:
        model: str | None = None

    c = LlmClient("http://unused/v1", "", gateway=Gw())
    assert model_name(c) == "(the gateway's build)"
    c.gateway.model = "v-verifier"
    assert model_name(c) == "v-verifier"
    assert model_name(LlmClient("http://x/v1", "local/qwen3.5-9b-awq")) == "local/qwen3.5-9b-awq"
