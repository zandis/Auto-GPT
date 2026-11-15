"""D-835: the installer's pin step pins the model pair or stops, and its long waits say they are alive.

On lane G's VM the image user (uid 10001) could not write the root-owned deploy/site: PermissionError on
/d/site/manifests was only a warning, so the install went on with NO model pinned. The pin containers now run as the
installer's own user (as the wizard, the secrets and doctor --serving already do), a failed pin stops the install
with what to do, and the hashing of the weights and the wait for a healthy stack print a heartbeat."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INSTALL = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")

pytestmark = pytest.mark.nodb


def _pin_block() -> str:
    start = INSTALL.index('if [ "$MODE" = gpu ]; then\n  # D-142')
    return INSTALL[start : INSTALL.index('\ncase "$MODE:$GPU" in', start)]


def _run(tmp: Path, docker_rc: int, env: str = "") -> tuple[subprocess.CompletedProcess[str], str]:
    (tmp / "deploy").mkdir()
    (tmp / "deploy" / ".env").write_text("JUDGE_MODEL=judge\n" + env, encoding="utf-8")
    log = tmp / "docker.log"
    stand_ins = (
        "set -euo pipefail\n"
        'die() { echo "install: $*" >&2; exit 1; }\n'
        'say() { echo "==> $*"; }\n'
        "tree_args() { TREE_D=(); }\n"
        'envget() { sed -n "s/^$1=//p" deploy/.env | tail -1; }\n'
        "alive_start() { :; }\nalive_stop() { :; }\n"
        f'docker() {{ echo "$*" >> {log}; return {docker_rc}; }}\n'
        f'MODE=gpu; GPU=rtxpro6000; IMAGE_PY=trialbox-py:1.0.0; ROOT="{tmp}"\n'
        f'cd "{tmp}"\n'
        'TB_ENV_SITE="$(envget TB_ENV)"\n'
    )
    res = subprocess.run(
        ["/bin/bash", "-c", stand_ins + _pin_block() + "\necho reached-the-end\n"],
        capture_output=True,
        text=True,
        env={**os.environ},
        check=False,
    )
    return res, log.read_text(encoding="utf-8") if log.exists() else ""


def test_a_failed_pin_stops_the_install(tmp_path: Path) -> None:
    res, _ = _run(tmp_path, docker_rc=1)
    assert res.returncode == 1
    assert "reached-the-end" not in res.stdout
    assert "not pinned" in res.stderr and "RUNBOOK §8" in res.stderr


@pytest.mark.parametrize("env", ["", "TB_ENV=TEST\n", "TB_REHEARSAL=1\n", "TB_ENV=PRODUCTION\nTB_REHEARSAL=1\n"])
def test_a_failed_pin_stops_every_box_but_a_rehearsal_box(tmp_path: Path, env: str) -> None:
    res, _ = _run(tmp_path, docker_rc=1, env=env)
    assert res.returncode == 1 and "not pinned" in res.stderr


def test_a_rehearsal_box_goes_on_with_its_placeholder_weights_unpinned(tmp_path: Path) -> None:
    """D-887: the rehearsal media's placeholder weights are never the release's (models/registry.yaml names the real
    ones), so the pin is refused there; the model stand-ins answer instead. Found by the box rehearsal in CI."""
    res, _ = _run(tmp_path, docker_rc=1, env="TB_ENV=TEST\nTB_REHEARSAL=1\n")
    assert res.returncode == 0 and "reached-the-end" in res.stdout
    assert "rehearsal box" in res.stdout and "no build is pinned" in res.stdout


def test_the_pin_container_runs_as_the_installer_user(tmp_path: Path) -> None:
    res, log = _run(tmp_path, docker_rc=0)
    assert res.returncode == 0, res.stderr
    install = next(line for line in log.splitlines() if "--install rtxpro6000" in line)
    assert f"--user {os.getuid()}:{os.getgid()}" in install, install


def test_every_pin_tool_run_is_the_installer_user() -> None:
    body = INSTALL[INSTALL.index("pin_tool() {") : INSTALL.index("}", INSTALL.index("pin_tool() {"))]
    assert '--user "$(id -u):$(id -g)"' in body


def test_the_weights_hashing_and_the_healthy_wait_say_they_are_alive() -> None:
    block = _pin_block()
    for step in ("--install", "--verify-all"):
        at = block.index(f"python -m tools.pin_model {step}")
        assert block.rfind("alive_start", 0, at) > block.rfind("alive_stop", 0, at), step
    up = INSTALL.index('"${COMPOSE[@]}" up -d --pull "$PULL" "${UP_EXTRA[@]}" --wait')  # the whole stack's wait
    assert INSTALL.rfind("alive_start", 0, up) > INSTALL.rfind("alive_stop", 0, up)
    assert "alive_stop" in INSTALL[up : up + 400]
    assert not re.search(r"is not pinned \(see above\).*\" >&2", block)  # no warning that lets it go on
