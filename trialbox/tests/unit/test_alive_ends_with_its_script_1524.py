"""OCR 1524-2 (card H-148, id 6): the keep-alive heartbeat of ``alive_start`` (deploy/poc.sh, deploy/install.sh) holds
the script's output while it lives. A script that ends without ``alive_stop`` (``set -e``, a signal) is a zombie until
its caller reaps it, and a caller that reads the output to its end first (``communicate``, ``capture_output``) reaps
it only then; ``kill -0`` finds a zombie, so the heartbeat never ended and the caller waited for its own timeout. It
must end within seconds of its script, however the script ended."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

from tests.unit.test_alive_sleep_holds_no_pipe_h148 import SLEEP, _functions

pytestmark = pytest.mark.nodb

ENDS = {"set -e": "false\n", "TERM": "kill -TERM $$\n", "KILL": "kill -KILL $$\n"}


@pytest.mark.parametrize("how", sorted(ENDS))
@pytest.mark.parametrize("script", ["deploy/poc.sh", "deploy/install.sh"])
def test_the_heartbeat_ends_with_a_script_that_ended_without_alive_stop(script: str, how: str, tmp_path: Path) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "sleep").write_text(SLEEP, encoding="utf-8")
    (bindir / "sleep").chmod(0o755)
    pids = tmp_path / "sleep.pids"
    body = (
        "set -euo pipefail\n" + _functions(script) + "alive_start 'a step'\n"
        f'until [ -s "{pids}" ]; do /bin/sleep 0.05; done\n' + ENDS[how] + "echo not-reached\n"
    )
    env = {**os.environ, "PATH": f"{bindir}:/usr/bin:/bin", "TB_TEST_SLEEP_PIDS": str(pids), "TB_POC_ALIVE_S": "600"}
    proc = subprocess.Popen(["bash", "-c", body], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    t = time.monotonic()
    try:
        out, _err = proc.communicate(timeout=30)
        took = time.monotonic() - t
    except subprocess.TimeoutExpired:
        took = None
    finally:
        for pid in (int(p) for p in pids.read_text(encoding="utf-8").split()) if pids.exists() else ():
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
    if took is None:
        proc.kill()
        out, _err = proc.communicate()
    assert took is not None, f"{script} ({how}): the heartbeat held the script's output after the script ended"
    assert "not-reached" not in out and proc.returncode != 0
