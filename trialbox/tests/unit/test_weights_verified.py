"""T-677 (D-393; deep review LLM-008, LLM-009, DEP-025): model weights verified beyond install.

* ``trialbox doctor --verify-all`` (and ``--weights`` alone, as the nightly timer and the update run it) hashes every
  pinned build's weights against its pin. A swapped weight file is a FAIL and writes the weights flag beside the site
  pins; the gateway refuses every model call while the flag is there, and reports itself unhealthy, so a start or
  an update's ``up --wait`` stops. A pass removes the flag.
* The gateway compares each on-box model server's ``GET /v1/models`` with the pin at start (and hourly): the folder
  vLLM serves (``root``) must be the pin's ``weights.model_dir`` and ``max_model_len`` must not be below the build's
  ``context_length``. A mismatch is refused ``model_mismatch``; a server that does not answer yet is not one.
* The browser test tools are in a lock: the vendored axe-core's sha256 and the Playwright version CI and the complete
  run install.

Synthetic weights of a few bytes; no model, no GPU, no network.
"""

from __future__ import annotations

import configparser
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from gateway.app import WEIGHTS_FLAG, StartCheck, create_app, served_problems, weights_flag_path
from gateway.core import Gateway, GatewayConfig
from gateway.policy import RoutingPolicy
from guard.guard import Guard
from llm_stub.app import app as stub
from registry.registry import Registry
from tb_common.audit import AuditLog
from tb_common.policy.classes import Environment, Topology

from tests.model_pins import promote_pins, qualified, release_registry
from tools import pin_model
from tools.trialbox import __main__ as cli
from tools.trialbox import doctor

ROOT = Path(__file__).resolve().parents[2]
JUDGE = "gemma-4-26b-a4b-it-spark"
VERIFIER = "qwen3.5-9b-spark"
JUDGE_DIR, VERIFIER_DIR = "gemma-4-26b-a4b-it-4bit", "qwen3.5-9b-4bit"


# ------------------------------------------------------------------------------------------------ doctor --verify-all
def _pinned_box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """A box pinned as install.sh pins the gb10 pair: (models folder, site override)."""
    models = tmp_path / "models"
    for name in (JUDGE_DIR, VERIFIER_DIR):
        (models / name).mkdir(parents=True)
        (models / name / "model.safetensors").write_bytes(f"synthetic {name}".encode())
    release_registry(tmp_path, {JUDGE: models / JUDGE_DIR, VERIFIER: models / VERIFIER_DIR}, monkeypatch)
    out = tmp_path / "site" / "registry.site.yaml"
    ok, lines = pin_model.install_pins("gb10", models, out, {})
    assert ok, lines
    promote_pins(out)
    return models, out


def _inputs(models: Path, out: Path) -> doctor.DoctorInputs:
    return doctor.DoctorInputs(env={"TB_MODELS_DIR": str(models), "TB_REGISTRY_OVERRIDE": str(out)})


def _gateway(tmp_path: Path, registry: Registry | None = None, http: Any = None) -> Gateway:
    return Gateway(
        RoutingPolicy.load(),
        registry or Registry.load(),
        AuditLog(tmp_path / "audit"),
        GatewayConfig(topology=Topology.A, environment=Environment.TEST),
        http=http or TestClient(stub),
        guard=Guard("^\\d{8}$"),
        env={},
    )


