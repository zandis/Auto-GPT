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

import pytest

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
    real = br.BoxRestore.restore

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


def start_entry(
    tmp_path: Path, body: str, deploy: Path, last: str = "", *more: str, ignored: str = ""
) -> subprocess.Popen[str]:
    """The entry as a script (``trialbox restore <file> --key <key> --yes --restart``) with the restore ``body``;
    ``last``: a signal on its way out; ``ignored``: a signal its caller ignores (``nohup``)."""
    child = tmp_path / "child.py"
    child.write_text(CHILD.format(body=textwrap.indent(textwrap.dedent(body).strip("\n"), "    ")), encoding="utf-8")
    argv = [sys.executable, str(child), str(ROOT), str(ENTRY), "restore", str(tmp_path / "nas" / BACKUP), "--key",
            str(tmp_path / "usb" / "backup.key"), "--yes", "--restart", "--deploy", str(deploy), *more]  # fmt: skip
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "H142_LAST": last}
    if ignored:  # nohup: the command starts with SIGHUP ignored
        assert ignored == "SIGHUP"
        argv = ["nohup", *argv]
    return subprocess.Popen(argv, cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def ended(p: subprocess.Popen[str]) -> tuple[int, str, str]:
    """The exit code as a shell reads it (a signal's death: 128 + its number), stdout and stderr."""
    out, err = p.communicate(timeout=60)
    code = p.returncode
    return (128 - code if code < 0 else code), out, err


def run_entry(tmp_path: Path, body: str, last: str = "", first: str = "") -> tuple[int, str, str]:
    """The entry with the stand-in restore ``body``; ``first``: a signal once it says ``ready``."""
    p = start_entry(tmp_path, body, _box(tmp_path), last)
    assert p.stdout is not None
    if first:
        line = p.stdout.readline()  # the first signal once the handlers are in, never after a fixed sleep
        assert line == "ready\n", (line, p.communicate(timeout=30))
        p.send_signal(getattr(signal, first))
    return ended(p)


def test_the_entry_keeps_the_said_130_when_the_walks_second_signal_lands_on_its_way_out(tmp_path: Path) -> None:
    """H-138 on the real entry: the restore said its interrupt (130) and put its handlers back; the second SIGTERM
    arrives after ``main`` returned. Without the entry's own ``_exit_code`` call: 143."""
    code, _out, err = run_entry(tmp_path, SAID_INTERRUPT, last="SIGTERM", first="SIGTERM")
    assert code == 130, (code, err[-2000:])


# ------------------------------------------------------------------------------------------------ the stand-in box
#: The box's engine and compose, stood in for by one script (``TB_DOCKER`` of the box file): compose answers from a
#: state folder, and ``run`` is the restore's container. Each step it reaches writes its mark (``marks``) and then
#: waits ``PAUSE`` s, the window a sweep's signal lands in. The container's start is the python's start: until it
#: takes its own handlers (``started``), a signal is the default's death, as a real one's is.
STANDIN = r"""
import json, os, signal, sys, time
state, args = sys.argv[1], sys.argv[2:]
cfg = json.load(open(os.path.join(state, "cfg.json")))
ALL = ["caddy", "console", "db", "orchestrator"]

def mark(name):
    with open(os.path.join(state, "marks"), "a") as fh:
        fh.write(name + "\n")
    time.sleep(cfg.get("pause", 0.15))

def running():
    try:
        return open(os.path.join(state, "running")).read().split()
    except OSError:
        return list(ALL)

def runs(names):
    open(os.path.join(state, "running"), "w").write("\n".join(names))

if args[0] == "compose":
    rest = args[args.index("--project-directory") + 2:] if "--project-directory" in args else args[1:]
    cmd = rest[0]
    if cmd == "ps":
        mark("ps")
        fmt = "--format" in rest
        print("\n".join(f"{s} healthy" if fmt else s for s in running()))
    elif cmd == "stop":
        mark("stop")
        runs(["db"])
    elif cmd == "up":
        mark("up")
        runs(ALL)
    elif cmd == "config":
        print("\n".join(ALL) if "--services" in rest else json.dumps({"services": {s: {} for s in ALL}}))
    elif cmd == "exec" and "psql" in rest:
        mark("db-size")
        print(1000)
    else:  # the orchestrator's audit: down, so the host keeps the event in its pending file
        sys.exit(1)
    sys.exit(0)

if args[0] in ("volume", "container"):  # H-132: no such volume or container here (the box file's folder is used)
    sys.exit(1)

# run: the restore's container
mark("container")
got = []
for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    signal.signal(s, lambda n, f: got.append(n))
mark("started")
if got or cfg.get("container") == "unchanged":
    print(json.dumps({"ok": False, "state": "unchanged"}))
    sys.exit(1)
mark("change")
if got:
    mark("put-back")
    print(json.dumps({"ok": False, "state": "rolled_back"}))
    sys.exit(1)
print(json.dumps({"ok": True, "state": "restored", "hold": "released", "refdata": {"missing": []}}))
sys.exit(0)
"""

#: the real restore of the host (the stand-in is the box's engine and compose only)
REAL = """
    return real(self, a)
"""


def stand_in_box(tmp_path: Path, **cfg: object) -> tuple[Path, Path]:
    """A box folder whose engine is the stand-in, and the stand-in's state folder."""
    import json

    deploy = _box(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    (state / "cfg.json").write_text(json.dumps(cfg), encoding="utf-8")
    script = tmp_path / "standin.py"
    script.write_text(STANDIN, encoding="utf-8")
    with (deploy / ".env").open("a", encoding="utf-8") as fh:
        fh.write(f"TB_DOCKER={sys.executable} {script} {state}\n")
    return deploy, state


def marks(state: Path) -> list[str]:
    try:
        return (state / "marks").read_text(encoding="utf-8").split()
    except OSError:
        return []


def at_mark(p: subprocess.Popen[str], state: Path, mark: str, delay: float, sig: str, n: int = 1) -> bool:
    """``sig`` sent ``delay`` s after the stand-in's ``n``-th ``mark``; False: the run ended before it."""
    import time

    t = time.monotonic()
    while marks(state).count(mark) < n:
        if p.poll() is not None or time.monotonic() - t > 30:
            return False
        time.sleep(0.002)
    time.sleep(delay)
    if p.poll() is not None:
        return False
    p.send_signal(getattr(signal, sig))
    return True


def test_a_complete_restore_on_the_real_entry_ends_0_and_says_its_state(tmp_path: Path) -> None:
    """The stand-in's whole run, no signal: 0, the services healthy, the state line said."""
    deploy, state = stand_in_box(tmp_path, pause=0)
    code, _out, err = ended(start_entry(tmp_path, REAL, deploy))
    assert code == 0 and "are healthy: 4 of 4" in err and "restore: the box now:" in err, (code, err[-3000:])
    assert marks(state)[:5] == ["db-size", "db-size", "ps", "stop", "ps"] and "up" in marks(state), marks(state)


# ------------------------------------------------------------------------------------------------ H138-02, .a, .b
@pytest.mark.parametrize("sig", ["SIGTERM", "SIGHUP"])
def test_a_signal_in_the_space_check_ends_130_and_says_nothing_was_changed(tmp_path: Path, sig: str) -> None:
    """.a: the handlers are taken at the top of restore(), before the lock, the key, the hash and the space check.
    Before: the default's death (143, 129) with no line, and a deploy/.restore-* folder left."""
    deploy, state = stand_in_box(tmp_path)
    p = start_entry(tmp_path, REAL, deploy)
    assert at_mark(p, state, "db-size", 0.05, sig)
    code, _out, err = ended(p)
    assert code == 130 and "nothing was changed" in err and "restore: the box now:" in err, (code, err[-3000:])
    assert "stop" not in marks(state) and not list(deploy.glob(".restore-*"))
    assert "backup.restore_failed" in (deploy / "site" / "backup-audit-pending.jsonl").read_text(encoding="utf-8")


@pytest.mark.parametrize(("container", "want"), [("restored", 0), ("unchanged", 1)])
@pytest.mark.parametrize("sig", ["SIGTERM", "SIGHUP"])
def test_a_signal_on_the_way_out_keeps_the_said_end_for_every_code(
    tmp_path: Path, container: str, want: int, sig: str
) -> None:
    """H138-02, .b: after the state line the signals stay ignored to the exit, whatever the code (#1496 kept 130
    only). Before: 143 or 129 in place of the 0 or 1 the restore said."""
    deploy, _state = stand_in_box(tmp_path, pause=0, container=container)
    code, _out, err = ended(start_entry(tmp_path, REAL, deploy, sig))
    assert code == want and "restore: the box now:" in err, (code, err[-3000:])


def test_a_signal_the_caller_ignored_stays_ignored(tmp_path: Path) -> None:
    """.j: ``nohup trialbox restore ...``: SIGHUP ignored when the command starts stays ignored, as update.Stops
    keeps it. Before: the restore took SIGHUP and stopped on it."""
    deploy, state = stand_in_box(tmp_path)
    p = start_entry(tmp_path, REAL, deploy, ignored="SIGHUP")
    assert at_mark(p, state, "stop", 0.05, "SIGHUP")
    code, _out, err = ended(p)
    assert code == 0 and "are healthy: 4 of 4" in err, (code, err[-3000:])


# ------------------------------------------------------------------------------------------------ .c to .g
def test_an_engine_client_that_died_of_the_signal_is_a_container_that_did_not_run(tmp_path: Path) -> None:
    """.c: the first signal reaches the engine client before it took its own handlers (the container never ran):
    said, 130, the services this run stopped started again. Before: its raw code (241 for -15) and NOT as it was."""
    deploy, state = stand_in_box(tmp_path)
    p = start_entry(tmp_path, REAL, deploy)
    assert at_mark(p, state, "container", 0.03, "SIGTERM")
    code, _out, err = ended(p)
    assert code == 130 and "the restore's container did not run" in err and "NOT as it was" not in err, (code, err)
    assert "restore: the box now:" in err and "started" not in marks(state) and "up" in marks(state), marks(state)


#: the restore's container (the real entry's module form, as the backup image runs it) with its unpack stood in:
#: the restore's first step marks and waits there
INSIDE = textwrap.dedent(
    """
    import os, runpy, sys, time
    root, mark = sys.argv[1], sys.argv[2]
    sys.path[:0] = [root, os.path.join(root, "libs"), os.path.join(root, "services")]
    from tools.trialbox import backup as bk

    def unpack(*a, **kw):
        open(mark, "w").write("unpack")
        time.sleep(5)
        raise SystemExit("the stand-in's unpack was not stopped")

    bk.unpack = unpack
    sys.argv = ["trialbox", *sys.argv[3:]]
    runpy.run_module("tools.trialbox", run_name="__main__", alter_sys=True)
    """
)


@pytest.mark.parametrize("sig", ["SIGTERM", "SIGHUP", "SIGINT"])
def test_a_signal_inside_the_container_before_its_first_change_is_a_refusal(tmp_path: Path, sig: str) -> None:
    """.d: backup.restore takes raising handlers (SIGINT too) at its start; one before the first change ends as a
    refusal: ``state: unchanged``, exit 1, "nothing was changed". Before: the signal was the default's (PID 1 in the
    container drops SIGTERM and SIGHUP and the restore ran on: 0 "healthy" after "told"; here, not PID 1, its death),
    and Ctrl-C a traceback."""
    import json
    import time

    child = tmp_path / "inside.py"
    child.write_text(INSIDE, encoding="utf-8")
    mark = tmp_path / "mark"
    f = tmp_path / BACKUP
    f.write_bytes(b"synthetic")
    argv = [sys.executable, str(child), str(ROOT), str(mark), "restore", str(f), "--key", str(f), "--yes",
            "--services-stopped", "--no-copy", "--dir", f"audit={tmp_path / 'audit'}"]  # fmt: skip
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "TB_DB_URL": "postgresql://x@127.0.0.1:1/x"}
    p = subprocess.Popen(argv, cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    t = time.monotonic()
    while not mark.exists() and p.poll() is None and time.monotonic() - t < 30:
        time.sleep(0.01)
    p.send_signal(getattr(signal, sig))
    code, out, err = ended(p)
    assert code == 1 and json.loads(out) == {"ok": False, "state": "unchanged"}, (code, out, err[-2000:])
    assert "before any change: nothing was changed" in err and "Traceback" not in err, err[-2000:]


CHUNKS = r"""
import signal, sys, time
got = []
signal.signal(signal.SIGTERM, lambda s, f: got.append(s))
sys.stdout.write('{"ok": false, ')
sys.stdout.flush()
open(sys.argv[1], "w").write("half")
t = time.time()
while not got and time.time() - t < 10:
    time.sleep(0.01)
sys.stdout.write('"state": "rolled_back"}\n')
sys.exit(1)
"""


def test_an_interrupt_in_the_wait_loses_none_of_the_containers_result(tmp_path: Path) -> None:
    """.e: the interrupt cut the read of the container's output and the wait, re-entered, read only what came after
    it: the restore's JSON was lost. Its stdout is a file now, and the wait loses nothing."""
    import threading
    import time

    from tools.trialbox import box_restore

    mark, script = tmp_path / "half", tmp_path / "chunks.py"
    script.write_text(CHUNKS, encoding="utf-8")

    def fire() -> None:
        while not mark.exists():
            time.sleep(0.01)
        time.sleep(0.1)
        os.kill(os.getpid(), signal.SIGTERM)

    back = box_restore._host_signals()
    try:
        threading.Thread(target=fire, daemon=True).start()
        code, out = box_restore._call([sys.executable, str(script), str(mark)], {}, dict(os.environ))
    finally:
        back()
    assert code == 1 and box_restore._said(out) == {"ok": False, "state": "rolled_back"}, out


def test_a_signal_after_the_container_ended_is_not_passed_on_and_says_so(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """.e: the container had ended when the signal came: nothing is sent, and the line says so (never "the restore
    is told and puts the box back")."""
    from tools.trialbox import box_restore

    sent: list[int] = []

    class Ended:
        def __init__(self, *a: object, **kw: object) -> None:
            self.returncode: int | None = None
            self.n = 0

        def communicate(self) -> tuple[str | None, None]:
            self.n += 1
            if self.n == 1:
                self.returncode = 0  # it ended just before the interrupt
                raise box_restore.HostInterrupted("signal SIGTERM")
            return '{"ok": true, "state": "restored"}', None

        def send_signal(self, sig: int) -> None:  # as Popen's: never to a process that has ended
            if self.returncode is None:
                sent.append(sig)

    monkeypatch.setattr(subprocess, "Popen", Ended)
    code, out = box_restore._call(["docker", "run"], {}, {"PATH": "/usr/bin"})
    err = capsys.readouterr().err
    assert code == 0 and not sent and "had ended (0) when the signal came" in err and "is told" not in err, err
    assert '"restored"' in out


def test_a_signal_in_a_clean_up_is_taken_after_it_and_said(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """.f: the signal that came while the work folder was being removed (a ``finally``) cut the removal short and no
    handler took it: a traceback, exit 1, no line, the services stopped. It waits for the clean-up now and the one
    outer handler says the state: 130."""
    import shutil
    from typing import Any

    from tests.unit.test_restore_from_the_host_h100 import Recorder, _restore

    deploy = _box(tmp_path)
    real: Any = shutil.rmtree

    def rmtree(path: Any, *a: Any, **kw: Any) -> None:
        if ".restore-" in str(path):
            os.kill(os.getpid(), signal.SIGTERM)
        real(path, *a, **kw)

    monkeypatch.setattr(shutil, "rmtree", rmtree)  # the restore's shutil is this one
    try:
        code: object = _restore(deploy, tmp_path, monkeypatch, Recorder(running=["db", "console"]), "{}", 0,
                                "--restart")[0]  # fmt: skip
    except BaseException as e:  # escaped the command: nothing said
        code = e
    err = capsys.readouterr().err
    assert code == 130 and "restore: the box now:" in err and "ended 0" in err, (code, err[-2000:])
    assert not list(deploy.glob(".restore-*"))


def test_a_closed_terminal_after_the_signal_breaks_no_line_and_the_host_waits(tmp_path: Path) -> None:
    """.g: the session closed (its pipes gone, then SIGHUP): every print raised, the host left without waiting for
    the container and ended 120. Its streams are tolerant from the first signal: it waits, and ends 130."""
    deploy, state = stand_in_box(tmp_path, pause=0.3)
    p = start_entry(tmp_path, REAL, deploy)
    assert p.stdout is not None and p.stderr is not None
    assert at_mark(p, state, "change", 0.05, "SIGCONT")  # the container is changing the box, its handlers in
    p.stdout.close()
    p.stderr.close()
    p.send_signal(signal.SIGHUP)
    code = p.wait(timeout=60)
    assert code == 130 and "put-back" in marks(state), (code, marks(state))


# ------------------------------------------------------------------------------------------------ THE INVARIANT
#: the stand-in's marks, in the order a restore reaches them: the space check, the stop, the container's start,
#: its handlers, its change, the services' start, the health check
PHASES = [("db-size", 1), ("stop", 1), ("container", 1), ("started", 1), ("change", 1), ("up", 1), ("ps", 4)]
DELAYS = (0.0, 0.07, 0.2)  # inside the stand-in's step (it waits 0.15 s at each mark), and past it into the host's


@pytest.mark.parametrize("sig", ["SIGTERM", "SIGINT", "SIGHUP"])
@pytest.mark.parametrize(("phase", "n"), PHASES)
def test_a_signal_at_any_phase_ends_0_1_or_130_and_says_the_state(tmp_path: Path, phase: str, n: int, sig: str) -> None:
    """THE INVARIANT (H-142): the real entry, the stand-in's engine and compose; a real signal at each phase mark and
    swept delay, the walk's second SIGTERM 30 ms after it and a third on the way out. Every run ends 0, 1 or 130,
    says ``restore: the box now:``, never a traceback, never "healthy" on data it changed and did not finish, and
    leaves no scratch
    folder it did not name. The mutants (each fix taken out) it catches are named on the card's page."""
    import time

    for i, delay in enumerate(DELAYS):
        run = tmp_path / str(i)
        run.mkdir()
        deploy, state = stand_in_box(run)
        p = start_entry(run, REAL, deploy, "SIGTERM")
        sent = at_mark(p, state, phase, delay, sig, n)
        if sent:
            time.sleep(0.03)
            if p.poll() is None:
                p.send_signal(signal.SIGTERM)
        code, _out, err = ended(p)
        where = (phase, delay, sig, code, marks(state), err[-2500:])
        assert code in (0, 1, 130), where
        assert "restore: the box now:" in err and "Traceback" not in err, where
        # "healthy" only after a complete restore, or a refused one whose data is as it was (LR-14)
        assert code == 0 or "are healthy" not in err or "the data not changed" in err, where
        assert "is kept" in err or not list(deploy.glob(".restore-*")), where


def test_a_signal_after_the_state_line_changes_neither_the_line_nor_the_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """H138-02, .b: the state line is the restore's end. A signal after it (here, while the hold is said) changes
    neither what it said nor its exit code. Before: a second line ("this step was interrupted after it") and 130 in
    place of the complete restore's 0."""
    import json

    from tests.unit.test_restore_from_the_host_h100 import Recorder, _restore
    from tools.trialbox import box_restore

    deploy = _box(tmp_path)
    real = box_restore.BoxRestore._hold_line

    def hold_line(hold: str, state: str) -> None:
        os.kill(os.getpid(), signal.SIGTERM)
        real(hold, state)

    monkeypatch.setattr(box_restore.BoxRestore, "_hold_line", staticmethod(hold_line))
    code, _seen = _restore(deploy, tmp_path, monkeypatch, Recorder(running=["db", "console"]),
                           json.dumps({"hold": "released"}), 0, "--restart")  # fmt: skip
    err = capsys.readouterr().err
    assert code == 0 and err.count("restore: the box now:") == 1 and "are healthy" in err, (code, err[-2000:])


@pytest.mark.parametrize("where", ["the stop fails", "the container call fails"])
def test_a_signal_while_a_failure_is_said_ends_130(
    where: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """OCR 1496-2 (#1496's review): a signal that cut the state line short ("not asked (interrupted again)") while a
    failure was said ended 1, the failure's code, as _after already did not; it ends 130 on every path. OCR's test."""
    from typing import Any

    from tests.unit.test_restore_from_the_host_h100 import Recorder, _stand_in
    from tools.trialbox import __main__ as cli
    from tools.trialbox import box_restore, update

    failed: list[bool] = []

    class SignalWhileSaid(Recorder):
        def __call__(self, argv: list[str], **kw: object) -> str:
            if "ps" in argv and failed:  # the state line asks compose: the signal lands here
                raise box_restore.HostInterrupted("signal SIGTERM")
            if "stop" in argv and where == "the stop fails":
                failed.append(True)
                raise update.UpdateFailed("compose stop ... exit 1: synthetic")
            return super().__call__(argv, **kw)

    def call(argv: list[str], values: dict[str, str], base: Any = None) -> tuple[int, str]:
        failed.append(True)
        raise ValueError("synthetic failure of the container call")

    deploy = _box(tmp_path)
    _stand_in(monkeypatch, SignalWhileSaid(running=["db", "console"]))
    monkeypatch.setattr(box_restore, "_call", call)
    argv = ["restore", str(tmp_path / "nas" / BACKUP), "--key", str(tmp_path / "usb" / "backup.key"), "--yes",
            "--restart", "--deploy", str(deploy)]  # fmt: skip
    code = cli.main(argv, installed=True)
    assert "not asked (interrupted again)" in capsys.readouterr().err
    assert code == 130
