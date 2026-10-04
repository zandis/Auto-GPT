"""Retention (SPEC §10.3): snapshot keep rule, adapter snapshot pruning, and the daily RETENTION job (objects by
age with audited hashes; pools of rulesets no longer approved)."""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from adapter.pipeline import AdapterConfig, prune_snapshots
from tb_common.retention import expired, snapshots_to_keep
from tb_contracts import JobCreate

from tests.inproc_box import make_box


def _daily(start: date, end: date) -> list[str]:
    out, d = [], start
    while d <= end:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def test_snapshots_to_keep() -> None:
    today = date(2026, 10, 4)
    snaps = _daily(date(2023, 1, 1), today)
    keep = snapshots_to_keep(snaps, today, nightly=3, month_end_months=36)
    assert {"2026-10-04", "2026-10-03", "2026-10-02"} <= keep
    assert "2026-09-30" in keep and "2023-10-31" in keep and "2023-09-30" not in keep
    assert "2026-09-29" not in keep
    assert len(keep) == 3 + 36  # Oct 2026 month-end == today (already among the nightly ones)
    assert snapshots_to_keep(["2026-10-01"], today, 0, 0) == set()
    assert expired(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 4, 2, tzinfo=UTC), 90)
    assert not expired(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 4, 2, tzinfo=UTC), 0)


def test_adapter_prunes_snapshots(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    snaps = ("2026-07-31", "2026-08-15", "2026-08-20", "2026-08-31", "2026-09-10", "2026-09-28")
    for s in (*snaps, "2026-10-01", "2026-10-02", "2026-10-03"):
        (lake / "ndjson" / s).mkdir(parents=True)
        (lake / "parquet" / f"snapshot={s}").mkdir(parents=True)
        (lake / "db").mkdir(parents=True, exist_ok=True)
        (lake / "db" / f"{s}.duckdb").write_bytes(b"x")
    (lake / "CURRENT").write_text("2026-08-15")  # the served snapshot is never removed
    cfg = AdapterConfig(lake_dir=lake, secrets_dir=tmp_path, mapping_path=tmp_path / "m.yaml", site_id="T")
    assert prune_snapshots(cfg, date(2026, 10, 3)) == ["2026-08-20", "2026-09-10"]
    for s in ("2026-08-20", "2026-09-10"):
        assert not (lake / "ndjson" / s).exists() and not (lake / "parquet" / f"snapshot={s}").exists()
        assert not (lake / "db" / f"{s}.duckdb").exists()
    assert (lake / "db" / "2026-08-15.duckdb").exists() and (lake / "db" / "2026-09-28.duckdb").exists()


def test_retention_job(tmp_path: Path) -> None:
    sec = tmp_path / "sec"
    sec.mkdir()
    box = make_box(tmp_path / "box", tmp_path / "lake", sec, date(2026, 10, 5))
    now = datetime.now(UTC)

    def put(key: str, age_days: int) -> None:
        box.store.put(key, key.encode())
        path = box.store.root / key  # FsStore layout: <root>/<bucket>/<name>
        t = (now - timedelta(days=age_days)).timestamp()
        os.utime(path, (t, t))

    put("attachments/J-OLD/protocol.pdf", 120)
    put("attachments/J-NEW/protocol.pdf", 10)
    put("outputs/J-OLD/list.xlsx", 400)
    put("outputs/J-MID/list.xlsx", 200)
    put("ctgov/NCT99000001/2026-08-15/parsed.json", 500)
    old = (now - timedelta(days=900)).isoformat()
    box.orch.db.pool_upsert("RETIRED", "1.0.0", [{"pid": "p1", "tier": "high", "verdicts": {}}], "J0", old)
    box.orch.db.pool_upsert("GZQO", "1.0.0", [{"pid": "p2", "tier": "high", "verdicts": {}}], "J0", old)
    created = box.orch.create(JobCreate(type="RETENTION", requested_by="scheduler"))
    box.orch.drain()
    job = box.orch.db.get(created.job_id)
    assert job is not None
    assert job.state == "done", job.error
    remaining = {o.key for p in ("attachments/", "outputs/", "ctgov/") for o in box.store.list(p)}
    assert "attachments/J-OLD/protocol.pdf" not in remaining and "outputs/J-OLD/list.xlsx" not in remaining
    assert "ctgov/NCT99000001/2026-08-15/parsed.json" not in remaining
    assert {"attachments/J-NEW/protocol.pdf", "outputs/J-MID/list.xlsx"} <= remaining
    assert box.orch.db.pool_rulesets() == ["GZQO"]  # RETIRED is not approved here and untouched for 900 days
    events = [
        json.loads(line)
        for f in sorted(box.audit_dir.glob("*.jsonl"))
        for line in f.read_text(encoding="utf-8").splitlines()
    ]
    deleted = [e for e in events if e["event"] == "retention.deleted"]
    assert {o["key"] for e in deleted for o in e["detail"]["objects"]} == {
        "attachments/J-OLD/protocol.pdf",
        "outputs/J-OLD/list.xlsx",
        "ctgov/NCT99000001/2026-08-15/parsed.json",
    }
    assert any(e["event"] == "retention.pools" and e["detail"]["pool"] == 1 for e in events)
