"""1494 CI (job 138877998556): a restore whose interrupt was said ends with the code it said (130) even when the walk's
second SIGTERM arrives after the restore put its handlers back, never by the default action (143)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from tests.unit.test_restore_from_the_host_h100 import _box

ROOT = Path(__file__).resolve().parents[2]

CHILD = textwrap.dedent(
    """
    import sys, time
    from tools.trialbox import box_restore as br
    import tools.trialbox.__main__ as cli

    def restore():  # the host step's shape: its handlers, the said interrupt, its handlers put back
        back = br._host_signals()
        try:
            try:
                print("ready", flush=True)  # the handlers are in: the test's signals come after this line
                time.sleep(30)
            except br.HostInterrupted:
                return 130
        finally:
            back()

    rc = cli._exit_code(restore())
    time.sleep(0.5)  # the way out, where the second signal lands
    sys.exit(rc)
    """
)


def test_a_second_sigterm_after_the_said_interrupt_keeps_130() -> None:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "libs"), str(ROOT / "services")])}
    p = subprocess.Popen([sys.executable, "-c", CHILD], cwd=ROOT, env=env, stdout=subprocess.PIPE, text=True)
    assert p.stdout is not None
    # the first signal after the child says its handlers are in, never after a fixed sleep: a slow start under
    # -n auto would take it before them and die by it
    assert p.stdout.readline() == "ready\n"
    p.send_signal(signal.SIGTERM)
    time.sleep(0.2)  # the walk's two
    p.send_signal(signal.SIGTERM)
    assert p.wait(timeout=30) == 130  # without _exit_code: killed by SIGTERM (143 in a shell), as in CI


def test_the_exit_code_keeps_handlers_for_any_other_code() -> None:
    import tools.trialbox.__main__ as cli

    before = signal.getsignal(signal.SIGINT)
    assert cli._exit_code(0) == 0 and cli._exit_code(1) == 1
    assert signal.getsignal(signal.SIGINT) is before


def test_an_in_process_restore_that_says_its_interrupt_keeps_its_callers_handlers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ignore is the process's own way out only: ``cli.main`` called in a process (the tests, a caller) returns
    the said 130 and leaves SIGINT, SIGTERM and SIGHUP as they were, never ignored."""
    import tools.trialbox.__main__ as cli
    from tools.trialbox import box_restore

    deploy = _box(tmp_path)
    monkeypatch.setattr(box_restore.BoxRestore, "restore", lambda self, a: 130)
    sigs = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    before = [signal.getsignal(s) for s in sigs]
    argv = ["restore", str(tmp_path / "nas" / "trialbox-CGMH-20261109T194500Z.tbbak"), "--key",
            str(tmp_path / "usb" / "backup.key"), "--yes", "--restart", "--deploy", str(deploy)]  # fmt: skip
    assert cli.main(argv, installed=True) == 130
    assert [signal.getsignal(s) for s in sigs] == before
