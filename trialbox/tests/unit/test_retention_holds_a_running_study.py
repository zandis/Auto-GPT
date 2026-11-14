"""NEW-LIFE-9 (D-765, the deep review's LIFE-009, old LIFE-027; T-305c re-ordered): retention holds a running study.

RETENTION deleted attachments after 90 days and outputs after 365 by object age only, whatever the study's state:
the candidate list a mark was made on, the evidence shown, the review workbook and the protocol file the criteria were
compiled from were gone three to twelve months later while the study ran (GCP keeps the study file). Now an object of
a job that belongs to a study is held while that study is not ``closed``; a study whose state cannot be read is held
(keep rather than delete); after the close, the configured ages apply. Objects of no study (pilot requests, the
public ClinicalTrials.gov cache) keep their ages. Synthetic data only."""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from tb_contracts import JobCreate

from tests.inproc_box import make_box


def _box(tmp_path: Path) -> Any:
    sec = tmp_path / "sec"
    sec.mkdir()
    return make_box(tmp_path / "box", tmp_path / "lake", sec, date(2026, 10, 5))


def _put(box: Any, key: str, age_days: int) -> None:
    box.store.put(key, key.encode())
    t = (datetime.now(UTC) - timedelta(days=age_days)).timestamp()
    os.utime(box.store.root / key, (t, t))


def _retention(box: Any) -> dict[str, Any]:
    created = box.orch.create(JobCreate(type="RETENTION", requested_by="scheduler"))
    box.orch.drain()
    job = box.orch.db.get(created.job_id)
    assert job is not None and job.state == "done", job.error if job else None
    out = next(o for o in job.outputs if o.filename.startswith("retention_"))
    report: dict[str, Any] = json.loads(box.store.get(out.minio_key))
    return report


def _study_job(box: Any) -> str:
    """A finished SCREEN of study GZQO (its record only: the files below are its attachments and outputs)."""
    from tb_contracts import Job

    jid = "01JSTVDYSCREEN0000000000AA"
    box.orch.db.put(Job(job_id=jid, type="SCREEN", ruleset="GZQO", requested_by="crc@hospa.test",
                        received_at=datetime(2026, 1, 5, tzinfo=UTC), state="done"), queued=False)  # fmt: skip
    return jid


@pytest.mark.parametrize("state", ["open", "paused", "startup"])
def test_a_study_that_is_not_closed_keeps_its_old_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                        state: str) -> None:  # fmt: skip
    from orchestrator import scheduler

    box = _box(tmp_path)
    jid = _study_job(box)
    _put(box, f"attachments/{jid}/protocol.pdf", 120)
    _put(box, f"outputs/{jid}/candidate_list.xlsx", 400)
    _put(box, "attachments/J-PILOT/request.pdf", 120)  # of no study: its age applies
    monkeypatch.setattr(scheduler, "study_state", lambda rid, url=None: state)
    report = _retention(box)
    assert box.store.exists(f"attachments/{jid}/protocol.pdf") and box.store.exists(
        f"outputs/{jid}/candidate_list.xlsx"
    )
    assert not box.store.exists("attachments/J-PILOT/request.pdf")
    assert report["held_for_running_studies"] == 2


def test_a_closed_study_goes_by_the_ages_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator import scheduler

    box = _box(tmp_path)
    jid = _study_job(box)
    _put(box, f"attachments/{jid}/protocol.pdf", 120)
    monkeypatch.setattr(scheduler, "study_state", lambda rid, url=None: "closed")
    report = _retention(box)
    assert not box.store.exists(f"attachments/{jid}/protocol.pdf") and report["held_for_running_studies"] == 0


def test_a_study_whose_state_cannot_be_read_is_held(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator import scheduler

    def down(rid: str, url: str | None = None) -> str:
        raise RuntimeError("the trial database did not answer")

    box = _box(tmp_path)
    jid = _study_job(box)
    _put(box, f"attachments/{jid}/protocol.pdf", 120)
    monkeypatch.setattr(scheduler, "study_state", down)
    report = _retention(box)
    assert box.store.exists(f"attachments/{jid}/protocol.pdf") and report["held_for_running_studies"] == 1