def test_a_swapped_weight_file_is_refused_at_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    models, out = _pinned_box(tmp_path, monkeypatch)
    flag = out.parent / WEIGHTS_FLAG
    assert doctor.check_weights(_inputs(models, out)).status == "PASS" and not flag.exists()

    # the judge's weights are swapped on disk (same name, other bytes): restart re-reads them
    (models / JUDGE_DIR / "model.safetensors").write_bytes(b"other weights entirely")
    c = doctor.check_weights(_inputs(models, out))
    assert c.status == "FAIL" and f"{JUDGE}: weights changed since the pin" in c.detail
    assert "the gateway refuses every model call" in c.detail
    doc = json.loads(flag.read_text(encoding="utf-8"))
    assert doc["format"] == "trialbox-weights-flag/1" and any(JUDGE in x for x in doc["lines"])

    # the gateway, started with these site pins, refuses every model call and is unhealthy
    env = {"TB_REGISTRY_OVERRIDE": str(out)}
    assert weights_flag_path(env) == flag
    gw = _gateway(tmp_path)
    sc = StartCheck(gw, env, get=lambda url, key: (None, "not asked"))
    with TestClient(create_app(gw, sc)) as http:  # the lifespan runs the start check
        r = http.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "x"}]})
        assert r.status_code == 403 and r.json()["error"]["code"] == "weights_changed"
        assert r.headers["X-TB-Refusal"] == "weights_changed" and JUDGE in r.json()["error"]["message"]
        assert http.get("/healthz").status_code == 503
    events = [json.loads(x) for f in sorted((tmp_path / "audit").rglob("*.jsonl")) for x in f.read_text().splitlines()]
    assert any(e.get("detail", {}).get("reason") == "weights_changed" for e in events)

    # the pinned file back: the check passes, the flag goes, the gateway serves again
    (models / JUDGE_DIR / "model.safetensors").write_bytes(f"synthetic {JUDGE_DIR}".encode())
    assert doctor.check_weights(_inputs(models, out)).status == "PASS" and not flag.exists()
    assert sc.refusal() is None and sc.health() == {"model_check": "ok"}


def test_doctor_verify_all_and_weights_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    models, out = _pinned_box(tmp_path, monkeypatch)
    monkeypatch.setenv("TB_MODELS_DIR", str(models))
    monkeypatch.setenv("TB_REGISTRY_OVERRIDE", str(out))
    assert cli.main(["doctor", "--weights", "--json"]) == 0
    assert [c["name"] for c in json.loads(capsys.readouterr().out)] == ["weights"]
    (models / VERIFIER_DIR / "extra.safetensors").write_bytes(b"a file added beside the pinned ones")
    assert cli.main(["doctor", "--weights"]) == 1
    assert "FAIL  weights" in capsys.readouterr().out and (out.parent / WEIGHTS_FLAG).is_file()
    cli.main(["doctor", "--verify-all", "--json"])  # the full doctor plus the weights check, last
    names = [c["name"] for c in json.loads(capsys.readouterr().out)]
    assert names[-1] == "weights" and "registry_pins" in names
    assert "weights" not in [c.__name__.removeprefix("check_") for c in doctor.CHECKS]  # hashing is opt-in


def test_nothing_pinned_is_a_warning_and_sets_no_flag(tmp_path: Path) -> None:
    out = tmp_path / "site" / "registry.site.yaml"
    c = doctor.check_weights(_inputs(tmp_path / "models", out))
    assert c.status == "WARN" and not (out.parent / WEIGHTS_FLAG).exists()


# ------------------------------------------------------------------------------------------------ /v1/models at start
def _registry(context: int = 16384) -> Registry:
    def build(build_id: str, alias: str, endpoint: str, served: str, folder: str, sha: str) -> dict[str, Any]:
        return {
            "build_id": build_id,
            "alias": alias,
            "status": "champion",
            "serving": "vllm",
            "served": {endpoint: served},
            "sha256": sha,
            "context_length": context,
            "weights": {"model_dir": folder},
            "licence": {"name": "test"},
            "origin": {"developer": "test"},
            "qualification": qualified(sha),
        }

    return Registry(
        {
            "version": "registry-test",
            "aliases": {a: {"class": "J"} for a in ("trialbox-stub", "j-workhorse", "v-verifier")},
            "builds": [
                build("j-test-1", "j-workhorse", "serving", "local/judge", JUDGE_DIR, "ab" * 32),
                build("v-test-1", "v-verifier", "verifier", "local/verifier", VERIFIER_DIR, "cd" * 32),
            ],
        }
    )


def _servers(rows: dict[str, dict[str, Any]]) -> FastAPI:
    """Model servers as vLLM answers ``GET /v1/models``, one row per host (llm-service, llm-verifier)."""
    app = FastAPI()

    @app.get("/v1/models")
    def models(request: Request) -> dict[str, Any]:
        host = request.headers["host"].split(":")[0]
        return {"object": "list", "data": [rows[host]] if host in rows else []}

    return app


