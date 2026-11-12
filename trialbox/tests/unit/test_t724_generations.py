"""T-724 (D-490; lifecycle review F-5, F-1; root cause S3): a lake generation.

A generation is the snapshot date plus a sequence number, with its cause and the lake's hash. A rebuild makes a new
generation and never rewrites one; a job pins a generation; the date stays as an alias. The row's acceptance test:
a job is byte-identical across a site publish. Around it, each state change interrupted once: a swap that dies
between the generation's file and the alias, a job started again after a restart, two jobs on two generations, a
file system without hard links. Synthetic patients, a real lake."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from lake.store import Lake, SnapshotHeld

from tests.unit.test_snapshot_holds import NIGHT, TZ, _night, _orch

SITE = {"Patient": [{"resourceType": "Patient", "id": "site-001", "gender": "male"}]}
ROWS = "SELECT pid, sex FROM patient ORDER BY pid"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _publish(lake_dir: Path) -> Any:
    """What a site publish does on the hospital's lake: put the site's inputs, build the served date again."""
    lake = Lake(lake_dir, TZ)
    lake.put_site(SITE)
    return lake.rebuild(NIGHT, HashEmbedder())


def _rows(lake: Any, snapshot: str | None = None) -> bytes:
    return json.dumps(lake.query(ROWS, snapshot=snapshot).to_pylist(), sort_keys=True).encode()


# ------------------------------------------------------------------------------------------- the generation itself
def test_a_rebuild_makes_a_new_generation_and_the_date_is_an_alias_of_the_newest(tmp_path: Path) -> None:
    lake_dir = tmp_path / "lake"
    _night(lake_dir, NIGHT, 3)
    lake = Lake(lake_dir, TZ)
    alias = lake.db_path(NIGHT)
    (g1,) = lake.generations(NIGHT)
    assert g1["generation"] == f"{NIGHT}.g1" == lake.generation(NIGHT) and (g1["snapshot"], g1["seq"]) == (NIGHT, 1)
    assert g1["cause"] == "night" and g1["sha256"] == _sha(alias) and g1["built_at"]
    first = lake.db_path(g1["generation"])
    assert first.parent.name == "gen" and first.stat().st_ino == alias.stat().st_ino  # the date is a link, no copy
    old_rows, old_sha = _rows(lake), _sha(first)
    stats = _publish(lake_dir)
    assert stats.generation == f"{NIGHT}.g2" == lake.generation(NIGHT)
    (g2,) = lake.generations(NIGHT)  # nobody held g1: it went at the swap, with its record
    assert (g2["seq"], g2["cause"]) == (2, "republish") and g2["sha256"] == _sha(alias) != old_sha
    assert not first.exists() and not first.with_suffix(".json").exists()
    assert _rows(lake) != old_rows and _rows(lake) == _rows(lake, g2["generation"])
    assert lake.current() == NIGHT and lake.snapshots() == [NIGHT] and lake.verify(NIGHT) == []
    with pytest.raises(FileNotFoundError, match="generation"):
        lake.db_path(f"{NIGHT}.g1")
    assert lake.rebuild(NIGHT, HashEmbedder(), cause="backfill").generation == f"{NIGHT}.g3"
    assert lake.generations(NIGHT)[-1]["cause"] == "backfill"


# ------------------------------------------------------------------------------------------- the acceptance test
def _run_job(tmp_path: Path, name: str, publish_mid_job: bool) -> dict[str, Any]:
    """One job that reads the lake three ways and hashes all it read; with ``publish_mid_job`` the site publishes
    between its reads. Returns what the job saw."""
    from orchestrator.core import Ctx, Outcome
    from tb_contracts import JobCreate

    lake_dir = tmp_path / name / "lake"
    nd = lake_dir / "ndjson" / NIGHT
    nd.mkdir(parents=True)
    note = {
        "resourceType": "DocumentReference",
        "id": "d1",
        "subject": {"reference": "Patient/syn-000"},
        "date": "2026-09-01T09:00:00+08:00",
        "type": {"text": "progress"},
        "content": [{"attachment": {"contentType": "text/plain",
                                    "data": base64.b64encode(b"No history of stroke. Gout flare last year.").decode()}}],
    }  # fmt: skip
    (nd / "DocumentReference.ndjson").write_text(json.dumps(note) + "\n", encoding="utf-8")
    _night(lake_dir, NIGHT, 3)
    seen: dict[str, Any] = {}

    def scenario(ctx: Ctx) -> Outcome:
        ctx.state("running")
        lake = ctx.services.lake
        parts = [_rows(lake)]
        seen["holds"] = Lake(lake_dir, TZ).holds()
        if publish_mid_job:
            seen["published"] = _publish(lake_dir).generation  # not refused, and the job is not waited for
        parts.append(_rows(lake))
        hits = lake.chunks_search("syn-000", "gout", 3)
        assert hits, "the note search reads the job's generation too"
        parts.append(json.dumps(hits, default=str, sort_keys=True).encode())
        parts.append(_rows(lake, lake.snapshot()))  # a caller that names the job's date reads the job's generation
        seen["digest"] = hashlib.sha256(b"|".join(parts)).hexdigest()
        seen["unpinned"] = _rows(Lake(lake_dir, TZ))
        return Outcome(summary_md="ok")

    orch = _orch(tmp_path / name, scenario, LakeLocal(lake_dir, HashEmbedder(), TZ))
    job = orch.create(JobCreate(type="FEAS", ruleset="GZQO", requested_by="scheduler"))
    orch.drain()
    got = orch.db.get(job.job_id)
    assert got is not None and got.state == "done", got
    seen["job"] = got
    assert seen["holds"] == {job.job_id: NIGHT} and Lake(lake_dir, TZ).holds() == {}
    return seen


def test_a_job_is_byte_identical_across_a_site_publish(tmp_path: Path) -> None:
    """The row's acceptance test. The same job, once on a quiet lake and once with a site publish between its
    reads: everything it read is the same, byte for byte. The publish made generation 2 at once (it was not
    refused and did not wait), and a reader by date saw it at once."""
    quiet, busy = _run_job(tmp_path, "quiet", False), _run_job(tmp_path, "busy", True)
    assert quiet["digest"] == busy["digest"]
    assert busy["published"] == f"{NIGHT}.g2" and busy["unpinned"] != quiet["unpinned"]
    for seen in (quiet, busy):  # the job's record names the generation it read, and its date as before
        assert (seen["job"].options or {})["lake_generation"] == f"{NIGHT}.g1"
        assert seen["job"].snapshot_date == date.fromisoformat(NIGHT)


def test_the_jobs_reads_are_the_same_bytes_before_and_after_the_publish(tmp_path: Path) -> None:
    """The acceptance, on the lake itself: pin, read, publish, read. The pinned generation's file and rows do not
    change; the hold names the generation; the held generation is kept until its job ends, then goes at the next
    swap."""
    lake_dir = tmp_path / "lake"
    _night(lake_dir, NIGHT, 3)
    lake = Lake(lake_dir, TZ)
    gen = lake.hold(NIGHT, "01SCREENJOB", pin=True)
    assert gen == f"{NIGHT}.g1" and lake.holds() == {"01SCREENJOB": NIGHT}
    file = lake.db_path(gen)
    before = (_sha(file), _rows(lake, gen))
    stats = _publish(lake_dir)  # not refused: a generation hold never blocks a rebuild
    assert stats.generation == f"{NIGHT}.g2" and stats.promoted
    assert (_sha(file), _rows(lake, gen)) == before  # the job's bytes and rows, untouched
    assert _rows(lake) != before[1] and _rows(lake) == _rows(lake, f"{NIGHT}.g2")
    assert [g["generation"] for g in lake.generations(NIGHT)] == [f"{NIGHT}.g1", f"{NIGHT}.g2"]  # g1 is kept: held
    _publish(lake_dir)
    assert [g["seq"] for g in lake.generations(NIGHT)] == [1, 3]  # g2: nobody's, gone; g1: still the job's
    lake.release("01SCREENJOB")
    _publish(lake_dir)
    assert [g["seq"] for g in lake.generations(NIGHT)] == [4] and not file.exists()


def test_a_hold_on_the_date_itself_still_keeps_the_date_still(tmp_path: Path) -> None:
    """D-403 and D-462 as they were, for a caller that reads by date: the date is not rebuilt under it."""
    lake_dir = tmp_path / "lake"
    _night(lake_dir, NIGHT, 2)
    lake = Lake(lake_dir, TZ)
    assert lake.hold(NIGHT, "01BYDATE") == NIGHT
    with pytest.raises(SnapshotHeld):
        lake.rebuild(NIGHT, HashEmbedder(), allow_empty=True)
    assert [g["seq"] for g in lake.generations(NIGHT)] == [1]


# ------------------------------------------------------------------------------------------- interrupted
def test_a_swap_that_dies_before_the_alias_moves_leaves_the_date_on_its_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Killed(BaseException):
        pass

    lake_dir = tmp_path / "lake"
    _night(lake_dir, NIGHT, 3)
    lake = Lake(lake_dir, TZ)
    before = (_sha(lake.db_path(NIGHT)), _rows(lake))
    real = os.link
    calls = {"n": 0}

    def dies(src: Any, dst: Any, *a: Any, **k: Any) -> None:
        if str(dst).endswith(".alias"):  # the generation's file is written; the date's alias is not yet moved
            calls["n"] += 1
            raise Killed
        real(src, dst, *a, **k)

    monkeypatch.setattr(os, "link", dies)
    lake.put_site(SITE)
    with pytest.raises(Killed):
        lake.rebuild(NIGHT, HashEmbedder())
    monkeypatch.setattr(os, "link", real)
    assert calls["n"] == 1
    # the date still names generation 1, whole; the unfinished generation 2 is nobody's newest
    assert lake.generation(NIGHT) == f"{NIGHT}.g1" and (_sha(lake.db_path(NIGHT)), _rows(lake)) == before
    assert lake.verify(NIGHT) == []
    stats = lake.rebuild(NIGHT, HashEmbedder())  # the next rebuild goes, and sweeps the leftover
    assert stats.generation == f"{NIGHT}.g3" and [g["seq"] for g in lake.generations(NIGHT)] == [3]
    assert sorted(p.name for p in (lake_dir / "db" / "gen").iterdir()) == [f"{NIGHT}.g3.duckdb", f"{NIGHT}.g3.json"]


def test_a_job_started_again_pins_the_generation_its_record_names_or_fails(tmp_path: Path) -> None:
    from orchestrator.clients import StepFailed
    from orchestrator.jobs import PinnedLake

    lake_dir = tmp_path / "lake"
    _night(lake_dir, NIGHT, 3)
    local = LakeLocal(lake_dir, HashEmbedder(), TZ)
    recorded: list[str] = []
    first = PinnedLake(local, lambda: date(2026, 10, 5), 0, holder="01JOB", on_generation=recorded.append)
    rows = _rows(first)
    assert recorded == [f"{NIGHT}.g1"] and first.snapshot() == NIGHT
    _publish(lake_dir)
    # the orchestrator restarts: a new process, the job's record names its date and its generation
    again = PinnedLake(local, lambda: date(2026, 10, 5), 0, pinned=NIGHT, holder="01JOB", generation=recorded[0])
    assert _rows(again) == rows != _rows(local)  # generation 1 again, not the date's newest
    again.release()
    _publish(lake_dir)  # nobody holds generation 1 now: it goes
    gone = PinnedLake(local, lambda: date(2026, 10, 5), 0, pinned=NIGHT, holder="01JOB", generation=recorded[0])
    with pytest.raises(StepFailed, match="generation"):
        gone.query(ROWS)  # never the date's newest in its place


def test_two_jobs_on_two_generations_each_keep_their_own(tmp_path: Path) -> None:
    lake_dir = tmp_path / "lake"
    _night(lake_dir, NIGHT, 3)
    lake = Lake(lake_dir, TZ)
    a = lake.hold(NIGHT, "01JOBA", pin=True)
    rows_a = _rows(lake, a)
    _publish(lake_dir)
    b = lake.hold(NIGHT, "01JOBB", pin=True)
    assert (a, b) == (f"{NIGHT}.g1", f"{NIGHT}.g2") and _rows(lake, b) != rows_a
    lake.put_site({"Patient": []})
    lake.rebuild(NIGHT, HashEmbedder())
    assert [g["seq"] for g in lake.generations(NIGHT)] == [1, 2, 3] and _rows(lake, a) == rows_a
    assert lake.hold(a, "01JOBA", pin=True) == a  # holding again refreshes the same generation
    lake.release("01JOBA")
    lake.rebuild(NIGHT, HashEmbedder())
    assert [g["seq"] for g in lake.generations(NIGHT)] == [2, 4]


def test_without_hard_links_a_generation_is_a_copy_and_still_never_rewritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_links(*a: Any, **k: Any) -> None:
        raise OSError("this file system has no hard links")

    monkeypatch.setattr(os, "link", no_links)
    lake_dir = tmp_path / "lake"
    _night(lake_dir, NIGHT, 3)
    lake = Lake(lake_dir, TZ)
    gen = lake.hold(NIGHT, "01JOB", pin=True)
    before = (_sha(lake.db_path(gen)), _rows(lake, gen))
    assert lake.db_path(gen).stat().st_ino != lake.db_path(NIGHT).stat().st_ino
    _publish(lake_dir)
    assert (_sha(lake.db_path(gen)), _rows(lake, gen)) == before and _rows(lake) != before[1]


# ------------------------------------------------------------------------------------------- the service, pruning
def test_the_generation_travels_over_http_beside_the_date(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient
    from lake import app as lake_app
    from lake.client import LakeHttp

    lake_dir = tmp_path / "lake"
    _night(lake_dir, NIGHT, 3)
    lake = Lake(lake_dir, TZ)
    monkeypatch.setattr(lake_app, "lake", lambda: lake)
    http = LakeHttp("http://testserver")
    http.client = TestClient(lake_app.app)
    gen = http.hold(NIGHT, "01HTTP", pin=True)
    assert gen == f"{NIGHT}.g1" and http.holds() == {"01HTTP": NIGHT}
    assert http.generation() == http.generation(NIGHT) == gen == LakeLocal(lake_dir, HashEmbedder(), TZ).generation()
    assert http.client.get("/generations/2020-01-01").status_code == 404
    assert http.client.get("/generations/latest").status_code == 400
    before = _rows(http, gen)
    _publish(lake_dir)
    assert _rows(http, gen) == before != _rows(http) and _rows(http, NIGHT) == _rows(http)
    assert http.generation(NIGHT) == f"{NIGHT}.g2"
    assert http.hold(NIGHT, "01BYDATE") == NIGHT  # without pin: the date, as before
    http.release("01HTTP")
    http.release("01BYDATE")
    _publish(lake_dir)
    with pytest.raises(RuntimeError, match="404"):
        _rows(http, gen)  # the generation is gone: said, never another one's rows


def test_pruning_a_date_takes_its_generations_and_a_held_generation_keeps_its_date(tmp_path: Path) -> None:
    from adapter.ndjson import snapshot_dir
    from adapter.pipeline import PASSED, AdapterConfig, prune_snapshots

    lake_dir = tmp_path / "lake"
    nights = ["2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-03", NIGHT]
    for n in nights:
        _night(lake_dir, n, 1)
        (snapshot_dir(lake_dir, n) / PASSED).write_text("{}\n")
    lake = Lake(lake_dir, TZ)
    held = lake.hold("2026-10-01", "01LONGJOB", pin=True)
    cfg = AdapterConfig(lake_dir=lake_dir, secrets_dir=tmp_path / "s", mapping_path=tmp_path / "m.yaml", site_id="T",
                        tz=TZ, keep_nightly=2, keep_month_end_months=0)  # fmt: skip
    gone = prune_snapshots(cfg, date(2026, 10, 5))
    assert "2026-10-01" not in gone and "2026-10-02" in gone and lake.db_path(held).exists()
    left = sorted(p.name for p in (lake_dir / "db" / "gen").glob("*.duckdb"))
    assert f"{held}.duckdb" in left and not any(n.startswith("2026-10-02") for n in left)
    lake.release("01LONGJOB")
    assert "2026-10-01" in prune_snapshots(cfg, date(2026, 10, 5))
    assert not any(p.name.startswith("2026-10-01") for p in (lake_dir / "db" / "gen").iterdir())


# ----------------------------------------------------- handed over by T-723 (D-489; the integrator's ruling, MED-3)
def test_a_generation_says_whether_it_holds_the_sites_inputs_of_now(tmp_path: Path) -> None:
    """Acceptance item (b), the lake's half: a generation's record keeps the hash of the site's inputs it was built
    with, and the lake says whether the served generation holds the inputs it stores now."""
    lake_dir = tmp_path / "lake"
    _night(lake_dir, NIGHT, 3)
    lake = Lake(lake_dir, TZ)
    assert lake.generations(NIGHT)[-1]["site"] == "" and lake.site_in_sync() is True  # no site inputs, none built in
    lake.put_site(SITE)
    assert lake.site_in_sync() is False  # the facts are on the lake, the served generation was built before them
    lake.rebuild(NIGHT, HashEmbedder())
    assert lake.site_in_sync() is True and lake.generations(NIGHT)[-1]["site"]
    assert LakeLocal(lake_dir, HashEmbedder(), TZ).site_in_sync() is True
    assert Lake(tmp_path / "empty", TZ).site_in_sync() is None  # no snapshot: not known


def test_a_night_promoted_over_a_site_publish_is_published_again_not_skipped_as_unchanged(tmp_path: Path) -> None:
    """Acceptance item (b) (D-462's guess, verified): a night was built before the site publish's ``put_site`` and
    promoted after it. The publish is recorded with its digest, so the next call said "unchanged" for ever while
    the served night held none of the site's facts. Now the site publish asks the lake and publishes again."""
    from datetime import UTC, datetime

    from sitesetup.service import SiteSetup
    from tb_common.audit import AuditLog

    from tests.unit.test_snapshot_holds import _fact, _Store

    later = "2026-10-05"
    lake_dir = tmp_path / "lake"
    _night(lake_dir, NIGHT, 3)
    lake = LakeLocal(lake_dir, HashEmbedder(), TZ)
    store = _Store()
    store.facts_.append(_fact(1))
    svc = SiteSetup(store, tmp_path / "setup", lake, None, AuditLog(tmp_path / "audit"),  # type: ignore[arg-type]
                    lambda: datetime(2026, 10, 5, 1, 0, tzinfo=UTC), lambda: date(2026, 10, 5), lambda: b"k" * 32)  # fmt: skip
    first = svc.publish("main", "crc")
    assert first["unchanged"] is False and first["snapshot"] == NIGHT and lake.site_in_sync() is True
    assert svc.publish("main", "crc")["unchanged"] is True  # nothing changed: nothing rebuilt
    built = len(lake.lake.generations(NIGHT))
    # the adapter's next night: built from a lake that did not hold the site's facts yet, promoted now
    site = lake_dir / "site"
    site.rename(lake_dir / "site.not-yet")
    _night(lake_dir, later, 3)
    (lake_dir / "site.not-yet").rename(site)
    assert lake.snapshot() == later and lake.site_in_sync() is False
    out = svc.publish("main", "crc")
    assert out["unchanged"] is False and out["snapshot"] == later  # published again, onto the served night
    assert lake.site_in_sync() is True and len(lake.lake.generations(NIGHT)) == built
    assert svc.publish("main", "crc")["unchanged"] is True
