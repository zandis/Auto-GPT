"""H-97 (the integrator's ruling 7101844662; finding H96-09; H-94 (5), a secret read from or written to a place others
can read): the first-run wizard's one-time code never reaches the system journal or a file others can read.

``trialbox-firstrun.service`` runs ``deploy/box-install.sh --firstrun`` at a prepared box's first boot and sends its
stdout and stderr to the journal (``StandardOutput=journal+console``), and box-install.sh wrote the code to stdout and,
outside WSL2, to ``/etc/issue.d/trialbox-firstrun.issue``, which every local user reads. Now ``show_code`` writes it
to stdout only when stdout is a terminal, else to the controlling terminal (the Windows installer's window, a terminal
whose output is piped to a log), and with no terminal at all to the box's virtual console directly and to a root-only
file in the home the passwd entry names (0600, made new, a link refused). No variable of the caller decides where it
goes: the old knob ``TB_ISSUE_DIR`` and ``HOME`` are exported at other folders in every test here, and receive
nothing.

These tests run the real ``deploy/box-install.sh --firstrun`` (a box folder whose install is done), with the repository's
code linked, a stand-in ``getent`` naming the test's own passwd home, and the run's output kept in a file: the
journal stand-in. The codes are synthetic (``tools.box code`` makes a new one per run) and never printed here.
"""

from __future__ import annotations

import json
import os
import pty
import re
import select
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]
CODE_NAME = "trialbox-firstrun-code"
SCRIPT = ROOT / "deploy" / "box-install.sh"
# a root test host may write the virtual console (the box's screen); a non-root one (CI) cannot
CONSOLE = os.path.exists("/dev/tty0") and os.access("/dev/tty0", os.W_OK)


def _box(tmp: Path) -> dict[str, Path]:
    """A box whose install is done (box-install.sh's answers and hardware files), waiting for its first run."""
    box = tmp / "box"
    site = box / "deploy" / "site" / "box"
    site.mkdir(parents=True)
    shutil.copy2(SCRIPT, box / "deploy" / "box-install.sh")
    for name in ("libs", "services", "tools", "schemas"):
        (box / name).symlink_to(ROOT / name)
    (site / "answers.json").write_text(json.dumps({"tls_hostname": "box1.local", "tz": "Asia/Tokyo"}), "utf-8")
    (site / "hardware.json").write_text(json.dumps({"tpm": True}), encoding="utf-8")
    stubs = tmp / "stubs"
    stubs.mkdir()
    pw_home = tmp / "pwhome"
    pw_home.mkdir()
    (stubs / "getent").write_text(f'#!/bin/sh\necho "tester:x:$(id -u):$(id -g)::{pw_home}:/bin/sh"\n', "utf-8")
    (stubs / "getent").chmod(0o755)
    # the caller's own variables point elsewhere: the old knob at a folder every user reads, HOME at another
    issue = tmp / "issue.d"
    issue.mkdir(mode=0o755)
    (tmp / "callers-home").mkdir()
    return {"box": box, "fr": tmp / "firstrun", "code": pw_home / CODE_NAME, "pw_home": pw_home, "issue": issue,
            "stubs": stubs, "journal": tmp / "journal.log"}  # fmt: skip


def _env(tmp: Path, b: dict[str, Path], wsl2: str = "0") -> dict[str, str]:
    return {
        "PATH": f"{b['stubs']}{os.pathsep}{Path(sys.executable).parent}{os.pathsep}/usr/bin:/bin",
        "HOME": str(tmp / "callers-home"), "TB_ISSUE_DIR": str(b["issue"]), "TB_BOX_NO_ROOT": "1",
        "TB_BOX_PY": sys.executable, "TB_FIRSTRUN_HOST_DIR": str(b["fr"]), "TB_BOX_POLL_S": "0.2",
        "TB_SYSTEMD": "0", "TB_BOX_WSL2": wsl2,
    }  # fmt: skip


def _argv(b: dict[str, Path]) -> list[str]:
    return ["/bin/bash", str(b["box"] / "deploy" / "box-install.sh"), "--firstrun"]


def _as_the_service(tmp: Path, b: dict[str, Path], env: dict[str, str]) -> subprocess.Popen[bytes]:
    """As trialbox-firstrun.service runs it: a new session with no terminal, stdout and stderr to the journal."""
    journal = b["journal"].open("ab")
    try:
        return subprocess.Popen(_argv(b), cwd=tmp, env=env, stdin=subprocess.DEVNULL, stdout=journal,
                                stderr=subprocess.STDOUT, start_new_session=True)  # fmt: skip
    finally:
        journal.close()


