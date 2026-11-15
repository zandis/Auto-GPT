"""D-839: `TB_LLM_MODE=gpu deploy/poc.sh` brings the real pair up on a plain GPU VM in one command.

It checks the host before it writes or starts anything (a GPU, Docker's nvidia runtime, the profile, the model folders
and the chat template the profile's overlay names, free disk), pins the pair from the weights (pin_model --install,
then --resolve), starts the stack with the profile's shipped serving settings (docker-compose.<profile>.yml), runs the
pair canary, and prints a heartbeat through its long steps. No bundle, signature, seal or hardening. Run here with
stand-ins for docker and nvidia-smi on a root of its own."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.nodb

DOCKER = r"""#!/bin/sh
echo "$*" >> "$TB_TEST_LOG"
case "$1" in
  info) case "$*" in *-f*) echo "$TB_TEST_DROOT" ;; *) [ "${TB_TEST_NO_NVIDIA:-0}" = 1 ] && echo "Runtimes: runc" || echo "Runtimes: nvidia runc" ;; esac ;;
esac
exit 0
"""
NVSMI = '#!/bin/sh\necho "GPU 0: NVIDIA RTX PRO 6000 Blackwell Server Edition (UUID: GPU-0)"\n'


def _root(tmp: Path, models: bool = True) -> Path:
    root = tmp / "root"
    (root / "deploy").mkdir(parents=True)
    for rel in ("deploy/poc.sh", "deploy/gpu_profile.sh", "deploy/docker-compose.rtxpro6000.yml", ".env.example"):
        shutil.copy2(ROOT / rel, root / rel)
    if models:
        for d in ("gemma-4-26b-a4b-it-4bit", "qwen3.5-9b-4bit"):
            (root / "deploy/models" / d).mkdir(parents=True)
            (root / "deploy/models" / d / "config.json").write_text("{}", encoding="utf-8")
        tpl = root / "deploy/models/chat-templates/gemma-4-26b-a4b-it/chat_template.jinja"
        tpl.parent.mkdir(parents=True)
        tpl.write_text("{{ messages }}", encoding="utf-8")
    return root


def _run(tmp: Path, root: Path, **env: str) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bindir = tmp / "bin"
    bindir.mkdir(exist_ok=True)
    for name, body in (("docker", DOCKER), ("nvidia-smi", NVSMI)):
        (bindir / name).write_text(body, encoding="utf-8")
        (bindir / name).chmod(0o755)
    log = tmp / "docker.log"
    full = {k: v for k, v in os.environ.items() if not k.startswith("TB_")}
    full.update(PATH=f"{bindir}:/usr/bin:/bin", TB_LLM_MODE="gpu", TB_GPU_PROFILE="rtxpro6000", TB_TEST_LOG=str(log),
                TB_TEST_DROOT=str(tmp), TB_POC_MIN_FREE_GB="0", TB_POC_SKIP_INGEST="1", **env)  # fmt: skip
    res = subprocess.run(["bash", str(root / "deploy/poc.sh")], capture_output=True, text=True, env=full,
                         timeout=120, check=False)  # fmt: skip
    return res, (log.read_text(encoding="utf-8").splitlines() if log.exists() else [])


def test_no_nvidia_runtime_stops_before_anything_is_written(tmp_path: Path) -> None:
    root = _root(tmp_path)
    res, log = _run(tmp_path, root, TB_TEST_NO_NVIDIA="1")
    assert res.returncode == 1 and "nvidia runtime" in res.stderr
    assert not (root / "deploy/.env").exists() and not any("compose" in line and " up " in f" {line} " for line in log)


def test_a_missing_model_folder_is_named_before_anything_is_written(tmp_path: Path) -> None:
    root = _root(tmp_path, models=False)
    res, _ = _run(tmp_path, root)
    assert res.returncode == 1 and "deploy/models/gemma-4-26b-a4b-it-4bit" in res.stderr
    assert not (root / "deploy/.env").exists()


def test_it_checks_pins_starts_with_the_profile_and_runs_the_canary(tmp_path: Path) -> None:
    root = _root(tmp_path)
    res, log = _run(tmp_path, root)
    assert res.returncode == 0, res.stdout + res.stderr
    for said in ("ok    GPU:", "ok    Docker's nvidia runtime", "ok    GPU profile rtxpro6000", "ok    model folder",
                 "ok    chat template", "the pair canary"):  # fmt: skip
        assert said in res.stdout, said

    def first(pred) -> int:  # type: ignore[no-untyped-def]
        return next(i for i, line in enumerate(log) if pred(line))

    pin = first(lambda s: "pin_model --install rtxpro6000" in s)
    up = first(lambda s: " up -d " in f" {s} " and "docker-compose.rtxpro6000.yml" in s)
    canary = first(lambda s: "exec -T orchestrator python -m tools.canary" in s)
    assert pin < up < canary
    assert any("pin_model --resolve" in s for s in log)


def test_the_poc_names_g1_and_has_no_bundle_seal_or_hardening() -> None:
    text = (ROOT / "deploy/poc.sh").read_text(encoding="utf-8")
    assert "tools.complete_run --only chat-template" in text
    for absent in ("seal_keys.sh", "hardening/apply.sh", "apply_update.sh"):
        assert absent not in text


def test_a_first_run_makes_its_env_file(tmp_path: Path) -> None:
    """`rand` under pipefail ended the script with exit 141 at the first `X="$(rand)"` (no deploy/.env yet)."""
    root = _root(tmp_path)
    res, _ = _run(tmp_path, root)
    assert res.returncode == 0, res.stderr
    env = (root / "deploy/.env").read_text(encoding="utf-8")
    assert "change-me" not in env.split("POSTGRES_WF_PASSWORD=", 1)[1].split("\n", 1)[0]
