"""Build step 4 browser walk (D-110): the five roles sign in, in Japanese, Traditional Chinese and English, on desktop
and on phone, against the role demo (``tools/role_demo.py``, the real pipeline on the synthetic hospital).

The browser part is ``tests/e2e/role_walk.js`` (Node Playwright, preinstalled Chromium). No stack is needed: the demo
runs in one process. ``TB_WALK_SHOTS=<dir>`` saves the step-4 screenshots at device scale 2.

    TB_INTEGRATION=1 .venv/bin/python -m pytest tests/e2e/test_role_walk.py -m e2e   # e2e tests need the flag
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).with_name("role_walk.js")


def _node_playwright() -> bool:
    node = shutil.which("node")
    if not node:
        return False
    r = subprocess.run([node, "-e", "require('playwright')"], cwd=ROOT, capture_output=True, timeout=60, check=False)
    return r.returncode == 0


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.mark.skipif(not _node_playwright(), reason="Node Playwright is not installed")
def test_five_roles_three_languages_desktop_and_phone(tmp_path: Path) -> None:
    password = secrets.token_urlsafe(16)
    port = _free_port()
    env = {**os.environ, "TB_DEMO_PASSWORD": password}
    log = (tmp_path / "demo.log").open("w")
    demo = subprocess.Popen(
        [sys.executable, "-m", "tools.role_demo", "--dir", str(tmp_path / "demo"), "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            assert demo.poll() is None, (tmp_path / "demo.log").read_text()[-2000:]
            try:
                if httpx.get(base + "/login", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(2)
        else:
            pytest.fail("the role demo did not start")
        shots = os.environ.get("TB_WALK_SHOTS", "")
        if shots:
            Path(shots).mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            [
                shutil.which("node") or "node",
                str(SCRIPT),
                json.dumps({"base": base, "password": password, "shots": shots}),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
        out = json.loads(r.stdout.strip().splitlines()[-1])
        assert r.returncode == 0 and out["failed"] == 0, (out, r.stderr[-2000:])
        assert out["checks"] >= 5 * 3 * 2 * 6
    finally:
        demo.terminate()
        demo.wait(timeout=30)
        log.close()
