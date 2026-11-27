"""r2rerun R-A (integrator ruling c, 2026-11-27): a job's lake hold is released when the job fails and when the
orchestrator starts again. Before, three SCREEN jobs that had failed still held their snapshot, and the next night's
rebuild of it was refused as "lake busy" until each hold was deleted by hand (holds last 14 days)."""

from __future__ import annotations

import threading
import time
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from adapter.ndjson import snapshot_dir
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from lake.store import Lake
from orchestrator import core
from orchestrator.clients import StepFailed
from orchestrator.core import Ctx, Orchestrator, Outcome, Services
from orchestrator.db import JobDB
from tb_common.audit import AuditLog
from tb_common.config import Config, load_env, load_settings
from tb_common.objstore import FsStore
from tb_contracts import JobCreate, JobError

ROOT = Path(__file__).resolve().parents[2]
NIGHT = "2026-10-04"
TZ = "Asia/Taipei"


class _DownMail:
    """A mail gateway that cannot be reached: the connection itself fails (not a ServiceError)."""

    def send(self, req: Any) -> Any:
        raise ConnectionRefusedError(111, "Connection refused")


def _lake(tmp_path: Path) -> Path:
    lake_dir = tmp_path / "lake"
    d = snapshot_dir(lake_dir, NIGHT)
    d.mkdir(parents=True)
    (d / "Patient.ndjson").write_text(
        "".join(f'{{"resourceType":"Patient","id":"p{i:04d}","gender":"female"}}\n' for i in range(3)),
        encoding="utf-8",
    )
    Lake(lake_dir, TZ).rebuild(NIGHT, HashEmbedder(), allow_empty=True)
    return lake_dir


def _orch(tmp_path: Path, scenario: Any, lake_dir: Path, db: JobDB | None = None) -> Orchestrator:
    cfg = Config(env=load_env(dotenv=tmp_path / "x.env", environ={}),
                 settings=load_settings(ROOT / "deploy/settings.example.yaml"))  # fmt: skip
    lake = LakeLocal(lake_dir, HashEmbedder(), TZ)
    services = Services(lake=lake, parser=None, compiler=None, mail=_DownMail())  # type: ignore[arg-type]
    return Orchestrator(cfg, db or JobDB(), FsStore(tmp_path / "obj"), AuditLog(tmp_path / "audit"), services,
                        {"FEAS": scenario}, tmp_path / "rulesets", tmp_path, today=lambda: date(2026, 10, 5),
                        workers=0, async_notify=False)  # fmt: skip


def test_a_failed_job_releases_its_hold_even_when_its_failed_mail_cannot_go(tmp_path: Path) -> None:
    lake_dir = _lake(tmp_path)
    seen: dict[str, Any] = {}

    def scenario(ctx: Ctx) -> Outcome:
        ctx.state("running")
        ctx.services.lake.query("SELECT count(*) AS n FROM patient")
        seen["holds"] = Lake(lake_dir, TZ).holds()
        raise StepFailed("running", "the screen could not finish")

    orch = _orch(tmp_path, scenario, lake_dir)
    job = orch.create(JobCreate(type="FEAS", ruleset="GZQO", requested_by="crc1@hospa.test"), notify=False)
    orch.drain()
    got = orch.db.get(job.job_id)
    assert got is not None and got.state == "failed", got
    assert seen["holds"] == {job.job_id: NIGHT}  # the job held its snapshot while it ran
    assert Lake(lake_dir, TZ).holds() == {}, "the failed job still holds the snapshot"


