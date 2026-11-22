"""H-85: the identity overlay's smoke run waits for the stand-in console behind Caddy, not for Caddy alone.

The wait used to end on any answer from Caddy, a 502 included (train 124, job 137209376074), and the step then
failed later on a missing header. Now only a 200 on the path the step checks ends the wait, and after the last try
the step fails there, naming the URL and the last status. The wait is run here with stand-ins for curl, sleep and
docker on PATH.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.guard, pytest.mark.nodb]  # the guard step of `checks`; no database

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT.parent / ".github" / "workflows" / "trialbox-identity.yml"
SMOKE = "smoke run (Caddy in front of a stand-in console)"


def _smoke_run() -> str:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    runs = [str(s.get("run") or "") for s in doc["jobs"]["overlay"]["steps"] if s.get("name") == SMOKE]
    assert len(runs) == 1, f"one step named {SMOKE!r} in {WORKFLOW.name}"
    return runs[0]


def _wait_block() -> str:
    run = _smoke_run()
    start = run.index('url="https://$TB_TLS_HOSTNAME/login"')
    end = run.index("\nfi\n", start) + len("\nfi\n")
    return run[start:end]


def test_wait_ends_only_on_a_200_and_fails_plainly() -> None:
    block = _wait_block()
    assert "-w '%{http_code}'" in block and '[ "$status" = 200 ] && break' in block
    assert "seq 1 30" in block and "sleep 1" in block
    assert "never answered" in block and "exit 1" in block
    for line in _smoke_run().splitlines():
        if "curl" in line and "&& break" in line:
            assert "http_code" in line or "-f" in line.split(), f"a wait that ends on any answer: {line.strip()}"


def _fake(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run_wait(tmp_path: Path, statuses: list[str]) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    assert bash, "bash is needed to run the workflow's wait"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (tmp_path / "statuses").write_text("\n".join(statuses) + "\n", encoding="utf-8")
    # curl prints the next status (the last one repeats); 000 stands for no connection, with a non-zero exit
    _fake(
        bin_dir,
        "curl",
        f"""f={tmp_path}/statuses
s=$(head -n 1 "$f")
if [ "$(wc -l < "$f")" -gt 1 ]; then sed -i 1d "$f"; fi
echo "$s" >> {tmp_path}/calls
printf '%s' "$s"
[ "$s" = 000 ] && exit 7
exit 0
""",
    )
    _fake(bin_dir, "sleep", "exit 0\n")
    _fake(bin_dir, "docker", "echo console log line\n")
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "TB_TLS_HOSTNAME": "trialbox.hosp.test"}
    script = "set -eu\n" + _wait_block() + "echo waited\n"
    return subprocess.run(
        [bash, "-eo", "pipefail", "-c", script], env=env, capture_output=True, text=True, timeout=60, check=False
    )


def test_a_502_keeps_waiting_until_the_backend_answers(tmp_path: Path) -> None:
    done = _run_wait(tmp_path, ["000", "502", "502", "503", "200"])
    assert done.returncode == 0, done.stdout + done.stderr
    assert "waited" in done.stdout
    assert (tmp_path / "calls").read_text(encoding="utf-8").split() == ["000", "502", "502", "503", "200"]


def test_after_the_last_try_the_step_fails_naming_the_url_and_status(tmp_path: Path) -> None:
    done = _run_wait(tmp_path, ["502"])
    assert done.returncode != 0
    assert "waited" not in done.stdout
    assert "the backend never answered" in done.stdout
    assert "https://trialbox.hosp.test/login gave HTTP 502 after 30 tries" in done.stdout
    assert len((tmp_path / "calls").read_text(encoding="utf-8").split()) == 30


def test_no_connection_at_all_fails_with_status_000(tmp_path: Path) -> None:
    done = _run_wait(tmp_path, ["000"])
    assert done.returncode != 0
    assert "gave HTTP 000 after 30 tries" in done.stdout
