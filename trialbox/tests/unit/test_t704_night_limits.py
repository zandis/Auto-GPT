"""T-704 (D-458; scale review F-32, F-34, F-33): the night's shared limits.

The row's acceptance tests that are this card's (its chain is T-726's):

* three micro-batches started together with an allowance of 100: at most 100 evaluated and each study gets a share;
* RETENTION then MICROBATCH on a study with a 366-day-old SCREEN passes;

and one worker kept for the ingest. A real orchestrator, job store and object store; stand-in scenarios."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from orchestrator.core import Ctx, Orchestrator, Outcome, Services
from orchestrator.db import JobDB
from orchestrator.scenarios import microbatch, retention
from tb_common.audit import AuditLog
from tb_common.config import Config, load_env, load_settings
from tb_common.objstore import FsStore
from tb_contracts import JobCreate, SendRequest, SendResult

ROOT = Path(__file__).resolve().parents[2]
DAY = 86400.0


class Mail:
    def send(self, req: SendRequest) -> SendResult:
        return SendResult(message_id="<1@t>", sent_to=req.to, encrypted=bool(req.encrypt))


def _orch(tmp_path: Path, scenarios: dict[str, Any], workers: int = 0, budget: str | None = None) -> Orchestrator:
    env = {} if budget is None else {"TB_MICROBATCH_NIGHT_BUDGET": budget}
    cfg = Config(
        env=load_env(dotenv=tmp_path / "x.env", environ=env),
        settings=load_settings(ROOT / "deploy/settings.example.yaml"),
    )
    return Orchestrator(
        cfg,
        JobDB(),
        FsStore(tmp_path / "obj"),
        AuditLog(tmp_path / "audit"),
        Services(lake=None, parser=None, compiler=None, mail=Mail()),  # type: ignore[arg-type]
        scenarios,
        tmp_path / "rulesets",
        tmp_path,
        today=lambda: date(2026, 11, 16),
        workers=workers,
        async_notify=False,
    )


def _wait(orch: Orchestrator, ids: list[str], seconds: float = 60.0) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        jobs = [orch.db.get(i) for i in ids]
        if all(j is not None and j.state in ("done", "failed") for j in jobs):
            return
        time.sleep(0.05)
    raise AssertionError(f"jobs did not end: {[(j.job_id, j.state) for j in jobs if j is not None]}")


# ------------------------------------------------------------------------------------------- the allowance (F-32)
def test_three_micro_batches_started_together_share_an_allowance_of_100(tmp_path: Path) -> None:
    """The row's acceptance test. Three studies, each with 80 patients due, start at the same moment (they wait
    for each other at a barrier before any of them asks for its allowance). Before: each read "nobody has used
    anything yet" and took 100. Now the three reservations add up to at most 100 and every study gets some."""
    gate = threading.Barrier(3, timeout=30)
    took: dict[str, int] = {}
    done = getattr(microbatch, "night_done", lambda ctx, used: None)

    def micro(ctx: Ctx) -> Outcome:
        ctx.state("running")
        gate.wait()  # all three are running before any asks
        left = microbatch.night_left(ctx)
        assert left is not None
        used = min(80, left)  # this study has 80 patients due
        took[str(ctx.job.ruleset)] = used
        ctx.metrics(patients_scoped=used)
        done(ctx, used)
        return Outcome(summary_md=f"{used} evaluated")

    orch = _orch(tmp_path, {"MICROBATCH": micro}, workers=4, budget="100")
    ids = [orch.create(JobCreate(type="MICROBATCH", ruleset=r, requested_by="scheduler")).job_id for r in "ABC"]
    orch.start()
    try:
        _wait(orch, ids)
    finally:
        orch.stop()
    assert sorted(took) == ["A", "B", "C"]
    assert sum(took.values()) <= 100, took  # at most the allowance is evaluated
    assert all(n >= 20 for n in took.values()), took  # and each study gets a share, whatever its place in the order
    assert sum(took.values()) >= 98  # the shares use the allowance (34 + 33 + 33, in some order)


