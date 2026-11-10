"""D-177: the on-box model servers take calls only with ``TB_LLM_API_KEY``, and only the gateway holds it."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
VLLM_FILES = ["docker-compose.yml", "docker-compose.gb10.yml", "docker-compose.rtx5090.yml",
              "docker-compose.rtxpro6000.yml"]  # fmt: skip


def _load(name: str) -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load((DEPLOY / name).read_text(encoding="utf-8"))
    return doc


def test_every_vllm_server_gets_the_key() -> None:
    seen = 0
    for name in VLLM_FILES:
        for svc, body in (_load(name).get("services") or {}).items():
            if svc in ("llm-service", "llm-verifier") and "command" in body:
                env = body.get("environment") or {}
                assert env.get("VLLM_API_KEY") == "${TB_LLM_API_KEY:-}", f"{name} {svc}"
                seen += 1
    assert seen == 7  # base llm-service; gb10, rtx5090, rtxpro6000: the pair each


def test_only_the_gateway_keeps_the_key() -> None:
    doc = _load("docker-compose.secrets.yml")
    for svc, body in doc["services"].items():
        env = body.get("environment") or {}
        if svc == "gateway":
            assert "TB_LLM_API_KEY" not in env
        else:
            assert env.get("TB_LLM_API_KEY") == "", svc


def test_routing_sends_the_key_to_the_on_box_endpoints() -> None:
    from gateway.policy import RoutingPolicy

    eps = RoutingPolicy.load(ROOT / "models" / "routing.yaml").endpoints
    assert eps["serving"].api_key_env == eps["verifier"].api_key_env == "TB_LLM_API_KEY"


def test_install_makes_the_key_and_checks_the_servers() -> None:
    sh = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert "TB_LLM_API_KEY=%s" in sh and "doctor --serving" in sh and "TB_COMPOSE_OVERRIDE" in sh


def _rendered(tmp_path: Path, profile_file: str | None) -> dict[str, Any]:
    """``docker compose config`` of the box's files with a .env that holds a key (env_file inlined)."""
    if shutil.which("docker") is None or subprocess.run(["docker", "compose", "version"], capture_output=True,
                                                        check=False).returncode:  # fmt: skip
        pytest.skip("docker compose is not installed")
    for f in DEPLOY.glob("docker-compose*.yml"):
        shutil.copy(f, tmp_path / f.name)
    (tmp_path / ".env").write_text("TB_LLM_API_KEY=key-0123456789\nCLOUD_LLM_API_KEY=c\nPOSTGRES_PASSWORD=p\n")
    argv = ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.secrets.yml"]
    argv += ["-f", profile_file] if profile_file else []
    argv += ["--profile", "gpu", "config", "--format", "json"]
    out = subprocess.run(argv, cwd=tmp_path, capture_output=True, text=True, check=True).stdout
    doc: dict[str, Any] = json.loads(out)
    return doc


@pytest.mark.parametrize("profile", [None, "docker-compose.gb10.yml", "docker-compose.rtx5090.yml",
                                     "docker-compose.rtxpro6000.yml"])  # fmt: skip
def test_rendered_config_only_the_gateway_and_the_guard_hold_the_key(tmp_path: Path, profile: str | None) -> None:
    svcs = _rendered(tmp_path, profile)["services"]
    holders = {n for n, s in svcs.items() if (s.get("environment") or {}).get("TB_LLM_API_KEY") == "key-0123456789"}
    assert holders == {"gateway", "model-guard"}
    on_model_net = {n for n, s in svcs.items() if "model-net" in (s.get("networks") or {})}
    assert on_model_net == {"gateway", "model-guard"}
    for n in ("llm-service", "llm-verifier"):
        if n in svcs:  # the vLLM servers: the key for /v1, and only model-guard reaches them
            assert svcs[n]["environment"]["VLLM_API_KEY"] == "key-0123456789"
            assert set(svcs[n]["networks"]) == {"model-backend-net"}
    guard = svcs["model-guard"]
    assert guard["read_only"] and guard["cap_drop"] == ["ALL"] and "env_file" not in guard
    assert guard["environment"]["TB_GUARD_ADMIN"] == ("1" if profile == "docker-compose.rtx5090.yml" else "0")


def test_an_update_makes_a_missing_key_and_checks_the_servers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from collections.abc import Sequence

    from tools.trialbox import update as up

    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text("COMPOSE_PROFILES=gpu\nTB_LLM_API_KEY=\nX=1\n")
    (deploy / ".env").chmod(0o600)
    calls: list[list[str]] = []

    def run(argv: Sequence[str], **_: Any) -> str:
        calls.append(list(argv))
        return ""

    box = up.ComposeBox(deploy, run=run)
    plan = up.Plan("b1", "", "", [], tmp_path / "stage")
    box.restart(plan)
    env = up._env_file(deploy / ".env")
    assert len(env["TB_LLM_API_KEY"]) >= 40 and env["X"] == "1"
    assert (deploy / ".env").stat().st_mode & 0o777 == 0o600
    assert "--pull" in calls[-1] and calls[-1][calls[-1].index("--pull") + 1] == "never"
    assert "doctor --serving" in box.check(plan) and calls[-1][-3:] == ["tools.trialbox", "doctor", "--serving"]
    assert "trialbox-model-net" in calls[-1]
    assert not box.ensure_model_key()  # already there: kept
    monkeypatch.setenv("TB_INSTALL_PULL", "always")
    with pytest.raises(up.UpdateFailed, match="never or missing"):
        box.restart(plan)


def test_a_stub_box_gets_no_key_and_no_serving_check(tmp_path: Path) -> None:
    from tools.trialbox import update as up

    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text("COMPOSE_PROFILES=stub\n")
    box = up.ComposeBox(deploy, run=lambda argv, **_: "")
    assert not box.ensure_model_key() and box.check_serving() == ""
