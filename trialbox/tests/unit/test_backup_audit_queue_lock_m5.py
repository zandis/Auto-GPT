"""INT-M5 line 5 (PR1305-H6): the backup's kept audit events (``deploy/site/backup-audit-pending.jsonl``) are read,
sent and written back under a lock, and a new event is kept before anything is sent.

``ComposeOps.audit`` is called outside ``backup.lock`` too (the nightly's alert, ``backup-status``, the host restore's
failure event): two callers that read the queue at once each wrote back only their own view, and one's event was lost.
And a new event lived only in memory while the older ones were sent: a signal partway through (SIGTERM, SIGHUP, the
service manager's stop) lost it. Now each call holds ``deploy/site/backup-audit.lock`` (``flock``) for its whole read,
send and write, and writes the queue with its new event whole (write-then-rename, fsync) before it sends.

The orchestrator is a stand-in (``box.run``); its waits are bounded by events, not by a clock. Synthetic events only."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from tools.trialbox import backup_schedule as bs


class _Orchestrator:
    """``box._c`` and ``box.run`` of a stand-in orchestrator: down (every send raises), and the first send of
    ``hold_first`` waits (bounded) until the test lets it go, so a second caller can run meanwhile."""

    def __init__(self, hold_first: threading.Event | None = None, entered: threading.Event | None = None,
                 raise_: type[BaseException] = RuntimeError) -> None:  # fmt: skip
        self.hold, self.entered, self.raise_ = hold_first, entered, raise_
        self.sent: list[str] = []

    def _c(self, *args: str) -> list[str]:
        return list(args)

    def run(self, argv: list[str], stdin_file: Path | None = None, **kw: Any) -> str:
        if self.hold is not None:
            hold, self.hold = self.hold, None
            if self.entered is not None:
                self.entered.set()
            hold.wait(timeout=5)
        raise self.raise_("synthetic: the orchestrator is down")


def _ops(deploy: Path, box: Any) -> bs.ComposeOps:
    ops = bs.ComposeOps.__new__(bs.ComposeOps)
    ops.deploy, ops.box = deploy, box
    return ops


def _kept(deploy: Path) -> list[dict[str, Any]]:
    pending = deploy / "site" / "backup-audit-pending.jsonl"
    return [json.loads(x) for x in pending.read_text(encoding="utf-8").splitlines()] if pending.is_file() else []


def test_two_callers_at_once_lose_no_event(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    let_go, entered = threading.Event(), threading.Event()
    first = _ops(deploy, _Orchestrator(hold_first=let_go, entered=entered))
    second = _ops(deploy, _Orchestrator())
    errors: list[BaseException] = []

    def call(ops: bs.ComposeOps, event: str) -> None:
        try:
            ops.audit(event, {"synthetic": event})
        except BaseException as e:  # reported below
            errors.append(e)

    a = threading.Thread(target=call, args=(first, "backup.nightly_alert"))
    a.start()
    assert entered.wait(timeout=5)  # the first caller is sending: it has read the queue
    b = threading.Thread(target=call, args=(second, "backup.status_alert"))
    b.start()
    b.join(timeout=1)  # with the lock, the second waits for the first; without it, it is done by now
    let_go.set()
    a.join(timeout=10)
    b.join(timeout=10)
    assert not errors, errors
    assert sorted(e["event"] for e in _kept(deploy)) == ["backup.nightly_alert", "backup.status_alert"]


@pytest.mark.parametrize("signal_like", [KeyboardInterrupt, SystemExit])
def test_a_signal_while_older_events_are_sent_keeps_the_new_one(tmp_path: Path,
                                                                 signal_like: type[BaseException]) -> None:  # fmt: skip
    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    old = {"event": "backup.restore_failed", "sha": "", "detail": {"synthetic": 1}}
    (deploy / "site" / "backup-audit-pending.jsonl").write_text(json.dumps(old) + "\n", encoding="utf-8")
    ops = _ops(deploy, _Orchestrator(raise_=signal_like))  # the handler's exception, partway through the send
    with pytest.raises(signal_like):
        ops.audit("backup.nightly_failed", {"synthetic": 2})
    assert [e["event"] for e in _kept(deploy)] == ["backup.restore_failed", "backup.nightly_failed"]
    assert not list((deploy / "site").glob(".audit-*")) and not list((deploy / "site").glob("*.tmp"))


def test_the_queue_is_written_whole_with_its_mode_and_the_lock_is_its_own_file(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    pending = deploy / "site" / "backup-audit-pending.jsonl"
    pending.write_text("", encoding="utf-8")
    pending.chmod(0o600)
    _ops(deploy, _Orchestrator()).audit("backup.synthetic", {"n": 1})
    assert pending.stat().st_mode & 0o777 == 0o600
    assert (deploy / "site" / bs.AUDIT_LOCK).is_file() and bs.AUDIT_LOCK != "backup.lock"
