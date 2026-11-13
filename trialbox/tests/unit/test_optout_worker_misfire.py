"""ARCH-003 (deep review `architecture`): the opt-out worker's scheduler has the box's misfire grace.

The night's and the console's schedulers take ``SCHEDULER_JOB_DEFAULTS`` (review F-14, D-130); the opt-out worker's
did not, so its interval job had APScheduler's own one-second grace: a tick the scheduler's thread reached late
under load was dropped, and an opt-out waited a whole interval more before it reached the stores."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from datacore import optout_worker
from tb_common.config import SCHEDULER_JOB_DEFAULTS

pytestmark = pytest.mark.nodb


def test_the_workers_job_has_the_boxs_misfire_grace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(optout_worker.MINUTES_ENV, "5")
    monkeypatch.setattr(optout_worker, "tick", lambda orch: None)  # no store is touched
    orch = SimpleNamespace(cfg=SimpleNamespace(env=SimpleNamespace(tz="Asia/Taipei")))
    sched = optout_worker.start(orch)
    assert sched is not None
    try:
        job = sched.get_job("optout-worker")
        assert job.misfire_grace_time == SCHEDULER_JOB_DEFAULTS["misfire_grace_time"]
        assert job.coalesce is True and job.max_instances == 1
    finally:
        sched.shutdown(wait=False)
