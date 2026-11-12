"""Snapshot pinning (T-305a, D-383, CR-063): a job reads one lake snapshot from start to end; a stale one is refused.

Synthetic patients only. The clock is frozen through the orchestrator's ``today`` (the job's run date)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from lake.store import Lake, StaleSnapshotError, check_snapshot_age, snapshot_age_days
from orchestrator.core import Ctx, Orchestrator, Outcome, Services
from orchestrator.db import JobDB
from orchestrator.jobs import PinnedLake
from tb_common.audit import AuditLog
from tb_common.config import Config, ConfigError, load_env, load_settings
from tb_common.objstore import FsStore
from tb_contracts import JobCreate

ROOT = Path(__file__).resolve().parents[2]
NIGHT_1 = "2026-10-04"
NIGHT_2 = "2026-10-05"
COUNT = "SELECT count(*) AS n FROM patient"


def _patients(n: int) -> list[dict[str, Any]]:
    return [
        {
            "resourceType": "Patient",
            "id": f"syn-{i:03d}",
            "gender": "female" if i % 2 else "male",
            "birthDate": f"19{50 + i}-01-0{1 + i % 9}",
        }
        for i in range(n)
    ]


def _night(lake_dir: Path, snap: str, n: int) -> None:
    """One synthetic night: ``n`` patients written as the adapter writes them, built and made CURRENT."""
    nd = lake_dir / "ndjson" / snap
    nd.mkdir(parents=True, exist_ok=True)
    (nd / "Patient.ndjson").write_text("".join(json.dumps(p) + "\n" for p in _patients(n)), encoding="utf-8")
    Lake(lake_dir, "Asia/Taipei").rebuild(snap, HashEmbedder())


def _count(lake: Any, snapshot: str | None = None) -> int:
    return int(lake.query(COUNT, [], snapshot).to_pylist()[0]["n"])


@pytest.fixture
def make(tmp_path: Path) -> Any:
    def build(scenarios: dict[str, Any], today: date, max_age: int, lake: Any) -> Orchestrator:
        environ = {"TB_LAKE_MAX_SNAPSHOT_AGE_DAYS": str(max_age)}
        cfg = Config(
            env=load_env(dotenv=tmp_path / "x.env", environ=environ),
            settings=load_settings(ROOT / "deploy/settings.example.yaml"),
        )
        services = Services(lake=lake, parser=None, compiler=None, mail=_Mail())  # type: ignore[arg-type]
        return Orchestrator(
            cfg,
            JobDB(),
            FsStore(tmp_path / "obj"),
            AuditLog(tmp_path / "audit"),
            services,
            scenarios,
            tmp_path / "rulesets",
            tmp_path,
            today=lambda: today,
            workers=0,
            async_notify=False,
        )

    return build


class _Mail:
    def send(self, req: Any) -> Any:
        from tb_contracts import SendResult

        return SendResult(message_id="<1@t>", sent_to=req.to, encrypted=False)


def _run(orch: Orchestrator) -> Any:
    job = orch.create(JobCreate(type="FEAS", ruleset="GZQO", requested_by="scheduler"))
    orch.drain()
    got = orch.db.get(job.job_id)
    assert got is not None
    return got


# ------------------------------------------------------------------ the age check (lake.store)


def test_snapshot_age_on_a_frozen_clock() -> None:
    assert snapshot_age_days("2026-10-04", date(2026, 10, 7)) == 3
    assert snapshot_age_days("2026-10-08", date(2026, 10, 7)) == 0  # a feed ahead of a pinned clock is not stale
    assert check_snapshot_age("2026-10-04", date(2026, 10, 7), 3) == 3  # exactly the limit passes
    with pytest.raises(StaleSnapshotError, match="LAKE-STALE.*4 days before 2026-10-08.*more than 3 days"):
        check_snapshot_age("2026-10-04", date(2026, 10, 8), 3)
    assert check_snapshot_age("2026-01-01", date(2026, 10, 8), 0) is None  # 0: no check
    with pytest.raises(StaleSnapshotError, match="not named after a night"):
        check_snapshot_age("latest", date(2026, 10, 8), 3)


def test_lake_pin_refuses_a_stale_current(tmp_path: Path) -> None:
    lake = Lake(tmp_path / "lake", "Asia/Taipei")
    (tmp_path / "lake" / "db" / f"{NIGHT_1}.duckdb").write_bytes(b"")
    lake.promote(NIGHT_1)
    assert lake.pin(date(2026, 10, 6), 3) == NIGHT_1
    with pytest.raises(StaleSnapshotError):
        lake.pin(date(2026, 10, 9), 3)


def test_max_age_is_a_declared_config_value(tmp_path: Path) -> None:
    assert load_env(dotenv=tmp_path / "x.env", environ={}).lake_max_snapshot_age_days == 0
    env = load_env(dotenv=tmp_path / "x.env", environ={"TB_LAKE_MAX_SNAPSHOT_AGE_DAYS": "3"})
    assert env.lake_max_snapshot_age_days == 3 and "TB_LAKE_MAX_SNAPSHOT_AGE_DAYS" not in env.extra
    with pytest.raises(ConfigError, match="TB_LAKE_MAX_SNAPSHOT_AGE_DAYS"):
        load_env(dotenv=tmp_path / "x.env", environ={"TB_LAKE_MAX_SNAPSHOT_AGE_DAYS": "-1"})
    compose = (ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8")
    assert 'TB_LAKE_MAX_SNAPSHOT_AGE_DAYS: "${TB_LAKE_MAX_SNAPSHOT_AGE_DAYS:-3}"' in compose  # on in production


# ------------------------------------------------------------------ pinning (orchestrator)


def test_a_job_started_before_a_publish_finishes_on_its_own_snapshot(make: Any, tmp_path: Path) -> None:
    lake_dir = tmp_path / "lake"
    _night(lake_dir, NIGHT_1, 3)
    seen: dict[str, Any] = {}

    def scenario(ctx: Ctx) -> Outcome:
        ctx.state("running")
        lake = ctx.services.lake
        seen["pinned"] = lake.snapshot()
        seen["before"] = _count(lake)
        if Lake(lake_dir).current() != NIGHT_2:  # T-305b: a held night is never rebuilt under its own job
            _night(lake_dir, NIGHT_2, 5)  # the next night publishes while the job runs
        seen["current"] = Lake(lake_dir).current()
        seen["after"] = _count(lake)  # no snapshot named: the job's own
        lake.chunks_search("syn-001", "gout")  # the note search names it too
        return Outcome(summary_md="ok")

    class Spy(LakeLocal):
        def chunks_search(self, *args: Any, snapshot: str | None = None, **kw: Any) -> list[dict[str, Any]]:
            seen["search_on"] = snapshot
            return []

    local = Spy(lake_dir, HashEmbedder(), "Asia/Taipei")
    orch = make({"FEAS": scenario}, date(2026, 10, 5), 3, local)
    job = _run(orch)
    assert job.state == "done", job.error
    assert seen["pinned"] == NIGHT_1 and seen["current"] == NIGHT_2
    assert seen["before"] == seen["after"] == 3 and seen["search_on"] == NIGHT_1
    assert job.snapshot_date == date.fromisoformat(NIGHT_1)  # the pin field, recorded on the job
    assert _count(local) == 5  # the next job reads the new night
    again = _run(orch)
    assert again.state == "done" and again.snapshot_date == date.fromisoformat(NIGHT_2)


def test_a_stale_snapshot_is_refused_on_a_frozen_clock(make: Any, tmp_path: Path) -> None:
    lake_dir = tmp_path / "lake"
    _night(lake_dir, NIGHT_1, 2)
    queried: list[int] = []

    def scenario(ctx: Ctx) -> Outcome:
        ctx.state("running")
        queried.append(_count(ctx.services.lake))
        return Outcome(summary_md="ok")

    local = LakeLocal(lake_dir, HashEmbedder(), "Asia/Taipei")
    stale = _run(make({"FEAS": scenario}, date(2026, 10, 8), 3, local))  # 4 days after the night
    assert stale.state == "failed" and stale.error is not None
    assert stale.error.message.startswith("LAKE-STALE") and "TB_LAKE_MAX_SNAPSHOT_AGE_DAYS" in stale.error.message
    assert queried == [] and stale.snapshot_date is None  # refused before any read; nothing pinned
    fresh = _run(make({"FEAS": scenario}, date(2026, 10, 7), 3, local))  # 3 days: still allowed
    assert fresh.state == "done" and queried == [2]
    off = _run(make({"FEAS": scenario}, date(2026, 12, 1), 0, local))  # 0: the check is off
    assert off.state == "done"


def test_a_job_that_never_reads_the_lake_is_not_refused(make: Any, tmp_path: Path) -> None:
    lake_dir = tmp_path / "lake"
    _night(lake_dir, NIGHT_1, 1)

    def scenario(ctx: Ctx) -> Outcome:
        ctx.state("running")
        return Outcome(summary_md="ok")

    job = _run(make({"FEAS": scenario}, date(2027, 1, 1), 3, LakeLocal(lake_dir, HashEmbedder(), "Asia/Taipei")))
    assert job.state == "done" and job.snapshot_date is None


def test_a_recorded_pin_is_kept_and_not_checked_again() -> None:
    calls: list[tuple[str, str | None]] = []

    class Fake:
        def snapshot(self) -> str:
            raise AssertionError("a recorded pin never reads CURRENT")

        def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any:
            calls.append((sql, snapshot))
            return None

    lake = PinnedLake(Fake(), today=lambda: date(2027, 6, 1), max_age_days=3, pinned=NIGHT_1)
    assert lake.snapshot() == NIGHT_1  # a resumed job, or a reproducibility re-run of an old job
    lake.query("SELECT 1")
    lake.query("SELECT 2", [], NIGHT_2)  # a query that names its snapshot keeps it
    assert calls == [("SELECT 1", NIGHT_1), ("SELECT 2", NIGHT_2)]
