"""The adapter's ingest runs on disk, and the lock of the one that runs (PERF-025 / PERF-008, D-663).

``<lake>/adapter-runs/<run id>.json``: the state of one ingest run (``running``, ``done`` with the ingest report,
``refused``, ``failed``), written whole. A restart of the adapter no longer forgets a run, and the run's own
process writes its end. Counts, times, a reason: what the ingest report already holds; no row of the feed.

``<lake>/locks/adapter.run.lock``: an ``flock`` held by the process that runs an ingest, handed to it as an open
file by the service (the pattern of ``lake.store.BuildLock``, D-539: inherited, never unlocked by the starter).
The kernel frees it when that process ends, however it ends. ``locks/adapter.run.holder`` names the run the lock
is held for: a run recorded ``running`` that is not that run, or whose lock nobody holds, ended without an answer.
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from adapter.ndjson import list_snapshots

RUNS = "adapter-runs"
LOCK = "adapter.run.lock"
HOLDER = "adapter.run.holder"  # the id of the run whose process holds the lock (written by the service that starts it)
#: the lock is asked about by taking it for a moment. Every asker and every starter is a thread of the one service
#: process (the ingest's own process only adopts): one at a time, so a question never refuses a night and two
#: questions never see each other as a night
_one_at_a_time = threading.Lock()
ENDED_WITHOUT_ANSWER = (
    "the ingest's process ended without an answer (it was killed, or the box restarted); run it again"
)


class RunLockHeld(RuntimeError):
    """Another process holds the run lock: an ingest runs."""


class RunLock:
    """The lock of the one ingest that runs, as an open file (see the module's text)."""

    def __init__(self, lake_dir: Path) -> None:
        self._fh: Any = _lock_path(lake_dir, make=True).open("a")
        try:
            with _one_at_a_time:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._fh.close()
            self._fh = None
            raise RunLockHeld("an ingest is already running (another process holds the run lock)") from None

    @classmethod
    def adopt(cls, fd: int, lake_dir: Path) -> RunLock:
        """The lock the service handed to this process. The file must be the run lock's file, and the lock is asked
        for again on it (granted only when this open file holds it or nobody does)."""
        lock = cls.__new__(cls)
        lock._fh = os.fdopen(fd, "a")
        try:
            want, got = _lock_path(lake_dir).stat(), os.fstat(fd)
            if (got.st_dev, got.st_ino) != (want.st_dev, want.st_ino):
                raise RunLockHeld("the file handed to this process is not the adapter's run lock")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RunLockHeld("the run lock handed to this process is held by another run") from None
        except BaseException:
            lock._fh.close()
            lock._fh = None
            raise
        return lock

    def fileno(self) -> int:
        return int(self._fh.fileno())

    def hand_over(self) -> None:
        """Let go of this process's end without unlocking: the process that inherited the file holds the lock."""
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def release(self) -> None:
        if self._fh is not None:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None


def _lock_path(lake_dir: Path, make: bool = False) -> Path:
    if make:
        (lake_dir / "locks").mkdir(parents=True, exist_ok=True)
    return lake_dir / "locks" / LOCK


def running(lake_dir: Path) -> bool:
    """Whether a live process holds the run lock: an ingest runs now."""
    p = _lock_path(lake_dir)
    if not p.exists():
        return False
    with _one_at_a_time, p.open("a") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    return False


def hold(lake_dir: Path, rid: str) -> None:
    """Say which run the lock is held for. Called by the starter, holding the lock, before the run's process
    exists."""
    p = lake_dir / "locks" / HOLDER
    tmp = p.with_name(f".{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(rid, encoding="ascii")
    tmp.replace(p)


def holder(lake_dir: Path) -> str:
    """The id of the run that runs now, or "" when none does. The name alone says nothing: only while a live process
    holds the lock is the named run the one it is held for."""
    if not running(lake_dir):
        return ""
    try:
        return (lake_dir / "locks" / HOLDER).read_text(encoding="ascii").strip()
    except OSError:
        return ""


def _path(lake_dir: Path, rid: str) -> Path:
    if not rid.isalnum():  # a run id is hex; nothing else names a file here
        raise ValueError("not a run id")
    return lake_dir / RUNS / f"{rid}.json"


def write(lake_dir: Path, state: dict[str, Any]) -> None:
    p = _path(lake_dir, str(state["run"]))
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


def read(lake_dir: Path, rid: str) -> dict[str, Any] | None:
    """The run's state, or None. A run recorded ``running`` whose lock nobody holds is answered ``failed``: its
    process ended without writing an end."""
    try:
        st = json.loads(_path(lake_dir, rid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(st, dict):
        return None
    if st.get("state") == "running" and holder(lake_dir) != rid:
        # nobody holds the lock, or it is held for another run (a later night): this run's process is gone
        again = _raw(lake_dir, rid) or st  # it may have just ended and written its answer
        if again.get("state") == "running":
            return {**again, "state": "failed", "detail": ENDED_WITHOUT_ANSWER}
        return again
    return st


def _raw(lake_dir: Path, rid: str) -> dict[str, Any] | None:
    try:
        st = json.loads(_path(lake_dir, rid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return st if isinstance(st, dict) else None


def all_runs(lake_dir: Path) -> list[dict[str, Any]]:
    """Every recorded run, the newest last (by its start)."""
    out = []
    for f in (lake_dir / RUNS).glob("*.json") if (lake_dir / RUNS).is_dir() else []:
        st = read(lake_dir, f.stem) if f.stem.isalnum() else None
        if st is not None:
            out.append(st)
    return sorted(out, key=lambda s: str(s.get("started") or ""))


def prune(lake_dir: Path) -> None:
    """Drop the records of runs that are older than the oldest snapshot the lake still keeps: the lake's own
    retention decides how far back a run is remembered, no number of this file's. A run's start is written in UTC
    and a snapshot is a date of the site, up to a day apart for the same night: a record goes only when its start
    is before the day before that snapshot. The run that runs stays. Never raises: a record that cannot be removed
    must not stop a night."""
    try:
        snaps = list_snapshots(lake_dir)
        if not snaps:
            return
        oldest = (date.fromisoformat(snaps[0][:10]) - timedelta(days=1)).isoformat()
        for st in all_runs(lake_dir):
            if st.get("state") != "running" and str(st.get("started") or "9999")[:10] < oldest:
                _path(lake_dir, str(st.get("run"))).unlink(missing_ok=True)
    except Exception:
        return
