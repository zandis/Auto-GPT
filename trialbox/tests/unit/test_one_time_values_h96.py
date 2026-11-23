"""H-96 (the integrator's 7097514776; H-94 (5), a secret where others can read it): the first administrator's password
and enrolment code are shown on a terminal once and are never written to a log.

box-install.sh runs install.sh with its output through ``tee deploy/site/box/install.log``, and the box rehearsal
keeps the installer's output as its step log: both held the generated password and the enrolment code, so anything
that read the log (a grep, a support bundle, a CI artifact) held them. Now install.sh's accounts step writes them to
stdout only when stdout is a terminal, else to the controlling terminal, and with no terminal at all to a root-only
file in the home its passwd entry names, which the output names but never prints. No variable of the caller
(HOME, a knob) decides where they go. These tests run the real accounts step of
install.sh (cut from the file) with a stand-in ``docker compose`` that prints synthetic values the way console.cli
prints them; the box rehearsal (tools/rehearse_box/box.sh) checks the same on the real path.
"""

from __future__ import annotations

import os
import pty
import select
import stat
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]
INSTALL = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
BOX_INSTALL = (ROOT / "deploy" / "box-install.sh").read_text(encoding="utf-8")
PASSWORD = "synthetic-h96-first-password-for-tests"  # synthetic; console.cli makes the real one
CODE = "SYNTH-H96-ENROL-CODE"  # synthetic
ONCE_NAME = "trialbox-admin-first-sign-in"

COMPOSE = """#!/usr/bin/env bash
case "$*" in
  *bootstrap-admin*)
    echo "console: administrator 'admin' created"
    echo "console: password (shown once): $FAKE_PASSWORD" ;;
  *enrol-code*)
    if [ "${FAKE_ENROL_RC:-0}" = 0 ]; then
      echo "Use this code at /enrol to choose your password."
      echo "console: enrolment code for 'admin' (shown once, valid 24 hours): $FAKE_CODE"
    else
      echo "console: enrol-code failed: synthetic error"
    fi
    exit "${FAKE_ENROL_RC:-0}" ;;
esac
"""


def _accounts_step() -> str:
    start = INSTALL.index(
        "# ------------------------------------------------------------------------------------------------ 5. accounts"
    )
    end = INSTALL.index("\n# NEW-STD-2 (D-562)", start) + 1
    return INSTALL[start:end]


GETENT = """#!/bin/sh
# a stand-in getent: the passwd entry of the user that runs it, with the test's home (PATH is the bench's own)
echo "tester:x:$(id -u):$(id -g)::$FAKE_PW_HOME:/bin/sh"
"""


def _bench(tmp: Path, enrol_rc: int = 0) -> tuple[Path, dict[str, str]]:
    (tmp / "deploy").mkdir()
    (tmp / "deploy" / ".env").write_text("TB_ENV=TEST\n", encoding="utf-8")
    (tmp / "bin").mkdir()
    for name, text in (("compose", COMPOSE), ("getent", GETENT)):
        (tmp / "bin" / name).write_text(text, encoding="utf-8")
        (tmp / "bin" / name).chmod(0o755)
    (tmp / "pwhome").mkdir()
    (tmp / "callers-home").mkdir()
    exposed = tmp / "world-readable"
    exposed.write_text("", encoding="utf-8")
    exposed.chmod(0o644)
    harness = tmp / "accounts.sh"
    harness.write_text(
        "set -euo pipefail\n"
        'say() { echo "==> $*"; }\n'
        "FAILS=()\n"
        f'COMPOSE=("{tmp / "bin" / "compose"}")\n'
        + _accounts_step()
        + 'for f in "${FAILS[@]+"${FAILS[@]}"}"; do echo "FAIL: $f"; done\n',
        encoding="utf-8",
    )
    # the caller's own variables point elsewhere: an exported TB_ONCE_TTY at a world-readable file, HOME at another
    # folder; neither may decide where a value is written
    env = {"PATH": f"{tmp / 'bin'}:{os.environ['PATH']}", "HOME": str(tmp / "callers-home"),
           "TB_ONCE_TTY": str(exposed), "FAKE_PW_HOME": str(tmp / "pwhome"), "FAKE_PASSWORD": PASSWORD,
           "FAKE_CODE": CODE, "FAKE_ENROL_RC": str(enrol_rc)}  # fmt: skip
    return harness, env


def _on_a_pty(tmp: Path, argv: list[str], env: dict[str, str]) -> tuple[int, str]:
    """argv in a new session whose controlling terminal is a pty; what the terminal showed."""
    pid, fd = pty.fork()
    if pid == 0:  # pragma: no cover - the child
        os.chdir(tmp)
        os.execve(argv[0], argv, env)
    out = b""
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
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
    _, status = os.waitpid(pid, 0)
    os.close(fd)
    return os.waitstatus_to_exitcode(status), out.decode("utf-8", "replace")


def _teed_on_a_terminal(tmp: Path, harness: Path, env: dict[str, str]) -> tuple[int, str, str]:
    """As box-install.sh runs it from a terminal: stdout and stderr through tee into an install log."""
    log = tmp / "install.log"
    rc, screen = _on_a_pty(
        tmp, ["/bin/bash", "-c", f'bash "{harness}" 2>&1 | tee "{log}" >/dev/null; exit "${{PIPESTATUS[0]}}"'], env
    )
    return rc, screen, log.read_text(encoding="utf-8")