def _row(served: str, folder: str, max_len: int = 16384) -> dict[str, Any]:
    return {"id": served, "object": "model", "root": f"/models/{folder}", "max_model_len": max_len}


GOOD = {
    "llm-service": _row("local/judge", JUDGE_DIR),
    "llm-verifier": _row("local/verifier", VERIFIER_DIR),
}


def test_the_gateway_refuses_a_models_mismatch_at_start(tmp_path: Path) -> None:
    # the judge's server was started on the verifier's folder (deploy/.env JUDGE_MODEL_DIR wrong): same served name
    swapped = {**GOOD, "llm-service": _row("local/judge", VERIFIER_DIR)}
    gw = _gateway(tmp_path, _registry(), TestClient(_servers(swapped)))
    sc = StartCheck(gw, {})
    with TestClient(create_app(gw, sc)) as http:
        r = http.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "x"}]})
        assert r.status_code == 403 and r.json()["error"]["code"] == "model_mismatch"
        assert f"from /models/{VERIFIER_DIR}, but the pin is the folder {JUDGE_DIR}" in r.json()["error"]["message"]
        assert http.get("/healthz").status_code == 503
    # fixed: the next check passes and calls go through to the pipeline again
    gw.http = TestClient(_servers(GOOD))
    assert sc.run() == [] and sc.refusal() is None and sc.health() == {"model_check": "ok"}


def test_a_shorter_max_model_len_is_a_mismatch(tmp_path: Path) -> None:
    short = {**GOOD, "llm-verifier": _row("local/verifier", VERIFIER_DIR, max_len=8192)}
    gw = _gateway(tmp_path, _registry(), TestClient(_servers(short)))
    mismatches, unchecked = served_problems(gw, {})
    assert unchecked == [] and mismatches == [
        "v-test-1: verifier serves 'local/verifier' with max_model_len 8192, below the pinned context_length 16384"
    ]
    longer = {**GOOD, "llm-verifier": _row("local/verifier", VERIFIER_DIR, max_len=32768)}
    gw.http = TestClient(_servers(longer))
    assert served_problems(gw, {}) == ([], [])  # a larger context is no risk: the gateway sizes from the pin


def test_a_server_not_up_yet_is_not_a_mismatch(tmp_path: Path) -> None:
    gw = _gateway(tmp_path, _registry())
    sc = StartCheck(gw, {}, get=lambda url, key: (None, "ConnectError: loading"))
    assert sc.run() == [] and sc.refusal() is None
    assert sc.health() == {"model_check": "pending"} and len(sc.unchecked) == 2
    # the stub reports its served name as root (no folder): only a path is compared, so the stub stack is not refused
    stubbed = {h: {**r, "root": r["id"]} for h, r in GOOD.items()}
    gw.http, sc.get = TestClient(_servers(stubbed)), None
    assert sc.run() == [] and sc.unchecked == []


def test_the_key_is_sent_and_an_injected_gateway_checks_nothing_by_default(tmp_path: Path) -> None:
    seen: list[tuple[str, str]] = []

    def get(url: str, key: str) -> tuple[int | None, Any]:
        seen.append((url, key))
        return 200, {"data": list(GOOD.values())}

    gw = _gateway(tmp_path, _registry())
    served_problems(gw, {"TB_LLM_API_KEY": "k" * 40}, get)
    assert sorted(seen) == [("http://llm-service:8000/v1", "k" * 40), ("http://llm-verifier:8000/v1", "k" * 40)]
    swapped = {**GOOD, "llm-service": _row("local/judge", VERIFIER_DIR)}
    gw.http = TestClient(_servers(swapped))
    with TestClient(create_app(gw)) as http:  # tests that give their own gateway are not affected
        assert http.get("/healthz").status_code == 200


# ------------------------------------------------------------------------------------------------ when it runs
def _unit(name: str) -> configparser.ConfigParser:
    cp = configparser.ConfigParser(strict=False, interpolation=None)
    cp.read_string((ROOT / "deploy" / "systemd" / name).read_text(encoding="utf-8"))
    return cp


