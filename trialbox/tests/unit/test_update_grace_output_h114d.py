"""H-114d (the review of #1472, 1472-1; the lead's go after #1479): after the limit's SIGTERM the group's pipes are
read through the grace. Before, the grace was a bare ``wait``: a put-back that wrote more than a pipe holds blocked
on its write, sat out the whole grace (with H-114b the update's own limit) and was SIGKILLed part way. The SIGKILL
still comes at the end of the grace for a group that does not stop, and as soon as the leader has exited for a child
left holding the pipes. The same steps serve ``update.run_cmd`` (each command of the update, ten seconds' grace)."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from pathlib import Path

import pytest

from tools.trialbox import procgroup
from tools.trialbox import update as up

BIG = 'head -c 200000 /dev/zero | tr "\\0" x'  # 200 kB: three times what a pipe holds


def _gone(pid_file: Path) -> bool:
    pid = int(pid_file.read_text().split()[0])
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.1)
    return False


def test_a_put_back_writing_more_than_a_pipe_holds_ends_inside_the_grace_and_is_not_killed(tmp_path: Path) -> None:
    """The put-back writes 200 kB on its stdout and on its stderr after the TERM, takes 2 s, and ends by itself
    (its last word written): well before the 60 s grace ends, and without a SIGKILL."""
    done = tmp_path / "done"
    script = (f"trap '{BIG}; {BIG} >&2; sleep 2; echo done > {done}; exit 1' TERM; "
              "while :; do sleep 0.1; done")  # fmt: skip
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        procgroup.run(["sh", "-c", script], timeout=0.5, grace=60, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    took = time.monotonic() - started
    assert done.is_file(), "the put-back was killed part way"
    assert took < 20, took


def test_the_kill_still_lands_at_the_end_of_the_grace_when_the_group_never_exits(tmp_path: Path) -> None:
    """A group that ignores the TERM and keeps writing: read through the grace (it never blocks), and SIGKILLed when
    the grace is up, not before and not never."""
    pid = tmp_path / "pid"
    script = f"trap '' TERM; echo $$ > {pid}; while :; do {BIG}; sleep 0.2; done"
    raised: list[subprocess.TimeoutExpired] = []

    def go() -> None:  # anything else it raises leaves ``raised`` empty, and the test fails below
        try:
            procgroup.run(["sh", "-c", script], timeout=0.5, grace=3, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.TimeoutExpired as exc:
            raised.append(exc)

    started = time.monotonic()
    t = threading.Thread(target=go, daemon=True)
    t.start()
    t.join(30)  # a grace that never ends fails here, not as a run that never ends
    took = time.monotonic() - started
    if t.is_alive():
        os.killpg(int(pid.read_text().split()[0]), signal.SIGKILL)
        pytest.fail("the grace never ended: no SIGKILL for a group that ignores the TERM")
    assert raised, "procgroup.run did not raise TimeoutExpired"
    assert 3.3 <= took < 15, took
    assert _gone(pid), "the group outlived its grace"


def test_a_child_left_holding_the_pipes_does_not_keep_the_kill_waiting(tmp_path: Path) -> None:
    """The leader ends on the TERM; a child it left in the group still holds the pipes. The grace ends with the
    leader (as the ``wait`` of before did), the child is SIGKILLed, and the 60 s grace is not sat out."""
    pid = tmp_path / "pid"
    script = (f"sh -c \"trap '' TERM; exec sleep 300\" & echo $! > {pid}; trap 'exit 1' TERM; "
              "while :; do sleep 0.1; done")  # fmt: skip
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        procgroup.run(["sh", "-c", script], timeout=1, grace=60, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    took = time.monotonic() - started
    assert took < 15, took
    assert _gone(pid), "the child left in the group was not killed"


def test_an_update_command_s_put_back_writing_more_than_a_pipe_holds_is_not_killed(tmp_path: Path) -> None:
    """``update.run_cmd`` (a command of the update under its own limit, ten seconds' grace): the same put-back ends by
    itself inside the grace."""
    done = tmp_path / "done"
    script = f"trap '{BIG}; {BIG} >&2; sleep 2; echo done > {done}; exit 1' TERM; while :; do sleep 0.1; done"
    with pytest.raises(subprocess.TimeoutExpired):
        up.run_cmd(["sh", "-c", script], timeout=0.5)
    assert done.is_file(), "the command's put-back was killed part way"


def test_the_grace_s_steps_are_shared_and_the_signals_are_term_then_kill(monkeypatch: pytest.MonkeyPatch,
                                                                         tmp_path: Path) -> None:  # fmt: skip
    """Both callers stop a group the same way: SIGTERM first, SIGKILL last, nothing else sent."""
    sent: list[int] = []
    real = procgroup._kill

    def kill(pgid: int, sig: int) -> None:
        sent.append(sig)
        real(pgid, sig)

    monkeypatch.setattr(procgroup, "_kill", kill)
    with pytest.raises(subprocess.TimeoutExpired):
        procgroup.run(["sh", "-c", "trap 'exit 1' TERM; while :; do sleep 0.1; done"], timeout=0.3, grace=5,
                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)  # fmt: skip
    with pytest.raises(subprocess.TimeoutExpired):
        up.run_cmd(["sh", "-c", "trap 'exit 1' TERM; while :; do sleep 0.1; done"], timeout=0.3)
    assert sent == [signal.SIGTERM, signal.SIGKILL] * 2, sent