def _code_in(path: Path, proc: subprocess.Popen[bytes], other_than: str = "", seconds: float = 60) -> str:
    """The code in the root-only file once it is there (a code other than ``other_than``)."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if path.is_file():
            m = re.search(r"One-time code:\s+(\S+)", path.read_text(encoding="utf-8"))
            if m and m.group(1) != other_than:
                return m.group(1)
        assert proc.poll() is None, "the first run ended before its code was kept"
        time.sleep(0.1)
    raise AssertionError(f"no code in {path}")


def _journal_says(b: dict[str, Path], text: str, proc: subprocess.Popen[bytes], seconds: float = 30) -> str:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        got = b["journal"].read_text(encoding="utf-8", errors="replace")
        if got.count(text) >= 1:
            return got
        assert proc.poll() is None, "the first run ended"
        time.sleep(0.1)
    raise AssertionError(f"the journal never said {text!r}")


def _stop(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=30)


def _nothing_elsewhere(tmp: Path, b: dict[str, Path]) -> None:
    assert list(b["issue"].iterdir()) == []  # the old knob names no place any more
    assert list((tmp / "callers-home").iterdir()) == []  # the caller's HOME is not where the file goes


def _private(path: Path) -> None:
    st = path.lstat()
    assert stat.S_ISREG(st.st_mode) and stat.S_IMODE(st.st_mode) == 0o600 and st.st_uid == os.geteuid()


@pytest.mark.parametrize("wsl2", ["0", "1"])
def test_the_code_never_reaches_the_journal_or_a_file_others_read(tmp_path: Path, wsl2: str) -> None:
    """THE RULE (ruling 7101844662): run as the boot's service runs it (no terminal; the journal stand-in keeps the
    output), on and off WSL2, the code is in the root-only file only: never in the journal, mode 0600, no copy where
    the caller's TB_ISSUE_DIR or HOME point. A voided code (five wrong codes) is replaced in the file, and neither the
    first nor the new code is in the journal; the journal names the file and how to read it."""
    b = _box(tmp_path)
    proc = _as_the_service(tmp_path, b, _env(tmp_path, b, wsl2))
    try:
        first = _code_in(b["code"], proc)
        journal = _journal_says(b, "the one-time code is not in this output", proc)
        assert first not in journal and "One-time code" not in journal
        _private(b["code"])
        assert f"in {b['code']} (root only, 0600)" in journal and f"sudo cat {b['code']}" in journal
        assert "open https://box1.local/login/first-run" in journal  # the address is no secret
        (b["fr"] / "code.json").unlink()  # tb_common.firstrun voids a code after five wrong ones
        second = _code_in(b["code"], proc, other_than=first)
        journal = _journal_says(b, "a new one", proc)
        _journal_says(b, "the one-time code is not in this output", proc)
        journal = b["journal"].read_text(encoding="utf-8", errors="replace")
        assert first not in journal and second not in journal
        _private(b["code"])
        assert first not in b["code"].read_text(encoding="utf-8")
    finally:
        _stop(proc)
    _nothing_elsewhere(tmp_path, b)


def _on_a_pty(
    tmp: Path, argv: list[str], env: dict[str, str], until: str, seconds: float = 60, log: Path | None = None
) -> str:
    """argv in a new session whose controlling terminal is a pty, until the terminal shows the pattern ``until`` (and
    ``log``, when given, says where the code was shown); what it showed."""
    pid, fd = pty.fork()
    if pid == 0:  # pragma: no cover - the child
        os.chdir(tmp)
        os.execve(argv[0], argv, env)
    out = b""
    deadline = time.monotonic() + seconds
    try:
        while time.monotonic() < deadline and not (
            re.search(until, out.decode("utf-8", "replace"))
            and (log is None or (log.is_file() and "shown on this terminal only" in log.read_text(encoding="utf-8")))
        ):
            ready, _, _ = select.select([fd], [], [], 1)
            if not ready:
                continue
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
    finally:
        os.kill(pid, 9)
        os.waitpid(pid, 0)
        os.close(fd)
    return out.decode("utf-8", "replace")


def test_at_a_terminal_the_code_is_shown_there_once_and_kept_nowhere(tmp_path: Path) -> None:
    """Typed at a terminal (hospital IT's line; over SSH with a terminal): stdout is the terminal, the code is on it
    once, and no file is made."""
    b = _box(tmp_path)
    screen = _on_a_pty(tmp_path, _argv(b), _env(tmp_path, b), r"One-time code:\s+\S+\r?\n")
    assert len(re.findall(r"One-time code:\s+\S+", screen)) == 1, screen[-800:]
    assert not b["code"].exists()
    _nothing_elsewhere(tmp_path, b)


def test_with_its_output_piped_to_a_log_the_code_goes_to_the_terminal_only(tmp_path: Path) -> None:
    """The Windows installer's window (wsl-setup.sh pipes the output through tee) or any terminal whose output a log
    keeps: the code is on the controlling terminal, never in the piped output, and no file is made."""
    b = _box(tmp_path)
    log = tmp_path / "piped.log"
    argv = ["/bin/bash", "-c", f'"$0" "$1" "$2" 2>&1 | tee "{log}" > /dev/null', *_argv(b)]
    screen = _on_a_pty(tmp_path, argv, _env(tmp_path, b, "1"), r"One-time code:\s+\S+\r?\n", log=log)
    piped = log.read_text(encoding="utf-8")
    m = re.search(r"One-time code:\s+(\S+)", screen)
    assert m and m.group(1) not in piped and "One-time code" not in piped
    assert "the one-time code is shown on this terminal only" in piped
    assert not b["code"].exists()
    _nothing_elsewhere(tmp_path, b)


def test_a_link_at_the_files_name_is_refused_and_never_followed(tmp_path: Path) -> None:
    """H-94 (5): a link planted at the file's name is not followed or written through; the code is in no output. With
    no screen to write either (a host that cannot write the virtual console) the first run stops and says why."""
    b = _box(tmp_path)
    victim = tmp_path / "victim"
    victim.write_text("kept\n", encoding="utf-8")
    victim.chmod(0o644)
    b["code"].symlink_to(victim)
    proc = _as_the_service(tmp_path, b, _env(tmp_path, b))
    try:
        if CONSOLE:  # the box's screen still shows it: the run waits for the owner
            journal = _journal_says(b, "it is on this box's screen only", proc)
        else:
            proc.wait(timeout=60)
            journal = b["journal"].read_text(encoding="utf-8", errors="replace")
            assert proc.returncode == 1 and "no terminal, no screen and no root-only file" in journal
    finally:
        _stop(proc)
    assert victim.read_text(encoding="utf-8") == "kept\n" and b["code"].is_symlink()
    assert "is a link or not a regular file" in journal and "H-94 (5)" in journal
    assert "One-time code" not in journal
    _nothing_elsewhere(tmp_path, b)


def test_the_screen_file_and_its_knob_are_gone() -> None:
    """No line of box-install.sh writes /etc/issue.d or reads TB_ISSUE_DIR (an earlier version's file is removed);
    the boot's unit sends no code anywhere; nothing else in deploy/ names the knob."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "TB_ISSUE_DIR" not in text
    issue_lines = [ln for ln in text.splitlines() if "/etc/issue.d" in ln and not ln.lstrip().startswith("#")]
    assert issue_lines == ["rm -f /etc/issue.d/trialbox-firstrun.issue 2>/dev/null || true  # H-97: an earlier "
                           "version's copy, readable by all"]  # fmt: skip
    unit = (ROOT / "deploy" / "systemd" / "trialbox-firstrun.service").read_text(encoding="utf-8")
    assert "issue.d" not in unit.split("[Unit]")[1]
    for path in (ROOT / "deploy").rglob("*"):
        if path.is_file() and path.suffix in {".sh", ".py", ".service", ".ps1", ""}:
            assert "TB_ISSUE_DIR" not in path.read_text(encoding="utf-8", errors="replace"), path


@pytest.mark.parametrize(("sig", "code"), [("SIGTERM", 143), ("SIGHUP", 129), ("SIGINT", 130)])
def test_a_first_run_stopped_while_it_waits_leaves_no_code_file(tmp_path: Path, sig: str, code: int) -> None:
    """The review of #1429, F10: the service stopped (SIGTERM), its terminal closed (SIGHUP) or the run interrupted
    (SIGINT) while it waits for the owner: the root-only file is removed on the way out, never left holding a code."""
    b = _box(tmp_path)
    proc = _as_the_service(tmp_path, b, _env(tmp_path, b))
    try:
        _code_in(b["code"], proc)
        proc.send_signal(getattr(__import__("signal"), sig))
        assert proc.wait(timeout=60) == code
    finally:
        _stop(proc)
    assert not b["code"].exists() and not b["code"].is_symlink()
    _nothing_elsewhere(tmp_path, b)


def test_a_terminal_that_hung_up_never_swallows_the_code(tmp_path: Path) -> None:
    """The review of #1429, F9: the run was started on a terminal under nohup with its output in a log, and the
    terminal hung up (an SSH session closed) before the code was shown: the write to the terminal fails, so the code
    goes to the screen and the root-only file, the log says where, and the code is never in the log."""
    b = _box(tmp_path)
    log = tmp_path / "nohup.log"
    argv = ["/bin/bash", "-c", f'trap "" HUP; echo ready; sleep 1; exec nohup "$0" "$1" "$2" > "{log}" 2>&1', *_argv(b)]
    pid, fd = pty.fork()
    if pid == 0:  # pragma: no cover - the child
        os.chdir(tmp_path)
        os.execve(argv[0], argv, _env(tmp_path, b))
    got = b""
    while b"ready" not in got:  # SIGHUP ignored from here on, as nohup does
        got += os.read(fd, 100)
    os.close(fd)  # the terminal hangs up before the run starts
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not (log.is_file() and "the one-time code is not in this output" in
                                                   log.read_text(encoding="utf-8", errors="replace")):  # fmt: skip
            time.sleep(0.1)
        said = log.read_text(encoding="utf-8", errors="replace")
        assert "the one-time code is not in this output" in said, said[-800:]
        assert "shown on this terminal only" not in said and "One-time code" not in said
        _private(b["code"])
        m = re.search(r"One-time code:\s+(\S+)", b["code"].read_text(encoding="utf-8"))
        assert m and m.group(1) not in said
    finally:
        os.kill(pid, 9)
        os.waitpid(pid, 0)
    _nothing_elsewhere(tmp_path, b)


#: on the pty: TOSTOP set, then the run in a process group of its own whose parent has exited (orphaned, in the
#: background): /dev/tty opens, and every write to it fails (EIO), as on a terminal the run can no longer write
_ORPHANED = """
import os, signal, sys, termios, time
log, pidfile, argv = sys.argv[1], sys.argv[2], sys.argv[3:]
# H-139: the write below fails (EIO) only while SIGTTOU has its default action; a caller that ignores it (the bench
# host's runner) let the write through and the code was taken as shown. Reset here, as on any host
signal.signal(signal.SIGTTOU, signal.SIG_DFL)
a = termios.tcgetattr(0)
a[3] |= termios.TOSTOP
termios.tcsetattr(0, termios.TCSANOW, a)
m = os.fork()
if m == 0:
    os.setpgid(0, 0)
    if os.fork() == 0:
        time.sleep(0.5)  # its parent has exited: the group is orphaned
        with open(pidfile, "w") as fh:
            fh.write(str(os.getpid()))
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.dup2(fd, 1)
        os.dup2(fd, 2)
        os.execv(argv[0], argv)
    os._exit(0)
os.waitpid(m, 0)
time.sleep(120)
"""


def test_a_terminal_write_that_fails_falls_through_to_the_screen_and_file(tmp_path: Path) -> None:
    """The review of #1429, F9: /dev/tty opens but the write fails (EIO): the code is not taken as shown. It goes to
    the screen and the root-only file, the output says where, and the code is never in the output."""
    b = _box(tmp_path)
    log, pidfile = tmp_path / "out.log", tmp_path / "run.pid"
    argv = [sys.executable, "-c", _ORPHANED, str(log), str(pidfile), *_argv(b)]
    pid, fd = pty.fork()
    if pid == 0:  # pragma: no cover - the child
        os.chdir(tmp_path)
        os.execve(argv[0], argv, _env(tmp_path, b))
    try:
        deadline = time.monotonic() + 60
        said = ""
        while time.monotonic() < deadline and "the one-time code is not in this output" not in said:
            ready, _, _ = select.select([fd], [], [], 0.2)
            if ready:  # the terminal is read, so it never fills
                with __import__("contextlib").suppress(OSError):
                    os.read(fd, 4096)
            said = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
        assert "the one-time code is not in this output" in said, said[-800:]
        assert "shown on this terminal only" not in said and "One-time code" not in said
        _private(b["code"])
        m = re.search(r"One-time code:\s+(\S+)", b["code"].read_text(encoding="utf-8"))
        assert m and m.group(1) not in said
    finally:
        if pidfile.is_file():
            with __import__("contextlib").suppress(ProcessLookupError):
                os.kill(int(pidfile.read_text()), 9)
        os.kill(pid, 9)
        os.waitpid(pid, 0)
        os.close(fd)
    _nothing_elsewhere(tmp_path, b)
