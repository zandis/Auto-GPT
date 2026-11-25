"""H-142 (.h): the update path's two windows, on the real entry (``tools/trialbox/__main__.py update`` run as a
script, through the real ``update.main_apply``; the box's ``running`` and the run's steps stood in).

1. Before the run's own handlers (``Stops`` in ``Updater.run``): a signal was the default's death, 143, no line.
   The handlers are taken at ``main_apply``'s first line now; a signal there is refused, said, 1.
2. After them: ``Stops`` gave the defaults back and the exit's ``_exit_code`` acts on 130 only, so a signal on the
   way out turned the update's 0 or 1 into 143 and lost the lines still in the buffer. They stay ignored to the exit
   now, and the lines are flushed first."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "tools" / "trialbox" / "__main__.py"

CHILD = textwrap.dedent(
    """
    import atexit, os, runpy, signal, sys, time
    root, marks, pause = sys.argv[1], sys.argv[2], float(sys.argv[3])
    sys.path[:0] = [root, os.path.join(root, "libs"), os.path.join(root, "services")]
    from tools.trialbox import launch, update as up

    launch.enter = lambda args, environ=None, installed=False: None  # this host is no box: run the command here

    def mark(name):
        with open(marks, "a") as fh:
            fh.write(name + "\\n")
        time.sleep(pause)

    def running(self):  # main_apply asks whether the box runs: before the run's own handlers
        mark("running")
        return True

    def preflight(self, plan, backup=True):  # the run's first step, under its handlers
        mark("preflight")
        return []

    def run_rest(self, plan, backup):  # the rest of the run: applied
        mark("applied")
        return {"ok": True}

    up.DemoBox.running = running
    up.Updater.preflight = preflight
    up.Updater._run = run_rest

    def way_out():  # a signal after main returned, before the process ends
        os.kill(os.getpid(), getattr(signal, os.environ["H142_LAST"]))
        time.sleep(0.3)

    if os.environ.get("H142_LAST"):
        atexit.register(way_out)
    sys.argv = [str(sys.argv[4]), *sys.argv[5:]]
    runpy.run_path(sys.argv[0], run_name="__main__")
    """
)


def _stage(tmp_path: Path) -> tuple[Path, Path, Path]:
    stage, deploy = tmp_path / "stage", tmp_path / "deploy"
    stage.mkdir()
    deploy.mkdir()
    (deploy / ".env").write_text("TB_ENV=TEST\n", encoding="utf-8")
    (stage / "manifest.json").write_bytes(b"{}")
    summary = stage / "summary.json"
    compat = {"format": "trialbox-update-compat/1", "bundle_id": "B0", "rows": [{}]}
    summary.write_text(json.dumps({"bundle_id": "B0", "manifest_sha256": hashlib.sha256(b"{}").hexdigest(),
                                   "signer": "v", "files": [], "release_seq": 1, "compat": compat,
                                   "trust_sha256": None}), encoding="utf-8")  # fmt: skip
    return stage, summary, deploy


def start(tmp_path: Path, last: str = "", pause: float = 0.0) -> tuple[subprocess.Popen[str], Path]:
    stage, summary, deploy = _stage(tmp_path)
    child, marks = tmp_path / "child.py", tmp_path / "marks"
    child.write_text(CHILD, encoding="utf-8")
    argv = [sys.executable, str(child), str(ROOT), str(marks), str(pause), str(ENTRY), "update", "--stage",
            str(stage), "--summary", str(summary), "--target", "demo", "--deploy", str(deploy)]  # fmt: skip
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "H142_LAST": last}
    p = subprocess.Popen(argv, cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return p, marks


def ended(p: subprocess.Popen[str]) -> tuple[int, str, str]:
    out, err = p.communicate(timeout=60)
    return (128 - p.returncode if p.returncode < 0 else p.returncode), out, err


def at_mark(p: subprocess.Popen[str], marks: Path, mark: str, delay: float, sig: str) -> bool:
    t = time.monotonic()
    while not (marks.is_file() and mark in marks.read_text(encoding="utf-8").split()):
        if p.poll() is not None or time.monotonic() - t > 30:
            return False
        time.sleep(0.002)
    time.sleep(delay)
    if p.poll() is not None:
        return False
    p.send_signal(getattr(signal, sig))
    return True


def test_an_update_on_the_real_entry_ends_0_and_says_it(tmp_path: Path) -> None:
    p, marks = start(tmp_path)
    code, out, err = ended(p)
    assert code == 0 and "update B0 applied, checked and audited" in out, (code, out, err[-2000:])
    assert marks.read_text(encoding="utf-8").split() == ["running", "preflight", "applied"]


@pytest.mark.parametrize("sig", ["SIGTERM", "SIGHUP", "SIGINT"])
def test_a_signal_before_the_runs_handlers_is_refused_and_said(tmp_path: Path, sig: str) -> None:
    """Window 1: a signal while main_apply asks whether the box runs (before Updater.run's Stops). Before: 143 or
    129 and no line (SIGINT: a traceback)."""
    p, marks = start(tmp_path, pause=0.3)
    assert at_mark(p, marks, "running", 0.05, sig)
    code, out, err = ended(p)
    assert code == 1 and "update REFUSED: stopped by " + sig in out and "nothing was changed" in out, (code, out, err)
    assert "Traceback" not in err and "preflight" not in marks.read_text(encoding="utf-8")


@pytest.mark.parametrize("sig", ["SIGTERM", "SIGHUP"])
def test_a_signal_on_the_way_out_keeps_the_updates_0_and_its_lines(tmp_path: Path, sig: str) -> None:
    """Window 2: after the run's Stops the defaults came back: a signal on the way out was 143 (129) in place of 0,
    and the lines still buffered were lost. Ignored to the exit now, flushed first."""
    p, _marks = start(tmp_path, last=sig)
    code, out, err = ended(p)
    assert code == 0 and "update B0 applied, checked and audited" in out, (code, out, err[-2000:])


@pytest.mark.parametrize("sig", ["SIGTERM", "SIGHUP"])
def test_a_refused_update_keeps_its_1_on_the_way_out(tmp_path: Path, sig: str) -> None:
    """Window 2 for a refusal: 1, never 143. The signal in the run's first step is said and refused; the second, on
    the way out, changes nothing."""
    p, marks = start(tmp_path, last=sig, pause=0.3)
    assert at_mark(p, marks, "preflight", 0.05, sig)
    code, out, err = ended(p)
    assert code == 1 and "before anything was changed; nothing was changed" in out, (code, out, err[-2000:])