def _teed_without_a_terminal(tmp: Path, harness: Path, env: dict[str, str]) -> tuple[int, str]:
    """No controlling terminal at all (a new session, as a rehearsal's docker exec without -t or a driver)."""
    log = tmp / "install.log"
    r = subprocess.run(["bash", "-c", f'bash "{harness}" 2>&1 | tee "{log}"; exit "${{PIPESTATUS[0]}}"'], cwd=tmp,
                       env=env, capture_output=True, text=True, timeout=60, check=False, start_new_session=True)  # fmt: skip
    return r.returncode, log.read_text(encoding="utf-8") + r.stdout + r.stderr


def _nothing_elsewhere(tmp: Path) -> None:
    assert (tmp / "world-readable").read_text(encoding="utf-8") == ""  # the exported TB_ONCE_TTY is ignored
    assert list((tmp / "callers-home").iterdir()) == []  # the caller's HOME is not where the file goes


def test_under_box_installs_tee_the_values_reach_the_terminal_and_not_the_install_log(tmp_path: Path) -> None:
    """THE LOG RULE: with stdout teed to a log (box-install.sh's install.log) and a controlling terminal, the password
    and the enrolment code are written to the terminal only: neither is in the log, the log says where they were
    shown, and a caller's exported TB_ONCE_TTY (a world-readable file) receives nothing."""
    harness, env = _bench(tmp_path)
    rc, screen, log = _teed_on_a_terminal(tmp_path, harness, env)
    assert rc == 0, screen
    for value in (PASSWORD, CODE):
        assert value not in log and screen.count(value) == 1
    assert "shown on this terminal only" in log
    assert "hand the enrolment code to the administrator in person" in screen
    assert not (tmp_path / "pwhome" / ONCE_NAME).exists()
    _nothing_elsewhere(tmp_path)


def test_with_no_terminal_the_values_go_to_a_root_only_file_in_the_passwd_home(tmp_path: Path) -> None:
    """No terminal at all: a new 0600 file in the home the passwd entry names (not the caller's HOME); the output
    names the file and holds neither value; an old regular file there is replaced."""
    harness, env = _bench(tmp_path)
    once = tmp_path / "pwhome" / ONCE_NAME
    once.write_text("an old run's\n", encoding="utf-8")
    once.chmod(0o644)
    rc, out = _teed_without_a_terminal(tmp_path, harness, env)
    assert rc == 0, out
    assert once.is_file() and not once.is_symlink() and stat.S_IMODE(once.lstat().st_mode) == 0o600
    text = once.read_text(encoding="utf-8")
    assert "an old run's" not in text
    for value in (PASSWORD, CODE):
        assert value in text and value not in out
    assert f"no terminal to show it on: it is in {once}" in out and f"sudo rm {once}" in out
    _nothing_elsewhere(tmp_path)


def test_with_no_terminal_a_link_at_the_files_name_is_refused(tmp_path: Path) -> None:
    """A link at the file's name is never followed or replaced: nothing is written, the values are in no output, and
    a FAIL line says how to get new ones."""
    harness, env = _bench(tmp_path)
    victim = tmp_path / "victim"
    victim.write_text("kept\n", encoding="utf-8")
    once = tmp_path / "pwhome" / ONCE_NAME
    once.symlink_to(victim)
    rc, out = _teed_without_a_terminal(tmp_path, harness, env)
    assert rc == 0, out
    assert victim.read_text(encoding="utf-8") == "kept\n" and once.is_symlink()
    assert PASSWORD not in out and CODE not in out
    assert "FAIL: no terminal, and" in out and "is a link or not a regular file" in out
    _nothing_elsewhere(tmp_path)


def test_on_a_terminal_the_operator_sees_both_values_on_stdout(tmp_path: Path) -> None:
    """The IT form run by hand: stdout is the terminal, so the values are shown there (once)."""
    harness, env = _bench(tmp_path)
    rc, screen = _on_a_pty(tmp_path, ["/bin/bash", str(harness)], env)
    assert rc == 0, screen
    assert screen.count(PASSWORD) == 1 and screen.count(CODE) == 1, screen
    assert not (tmp_path / "pwhome" / ONCE_NAME).exists()
    _nothing_elsewhere(tmp_path)


@pytest.mark.parametrize("rc", [1, 2])
def test_no_code_or_a_failed_code_writes_nothing_of_it_to_the_log(tmp_path: Path, rc: int) -> None:
    """enrol-code exit 2 (an authenticator already) says so; any other failure is a FAIL line, and the command's own
    output goes to the terminal with the password, never to the log."""
    harness, env = _bench(tmp_path, enrol_rc=rc)
    code, screen, log = _teed_on_a_terminal(tmp_path, harness, env)
    assert code == 0, screen
    assert PASSWORD not in log and PASSWORD in screen
    if rc == 2:
        assert "admin has an authenticator already" in log
    else:
        assert "FAIL: no enrolment code for admin" in log
        assert "synthetic error" not in log and "synthetic error" in screen


def test_the_box_form_tees_the_install_and_no_caller_variable_names_the_place() -> None:
    """The path the rule closes: box-install.sh tees install.sh's output to deploy/site/box/install.log, and its
    unattended form (an owner's answers file) runs install.sh with TB_BOX=0, which makes the administrator. The step
    reads no knob and no HOME to choose where a value goes."""
    assert '2>&1 | tee "$BOX/install.log"' in BOX_INSTALL
    assert 'INBOX=1; [ -z "$OWNER" ] || INBOX=0' in BOX_INSTALL
    step = _accounts_step()
    assert step.count('show_once "$(') == 1 and "show_once() {" in step
    assert 'echo "$ENROL"' not in step  # the code is never echoed to the output
    assert "TB_ONCE" not in step and "$HOME" not in step and "${HOME" not in step
