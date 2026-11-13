"""PERF-001 / PERF-025 (D-539): the lake's rebuild runs as a process of its own, not as a thread of a query worker.

A build that is killed (out of memory under the container's cap) took the query worker and its queries with it.
The service now starts the build as a child process that holds the build lock; the worker only starts it and
reads its state."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from embed_service.embedder import HashEmbedder
from lake.store import Lake, build_running

NIGHT, NEXT = "2026-10-04", "2026-10-05"
TZ = "Asia/Taipei"


def _patients(lake_dir: Path, snap: str, n: int) -> None:
    nd = lake_dir / "ndjson" / snap
    nd.mkdir(parents=True, exist_ok=True)
    pats = [{"resourceType": "Patient", "id": f"syn-{i:03d}", "gender": "female"} for i in range(n)]
    (nd / "Patient.ndjson").write_text("".join(json.dumps(p) + "\n" for p in pats), encoding="utf-8")


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """The lake service as the box runs it: its lake and its embedder come from the environment, which the build's
    process reads too."""
    from fastapi.testclient import TestClient
    from lake import app as lake_app

    d = tmp_path / "lake"
    _patients(d, NIGHT, 3)
    Lake(d, TZ).rebuild(NIGHT, HashEmbedder())
    monkeypatch.setenv("TB_LAKE_DIR", str(d))
    monkeypatch.setenv("TB_LAKE_EMBEDDER", "hash")
    monkeypatch.setenv("TB_LAKE_BUILD", "process")
    monkeypatch.setattr(lake_app, "_lake", None)
    monkeypatch.setattr(lake_app, "_embedder", None)
    client = TestClient(lake_app.app)
    client.lake_dir = d
    yield client
    for proc in list(lake_app._builds.values()):  # no build outlives its test
        if proc.poll() is None:
            proc.kill()
        proc.wait()


def _wait(read: Callable[[], dict[str, Any]], while_state: str = "running") -> dict[str, Any]:
    for _ in range(1200):
        st = read()
        if st["state"] != while_state:
            return st
        time.sleep(0.05)
    raise AssertionError(f"the rebuild stayed {while_state}")


def test_the_build_runs_in_a_process_of_its_own_and_ends_done(api: Any) -> None:
    from lake import app as lake_app

    _patients(api.lake_dir, NEXT, 5)
    r = api.post("/rebuild", json={"snapshot": NEXT})
    assert r.status_code == 202 and r.json()["state"] == "running" and r.headers["Location"] == f"/rebuild/{NEXT}"
    proc = lake_app._builds[NEXT]
    assert proc.pid != os.getpid()
    st = _wait(lambda: api.get(f"/rebuild/{NEXT}").json())
    assert st["state"] == "done" and st["job"] == r.json()["job"] and st["result"]["tables"]["patient"] == 5
    assert Lake(api.lake_dir, TZ).current() == NEXT and st["result"]["generation"] == f"{NEXT}.g1"
    assert proc.wait(60) == 0  # reaped: no process is left behind
    assert not build_running(api.lake_dir, NEXT)  # the build lock went with the process


def test_a_build_killed_as_it_starts_leaves_the_worker_answering_and_the_job_interrupted(api: Any) -> None:
    """The interrupt test: the build's process is stopped the moment it starts, then killed (as the kernel does when
    the container's memory cap is passed). The worker answers queries all along; the job reads ``interrupted``;
    nothing of the half build is served; the same rebuild started again ends ``done``."""
    from lake import app as lake_app

    _patients(api.lake_dir, NEXT, 5)
    r = api.post("/rebuild", json={"snapshot": NEXT})
    assert r.status_code == 202
    proc = lake_app._builds[NEXT]
    os.kill(proc.pid, signal.SIGSTOP)  # it has not built anything yet: it is still starting
    try:
        assert api.get(f"/rebuild/{NEXT}").json()["state"] == "running"  # the stopped process holds the build lock
        assert build_running(api.lake_dir, NEXT)
        again = api.post("/rebuild", json={"snapshot": NEXT})  # one rebuild per snapshot, across processes
        assert again.status_code == 409 and again.headers["X-TB-Lake-Busy"] == "building"
    finally:
        os.kill(proc.pid, signal.SIGKILL)
    assert proc.wait(60) == -signal.SIGKILL
    st = _wait(lambda: api.get(f"/rebuild/{NEXT}").json())
    assert st["state"] == "interrupted" and st["job"] == r.json()["job"]
    q = api.post("/query", json={"sql": "SELECT count(*) AS n FROM patient"})  # the worker is alive and serves
    assert q.status_code == 200 and Lake(api.lake_dir, TZ).current() == NIGHT  # ... the night it served before
    r2 = api.post("/rebuild", json={"snapshot": NEXT})
    assert r2.status_code == 202 and r2.json()["job"] != r.json()["job"]
    st = _wait(lambda: api.get(f"/rebuild/{NEXT}").json())
    assert st["state"] == "done" and Lake(api.lake_dir, TZ).current() == NEXT


def test_a_refusal_found_in_the_build_is_the_jobs_state_across_the_process(api: Any) -> None:
    nd = api.lake_dir / "ndjson" / NEXT
    nd.mkdir(parents=True)
    (nd / "Patient.ndjson").write_text("\n")
    assert api.post("/rebuild", json={"snapshot": NEXT}).status_code == 202
    st = _wait(lambda: api.get(f"/rebuild/{NEXT}").json())
    assert st["state"] == "refused" and "holds no patient or clinical record" in st["detail"]
    assert Lake(api.lake_dir, TZ).current() == NIGHT


def test_a_build_that_cannot_be_started_is_failed_and_frees_the_snapshot(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:

    def no_process(*a: Any, **kw: Any) -> Any:
        raise OSError("cannot start a process")

    _patients(api.lake_dir, NEXT, 5)
    with monkeypatch.context() as mp:
        mp.setattr(subprocess, "Popen", no_process)
        r = api.post("/rebuild", json={"snapshot": NEXT})
    assert r.status_code == 202 and r.json()["state"] == "failed" and "OSError" in r.json()["detail"]
    assert not build_running(api.lake_dir, NEXT)  # the lock is free: the next start is not refused as "building"
    assert api.post("/rebuild", json={"snapshot": NEXT}).status_code == 202
    assert _wait(lambda: api.get(f"/rebuild/{NEXT}").json())["state"] == "done"


def test_thread_is_still_there_for_a_lake_that_is_not_the_environments(monkeypatch: pytest.MonkeyPatch) -> None:
    """``TB_LAKE_BUILD=thread``: the build runs in the worker, as before (a lake or an embedder handed to the service
    in memory cannot be given to another process). Anything else is refused by name."""
    from lake import app as lake_app

    monkeypatch.setenv("TB_LAKE_BUILD", "thread")
    assert lake_app.build_mode() == "thread"
    monkeypatch.delenv("TB_LAKE_BUILD")
    assert lake_app.build_mode() == "process"  # the default: what the box runs
    monkeypatch.setenv("TB_LAKE_BUILD", "fork")
    with pytest.raises(ValueError, match="TB_LAKE_BUILD"):
        lake_app.build_mode()


# ------------------------------------------------------------------------------------------------ review fixes
def test_a_launch_that_fails_after_the_process_started_leaves_no_build_behind(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The process started, then something after it failed (no thread to reap it with). The caller is told
    ``failed``: the process must not go on, build and promote behind that answer."""
    import threading

    started: list[Any] = []
    real = subprocess.Popen

    def popen(*a: Any, **kw: Any) -> Any:
        started.append(real(*a, **kw))
        return started[-1]

    class NoThread:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("can't start new thread")

    _patients(api.lake_dir, NEXT, 5)
    with monkeypatch.context() as mp:
        mp.setattr(subprocess, "Popen", popen)
        mp.setattr(threading, "Thread", NoThread)
        r = api.post("/rebuild", json={"snapshot": NEXT})
    assert r.status_code == 202 and r.json()["state"] == "failed"
    (proc,) = started
    assert proc.wait(60) == -signal.SIGKILL  # ended by the launch, not left to run
    assert not build_running(api.lake_dir, NEXT)
    assert api.get(f"/rebuild/{NEXT}").json()["state"] == "failed"
    assert Lake(api.lake_dir, TZ).current() == NIGHT  # nothing was built behind the answer


