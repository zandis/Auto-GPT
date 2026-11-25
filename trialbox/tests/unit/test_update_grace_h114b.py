"""H-114b (the integrator's ruling 7124945074 on H114-05, the review of #1461's 1461-3): the console's update limit
sends SIGTERM to the update's group, which starts its rollback; the SIGKILL after it no longer cuts that rollback
short. ``procgroup.run`` takes an optional ``grace`` (default :data:`procgroup.TERM_GRACE_S`, ten seconds, as before)
and ``ops.do_update_apply`` passes the update's own limit as the grace."""

from __future__ import annotations

import inspect
import json
import os
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_update_signals_h114 import ROOT, _start
from tools.trialbox import ops as tb_ops
from tools.trialbox import procgroup


def test_the_default_grace_is_still_ten_seconds_between_term_and_kill(tmp_path: Path) -> None:
    """Every other caller: the default path's signals and timing are unchanged (TERM, ten seconds, KILL)."""
    assert procgroup.TERM_GRACE_S == 10
    assert inspect.signature(procgroup.run).parameters["grace"].default == procgroup.TERM_GRACE_S
    seen = tmp_path / "seen"
    script = f'trap "echo term >> {seen}" TERM; while :; do sleep 0.1; done'  # takes the TERM and goes on
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        procgroup.run(["sh", "-c", script], timeout=0.5, stdout=subprocess.PIPE)
    took = time.monotonic() - started
    assert 10 <= took < 14, took  # the limit, then ten seconds of grace, then the SIGKILL
    assert seen.read_text().split() == ["term"]


def test_a_longer_grace_lets_the_rollback_the_term_started_finish(tmp_path: Path) -> None:
    """The real updater under ``procgroup.run`` with a limit that lands in its apply: the TERM starts the rollback,
    which takes longer than the default grace; with the update's grace it runs to its end and is audited."""
    argv, env, out = _start(tmp_path, apply_sleep=60, rollback_sleep=12)
    with pytest.raises(subprocess.TimeoutExpired):
        procgroup.run(argv, timeout=1.5, grace=120, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                      stderr=subprocess.PIPE)  # fmt: skip
    calls = (tmp_path / "calls.txt").read_text().splitlines()
    assert "rollback done" in calls, calls
    res = json.loads(out.read_text())
    assert res["outcome"] == "failed" and "stopped by SIGTERM" in res["message"] and res["marker"] is None, res
    audits = [json.loads(x) for x in (tmp_path / "audits.jsonl").read_text().splitlines()]
    assert audits[-1][0] == "update.rolled_back" and audits[-1][1]["rolled_back"] is True


def test_the_console_gives_the_update_its_own_limit_as_grace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    deploy = tmp_path / "deploy"
    incoming = deploy / "updates" / "incoming"
    incoming.mkdir(parents=True)
    (incoming / "trialbox-2026.11-2.tar").write_bytes(b"stand-in bundle")
    seen: list[dict[str, Any]] = []

    def run(argv: list[str], timeout: float | None = None, **kw: Any) -> subprocess.CompletedProcess[str]:
        seen.append({"argv": argv, "timeout": timeout, "grace": kw.get("grace", "default")})
        return subprocess.CompletedProcess(argv, 0, "applied (stand-in)\n", "")

    monkeypatch.setattr(procgroup, "run", run)
    monkeypatch.setattr(tb_ops.OpsRunner, "apply_limit", lambda self: 4321)
    runner = tb_ops.OpsRunner(tb_ops.Box("compose", deploy), tb_ops.OpsDir(tmp_path / "ops"))
    _said, lines = runner.do_update_apply({"bundle": "trialbox-2026.11-2.tar"})
    assert seen and seen[0]["timeout"] == 4321 and seen[0]["grace"] == 4321, seen
    assert seen[0]["argv"][1].endswith("tools/apply_update.sh") and lines == ["applied (stand-in)"]
    calls: list[tuple[Sequence[str], int | None]] = []  # a stand-in runner (the console's tests): called as before

    def stand_in(argv: Sequence[str], timeout: int | None) -> str:
        calls.append((argv, timeout))
        return "ok\n"

    runner = tb_ops.OpsRunner(tb_ops.Box("compose", deploy, run=stand_in), tb_ops.OpsDir(tmp_path / "ops2"))
    runner.do_update_apply({"bundle": "trialbox-2026.11-2.tar"})
    assert calls and calls[0][1] == 4321
    assert os.path.basename(calls[0][0][1]) == "apply_update.sh"


def test_a_rollback_that_writes_more_than_a_pipe_holds_is_not_stalled_in_the_grace(tmp_path: Path) -> None:
    """OCR 1472-1: in the grace the group's output is still read. A put-back that writes more than a pipe holds
    (here 200 kB of progress) and then takes 3 s ends by itself well inside a 60 s grace."""
    done = tmp_path / "done"
    script = (f'trap \'head -c 200000 /dev/zero | tr "\\0" x; sleep 3; echo done > {done}; exit 1\' TERM; '
              "while :; do sleep 0.1; done")  # fmt: skip
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        procgroup.run(["sh", "-c", script], timeout=0.5, grace=60, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    took = time.monotonic() - started
    assert done.is_file(), "the put-back was killed: it blocked on its full output pipe for the whole grace"
    assert took < 30, took
