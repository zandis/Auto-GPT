"""H-96 (the integrator's 7097514776; H-94 (5), a secret where others can read it): the first administrator's password
and enrolment code are shown on a terminal once and are never written to a log.

box-install.sh runs install.sh with its output through ``tee deploy/site/box/install.log``, and the box rehearsal
keeps the installer's output as its step log: both held the generated password and the enrolment code, so anything
that read the log (a grep, a support bundle, a CI artifact) held them. Now install.sh's accounts step writes them to
stdout only when stdout is a terminal, else to the controlling terminal, and with no terminal at all to a root-only
file under root's home that the output names but never prints. These tests run the real accounts step of
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
    start = INSTALL.index("# ------------------------------------------------------------------------------------------------ 5. accounts")
    end = INSTALL.index("\n# NEW-STD-2 (D-562)", start) + 1
    return INSTALL[start:end]


def _bench(tmp: Path, enrol_rc: int = 0) -> tuple[Path, dict[str, str]]:
    (tmp / "deploy").mkdir()
    (tmp / "deploy" / ".env").write_text("TB_ENV=TEST\n", encoding="utf-8")
    fake = tmp / "compose"
    fake.write_text(COMPOSE, encoding="utf-8")
    fake.chmod(0o755)
    home = tmp / "home"
    home.mkdir()
    harness = tmp / "accounts.sh"
    harness.write_text(
        "set -euo pipefail\n"
        'say() { echo "==> $*"; }\n'
        "FAILS=()\n"
        f'COMPOSE=("{fake}")\n'
        + _accounts_step()
        + 'for f in "${FAILS[@]+"${FAILS[@]}"}"; do echo "FAIL: $f"; done\n',
        encoding="utf-8",
    )
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "FAKE_PASSWORD": PASSWORD, "FAKE_CODE": CODE,
           "FAKE_ENROL_RC": str(enrol_rc)}  # fmt: skip
    return harness, env


def _run_teed(tmp: Path, harness: Path, env: dict[str, str]) -> tuple[subprocess.CompletedProcess[str], str]:
    """As box-install.sh runs it: stdout and stderr through tee into an install log (no terminal on stdout)."""
    log = tmp / "install.log"
    r = subprocess.run(["bash", "-c", f'bash "{harness}" 2>&1 | tee "{log}"; exit "${{PIPESTATUS[0]}}"'],
                       cwd=tmp, env=env, capture_output=True, text=True, timeout=60, check=False)  # fmt: skip
    return r, log.read_text(encoding="utf-8")


def test_under_box_installs_tee_the_values_reach_the_terminal_and_not_the_install_log(tmp_path: Path) -> None:
    """THE LOG RULE: with stdout teed to a log (box-install.sh's install.log, a rehearsal's step log) and a terminal
    present, the password and the enrolment code are written to the terminal only: neither is in the log or the
    output, and the log says where they were shown."""
    harness, env = _bench(tmp_path)
    tty = tmp_path / "terminal"
    tty.write_text("", encoding="utf-8")
    r, log = _run_teed(tmp_path, harness, {**env, "TB_ONCE_TTY": str(tty)})
    assert r.returncode == 0, r.stdout + r.stderr
    for value in (PASSWORD, CODE):
        assert value not in log and value not in r.stdout + r.stderr
        assert value in tty.read_text(encoding="utf-8")
    assert "shown on this terminal only" in log
    assert "hand the enrolment code to the administrator in person" in tty.read_text(encoding="utf-8")
    assert not (tmp_path / "home" / ONCE_NAME).exists()


def test_with_no_terminal_the_values_go_to_a_root_only_file_that_the_output_names(tmp_path: Path) -> None:
    """No terminal at all (a rehearsal's docker exec, a service): a 0600 file under root's home, made fresh (a link
    already at its name is replaced, never followed); the output names the file and holds neither value."""
    harness, env = _bench(tmp_path)
    victim = tmp_path / "victim"
    victim.write_text("kept\n", encoding="utf-8")
    once = tmp_path / "home" / ONCE_NAME
    once.symlink_to(victim)
    r, log = _run_teed(tmp_path, harness, {**env, "TB_ONCE_TTY": str(tmp_path / "no-such-dir" / "tty")})
    assert r.returncode == 0, r.stdout + r.stderr
    assert victim.read_text(encoding="utf-8") == "kept\n"
    assert once.is_file() and not once.is_symlink()
    assert stat.S_IMODE(once.lstat().st_mode) == 0o600
    text = once.read_text(encoding="utf-8")
    for value in (PASSWORD, CODE):
        assert value in text and value not in log and value not in r.stdout + r.stderr
    assert f"no terminal to show it on: it is in {once}" in log and f"sudo rm {once}" in log


def test_on_a_terminal_the_operator_sees_both_values_on_stdout(tmp_path: Path) -> None:
    """The IT form run by hand: stdout is the terminal, so the values are shown there as before (once)."""
    harness, env = _bench(tmp_path)
    pid, fd = pty.fork()
    if pid == 0:  # pragma: no cover - the child
        os.chdir(tmp_path)
        os.execve("/bin/bash", ["bash", str(harness)], {**env, "TB_ONCE_TTY": str(tmp_path / "no-such-dir" / "tty")})
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
    text = out.decode("utf-8", "replace")
    assert os.waitstatus_to_exitcode(status) == 0, text
    assert text.count(PASSWORD) == 1 and text.count(CODE) == 1, text
    assert not (tmp_path / "home" / ONCE_NAME).exists()


@pytest.mark.parametrize("rc", [1, 2])
def test_no_code_or_a_failed_code_writes_nothing_of_it_to_the_log(tmp_path: Path, rc: int) -> None:
    """enrol-code exit 2 (an authenticator already) says so; any other failure is a FAIL line, and the command's own
    output goes to the terminal with the password, never to the log."""
    harness, env = _bench(tmp_path, enrol_rc=rc)
    tty = tmp_path / "terminal"
    tty.write_text("", encoding="utf-8")
    r, log = _run_teed(tmp_path, harness, {**env, "TB_ONCE_TTY": str(tty)})
    assert r.returncode == 0, r.stdout + r.stderr
    assert PASSWORD not in log and PASSWORD in tty.read_text(encoding="utf-8")
    if rc == 2:
        assert "admin has an authenticator already" in log
    else:
        assert "FAIL: no enrolment code for admin" in log
        assert "synthetic error" not in log and "synthetic error" in tty.read_text(encoding="utf-8")


def test_the_box_form_tees_the_install_and_the_unattended_form_makes_the_administrator() -> None:
    """The path the rule closes: box-install.sh tees install.sh's output to deploy/site/box/install.log, and its
    unattended form (an owner's answers file) runs install.sh with TB_BOX=0, which makes the administrator."""
    assert '2>&1 | tee "$BOX/install.log"' in BOX_INSTALL
    assert 'INBOX=1; [ -z "$OWNER" ] || INBOX=0' in BOX_INSTALL
    step = _accounts_step()
    assert step.count("| show_once") == 1 and "show_once() {" in step
    assert 'echo "$ENROL"' not in step  # the code is never echoed to the output