def test_a_start_releases_the_holds_of_ended_jobs_and_keeps_the_others(tmp_path: Path) -> None:
    lake_dir = _lake(tmp_path)

    def scenario(ctx: Ctx) -> Outcome:
        return Outcome(summary_md="ok")

    db = JobDB()
    orch = _orch(tmp_path, scenario, lake_dir, db)
    ended = orch.create(JobCreate(type="FEAS", ruleset="GZQO", requested_by="scheduler"), notify=False)
    orch.set_state(ended, "failed", error=JobError(step="running", message="killed"))
    waiting = orch.create(JobCreate(type="FEAS", ruleset="RA-JAK", requested_by="scheduler"), notify=False)
    lake = Lake(lake_dir, TZ)
    # the process died between each job's end and its release: the holds are still on the lake
    for holder in (ended.job_id, waiting.job_id, "sitesetup-publish"):
        lake.hold(NIGHT, holder, pin=True)

    again = _orch(tmp_path, scenario, lake_dir, db)  # the orchestrator starts again on the same job database
    again.start()
    again.stop()
    left = Lake(lake_dir, TZ).holds()
    assert ended.job_id not in left, "an ended job's hold outlived the restart"
    assert set(left) == {waiting.job_id, "sitesetup-publish"}  # an unfinished job and a non-job keep theirs


def test_the_next_job_to_end_releases_a_hold_the_start_could_not(tmp_path: Path) -> None:
    lake_dir = _lake(tmp_path)

    def scenario(ctx: Ctx) -> Outcome:
        ctx.state("running")
        ctx.services.lake.query("SELECT count(*) AS n FROM patient")
        return Outcome(summary_md="ok")

    orch = _orch(tmp_path, scenario, lake_dir)
    ended = orch.create(JobCreate(type="FEAS", ruleset="GZQO", requested_by="scheduler"), notify=False)
    orch.set_state(ended, "failed", error=JobError(step="running", message="killed"))
    Lake(lake_dir, TZ).hold(NIGHT, ended.job_id, pin=True)  # left by a process that died; the lake was down at start
    nxt = orch.create(JobCreate(type="FEAS", ruleset="RA-JAK", requested_by="scheduler"), notify=False)
    orch.drain()
    got = orch.db.get(nxt.job_id)
    assert got is not None and got.state == "done", got
    assert Lake(lake_dir, TZ).holds() == {}, "the ended job's hold outlived the next job"


class _LateLake:
    """The lake client of a box's boot: its holds cannot be read until the lake is up."""

    def __init__(self, inner: Any) -> None:
        self.inner, self.up, self.tries = inner, threading.Event(), 0

    def holds(self) -> Any:
        self.tries += 1
        if not self.up.is_set():
            raise ConnectionRefusedError(111, "Connection refused")
        return self.inner.holds()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


def test_a_start_that_met_a_lake_not_up_releases_the_holds_once_it_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex R-A-1: no other job ends after the start (none may come before the night's rebuild); the start's sweep
    is tried again until the lake answers."""
    monkeypatch.setattr(core, "HOLD_SWEEP_RETRY", 0.05)
    lake_dir = _lake(tmp_path)

    def scenario(ctx: Ctx) -> Outcome:
        return Outcome(summary_md="ok")

    db = JobDB()
    orch = _orch(tmp_path, scenario, lake_dir, db)
    ended = orch.create(JobCreate(type="FEAS", ruleset="GZQO", requested_by="scheduler"), notify=False)
    orch.set_state(ended, "failed", error=JobError(step="running", message="killed"))
    waiting = orch.create(JobCreate(type="FEAS", ruleset="RA-JAK", requested_by="scheduler"), notify=False)
    for holder in (ended.job_id, waiting.job_id, "sitesetup-publish"):
        Lake(lake_dir, TZ).hold(NIGHT, holder, pin=True)

    again = _orch(tmp_path, scenario, lake_dir, db)
    late = _LateLake(again.services.lake)
    again.services.lake = late  # type: ignore[assignment]
    again.start()
    try:
        deadline = time.monotonic() + 5
        while late.tries < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert late.tries >= 2, "the start's sweep was not tried again"
        assert ended.job_id in Lake(lake_dir, TZ).holds()  # the lake still down: nothing released
        late.up.set()
        while ended.job_id in Lake(lake_dir, TZ).holds() and time.monotonic() < deadline:
            time.sleep(0.01)
        left = Lake(lake_dir, TZ).holds()
        assert ended.job_id not in left, "an ended job's hold waited for another job to end"
        assert set(left) == {waiting.job_id, "sitesetup-publish"}
        assert again.workers_alive() == (0, 0)  # the sweep is not a worker: the health line stays as it was
    finally:
        again.stop()
