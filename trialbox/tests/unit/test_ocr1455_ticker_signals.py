"""OCR #1455 (1455-4): a signal that ends poc.sh or install.sh never leaves the ticker holding the caller's output."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT, signal.SIGHUP])
@pytest.mark.parametrize(("script", "start"), [("deploy/poc.sh", 'ALIVE_PID=""\nalive_start() {'),
                                                ("deploy/install.sh", "alive_start() {")])  # fmt: skip
def test_a_signal_that_ends_the_script_frees_the_callers_output(tmp_path: Path, script: str, start: str,
                                                                sig: int) -> None:  # fmt: skip
    text = (ROOT / script).read_text(encoding="utf-8")
    a = text.index(start)
    b = text.index("\n}\n", text.index("alive_stop()", a)) + 3
    run = tmp_path / "ticker.sh"  # the script's own ticker, then a long step (its output elsewhere), as a real one
    run.write_text('ALIVE_PID=""\n' + text[a:b] + "alive_start x\nsleep 100 >/dev/null 2>&1 </dev/null\nalive_stop\n",
                   encoding="utf-8")  # fmt: skip
    p = subprocess.Popen(["bash", str(run)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        time.sleep(0.5)
        t = time.monotonic()
        if sig == signal.SIGINT:
            os.killpg(p.pid, sig)  # ^C reaches the whole foreground group
        else:
            os.kill(p.pid, sig)
        p.communicate(timeout=30)
        assert time.monotonic() - t < 5, "the caller's output was held after the script ended"
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(p.pid, signal.SIGKILL)


@pytest.mark.parametrize("script", ["deploy/install.sh", "deploy/poc.sh"])
def test_the_heartbeat_holds_no_lock_fd_of_the_caller(tmp_path: Path, script: str) -> None:
    """1452-12 (the review 7131110953): the heartbeat's subshell and its sleep inherited fd 9 (INSTALL-LOCK) and fd 6
    (the host lock): a ticker left running held the install's lock. Neither holds them now."""
    text = (ROOT / script).read_text(encoding="utf-8")
    a = text.index("alive_start() {")
    body = text[a : text.index("\n}\n", a) + 3]
    run = tmp_path / "hb.sh"
    run.write_text(
        'ALIVE_PID=""\nTB_POC_ALIVE_S=60\n' + body + f'exec 9>"{tmp_path}/lock9" 6>"{tmp_path}/lock6"\n'
        "alive_start x\nsleep 0.5\n"
        'for p in "$ALIVE_PID" $(cat /proc/"$ALIVE_PID"/task/*/children 2>/dev/null); do\n'
        '  for f in 9 6; do [ -e "/proc/$p/fd/$f" ] && echo "HELD $p $f"; done\ndone\n'
        'kill "$ALIVE_PID"; wait "$ALIVE_PID" 2>/dev/null; echo done\n',
        encoding="utf-8",
    )
    r = subprocess.run(["bash", str(run)], capture_output=True, text=True, check=False, timeout=60)
    assert "done" in r.stdout and "HELD" not in r.stdout, (r.stdout, r.stderr)


# H106-14 / 1452-12: #1452's two heartbeat tests, by the integrator's rulings 7131125435 and 7131128250 (the heartbeat
# fix lives in #1455 only); their text as #1452's worker wrote them
def test_h106_14_the_heartbeat_s_sleep_never_holds_the_caller_s_output() -> None:
    text = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    start = text.index("alive_start() {")
    end = text.index("\n}\n", text.index("alive_stop() {")) + 3
    script = text[start:end] + 'alive_start test; sleep 0.5; kill -9 "$ALIVE_PID"; echo done\n'
    t0 = time.monotonic()
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30, check=False)
    assert r.stdout.strip() == "done" and time.monotonic() - t0 < 10, r


def test_h106_14_the_poc_heartbeat_s_sleep_never_holds_the_caller_s_output() -> None:
    text = (ROOT / "deploy" / "poc.sh").read_text(encoding="utf-8")
    start = text.index("alive_start() {")
    end = text.index("\n", text.index("alive_stop() {")) + 1
    script = text[start:end] + 'alive_start test; sleep 0.5; kill -9 "$ALIVE_PID"; echo done\n'
    t0 = time.monotonic()
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30, check=False)
    assert r.stdout.strip() == "done" and time.monotonic() - t0 < 10, r