def test_a_build_process_that_exits_with_an_error_is_failed_not_interrupted(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A process that ends by itself with an error and no answer (it could not import, its job could not be read)
    would fail the same way again: ``failed``, with its exit code, not ``interrupted: start it again``."""
    import sys

    from lake import app as lake_app

    _patients(api.lake_dir, NEXT, 5)
    with monkeypatch.context() as mp:
        mp.setattr(lake_app, "_command", lambda fd, spec: [sys.executable, "-c", "import sys; sys.exit(3)"])
        r = api.post("/rebuild", json={"snapshot": NEXT})
        assert r.status_code == 202
        lake_app._builds[NEXT].wait(60)
        st = _wait(lambda: api.get(f"/rebuild/{NEXT}").json())
        st = _wait(lambda: api.get(f"/rebuild/{NEXT}").json(), while_state="interrupted")  # the reaper writes it
    assert st["state"] == "failed" and "exit code 3" in st["detail"] and st["job"] == r.json()["job"]
    assert api.post("/rebuild", json={"snapshot": NEXT}).status_code == 202  # and the snapshot is free
    assert _wait(lambda: api.get(f"/rebuild/{NEXT}").json())["state"] == "done"


def test_the_lock_handed_to_a_build_is_checked_to_be_the_snapshots(tmp_path: Path) -> None:
    from lake.store import BuildLock, SnapshotBuilding

    lock = BuildLock(tmp_path, NEXT)
    fd = os.dup(lock.fileno())
    lock.hand_over()
    mine = BuildLock.adopt(fd, tmp_path, NEXT)  # the open file that holds the snapshot's lock: adopted
    assert build_running(tmp_path, NEXT)
    other = os.open(tmp_path / "another-file", os.O_CREAT | os.O_RDWR)
    with pytest.raises(SnapshotBuilding, match="not the build lock"):
        BuildLock.adopt(other, tmp_path, NEXT)  # some other file: refused, a build never runs without its lock
    mine.release()
    assert not build_running(tmp_path, NEXT)


def test_two_starts_at_once_do_not_trip_over_a_finished_build(api: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two requests prune the same finished entry: neither fails for it."""
    from lake import app as lake_app

    class Gone(dict):  # type: ignore[type-arg]
        def items(self) -> Any:  # the other request removed the entry between the listing and the removal
            got = list(super().items())
            self.clear()
            return got

    class Done:
        def poll(self) -> int:
            return 0

    builds = Gone({"2026-01-01": Done()})
    monkeypatch.setattr(lake_app, "_builds", builds)
    _patients(api.lake_dir, NEXT, 5)
    r = api.post("/rebuild", json={"snapshot": NEXT})
    assert r.status_code == 202 and r.json()["state"] == "running"
    assert _wait(lambda: api.get(f"/rebuild/{NEXT}").json())["state"] == "done"
