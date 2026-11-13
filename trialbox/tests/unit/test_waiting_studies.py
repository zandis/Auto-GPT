"""NEW-JRN-1b (D-545): the studies waiting for approval are asked as studies, not cut from a list of jobs.

NEW-JRN-1 (D-540) read up to 500 waiting jobs and took their studies; a study whose one waiting job stood behind
500 newer waiting jobs was not offered for its first approval (the limits lint named it, OD-10). The job store now
answers the question itself: the distinct studies with a job in ``awaiting_approval``, newest first."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from orchestrator.db import JobDB
from tb_contracts import Job

T0 = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


def _job(n: int, ruleset: str | None, state: Any = "awaiting_approval") -> Job:
    at = T0 + timedelta(minutes=n)
    return Job(job_id=f"01JWA1T{n:019d}", type="FEAS", ruleset=ruleset, requested_by="crc@hospa.test",
               received_at=at, updated_at=at, state=state, options={}, outputs=[])  # fmt: skip


def test_a_study_behind_more_waiting_jobs_than_any_listing_reads_is_still_named(db_url: str) -> None:
    db = JobDB(db_url)
    db.put(_job(0, "OLDEST"))
    for n in range(1, 520):
        db.put(_job(n, "BUSY"))
    db.put(_job(600, "DONE1", state="done"))
    db.put(_job(601, None))  # a waiting job with no study names none
    db.put(_job(603, "   "))  # nor one whose study is blanks (the review)
    db.put(_job(602, "newer"))
    # the old way: the newest 500 waiting jobs do not hold the oldest study's
    assert "OLDEST" not in {j.ruleset for j in db.find(state="awaiting_approval", limit=500)}
    assert db.waiting_rulesets() == ["newer", "BUSY", "OLDEST"]  # newest waiting job first; as stored


def test_no_waiting_job_is_no_study(db_url: str) -> None:
    db = JobDB(db_url)
    db.put(_job(1, "DONE1", state="done"))
    assert db.waiting_rulesets() == []
