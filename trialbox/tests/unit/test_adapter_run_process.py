"""PERF-025 / PERF-008 (D-663): the night's ingest runs as a process of its own, and its run record is on disk.

The ingest ran as a thread of the adapter's API process with its state in a dictionary: a night killed for memory
took the service with it, and a restart of the service forgot the run (the orchestrator's job then failed beside a
night that might be published). The service now starts ``python -m adapter.run_job``, which holds the run lock and
writes the run's end to ``<lake>/adapter-runs/``."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from adapter import runs

from tests.unit.test_site_inputs import site  # noqa: F401 (a fixture: a site configured from the environment)

NIGHT = "2026-10-04"


@pytest.fixture
def api(site: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:  # noqa: F811
    """The adapter service as the box runs it: its configuration comes from the environment, which the ingest's
    process reads too."""
    from adapter import app as adapter_app
    from adapter import cli
    from fastapi.testclient import TestClient

    assert cli.main(["keys-init"]) == 0
    monkeypatch.setenv("TB_ADAPTER_RUN", "process")
    monkeypatch.setattr(adapter_app, "_runs", {})
    monkeypatch.setattr(adapter_app, "_running", threading.Lock())
    client = TestClient(adapter_app.app)
    client.lake_dir = site["tmp"] / "lake"
    yield client
    for proc in list(adapter_app._children.values()):  # no ingest outlives its test
        if proc.poll() is None:
            proc.kill()
        proc.wait()


BODY = {"source": "csv", "snapshot": NIGHT, "load_fhir": False, "validate": False}


def _wait(read: Callable[[], dict[str, Any]], while_state: str = "running") -> dict[str, Any]:
    for _ in range(2400):
        st = read()
        if st["state"] != while_state:
            return st
        time.sleep(0.05)
    raise AssertionError(f"the run stayed {while_state}")


def _child(rid: str) -> subprocess.Popen[bytes]:
    from adapter import app as adapter_app

    for _ in range(6000):  # a loaded machine starts a thread late; the test must not give up before it does
        if rid in adapter_app._children:
            return adapter_app._children[rid]
        time.sleep(0.01)
    raise AssertionError("no ingest process was started")


def _restart(monkeypatch: pytest.MonkeyPatch) -> None:
    """The adapter service restarted: it remembers nothing in memory, and its lock is a new one."""
    from adapter import app as adapter_app

    monkeypatch.setattr(adapter_app, "_runs", {})
    monkeypatch.setattr(adapter_app, "_running", threading.Lock())


def test_the_night_runs_in_a_process_of_its_own_and_its_record_survives_a_restart(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = api.post("/run", json=BODY)
    assert r.status_code == 202 and r.json()["state"] == "running"
    rid = r.json()["run"]
    proc = _child(rid)
    assert proc.pid != os.getpid()
    st = _wait(lambda: api.get(f"/run/{rid}").json())
    assert st["state"] == "done", st.get("detail")
    assert st["report"]["passed"] and st["report"]["counts"]["Patient"] > 0
    assert (api.lake_dir / "CURRENT").read_text().strip() == NIGHT and not runs.running(api.lake_dir)
    on_disk = json.loads((api.lake_dir / runs.RUNS / f"{rid}.json").read_text())
    assert on_disk["state"] == "done" and on_disk["report"]["passed"]
    _restart(monkeypatch)  # PERF-008: the run is not forgotten
    assert api.get(f"/run/{rid}").json()["state"] == "done"
    assert api.get("/run").json()["run"] == rid
    assert api.get("/run/0000").status_code == 404


def test_a_night_killed_as_it_starts_leaves_the_service_answering_and_the_run_failed(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The interrupt test. The ingest's process is stopped the moment it starts and then killed (as the kernel does
    at the container's memory cap). The service answers all along; a second start is refused and names the run,
    also after the service itself restarted; the run then reads ``failed``; nothing is served; the night run again
    ends ``done``."""
    r = api.post("/run", json=BODY)
    rid = r.json()["run"]
    proc = _child(rid)
    os.kill(proc.pid, signal.SIGSTOP)
    try:
        assert api.get(f"/run/{rid}").json()["state"] == "running" and runs.running(api.lake_dir)
        again = api.post("/run", json=BODY)
        assert again.status_code == 409 and again.headers["X-TB-Run"] == rid
        _restart(monkeypatch)  # the service restarts under a running night: the night goes on, and is still the one
        after = api.post("/run", json=BODY)
        assert after.status_code == 409 and after.headers["X-TB-Run"] == rid
        assert api.get(f"/run/{rid}").json()["state"] == "running"
        accept = api.post("/publish", json={"snapshot": NIGHT})  # and an accept does not publish beside it
        assert accept.status_code == 409
    finally:
        os.kill(proc.pid, signal.SIGKILL)
    assert proc.wait(60) == -signal.SIGKILL
    st = _wait(lambda: api.get(f"/run/{rid}").json())
    assert st["state"] == "failed" and "ended without an answer" in st["detail"]
    assert not (api.lake_dir / "CURRENT").exists()  # nothing of the killed night is served
    r2 = api.post("/run", json=BODY)
    assert r2.status_code == 202 and r2.json()["run"] != rid
    assert _wait(lambda: api.get(f"/run/{r2.json()['run']}").json())["state"] == "done"


