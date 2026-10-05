"""Phase 8 DoD "egress test: all blocked except allowlist" on the running compose stack (root, nftables, iproute2).

A network namespace plays the outside world (198.51.100.1, TEST-NET-2) with three listeners: :8443 (the NHI TWPAS
endpoint), :2525 (the hospital SMTP relay) and :9443 (anything else). Before the rules every container on a routed
network reaches all three (the test proves the path exists); after ``deploy/network.sh apply`` only
orchestrator -> :8443 and mail-gateway -> :2525 connect, everything else times out, and traffic inside the box still
works. The rules and the namespace are removed afterwards.

    sudo make test-egress
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = [pytest.mark.egress]
ROOT = Path(__file__).resolve().parents[2]
NS, HOST_IF, NS_IF = "tbfake", "tbv0", "tbv1"
OUTSIDE, GW = "198.51.100.1", "198.51.100.254"
PORTS = (8443, 2525, 9443)


def sh(*cmd: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def connects(container: str, host: str, port: int, timeout: float = 3.0) -> bool:
    code = (
        "import socket,sys\n"
        f"try:\n socket.create_connection(({host!r}, {port}), timeout={timeout}).close()\n"
        "except OSError:\n sys.exit(1)\n"
    )
    return sh("docker", "exec", container, "python", "-c", code, check=False).returncode == 0


@pytest.fixture(scope="module")
def outside() -> Iterator[None]:
    if os.geteuid() != 0 or not (shutil.which("nft") and shutil.which("ip")):
        pytest.skip("needs root, nft and iproute2")
    sh("ip", "netns", "del", NS, check=False)
    sh("ip", "netns", "add", NS)
    sh("ip", "link", "add", HOST_IF, "type", "veth", "peer", "name", NS_IF)
    sh("ip", "link", "set", NS_IF, "netns", NS)
    sh("ip", "addr", "add", f"{GW}/24", "dev", HOST_IF)
    sh("ip", "link", "set", HOST_IF, "up")
    sh("ip", "netns", "exec", NS, "ip", "addr", "add", f"{OUTSIDE}/24", "dev", NS_IF)
    sh("ip", "netns", "exec", NS, "ip", "link", "set", NS_IF, "up")
    sh("ip", "netns", "exec", NS, "ip", "link", "set", "lo", "up")
    sh("ip", "netns", "exec", NS, "ip", "route", "add", "default", "via", GW)
    servers = [
        subprocess.Popen(
            ["ip", "netns", "exec", NS, "python3", "-m", "http.server", str(p), "--bind", OUTSIDE],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for p in PORTS
    ]
    deadline = time.monotonic() + 20
    probe = "import socket, sys; socket.create_connection((sys.argv[1], int(sys.argv[2])), 1)"
    for port in PORTS:  # wait until every listener answers from the host
        while sh("python3", "-c", probe, OUTSIDE, str(port), check=False).returncode:
            if time.monotonic() > deadline:
                raise RuntimeError(f"fake outside listener :{port} did not start")
            time.sleep(0.3)
    try:
        yield
    finally:
        sh(str(ROOT / "deploy/network.sh"), "flush", check=False)
        for s in servers:
            s.terminate()
        sh("ip", "netns", "del", NS, check=False)
        sh("ip", "link", "del", HOST_IF, check=False)


def test_only_allowlisted_egress(outside: None, tmp_path: Path) -> None:
    sh(str(ROOT / "deploy/network.sh"), "flush", check=False)
    # without rules the path exists (otherwise "blocked" would prove nothing)
    assert connects("trialbox-orchestrator-1", OUTSIDE, 9443)
    assert connects("trialbox-mail-gateway-1", OUTSIDE, 9443)
    env = tmp_path / "egress.env"
    env.write_text(
        f"SMTP_HOST={OUTSIDE}\nSMTP_PORT=2525\nIMAP_HOST=\nNHI_TWPAS_BASE_URL=https://{OUTSIDE}:8443/twpas\n"
        "CLOUD_LLM_BASE_URL=\nTB_CTGOV_MODE=cassette\n",
        encoding="utf-8",
    )
    applied = sh(str(ROOT / "deploy/network.sh"), "apply", "--env", str(env))
    assert "applied table inet trialbox_egress" in applied.stdout
    allowed = {("trialbox-orchestrator-1", 8443), ("trialbox-mail-gateway-1", 2525)}
    containers = [
        "trialbox-orchestrator-1",
        "trialbox-mail-gateway-1",
        "trialbox-criteria-compiler-1",
        "trialbox-adapter-1",
        "trialbox-lake-1",
    ]
    for c in containers:
        for port in PORTS:
            assert connects(c, OUTSIDE, port) == ((c, port) in allowed), (c, port)
    # inside the box nothing changed
    assert connects("trialbox-orchestrator-1", "lake", 8013)
    assert connects("trialbox-mail-gateway-1", "greenmail", 3143)
    status = sh("nft", "list", "table", "inet", "trialbox_egress").stdout
    assert "trialbox default deny" in status
