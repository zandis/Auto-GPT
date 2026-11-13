"""NEW-B-11 (D-532): a job is run by one worker at a time, in every process.

A starting orchestrator takes every job that is neither queued nor ended for "interrupted by a restart" and queues
it again. A second orchestrator process on the same database (an update that starts the new container before the
old one has stopped, a second replica by mistake) did that to the jobs the first one was running: two workers ran
one job. A running job now holds a lease (a session lock of the database, given up with the connection)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from orchestrator.db import JobDB, JobLeased

import tests.unit.test_t689_outage_restart as t689
from tests.unit.test_t689_outage_restart import Scripted, _events, _job, screen_of

make = t689.make  # that file's fixture (an orchestrator on the test database), used here under its own name


def test_a_lease_is_one_holders_and_ends_with_its_connection(db_url: str) -> None:
    a, b = JobDB(), JobDB()
    try:
        held = a.lease("01JOBAAAAAAAAAAAAAAAAAAAAA")
        assert b.leased("01JOBAAAAAAAAAAAAAAAAAAAAA") and not b.leased("01JOBBBBBBBBBBBBBBBBBBBBBB")
        with pytest.raises(JobLeased):
            b.lease("01JOBAAAAAAAAAAAAAAAAAAAAA")
        held.release()
        assert not b.leased("01JOBAAAAAAAAAAAAAAAAAAAAA")
        again = b.lease("01JOBAAAAAAAAAAAAAAAAAAAAA")  # free again: the next holder takes it
        assert a.leased("01JOBAAAAAAAAAAAAAAAAAAAAA")
        again.drop_connection()  # the holder dies: no release is ever called
        assert not a.leased("01JOBAAAAAAAAAAAAAAAAAAAAA")
    finally:
        a.close()
        b.close()


def test_a_second_orchestrator_does_not_take_a_running_job_for_interrupted(make: Any, tmp_path: Path) -> None:
    llm = Scripted(lambda n: False)
    seen: dict[str, Any] = {}
    first = make(llm, screen_of(3, seen))
    job_id = _job(first)
    assert first.db.claim() == job_id  # the first process's worker took it ...
    lease = first.db.lease(job_id)  # ... and runs it (the run holds the lease)
    job = first.db.get(job_id)
    assert job is not None
    first.set_state(job, "running")
    second = make(llm, screen_of(3, seen))
    second.start()  # the restart recovery of another process on the same database
    assert second.db.restarts(job_id) == 0 and second.db.claim() is None  # not counted, not queued again
    now = second.db.get(job_id)
    assert now is not None and now.state == "running" and _events(tmp_path, "job.requeued") == []
    second.run(job_id)  # and a worker that got hold of the id all the same runs nothing
    assert llm.calls == 0
    # the first process dies (or is stopped before the job ended): its lease goes with its connection. The second
    # process, which left the job alone, finds it interrupted by itself: no third start is needed (review HIGH-1)
    lease.drop_connection()
    second.drain()
    assert second.db.restarts(job_id) == 1 and len(_events(tmp_path, "job.requeued")) == 1
    done = second.db.get(job_id)
    assert done is not None and done.state == "done", done.error
    assert not second.db.leased(job_id)  # a finished run gives its lease up


def test_a_job_that_ended_under_its_holder_is_not_queued_again(make: Any, tmp_path: Path) -> None:
    llm = Scripted(lambda n: False)
    seen: dict[str, Any] = {}
    first = make(llm, screen_of(2, seen))
    job_id = _job(first)
    assert first.db.claim() == job_id
    lease = first.db.lease(job_id)
    second = make(llm, screen_of(2, seen))
    second.start()  # watched, not queued
    job = first.db.get(job_id)
    assert job is not None
    first.set_state(job, "done")  # the holder finishes its run ...
    lease.release()
    calls = llm.calls
    second.drain()  # ... and the watcher has nothing to do
    assert llm.calls == calls and second.db.restarts(job_id) == 0 and _events(tmp_path, "job.requeued") == []


def test_a_lease_that_cannot_be_asked_for_puts_the_job_back_on_the_queue(make: Any, monkeypatch: Any) -> None:
    """Review HIGH-2: the database refuses the lease's connection. The claimed job is not lost."""
    from tb_common.db import DatabaseError

    llm = Scripted(lambda n: False)
    seen: dict[str, Any] = {}
    orch = make(llm, screen_of(2, seen))
    job_id = _job(orch)
    real = orch.db.lease
    fail = [True]

    def lease(jid: str) -> Any:
        if fail[0]:
            fail[0] = False
            raise DatabaseError("too many clients already")
        return real(jid)

    monkeypatch.setattr(orch.db, "lease", lease)
    assert orch.db.claim() == job_id
    with pytest.raises(DatabaseError):
        orch.run(job_id)
    assert llm.calls == 0
    orch.drain()  # it is on the queue again, and runs
    done = orch.db.get(job_id)
    assert done is not None and done.state == "done", done.error


def test_six_workers_given_one_job_run_it_once(make: Any) -> None:
    import threading

    llm = Scripted(lambda n: False)
    seen: dict[str, Any] = {}
    orch = make(llm, screen_of(4, seen))
    job_id = _job(orch)
    assert orch.db.claim() == job_id
    go = threading.Barrier(6)

    def worker() -> None:
        go.wait(30)
        orch.run(job_id)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    done = orch.db.get(job_id)
    assert done is not None and done.state == "done", done.error
    assert llm.calls == 4  # the four pairs of one run, not of six


@pytest.mark.nodb
def test_two_jobs_whose_32_bit_hashes_meet_do_not_share_a_lease() -> None:
    """Review LOW-5: PostgreSQL's hashtext gives these two ids one value; the lease's keys are 64 bits of both."""
    from orchestrator.db import lease_keys

    a, b = lease_keys("tb_orch", "01JOB199167"), lease_keys("tb_orch", "01JOB31483")
    assert a != b and all(-(2**31) <= k < 2**31 for k in (*a, *b))
    assert lease_keys("tb_orch", "01JOB199167") == a and lease_keys("other_orch", "01JOB199167") != a