def test_a_process_that_cannot_be_started_or_exits_with_an_error_is_a_failed_run(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    from adapter import app as adapter_app

    def no_process(*a: Any, **kw: Any) -> Any:
        raise OSError("cannot start a process")

    with monkeypatch.context() as mp:
        mp.setattr(subprocess, "Popen", no_process)
        rid = api.post("/run", json=BODY).json()["run"]
        st = _wait(lambda: api.get(f"/run/{rid}").json())
    assert st["state"] == "failed" and "OSError" in st["detail"] and not runs.running(api.lake_dir)
    with monkeypatch.context() as mp:
        mp.setattr(adapter_app, "_run_command", lambda fd, spec: [sys.executable, "-c", "import sys; sys.exit(3)"])
        rid = api.post("/run", json=BODY).json()["run"]
        st = _wait(lambda: api.get(f"/run/{rid}").json())
    assert st["state"] == "failed" and "exit code 3" in st["detail"]
    rid = api.post("/run", json=BODY).json()["run"]  # and the adapter is free for the next night
    assert _wait(lambda: api.get(f"/run/{rid}").json())["state"] == "done"


def test_the_run_lock_handed_over_is_checked_and_the_mode_is_a_declared_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from adapter import app as adapter_app

    lock = runs.RunLock(tmp_path)
    fd = os.dup(lock.fileno())
    lock.hand_over()
    with pytest.raises(runs.RunLockHeld):
        runs.RunLock(tmp_path)  # held by the open file that was handed over
    mine = runs.RunLock.adopt(fd, tmp_path)
    other = os.open(tmp_path / "another-file", os.O_CREAT | os.O_RDWR)
    with pytest.raises(runs.RunLockHeld, match="not the adapter's run lock"):
        runs.RunLock.adopt(other, tmp_path)
    mine.release()
    assert not runs.running(tmp_path)
    monkeypatch.delenv("TB_ADAPTER_RUN")
    assert adapter_app.run_mode() == "process"
    monkeypatch.setenv("TB_ADAPTER_RUN", "fork")
    with pytest.raises(ValueError, match="TB_ADAPTER_RUN"):
        adapter_app.run_mode()


def test_run_records_go_with_the_lakes_own_retention(tmp_path: Path) -> None:
    for rid, started in (("aa", "2026-09-30T17:00:00+00:00"), ("bb", "2026-10-02T17:00:00+00:00")):
        runs.write(tmp_path, {"run": rid, "state": "done", "started": started})
    runs.prune(tmp_path)  # no snapshot in the lake: nothing is judged old
    assert [r["run"] for r in runs.all_runs(tmp_path)] == ["aa", "bb"]
    (tmp_path / "ndjson" / "2026-10-02").mkdir(parents=True)
    runs.prune(tmp_path)
    assert [r["run"] for r in runs.all_runs(tmp_path)] == ["bb"]  # older than the oldest night the lake keeps
    with pytest.raises(ValueError):
        runs.write(tmp_path, {"run": "../x", "state": "done"})


# ------------------------------------------------------------------------------------------------ review fixes
def test_asking_whether_a_night_runs_never_refuses_a_night_or_sees_one_that_is_not_there(tmp_path: Path) -> None:
    """The question is asked by taking the lock for a moment. Asked while a night starts (a poll of an old run's
    state), it must not make the start fail, and two askers must not see each other as a running night."""
    stop = threading.Event()
    saw: list[bool] = []

    def ask() -> None:
        while not stop.is_set():
            saw.append(runs.running(tmp_path))

    askers = [threading.Thread(target=ask) for _ in range(2)]
    for t in askers:
        t.start()
    time.sleep(0.2)
    alone = list(saw)  # two askers and nobody holding the lock
    try:
        for _ in range(3000):
            runs.RunLock(tmp_path).release()  # RunLockHeld here would be a night refused for a question
    finally:
        stop.set()
        for t in askers:
            t.join()
    assert alone and not any(alone)


def test_a_run_left_running_by_a_crash_is_failed_also_while_another_night_runs(tmp_path: Path) -> None:
    """A record left ``running`` (the box lost power, a restored backup). While a LATER night runs the lock is
    held, by that night: the old record must not read ``running`` because of it, and must not be kept for ever."""
    runs.write(tmp_path, {"run": "dead01", "state": "running", "started": "2026-09-01T17:00:00+00:00"})
    assert runs.read(tmp_path, "dead01")["state"] == "failed"  # type: ignore[index]
    lock = runs.RunLock(tmp_path)
    runs.hold(tmp_path, "live02")  # the night that runs now says which run it is
    runs.write(tmp_path, {"run": "live02", "state": "running", "started": "2026-10-03T17:00:00+00:00"})
    try:
        assert runs.read(tmp_path, "live02")["state"] == "running"  # type: ignore[index]
        dead = runs.read(tmp_path, "dead01")
        assert dead is not None and dead["state"] == "failed" and "ended without an answer" in dead["detail"]
        assert runs.holder(tmp_path) == "live02"
        (tmp_path / "ndjson" / "2026-10-04").mkdir(parents=True)
        runs.prune(tmp_path)
        assert [r["run"] for r in runs.all_runs(tmp_path)] == ["live02"]  # the dead one went with the lake's retention
    finally:
        lock.release()
    assert runs.holder(tmp_path) == ""  # nobody holds the lock: nobody is the holder


def test_the_record_of_the_night_that_made_the_oldest_snapshot_is_kept(tmp_path: Path) -> None:
    """A run's start is written in UTC and a snapshot is a date of the site: a Taipei night of the 4th starts on
    the 3rd in UTC. Its record is not older than its own snapshot."""
    runs.write(tmp_path, {"run": "aa", "state": "done", "started": "2026-10-03T18:00:00+00:00"})
    runs.write(tmp_path, {"run": "old", "state": "done", "started": "2026-10-01T18:00:00+00:00"})
    (tmp_path / "ndjson" / "2026-10-04").mkdir(parents=True)
    runs.prune(tmp_path)
    assert [r["run"] for r in runs.all_runs(tmp_path)] == ["aa"]
