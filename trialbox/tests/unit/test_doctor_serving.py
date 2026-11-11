"""``trialbox doctor --live``: the pinned served names against the model servers, and their key (D-177).

The servers are the strict vLLM stand-in of the box rehearsal (``tools/vllm_standin.py``) on a local port.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import model_guard
import pytest

from tests.model_pins import promote_pins, release_registry
from tools import pin_model
from tools import vllm_standin as vs
from tools.trialbox import doctor
from tools.trialbox.__main__ import main as trialbox_main

KEY = "doctor-key-0123456789abcdef"
JUDGE = ("gemma-4-26b-a4b-it-rtxpro6000", "serving", "gemma-4-26b-a4b-it")
VERIFIER = ("qwen3.5-9b-rtxpro6000", "verifier", "qwen3.5-9b")


def _start(handler: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, str]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/v1"


def _guarded(name: str, guard: bool = True) -> tuple[list[ThreadingHTTPServer], str]:
    """A strict stand-in, behind model-guard as on a box (or bare, as vLLM without the guard)."""
    s, _, _ = vs.build([f"--served-model-name={name}", "--api-key", KEY], {})
    srv, url = _start(vs.make_handler(s))
    if not guard:
        return [srv], url
    g = model_guard.Guard(KEY, {"127.0.0.1": ("127.0.0.1", srv.server_address[1])})
    gsrv, gurl = _start(model_guard.make_handler(g))
    return [srv, gsrv], gurl


@pytest.fixture()
def servers() -> Iterator[dict[str, str]]:
    """Two strict stand-ins (judge and verifier) with the compose served names and one key, each behind model-guard."""
    started = []
    urls: dict[str, str] = {}
    for _, endpoint, name in (JUDGE, VERIFIER):
        srvs, url = _guarded(name)
        started += srvs
        urls[endpoint] = url
    yield urls
    for srv in started:
        srv.shutdown()


@pytest.mark.parametrize(("env", "status"), [("PRODUCTION", "FAIL"), ("TEST", "WARN")])
def test_a_server_without_the_guard_is_reachable_without_the_key(tmp_path: Path, env: str, status: str) -> None:
    started: list[ThreadingHTTPServer] = []
    urls: dict[str, str] = {}
    for _, endpoint, name in (JUDGE, VERIFIER):
        srvs, urls[endpoint] = _guarded(name, guard=False)
        started += srvs
    try:
        c = doctor.check_serving(_inputs(_pins(tmp_path), urls, env=env))
        assert c.status == status
        assert "POST /invocations without the key answered HTTP" in c.detail and "POST /tokenize" in c.detail
    finally:
        for srv in started:
            srv.shutdown()


def _pins(tmp_path: Path, served: dict[str, str] | None = None) -> Path:
    out = tmp_path / "site" / "registry.site.yaml"
    folders: dict[str, Path] = {}
    for build, _endpoint, _name in (JUDGE, VERIFIER):
        d = folders[build] = tmp_path / "models" / build
        d.mkdir(parents=True)
        (d / "config.json").write_text('{"architectures": ["Placeholder"]}\n', encoding="utf-8")
        (d / "model.safetensors").write_bytes(b"synthetic placeholder, not a model\n")
    with pytest.MonkeyPatch.context() as mp:  # the synthetic folders are the release (T-012b)
        release_registry(tmp_path, folders, mp)
        for build, endpoint, name in (JUDGE, VERIFIER):
            pin_model.pin(build, folders[build], served_name=(served or {}).get(endpoint, name), endpoint=endpoint,
                          out=out)  # fmt: skip
    promote_pins(out)
    return out


def _inputs(
    override: Path, urls: dict[str, str], key: str | None = KEY, env: str = "PRODUCTION"
) -> doctor.DoctorInputs:
    e = {"TB_ENV": env, "TB_REGISTRY_OVERRIDE": str(override), "TB_EP_SERVING_URL": urls["serving"],
         "TB_EP_VERIFIER_URL": urls["verifier"]}  # fmt: skip
    if key is not None:
        e["TB_LLM_API_KEY"] = key
    return doctor.DoctorInputs(env=e)


def test_pass_when_names_match_and_the_key_is_required(tmp_path: Path, servers: dict[str, str]) -> None:
    c = doctor.check_serving(_inputs(_pins(tmp_path), servers))
    assert c.status == "PASS", c.detail
    assert "'gemma-4-26b-a4b-it'" in c.detail and "'qwen3.5-9b'" in c.detail and "key required" in c.detail


def test_wrong_served_name_fails_and_names_both(tmp_path: Path, servers: dict[str, str]) -> None:
    c = doctor.check_serving(_inputs(_pins(tmp_path, {"serving": "gemma-4-26b-a4b-it-4bit"}), servers))
    assert c.status == "FAIL"
    assert "'gemma-4-26b-a4b-it-4bit'" in c.detail and "['gemma-4-26b-a4b-it']" in c.detail and "404" in c.detail
    assert "verifier" not in c.detail  # the verifier still matches


@pytest.mark.parametrize("env", ["PRODUCTION", "DEV"])
def test_missing_key_fails_in_every_environment(tmp_path: Path, servers: dict[str, str], env: str) -> None:
    c = doctor.check_serving(_inputs(_pins(tmp_path), servers, key=None, env=env))
    assert c.status == "FAIL"  # the server has a key: the gateway's calls would all be refused
    assert "HTTP 401" in c.detail and "TB_LLM_API_KEY" in c.detail


def test_wrong_key_fails(tmp_path: Path, servers: dict[str, str]) -> None:
    c = doctor.check_serving(_inputs(_pins(tmp_path), servers, key="not-the-key"))
    assert c.status == "FAIL" and "refused the key" in c.detail


def test_server_down_fails(tmp_path: Path) -> None:
    urls = {"serving": "http://127.0.0.1:9/v1", "verifier": "http://127.0.0.1:9/v1"}
    c = doctor.check_serving(_inputs(_pins(tmp_path), urls))
    assert c.status == "FAIL" and "not reachable" in c.detail


class _Open(BaseHTTPRequestHandler):
    """A vLLM started without a key: answers anyone."""

    def do_GET(self) -> None:
        data = json.dumps({"data": [{"id": JUDGE[2]}, {"id": VERIFIER[2]}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.mark.parametrize(("env", "status"), [("PRODUCTION", "FAIL"), ("TEST", "WARN")])
def test_open_server_and_no_key(tmp_path: Path, env: str, status: str) -> None:
    srv, url = _start(_Open)
    try:
        c = doctor.check_serving(_inputs(_pins(tmp_path), {"serving": url, "verifier": url}, key=None, env=env))
        assert c.status == status and "no key" in c.detail
        c = doctor.check_serving(_inputs(_pins(tmp_path / "b"), {"serving": url, "verifier": url}, env=env))
        assert c.status == status and "answers without the key" in c.detail
    finally:
        srv.shutdown()


def test_nothing_pinned_is_a_warning(tmp_path: Path) -> None:
    c = doctor.check_serving(_inputs(tmp_path / "none.yaml", {"serving": "http://x/v1", "verifier": "http://x/v1"}))
    assert c.status == "WARN" and "no pinned" in c.detail


def test_cli_serving_runs_only_the_live_check(
    tmp_path: Path, servers: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    override = _pins(tmp_path)
    for k, v in _inputs(override, servers).env.items():
        monkeypatch.setenv(k, v)
    assert trialbox_main(["doctor", "--serving"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("PASS  serving") and "doctor passed" in out and "topology" not in out
    monkeypatch.setenv("TB_LLM_API_KEY", "wrong")
    assert trialbox_main(["doctor", "--serving"]) == 1
    assert "FAIL  serving" in capsys.readouterr().out


def test_box_env_file_gets_the_compose_gateway_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An installed box's deploy/.env has no TB_GATEWAY_URL (compose sets it for the orchestrator), so note_block
    must read the box as it runs: both_agree with a verifier build passes in PRODUCTION (found by the rehearsal)."""
    for k in [k for k in os.environ if k.startswith("TB_")]:
        monkeypatch.delenv(k)
    env = tmp_path / ".env"
    env.write_text("TB_ENV=PRODUCTION\nTB_GATEWAY_VERIFIER_MODEL=v-verifier\nCOMPOSE_FILE=/opt/trialbox/deploy/x.yml\n")
    inp = doctor.inputs_from(env_file=env, settings=None, routing=None, lake=None)
    assert inp.env["TB_GATEWAY_URL"] == "http://gateway:8020/v1"
    assert doctor.check_note_block(inp).status == "PASS"
    env.write_text("TB_ENV=PRODUCTION\nTB_GATEWAY_VERIFIER_MODEL=v-verifier\n")  # not a box: nothing assumed
    inp = doctor.inputs_from(env_file=env, settings=None, routing=None, lake=None)
    assert "TB_GATEWAY_URL" not in inp.env and doctor.check_note_block(inp).status == "FAIL"
