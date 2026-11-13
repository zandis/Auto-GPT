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
    # the first process dies: its lease goes with its connection, and the next start finds the job interrupted
    lease.drop_connection()
    third = make(llm, screen_of(3, seen))
    third.start()
    assert third.db.restarts(job_id) == 1 and len(_events(tmp_path, "job.requeued")) == 1
    third.drain()
    done = third.db.get(job_id)
    assert done is not None and done.state == "done", done.error
    assert not third.db.leased(job_id)  # a finished run gives its lease up
