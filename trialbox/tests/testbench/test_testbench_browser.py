"""Browser smoke test of the Test Bench with Playwright (docs/HANDOFF.md §5).

The Python ``playwright`` package is not in the venv, so the browser part is ``tests/testbench/browser_smoke.js`` on
Node Playwright with the preinstalled Chromium (``PLAYWRIGHT_BROWSERS_PATH``); this wrapper starts the bench on a free
loopback port (TB_ENV=TEST) and runs it. ``TB_TESTBENCH_SCREENSHOTS=<dir>`` also saves the home and run pages.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).with_name("browser_smoke.js")


def _node_playwright() -> bool:
    node = shutil.which("node")
    if not node:
        return False
    r = subprocess.run([node, "-e", "require('playwright')"], cwd=ROOT, capture_output=True, timeout=60, check=False)
    return r.returncode == 0


pytestmark = pytest.mark.skipif(not _node_playwright(), reason="Node Playwright is not available")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def bench(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    port = _free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith("TB_")}
    env.update(
        TB_ENV="TEST",
        PYTHONPATH="libs:services:.",
        TB_TESTBENCH_WORKDIR=str(tmp_path_factory.mktemp("bench-browser")),
    )
    log = tmp_path_factory.mktemp("bench-log") / "server.log"
    with log.open("w") as fh:
        proc = subprocess.Popen(
            [sys.executable, "-m", "tools.testbench", "--host", "127.0.0.1", "--port", str(port)],
            cwd=ROOT,
            env=env,
            stdout=fh,
            stderr=subprocess.STDOUT,
        )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            try:
                with urllib.request.urlopen(base + "/healthz", timeout=2) as r:
                    if r.status == 200:
                        break
            except OSError:
                if proc.poll() is not None:
                    pytest.fail(f"bench exited: {log.read_text()[-2000:]}")
                time.sleep(0.5)
        else:
            pytest.fail(f"bench did not start: {log.read_text()[-2000:]}")
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_browser_smoke_every_page_and_run_end_to_end(bench: str) -> None:
    args = ["node", str(SCRIPT), bench]
    shots = os.environ.get("TB_TESTBENCH_SCREENSHOTS")
    if shots:
        Path(shots).mkdir(parents=True, exist_ok=True)
        args.append(shots)
    r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=900, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ok run end to end: PASS" in r.stdout
    for p in ("/", "/run", "/dataplat", "/llm", "/guard", "/recall", "/match"):
        assert f"ok page {p}\n" in r.stdout
