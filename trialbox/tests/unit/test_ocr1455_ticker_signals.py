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
