"""H-142: a restore ends 0, 1 or 130 (its own refusals 2, 3 and 4 as RUNBOOK §5 says) and says its state, whatever
signal comes, on the real entry: ``tools/trialbox/__main__.py`` run as a script, as ``trialbox`` is installed.

.i (H-140 table 2a): H-138's test called ``cli._exit_code`` itself, so taking the entry's own call out left it green.
Here the child runs the entry file as a script (``runpy.run_path`` with ``run_name="__main__"``: its own ``__main__``
block, ``installed`` as on the host) with a stand-in restore, and the walk's second signal is sent on the process's
own way out (an ``atexit`` step, after ``main`` returned and before the exit), never by calling the entry's code."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

from tests.unit.test_restore_from_the_host_h100 import _box

ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "tools" / "trialbox" / "__main__.py"
BACKUP = "trialbox-CGMH-20261109T194500Z.tbbak"

#: the child: the real entry file as a script; the host's restore stood in for by ``RESTORE`` (its body)
CHILD = textwrap.dedent(
    """
    import atexit, os, runpy, signal, sys, time
    root = sys.argv[1]
    sys.path[:0] = [root, os.path.join(root, "libs"), os.path.join(root, "services")]
    from tools.trialbox import box_restore as br, launch

    launch.enter = lambda args, environ=None, installed=False: None  # this host is no box: run the command here

    def restore(self, a):
    {body}

    br.BoxRestore.restore = restore

    def way_out():  # the walk's second signal, after main returned and before the process ends
        os.kill(os.getpid(), getattr(signal, os.environ["H142_LAST"]))
        time.sleep(0.3)

    if os.environ.get("H142_LAST"):
        atexit.register(way_out)
    sys.argv = [sys.argv[2], *sys.argv[3:]]
    runpy.run_path(sys.argv[0], run_name="__main__")
    """
)

#: H-138's host step: its handlers in, the said interrupt, its handlers put back, 130
SAID_INTERRUPT = """
    back = br._host_signals()
    try:
        try:
            print("ready", flush=True)
            time.sleep(30)
        except br.HostInterrupted:
            return 130
    finally:
        back()
"""


def run_entry(tmp_path: Path, body: str, last: str = "", first: str = "") -> tuple[int, str, str]:
    """The entry as a script with the stand-in restore ``body``; ``first``: a signal once it says ``ready``;
    ``last``: a signal on its way out. The exit code as a shell reads it (a signal's death: 128 + its number)."""
    deploy = _box(tmp_path)
    child = tmp_path / "child.py"
    child.write_text(CHILD.format(body=textwrap.indent(textwrap.dedent(body).strip("\n"), "    ")), encoding="utf-8")
    argv = [sys.executable, str(child), str(ROOT), str(ENTRY), "restore", str(tmp_path / "nas" / BACKUP), "--key",
            str(tmp_path / "usb" / "backup.key"), "--yes", "--restart", "--deploy", str(deploy)]  # fmt: skip
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "H142_LAST": last}
    p = subprocess.Popen(argv, cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert p.stdout is not None
    if first:
        line = p.stdout.readline()  # the first signal once the handlers are in, never after a fixed sleep
        assert line == "ready\n", (line, p.communicate(timeout=30))
        p.send_signal(getattr(signal, first))
    out, err = p.communicate(timeout=60)
    code = p.returncode
    return (128 - code if code < 0 else code), out, err


def test_the_entry_keeps_the_said_130_when_the_walks_second_signal_lands_on_its_way_out(tmp_path: Path) -> None:
    """H-138 on the real entry: the restore said its interrupt (130) and put its handlers back; the second SIGTERM
    arrives after ``main`` returned. Without the entry's own ``_exit_code`` call: 143."""
    code, _out, err = run_entry(tmp_path, SAID_INTERRUPT, last="SIGTERM", first="SIGTERM")
    assert code == 130, (code, err[-2000:])
