"""NEW-B-29 (D-670): a re-run of a merge rebuilds the alliance tables from the store's own record (D-648), through
``rerun()`` itself.

D-666 told what an earlier merge had stored from how its job ended, and said "cannot be re-run" where the ending did
not tell; one stopped merge made every later merge's re-run "cannot" for good, and a stopped merge that was run to
its end later was replayed whole, before the merges that had in fact read between. The store now records each
table as it stores it and each merge's read. The re-run reads that record."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from orchestrator import rerun as rr
from orchestrator.db import JobDB
from orchestrator.scenarios import cohort

from tests.unit.test_cohort_store_record import SENDER, _Box, _fault, _run, _table, box  # noqa: F401 (fixture)


def _scratch_schemas(b: _Box) -> list[str]:
    with b.db.tx() as tx:
        rows = tx.fetchall("SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'orch_rerun_%'")
    return sorted(r[0] for r in rows)


def _first_run_bytes(b: _Box, job: Any) -> dict[str, bytes]:
    return {o.filename: b.store.get(o.minio_key) for o in job.outputs or []}


def test_a_later_merge_run_again_after_a_stopped_one_gives_the_bytes_of_its_first_run(
    box: Callable[[], _Box],  # noqa: F811
) -> None:
    """A merge is killed after its first table; a later merge reads the store as that left it; then the stopped
    merge is run to its end (it stores all three of its tables) and a site sends a new table. Told from the jobs'
    endings, the stopped merge is "done" and would be replayed whole before the later one: HOSP-D in the output,
    which the first run never saw."""
    b = box()
    before = _scratch_schemas(b)
    stopped = b.merge([_table("HOSP-B", n=12), _table("HOSP-C", n=7), _table("HOSP-D", n=3)])
    with pytest.MonkeyPatch.context() as mp:
        _fault(b, mp, "read", 1, SystemExit(1))
        _run(b, stopped)
    later = b.merge([_table("HOSP-C", n=9)])
    b.orch.run(later)
    first = b.db.get(later)
    assert first is not None and first.state == "done" and first.outputs
    assert b"HOSP-D" not in b"".join(_first_run_bytes(b, first).values())
    b.orch.run(stopped)
    b.orch.run(b.merge([_table("HOSP-B", n=30)]))

    got = rr.rerun(b.orch, later)
    assert got.error is None and got.identical, got
    assert got.files and all(f["same"] and f["original"] == f["rerun"] for f in got.files)
    assert {f["filename"]: f["original"] for f in got.files} == {o.filename: o.sha256 for o in first.outputs}
    # the stopped merge itself, done in the end, is run again from where it read
    again = rr.rerun(b.orch, stopped)
    assert again.error is None and again.identical, again
    assert _scratch_schemas(b) == before  # each re-run's scratch store is gone


def test_a_merge_stopped_for_good_no_longer_makes_a_later_merges_rerun_impossible(
    box: Callable[[], _Box],  # noqa: F811
) -> None:
    """D-666's stated cost: a merge that crashed at a point nobody recorded made every later re-run "cannot"."""
    b = box()
    stopped = b.merge([_table("HOSP-B", n=12), _table("HOSP-C", n=7)])
    with pytest.MonkeyPatch.context() as mp:
        _fault(b, mp, "stored", 0, RuntimeError("the box lost its database for a moment"))
        _run(b, stopped)
    assert b.db.get(stopped).state == "failed"  # type: ignore[union-attr]
    with pytest.raises(rr.ReplayUnknown):  # how the job ended does not tell what it stored
        rr._stored_then(b.db.get(stopped))
    later = b.merge([_table("HOSP-D", n=5)])
    b.orch.run(later)
    got = rr.rerun(b.orch, later)
    assert got.error is None and got.identical, got


@pytest.mark.parametrize("unsure", ["another job stored the same site's table before the read", "a changed record"])
def test_a_record_that_does_not_settle_the_rerun_is_said_and_the_scratch_store_is_dropped(
    box: Callable[[], _Box],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    unsure: str,
) -> None:
    b = box()
    before = _scratch_schemas(b)
    job_id = b.merge([_table("HOSP-B", n=12), _table("HOSP-C", n=7)])
    if unsure.startswith("another"):
        real = b.db.cohort_read

        def another_store_first(*a: Any, **kw: Any) -> Any:
            b.db.cohort_store(_table("HOSP-C", n=99), "J-OTHER", SENDER)  # a merge running at the same time
            return real(*a, **kw)

        with monkeypatch.context() as mp:
            mp.setattr(b.db, "cohort_read", another_store_first)
            b.orch.run(job_id)
    else:
        b.orch.run(job_id)
        with b.db.tx() as tx:
            tx.execute("UPDATE cohort_stored SET rows = 'not json' WHERE job_id = ?", (job_id,))
    assert b.db.get(job_id).state == "done"  # type: ignore[union-attr]
    got = rr.rerun(b.orch, job_id)
    assert not got.identical and got.files == []
    assert got.error is not None and got.error.startswith("this job cannot be re-run: ")
    assert ("HOSP-C" if unsure.startswith("another") else job_id) in got.error
    assert _scratch_schemas(b) == before


def test_the_record_is_asked_once_and_for_the_merge_being_run_again(
    box: Callable[[], _Box],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    b = box()
    b.orch.run(b.merge([_table("HOSP-B", n=12)]))
    job_id = b.merge([_table("HOSP-C", n=7)])
    b.orch.run(job_id)
    asked: list[tuple[JobDB, str]] = []
    real = cohort.replay_stored

    def once(record: JobDB, into: JobDB, jid: str) -> bool:
        asked.append((record, jid))
        return real(record, into, jid)

    monkeypatch.setattr(cohort, "replay_stored", once)
    monkeypatch.setattr(rr, "_replay_alliance_tables", lambda *_a, **_k: pytest.fail("the record settled it"))
    assert rr.rerun(b.orch, job_id).identical
    assert asked == [(b.db, job_id)]


def test_a_merge_with_no_recorded_read_is_run_again_the_old_way_or_says_it_cannot(
    box: Callable[[], _Box],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A merge that read before the record began (a box updated in place): the record answers False, and what is
    left is how the earlier jobs ended (D-666), with its "cannot"."""
    b = box()
    job_id = b.merge([_table("HOSP-B", n=12)])
    b.orch.run(job_id)
    with b.db.tx() as tx:  # as on a box whose merge read before the update: no read was recorded
        tx.execute("DELETE FROM cohort_read WHERE job_id = ?", (job_id,))
    assert b.db.cohort_read_point(job_id) is None
    old_way: list[str] = []
    real = rr._replay_alliance_tables

    def spy(orch: Any, db: Any, jid: str) -> None:
        old_way.append(jid)
        real(orch, db, jid)

    monkeypatch.setattr(rr, "_replay_alliance_tables", spy)
    got = rr.rerun(b.orch, job_id)
    assert old_way == [job_id] and got.error is None and got.identical, got

    def unknown(*_a: Any, **_k: Any) -> None:
        raise rr.ReplayUnknown("the merge J-OLD stopped at a point that was not recorded")

    monkeypatch.setattr(rr, "_replay_alliance_tables", unknown)
    got = rr.rerun(b.orch, job_id)
    assert got.error == "this job cannot be re-run: the merge J-OLD stopped at a point that was not recorded"
