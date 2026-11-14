"""NEW-LIFE-9 (D-765, the deep review's LIFE-009, old LIFE-027; T-305c re-ordered): retention holds a running study.

RETENTION deleted attachments after 90 days and outputs after 365 by object age only, whatever the study's state:
the candidate list a mark was made on, the evidence shown, the review workbook and the protocol file the criteria were
compiled from were gone three to twelve months later while the study ran (GCP keeps the study file). Now an object of
a job whose ruleset is a study with a recorded state that is not ``closed`` is held; a study whose state cannot be
read is held (keep rather than delete); after the close, the configured ages apply. A ruleset the console never set
up as a study (no recorded state: a feasibility of a declined trial, a cohort, a case), a job of no ruleset and the
public ClinicalTrials.gov cache keep their ages. On the test's own trial database (the console's real state table).
Synthetic data only."""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from tb_contracts import JobCreate

from tests.inproc_box import make_box

JID = "01JSTVDYSCREEN0000000000AA"  # a SCREEN of study GZQO
FEAS = "01JFEASDEC11NED00000000000"  # a feasibility of a trial the site declined (never a study here)


def _box(tmp_path: Path) -> Any:
    sec = tmp_path / "sec"
    sec.mkdir()
    return make_box(tmp_path / "box", tmp_path / "lake", sec, date(2026, 10, 5))


def _put(box: Any, key: str, age_days: int) -> None:
    box.store.put(key, key.encode())
    t = (datetime.now(UTC) - timedelta(days=age_days)).timestamp()
    os.utime(box.store.root / key, (t, t))


def _job(box: Any, jid: str, type_: str, ruleset: str) -> None:
    from tb_contracts import Job

    box.orch.db.put(Job(job_id=jid, type=type_, ruleset=ruleset, requested_by="crc@hospa.test",
                        received_at=datetime(2026, 1, 5, tzinfo=UTC), state="done"), queued=False)  # fmt: skip


def _state(rid: str, state: str) -> None:
    """The console's own study state (``site.study_state``), as its state page writes it (a study with no row is
    open by default, so "open" is recorded by a pause and an open again)."""
    from console.sitestore import SiteStore

    moves = {"open": ["paused", "open"], "paused": ["paused"], "closed": ["closed"]}[state]
    store = SiteStore()
    for i, s in enumerate(moves):
        store.set_study_state(rid, s, "reason", "crc", f"2026-01-0{i + 2}T00:00:00+00:00")


def _retention(box: Any) -> dict[str, Any]:
    created = box.orch.create(JobCreate(type="RETENTION", requested_by="scheduler"))
    box.orch.drain()
    job = box.orch.db.get(created.job_id)
    assert job is not None and job.state == "done", job.error if job else None
    out = next(o for o in job.outputs if o.filename.startswith("retention_"))
    report: dict[str, Any] = json.loads(box.store.get(out.minio_key))
    return report


@pytest.mark.parametrize("state", ["open", "paused"])
def test_a_study_that_is_not_closed_keeps_its_old_files(tmp_path: Path, state: str) -> None:
    box = _box(tmp_path)
    _job(box, JID, "SCREEN", "GZQO")
    _state("GZQO", state)
    _put(box, f"attachments/{JID}/protocol.pdf", 120)
    _put(box, f"outputs/{JID}/candidate_list.xlsx", 400)
    _put(box, "attachments/J-PILOT/request.pdf", 120)  # of no study: its age applies
    report = _retention(box)
    assert box.store.exists(f"attachments/{JID}/protocol.pdf") and box.store.exists(f"outputs/{JID}/candidate_list.xlsx")
    assert not box.store.exists("attachments/J-PILOT/request.pdf")
    assert report["held_for_running_studies"] == 2


def test_a_closed_study_goes_by_the_ages_again(tmp_path: Path) -> None:
    box = _box(tmp_path)
    _job(box, JID, "SCREEN", "GZQO")
    _state("GZQO", "closed")
    _put(box, f"attachments/{JID}/protocol.pdf", 120)
    report = _retention(box)
    assert not box.store.exists(f"attachments/{JID}/protocol.pdf") and report["held_for_running_studies"] == 0


def test_a_ruleset_never_set_up_as_a_study_keeps_its_ages(tmp_path: Path) -> None:
    """The review of D-765 (F1): "no recorded state" is not a running study. A feasibility of a trial the site
    declined keeps its ages (its raw output is patient-level): retention is not switched off for every ruleset."""
    box = _box(tmp_path)
    _job(box, FEAS, "FEAS", "DECLINED1")
    _put(box, f"outputs/{FEAS}/feas_DECLINED1.raw.json", 400)
    report = _retention(box)
    assert not box.store.exists(f"outputs/{FEAS}/feas_DECLINED1.raw.json") and report["held_for_running_studies"] == 0


def test_a_study_whose_state_cannot_be_read_is_held(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator import scheduler

    def down(rid: str, url: str | None = None) -> str:
        raise RuntimeError("the trial database did not answer")

    box = _box(tmp_path)
    _job(box, JID, "SCREEN", "GZQO")
    _put(box, f"attachments/{JID}/protocol.pdf", 120)
    monkeypatch.setattr(scheduler, "recorded_study_state", down)
    report = _retention(box)
    assert box.store.exists(f"attachments/{JID}/protocol.pdf") and report["held_for_running_studies"] == 1


def test_a_running_studys_pool_is_kept_while_its_approval_has_lapsed(tmp_path: Path) -> None:
    """The review of D-765 (F3): the pool and marks of a running study whose ruleset is not approved today."""
    box = _box(tmp_path)
    old = (datetime.now(UTC) - timedelta(days=900)).isoformat()
    box.orch.db.pool_upsert("LAPSED1", "1.0.0", [{"pid": "p1", "tier": "high", "verdicts": {}}], "J0", old)
    box.orch.db.pool_upsert("RETIRED", "1.0.0", [{"pid": "p2", "tier": "high", "verdicts": {}}], "J0", old)
    _state("LAPSED1", "paused")
    _retention(box)
    assert "LAPSED1" in box.orch.db.pool_rulesets() and "RETIRED" not in box.orch.db.pool_rulesets()