def test_what_a_study_does_not_use_is_there_for_the_next_and_a_resumed_job_keeps_its_share(tmp_path: Path) -> None:
    need = {"A": 5, "B": 80, "C": 80}
    took: dict[str, int] = {}
    lefts: dict[str, list[int | None]] = {}
    done = getattr(microbatch, "night_done", lambda ctx, used: None)

    def micro(ctx: Ctx) -> Outcome:
        ctx.state("running")
        rid = str(ctx.job.ruleset)
        left = microbatch.night_left(ctx)
        lefts.setdefault(rid, []).append(left)
        lefts[rid].append(microbatch.night_left(ctx))  # asked again (a resumed job): the same answer
        used = min(need[rid], left or 0)
        took[rid] = used
        ctx.metrics(patients_scoped=used)
        done(ctx, used)
        return Outcome(summary_md="ok")

    orch = _orch(tmp_path, {"MICROBATCH": micro}, budget="100")
    for r in "ABC":
        orch.create(JobCreate(type="MICROBATCH", ruleset=r, requested_by="scheduler"))
    orch.drain()
    assert all(a == b for a, b in lefts.values())
    # one after another: A is offered a third and uses 5; B half of the 95 left; C all that is left
    assert lefts["A"][0] == 34 and lefts["B"][0] == 48 and lefts["C"][0] == 47
    assert took == {"A": 5, "B": 48, "C": 47} and sum(took.values()) == 100


def test_no_allowance_means_no_limit(tmp_path: Path) -> None:
    seen: list[int | None] = []

    def micro(ctx: Ctx) -> Outcome:
        ctx.state("running")
        seen.append(microbatch.night_left(ctx))
        return Outcome(summary_md="ok")

    orch = _orch(tmp_path, {"MICROBATCH": micro}, budget="0")
    orch.create(JobCreate(type="MICROBATCH", ruleset="A", requested_by="scheduler"))
    orch.drain()
    assert seen == [None]


# ------------------------------------------------------------------------------------------- retention (F-34)
def _age(store_root: Path, key: str, days: float) -> None:
    p = store_root / key
    old = time.time() - days * DAY
    os.utime(p, (old, old))