def test_the_timer_runs_it_before_the_night_and_install_enables_it() -> None:
    timer = _unit("trialbox-weights.timer")
    assert timer["Timer"]["OnCalendar"] == "*-*-* 01:30:00" and timer["Timer"]["Persistent"] == "true"
    first = min(v for v in _schedule().values() if re.fullmatch(r"\d\d:\d\d", v))
    assert first > "01:30"  # after the timer: the first daily scheduled run of the example settings
    service = _unit("trialbox-weights.service")
    assert service["Service"]["ExecStart"] == "@TB_ROOT@/deploy/check_weights.sh @TB_ROOT@"
    script = (ROOT / "deploy" / "check_weights.sh").read_text(encoding="utf-8")
    assert "doctor --weights" in script and "--network none" in script
    install = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    enable = install.split("systemctl enable ", 1)[1].split(">/dev/null", 1)[0]
    assert "trialbox-weights.timer" in enable


def _schedule() -> dict[str, str]:
    import yaml

    doc = yaml.safe_load((ROOT / "deploy" / "settings.example.yaml").read_text(encoding="utf-8"))
    return {k: str(v) for k, v in doc["schedule"].items()}


def test_an_update_checks_the_weights_before_it_waits_for_health(tmp_path: Path) -> None:
    from tools.trialbox import update as up

    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text("COMPOSE_PROFILES=gpu\nTB_LLM_API_KEY=" + "k" * 40 + "\n")
    calls: list[list[str]] = []

    def run(argv: Any, **_: Any) -> str:
        calls.append(list(argv))
        return ""

    box = up.ComposeBox(deploy, run=run)
    note = box.check(up.Plan("b1", "", "", [], tmp_path / "stage"))
    assert "doctor --weights" in note
    weights = next(i for i, c in enumerate(calls) if c[-2:] == ["doctor", "--weights"])
    wait = next(i for i, c in enumerate(calls) if "--wait" in c)
    assert weights < wait  # the flag it writes makes the gateway unhealthy for that wait: the update rolls back
    argv = calls[weights]
    assert f"{deploy}:/app/deploy" in argv and "TB_MODELS_DIR=/app/deploy/models" in argv
    stub_box = tmp_path / "stub"
    stub_box.mkdir()
    (stub_box / ".env").write_text("COMPOSE_PROFILES=stub\n")
    assert up.ComposeBox(stub_box, run=lambda argv, **_: "").check_weights() == ""


# ------------------------------------------------------------------------------------------------ browser tools lock
def test_axe_and_playwright_are_locked() -> None:
    pkg = json.loads((ROOT / "tools" / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "tools" / "package-lock.json").read_text(encoding="utf-8"))
    axe = ROOT / pkg["trialbox"]["axe_min_js"]
    assert hashlib.sha256(axe.read_bytes()).hexdigest() == pkg["trialbox"]["axe_min_js_sha256"]
    head = axe.read_text(encoding="utf-8")[:40]
    assert head.startswith(f"/*! axe v{pkg['devDependencies']['axe-core']}\n")
    for name, version in pkg["devDependencies"].items():
        entry = lock["packages"][f"node_modules/{name}"]
        assert entry["version"] == version and entry["integrity"].startswith("sha512-")
    pw = pkg["devDependencies"]["playwright"]
    wf = (ROOT.parent / ".github" / "workflows" / "trialbox-e2e.yml").read_text(encoding="utf-8")
    assert f'PLAYWRIGHT_VERSION: "{pw}"' in wf and "npm ci --prefix" in wf
    vm = (ROOT / "deploy" / "gcp" / "complete-run-vm.sh").read_text(encoding="utf-8")
    assert re.findall(r"playwright@([\d.]+)", vm) == [pw]
    walk = (ROOT / "tools" / "public_walk.js").read_text(encoding="utf-8")
    assert 'path.join(__dirname, "vendor", "axe.min.js")' in walk and 'require.resolve("axe-core' not in walk
