"""Card H-148, id 6: a left-over keep-alive ``sleep`` never holds the caller's output open.

``alive_start`` (deploy/poc.sh, deploy/install.sh) runs ``sleep N &`` in a subshell and ``alive_stop`` sends that
subshell TERM; its trap kills the sleep by ``$s``. When TERM lands after ``sleep`` was forked but before ``s=$!`` (a
step that ends at once, as compose does with the stand-in docker), the trap kills nothing and the sleep lives on with
the script's stdout and stderr: whoever reads the script's output (a test's ``capture_output``, a pipe into ``tee``)
waits up to N seconds for the end of it. ``test_poc_real_embedder::test_without_the_switch_nothing_changes`` timed out
at 120 s this way on a loaded bench (TB_POC_ALIVE_S=600); 2 runs in 200 of the bare pair held the pipe here.

The race itself cannot be timed from a test, so each case takes the worst of it on purpose: the subshell is killed
(KILL, no trap runs) while its sleep sleeps. The sleep must then hold neither stream of the script."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.nodb

# a sleep that says it started (its own pid, for the clean-up) and then sleeps as the real one does
SLEEP = """#!/bin/sh
echo $$ >> "$TB_TEST_SLEEP_PIDS"
exec /bin/sleep "$@"
"""


# this test's own sleep (the integrator's M1 on #1524): it sleeps 600 s whatever the heartbeat asks, so a sleep that
# keeps the script's streams holds them for longer than the test waits, as the heartbeat's 60 s sleep did; with the
# heartbeat's 1 s tick (OCR 1524-2) a forwarded argument let a held stream go after a second and the test could not fail.
# SLEEP above stays as it is: test_alive_ends_with_its_script_1524 needs the 1 s tick
LONG_SLEEP = """#!/bin/sh
echo $$ >> "$TB_TEST_SLEEP_PIDS"
exec /bin/sleep 600
"""


def _functions(script: str) -> str:
    text = (ROOT / script).read_text(encoding="utf-8")
    start = text.index("alive_start() {")
    stop = text.index("alive_stop() {")
    end = text.index("\n", stop)
    if not text[stop:end].rstrip().endswith("}"):  # written over several lines (install.sh)
        end = text.index("\n}\n", stop) + 2
    return text[start:end] + "\n"


@pytest.mark.parametrize("script", ["deploy/poc.sh", "deploy/install.sh"])
def test_a_left_over_keep_alive_sleep_holds_no_output(script: str, tmp_path: Path) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "sleep").write_text(LONG_SLEEP, encoding="utf-8")
    (bindir / "sleep").chmod(0o755)
    pids = tmp_path / "sleep.pids"
    body = (
        _functions(script)
        + "alive_start 'a step'\n"
        + f'until [ -s "{pids}" ]; do /bin/sleep 0.05; done\n'  # the keep-alive's sleep has started
        + 'kill -KILL "$ALIVE_PID"; wait "$ALIVE_PID" 2>/dev/null; echo the-script-ended\n'
    )
    env = {**os.environ, "PATH": f"{bindir}:/usr/bin:/bin", "TB_TEST_SLEEP_PIDS": str(pids), "TB_POC_ALIVE_S": "600"}
    proc = subprocess.Popen(["bash", "-c", body], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    try:
        out, _err = proc.communicate(timeout=60)  # the end of both streams: at once, or after the 600 s sleep
        held = False
    except subprocess.TimeoutExpired:
        held = True
    finally:
        for pid in (int(p) for p in pids.read_text(encoding="utf-8").split()) if pids.exists() else ():
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)  # the sleep first: while it lives, the streams stay open
    if held:
        proc.kill()
        out, _err = proc.communicate()
    assert not held, f"{script}: the keep-alive's sleep held the script's output after the script ended"
    assert "the-script-ended" in out and proc.returncode == 0