def test_retention_then_a_micro_batch_on_a_study_whose_screen_is_366_days_old(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row's acceptance test. The study's last SCREEN is 366 days old. Retention ran, and the micro-batch's
    first step (reading whom the study has seen) then failed for ever. Now the lists an open study's next
    micro-batch reads are kept; everything else of that age goes, and a closed study's lists go too."""
    from orchestrator import scheduler

    state = {"OPEN1": "open", "SHUT1": "closed"}
    monkeypatch.setattr(scheduler, "study_state", lambda rid, url=None: state[rid])
    monkeypatch.setattr(retention, "prune_mail_logs", lambda before_iso, before_day: {})

    def screen(ctx: Ctx) -> Outcome:
        ctx.state("running")
        rid = str(ctx.job.ruleset)
        rows = {"rows": [{"pid": f"{rid}-p1"}, {"pid": f"{rid}-p2"}]}
        ctx.publish(f"candidate_list_{rid}.json", json.dumps(rows).encode(), "phi", [])
        ctx.publish(f"excluded_{rid}.json", json.dumps({"rows": [{"pid": f"{rid}-x"}]}).encode(), "phi", [])
        ctx.publish(f"screen_{rid}.pdf", b"%PDF the report", "phi", [])
        return Outcome(summary_md="ok")

    seen: dict[str, Any] = {}

    def micro(ctx: Ctx) -> Outcome:
        ctx.state("running")
        rs: Any = type("Rs", (), {"id": ctx.job.ruleset})()
        keys = microbatch.seen_sources(ctx, rs)
        seen[str(ctx.job.ruleset)] = sorted(microbatch.read_seen(ctx, keys)[0])
        return Outcome(summary_md="ok")

    orch = _orch(tmp_path, {"SCREEN": screen, "MICROBATCH": micro, "RETENTION": retention.run})
    jobs = {r: orch.create(JobCreate(type="SCREEN", ruleset=r, requested_by="crc1@hospa.test")).job_id for r in state}
    orch.drain()
    at = "2025-11-15T03:00:00+08:00"
    for rid, jid in jobs.items():
        orch.db.pool_upsert(rid, "1", [{"pid": f"{rid}-p1", "tier": "high", "verdicts": []}], jid, at)
    root = tmp_path / "obj"
    keys = sorted(o.key for o in orch.store.list("outputs/"))
    assert len(keys) == 6
    for k in keys:
        _age(root, k, 366)
    orch.create(JobCreate(type="RETENTION", requested_by="scheduler"))
    orch.drain()
    left = sorted(o.key.rsplit("/", 1)[1] for o in orch.store.list("outputs/") if "retention_" not in o.key)
    assert left == ["candidate_list_OPEN1.json", "excluded_OPEN1.json"]  # the PDF, and the closed study's lists, went
    report = json.loads(next(orch.store.get(o.key) for o in orch.store.list("outputs/") if "retention_" in o.key))
    assert report["objects_deleted"] == 4 and report["kept_for_open_studies"] == 2
    # the micro-batch's first step on the open study passes
    mb = orch.create(JobCreate(type="MICROBATCH", ruleset="OPEN1", requested_by="scheduler")).job_id
    orch.drain()
    got = orch.db.get(mb)
    assert got is not None
    assert got.state == "done", got.error
    assert seen["OPEN1"] == ["OPEN1-p1", "OPEN1-p2", "OPEN1-x"]
    # the study is screened again: the old lists are no longer what its next micro-batch reads, and they go
    orch.create(JobCreate(type="SCREEN", ruleset="OPEN1", requested_by="crc1@hospa.test"))
    orch.create(JobCreate(type="RETENTION", requested_by="scheduler", options={"again": "1"}))
    orch.drain()
    names = sorted(o.key for o in orch.store.list("outputs/") if "retention_" not in o.key)
    assert len(names) == 3 and not any(jobs["OPEN1"] in k for k in names)  # only the new SCREEN's three outputs


def test_a_study_whose_state_cannot_be_read_keeps_its_lists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator import scheduler

    def down(rid: str, url: str | None = None) -> str:
        raise RuntimeError("the trial database is down")

    monkeypatch.setattr(scheduler, "study_state", down)
    monkeypatch.setattr(retention, "prune_mail_logs", lambda before_iso, before_day: {})

    def screen(ctx: Ctx) -> Outcome:
        ctx.state("running")
        ctx.publish("candidate_list_X.json", b'{"rows": []}', "phi", [])
        return Outcome(summary_md="ok")

    orch = _orch(tmp_path, {"SCREEN": screen, "RETENTION": retention.run})
    jid = orch.create(JobCreate(type="SCREEN", ruleset="GZQO", requested_by="crc1@hospa.test")).job_id
    orch.drain()
    orch.db.pool_upsert("GZQO", "1", [{"pid": "p1", "tier": "high", "verdicts": []}], jid, "2025-11-15T03:00:00+08:00")
    (key,) = [o.key for o in orch.store.list("outputs/")]
    _age(tmp_path / "obj", key, 400)
    orch.create(JobCreate(type="RETENTION", requested_by="scheduler"))
    orch.drain()
    assert key in [o.key for o in orch.store.list("outputs/")]


# ------------------------------------------------------------------------------------------- the ingest's worker
def test_one_worker_is_kept_for_the_ingest(tmp_path: Path) -> None:
    """F-33: long jobs took every worker and the night's ingest waited behind them. With two workers one is the
    ingest's: the ingest runs while a long job runs, and a second long job waits for the other worker."""
    release = threading.Event()
    started: list[str] = []
    order: list[str] = []

    def long_job(ctx: Ctx) -> Outcome:
        started.append(str(ctx.job.ruleset))
        release.wait(timeout=60)
        order.append(f"SCREEN {ctx.job.ruleset}")
        return Outcome(summary_md="ok")

    def ingest(ctx: Ctx) -> Outcome:
        order.append("INGEST")
        return Outcome(summary_md="ok")

    orch = _orch(tmp_path, {"SCREEN": long_job, "INGEST": ingest}, workers=2)
    a = orch.create(JobCreate(type="SCREEN", ruleset="A", requested_by="crc1@hospa.test")).job_id
    b = orch.create(JobCreate(type="SCREEN", ruleset="B", requested_by="crc1@hospa.test")).job_id
    orch.start()
    try:
        end = time.monotonic() + 30
        while not started and time.monotonic() < end:
            time.sleep(0.02)
        ing = orch.create(JobCreate(type="INGEST", requested_by="scheduler")).job_id
        _wait(orch, [ing], 30)  # the ingest ends while the long job still runs
        assert order == ["INGEST"] and started == ["A"]  # and the second long job has not taken the ingest's worker
        release.set()
        _wait(orch, [a, b], 30)
    finally:
        release.set()
        orch.stop()
    assert order == ["INGEST", "SCREEN A", "SCREEN B"]


def test_a_box_with_one_worker_runs_everything_on_it(tmp_path: Path) -> None:
    ran: list[str] = []

    def any_job(ctx: Ctx) -> Outcome:
        ran.append(ctx.job.type)
        return Outcome(summary_md="ok")

    orch = _orch(tmp_path, {"SCREEN": any_job, "INGEST": any_job}, workers=1)
    ids = [
        orch.create(JobCreate(type="SCREEN", ruleset="A", requested_by="crc1@hospa.test")).job_id,
        orch.create(JobCreate(type="INGEST", requested_by="scheduler")).job_id,
    ]
    orch.start()
    try:
        _wait(orch, ids, 30)
    finally:
        orch.stop()
    assert ran == ["SCREEN", "INGEST"]
