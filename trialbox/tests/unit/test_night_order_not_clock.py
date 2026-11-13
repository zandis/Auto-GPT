"""Deep review 2026-11-13 (operations, FAIL-2): the night chain picked "the newest night" by the ingest job's
wall-clock ``received_at``. One ingest received while the box's clock ran ahead (a WSL2 clock after sleep, a real-time
clock set wrong, an NTP step) stayed "newest" after the clock was put right, and the chain never moved on to the real
nights after it: no micro-batch, NAV or retention, and no message. The newest night is the last one put in the job
store (its ``seq``), whatever the clock said."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

from orchestrator import night
from orchestrator.db import JobDB
from tb_common.ulid import new_ulid
from tb_contracts import Job


def _ingest(at: datetime, snap: date, by: str = "scheduler") -> Job:
    return Job(
        job_id=new_ulid(),
        type="INGEST",
        requested_by=by,
        received_at=at,
        state="done",
        snapshot_date=snap,
        options={"timer": "1", "chain": "1"},
    )


def test_the_newest_night_is_the_last_ingest_stored_not_the_latest_clock(db_url: str) -> None:
    db = JobDB()
    db.put(_ingest(datetime(2026, 12, 23, 2, 0, tzinfo=UTC), date(2026, 12, 23)), queued=False)  # clock 40 days ahead
    db.put(_ingest(datetime(2026, 11, 14, 2, 0, tzinfo=UTC), date(2026, 11, 14)), queued=False)  # the clock put right
    orch = SimpleNamespace(db=db, scheduled_root=lambda j: j)
    assert night.current_night(orch) == ("2026-11-14", date(2026, 11, 14))  # type: ignore[arg-type]


def test_a_persons_ingest_with_the_option_is_passed_over_for_the_one_before(db_url: str) -> None:
    db = JobDB()
    db.put(_ingest(datetime(2026, 11, 13, 2, 0, tzinfo=UTC), date(2026, 11, 13)), queued=False)
    # a person's ingest stored after it, its clock behind: not the night; the scheduler's before it is
    db.put(_ingest(datetime(2026, 11, 12, 9, 0, tzinfo=UTC), date(2026, 11, 12), by="admin"), queued=False)
    orch = SimpleNamespace(db=db, scheduled_root=lambda j: None)
    assert night.current_night(orch) == ("2026-11-13", date(2026, 11, 13))  # type: ignore[arg-type]
