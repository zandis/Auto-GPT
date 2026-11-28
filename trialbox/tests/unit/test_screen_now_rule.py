"""M8 (R1-N1): the job rule of "screen now" (``orchestrator.scheduler``): one per study at a time, a request during the
night queued with its wait, the time expected from the last measured runs. Fixed times; synthetic jobs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from tb_common import screen_now as sch
from tb_contracts import Job

pytestmark = pytest.mark.nodb
T0 = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)


def job(n: int, type_: str, rs: str | None = "GZQO", state: str = "running", wall: float = 0, scoped: int = 0) -> Job:
    body: dict[str, Any] = {
        "job_id": f"01JB{n:022d}", "type": type_, "ruleset": rs, "requested_by": "crc@hospa.test",
        "received_at": T0 + timedelta(minutes=n), "updated_at": T0 + timedelta(minutes=n), "state": state,
        "metrics": {"wall_seconds": wall, "patients_scoped": scoped},
    }  # fmt: skip
    return Job.model_validate(body)


def test_no_job_ahead_starts_at_once() -> None:
    assert sch.screen_now_plan([], "GZQO") == sch.ScreenNowPlan("start", None, 0)
    assert sch.screen_now_plan([job(1, "SCREEN", state="done")], "GZQO").action == "start"  # an ended job is not ahead


def test_a_second_request_for_one_study_joins_the_first() -> None:
    first, other = job(1, "SCREEN"), job(2, "SCREEN", "OTHER")
    plan = sch.screen_now_plan([other, first, job(3, "SCREEN", state="received")], "gzqo")
    assert (plan.action, plan.job_id) == ("join", first.job_id)  # the earliest, whatever the order given


def test_another_study_is_not_joined() -> None:
    assert sch.screen_now_plan([job(2, "SCREEN", "OTHER")], "GZQO").action == "start"


@pytest.mark.parametrize("night", ["INGEST", "MICROBATCH", "NAV", "RETENTION"])
def test_a_request_during_the_night_is_queued_behind_it(night: str) -> None:
    plan = sch.screen_now_plan([job(1, night, "OTHER"), job(2, night, "GZQO", state="done")], "GZQO")
    assert (plan.action, plan.behind, plan.job_id) == ("queue", 1, None)


def test_a_study_running_wins_over_the_night() -> None:
    both = [job(1, "INGEST", None), job(2, "SCREEN")]
    assert sch.screen_now_plan(both, "GZQO").action == "join"


def test_the_time_expected_is_the_median_of_the_last_runs_per_1000_patients() -> None:
    done = [job(1, "SCREEN", state="done", wall=300, scoped=600), job(2, "MICROBATCH", state="done", wall=100, scoped=100),
            job(3, "SCREEN", state="done", wall=900, scoped=1000), job(4, "SCREEN", "OTHER", state="done", wall=1, scoped=1000)]  # fmt: skip
    assert sch.per_1000_seconds(done, "GZQO") == 900.0  # 500, 1000, 900 per 1,000: the median
    assert sch.per_1000_seconds(done[:1], "GZQO") == 500.0


def test_no_measured_run_gives_no_time_never_a_made_up_one() -> None:
    assert sch.per_1000_seconds([], "GZQO") is None
    assert (
        sch.per_1000_seconds([job(1, "SCREEN", state="done", wall=5, scoped=0)], "GZQO") is None
    )  # no patients counted
    assert sch.per_1000_seconds([job(1, "SCREEN", state="failed", wall=5, scoped=9)], "GZQO") is None


def test_the_wait_behind_the_night_is_the_jobs_ahead_at_their_usual_time() -> None:
    ahead = [job(5, "INGEST", None), job(6, "MICROBATCH"), job(7, "SCREEN")]
    done = [job(1, "INGEST", None, "done", wall=60), job(2, "INGEST", None, "done", wall=100),
            job(3, "MICROBATCH", state="done", wall=500)]  # fmt: skip
    assert sch.expected_wait(ahead, done) == 600.0  # ingest 100 (the median of 60, 100 is the upper), micro-batch 500
    assert sch.expected_wait(ahead, done[:2]) is None  # a micro-batch with no earlier run: not known, not guessed
    assert sch.expected_wait([job(7, "SCREEN")], []) == 0.0
