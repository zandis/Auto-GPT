"""All-history back-fill (T-305b, D-403, CR-061 back-fill half): by year, newest first, resumable, bounded memory.

The synthetic site A (600 fictional patients, 2014 to 2026) is loaded twice: once as the nightly full load
(``run_ingest``) and once by the back-fill. The NDJSON must be the same bytes. A run killed after a year resumes there
and ends with the same bytes; the first years are published before the rest; a held snapshot's publish is refused
and simply run again."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from adapter.backfill import BASE, DQ, REPORT, BackfillStop, backfill, resource_year
from adapter.ndjson import snapshot_dir
from adapter.pipeline import PASSED, AdapterConfig, run_ingest
from lake.store import SnapshotHeld
from tb_contracts import RebuildResult

ROOT = Path(__file__).resolve().parents[2]
SITE_A = ROOT / "tests/fixtures/synthetic_patients/site-a"
MAPPING = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
SNAP = "2026-11-10"


class _Rebuild:
    """The adapter's lake hook, a stand-in: records each call and what the folder held, and moves ``CURRENT``."""

    def __init__(self, lake_dir: Path) -> None:
        self.lake_dir = lake_dir
        self.calls: list[dict[str, Any]] = []
        self.refuse = 0

    def __call__(self, snap: str, nd: Path) -> RebuildResult:
        if self.refuse:
            self.refuse -= 1
            raise SnapshotHeld(f"lake snapshot {snap} is being read by a running job")
        report = json.loads((nd / REPORT).read_text(encoding="utf-8"))
        conds = [json.loads(x) for x in (nd / "Encounter.ndjson").read_text(encoding="utf-8").splitlines()]
        self.calls.append({"snap": snap, "report": report, "years": sorted({resource_year(c) for c in conds})})
        (self.lake_dir / "db").mkdir(parents=True, exist_ok=True)
        (self.lake_dir / "db" / f"{snap}.duckdb").write_bytes(b"")
        (self.lake_dir / "CURRENT").write_text(snap)
        return RebuildResult(snapshot=snap, tables={}, chunks=0, embedded_new=0, seconds=0.0)


def _cfg(tmp: Path, name: str, rebuild: Any = None) -> AdapterConfig:
    sec = tmp / "secrets"
    sec.mkdir(exist_ok=True)
    (sec / "site_hmac.key").write_bytes(b"k" * 32)
    return AdapterConfig(
        lake_dir=tmp / name, secrets_dir=sec, mapping_path=MAPPING, site_id="T", audit_dir=tmp / "audit",
        rebuild=rebuild,
    )  # fmt: skip


def _feed(tmp: Path) -> Path:
    dst = tmp / "feed"
    if not dst.exists():
        shutil.copytree(SITE_A, dst, ignore=shutil.ignore_patterns("*.json"))
    return dst


def _ndjson(folder: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(folder.glob("*.ndjson"))}


@pytest.fixture
def nightly(tmp_path: Path, db_url: str) -> dict[str, bytes]:
    """The same source loaded by the nightly full load: the bytes the back-fill must give."""
    cfg = _cfg(tmp_path, "nightly")
    rep = run_ingest(cfg, "csv", str(_feed(tmp_path)), snapshot=SNAP, load_fhir=False, rebuild_lake=False,
                     validate=False)  # fmt: skip
    assert rep.passed, rep.errors
    return _ndjson(snapshot_dir(cfg.lake_dir, SNAP))


def test_backfill_gives_the_nightly_full_load_byte_for_byte(tmp_path: Path, nightly: dict[str, bytes]) -> None:
    cfg = _cfg(tmp_path, "lake", _Rebuild(tmp_path / "lake"))
    seen: list[str] = []
    rep = backfill(cfg, "csv", str(_feed(tmp_path)), snapshot=SNAP, validate=False, on_bucket=seen.append)
    assert rep.state == "published", rep.errors
    assert _ndjson(snapshot_dir(cfg.lake_dir, SNAP)) == nightly
    # base first, then the newest year down to the oldest; each year has its own DQ report
    years = [y for y in seen if y != BASE]
    assert seen[0] == BASE and years == sorted(years, reverse=True) and len(years) >= 10
    assert years[0] == "2026" and years[-1] <= "2014"  # a booked appointment in 2027 is in the snapshot's year
    work = cfg.lake_dir / "backfill" / SNAP
    for y in seen:
        dq = json.loads((work / "runs" / y / DQ).read_text(encoding="utf-8"))
        assert dq["bucket"] == y and sum(dq["counts"].values()) > 0
    total = sum(sum(json.loads((work / "runs" / y / DQ).read_text())["counts"].values()) for y in seen)
    assert total == sum(rep.counts.values())
    assert (snapshot_dir(cfg.lake_dir, SNAP) / PASSED).exists()
    assert json.loads((snapshot_dir(cfg.lake_dir, SNAP) / REPORT).read_text())["complete"] is True


def test_a_run_killed_at_year_n_resumes_there(tmp_path: Path, nightly: dict[str, bytes]) -> None:
    cfg = _cfg(tmp_path, "lake", _Rebuild(tmp_path / "lake"))
    done: list[str] = []

    def kill_after_three(bucket: str) -> None:
        done.append(bucket)
        if len(done) == 3:
            raise BackfillStop(bucket)

    first = backfill(cfg, "csv", str(_feed(tmp_path)), snapshot=SNAP, validate=False, on_bucket=kill_after_three)
    assert first.state == "running" and not first.published and len(done) == 3
    assert not snapshot_dir(cfg.lake_dir, SNAP).exists()  # nothing published by the killed run
    again: list[str] = []
    rep = backfill(cfg, "csv", str(_feed(tmp_path)), snapshot=SNAP, validate=False, on_bucket=again.append)
    assert rep.spool_reused and rep.state == "published"
    assert not set(again) & set(done) and again[0] == rep.years[3]  # the three done years were not sorted again
    assert _ndjson(snapshot_dir(cfg.lake_dir, SNAP)) == nightly


def test_the_newest_years_are_published_first(tmp_path: Path, db_url: str) -> None:
    hook = _Rebuild(tmp_path / "lake")
    cfg = _cfg(tmp_path, "lake", hook)
    rep = backfill(cfg, "csv", str(_feed(tmp_path)), snapshot=SNAP, validate=False, first_years=2)
    assert rep.state == "published" and len(rep.published) == 2
    first, final = hook.calls
    assert first["report"] == {"snapshot": SNAP, "years": ["2026", "2025"], "complete": False}
    assert set(first["years"]) <= {"2026", "2025", BASE}
    assert final["report"]["complete"] is True and "2014" in final["years"]


def test_a_publish_refused_for_a_held_snapshot_is_run_again(tmp_path: Path, db_url: str) -> None:
    hook = _Rebuild(tmp_path / "lake")
    hook.refuse = 1
    cfg = _cfg(tmp_path, "lake", hook)
    rep = backfill(cfg, "csv", str(_feed(tmp_path)), snapshot=SNAP, validate=False)
    assert rep.state == "held" and "running job" in rep.errors[-1]
    assert not (snapshot_dir(cfg.lake_dir, SNAP) / PASSED).exists()
    again: list[str] = []
    rep = backfill(cfg, "csv", str(_feed(tmp_path)), snapshot=SNAP, validate=False, on_bucket=again.append)
    assert rep.state == "published" and again == []  # every year was done: only the publish ran again
    assert (snapshot_dir(cfg.lake_dir, SNAP) / PASSED).exists()


def test_resource_year_reads_the_clinical_date() -> None:
    assert resource_year({"resourceType": "Patient", "birthDate": "1950-01-01"}) == BASE
    assert resource_year({"resourceType": "Encounter", "period": {"start": "2019-03-01T10:00:00+08:00"}}) == "2019"
    assert resource_year({"resourceType": "Observation", "effectiveDateTime": "2021-05-05"}) == "2021"
    assert resource_year({"resourceType": "MedicationRequest"}) == BASE  # undated: kept, in every publish


# ------------------------------------------------------------------ tombstones into OMOP (D-149, CR-061)
DIAG = ["diag_no", "enc_no", "mrn", "icd10", "diag_date", "recorded_date", "status", "deleted"]
PAT = ["mrn", "name", "id_no", "birth_date", "sex", "death_date", "phone"]


def _write(path: Path, name: str, fields: list[str], rows: list[dict[str, str]]) -> None:
    import csv

    path.mkdir(parents=True, exist_ok=True)
    with (path / f"{name}.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def _diag(no: str, day: str, deleted: str = "") -> dict[str, str]:
    return {"diag_no": no, "enc_no": "E1", "mrn": "10000001", "icd10": "E11.9", "diag_date": day,
            "recorded_date": day, "status": "A", "deleted": deleted}  # fmt: skip


def test_omop_says_which_records_the_source_deleted(tmp_path: Path, db_url: str, monkeypatch: Any) -> None:
    """A diagnosis deleted at the source on a ``--since`` night is tombstoned in OMOP with the reason "deleted at the
    source"; one that only left a later full export says "left the feed"."""
    from omop import schema
    from omop.load import DELETED_AT_SOURCE, LEFT_THE_FEED

    monkeypatch.setenv("TB_OMOP_DUAL_WRITE", "on")
    cfg = _cfg(tmp_path, "lake")
    cfg.db_url = db_url
    pat = [{"mrn": "10000001", "name": "Test Person", "birth_date": "1960-01-01", "sex": "F"}]
    full = [_diag(f"D{i:02d}", "2026-09-01") for i in range(20)]
    _write(tmp_path / "full", "patient", PAT, pat)
    _write(tmp_path / "full", "diagnosis", DIAG, full)
    rep = run_ingest(cfg, "csv", str(tmp_path / "full"), snapshot="2026-10-01", load_fhir=False, validate=False)
    assert rep.passed and rep.omop is not None and rep.omop.state == "loaded", rep
    _write(tmp_path / "delta", "patient", PAT, pat)
    _write(tmp_path / "delta", "diagnosis", DIAG, [_diag("D01", "2026-10-01", deleted="1")])
    rep = run_ingest(cfg, "csv", str(tmp_path / "delta"), since="2026-10-01", snapshot="2026-10-02",
                     load_fhir=False, validate=False)  # fmt: skip
    assert rep.passed and rep.tombstoned == 1 and rep.omop is not None and rep.omop.state == "loaded", rep.errors
    _write(tmp_path / "full3", "patient", PAT, pat)
    _write(tmp_path / "full3", "diagnosis", DIAG, [r for r in full if r["diag_no"] not in ("D01", "D02")])
    rep = run_ingest(cfg, "csv", str(tmp_path / "full3"), snapshot="2026-10-03", load_fhir=False, validate=False)
    assert rep.passed and rep.omop is not None and rep.omop.state == "loaded", rep
    db = schema.connect(db_url, schema.schema_for(cfg.lake_dir))
    try:
        got = db.fetchall(
            "SELECT e.batch, e.reason FROM tb_record_event e JOIN tb_record r USING (record_key) "
            "WHERE e.event = 'tombstone' AND r.resource_type = 'Condition' ORDER BY e.batch"
        )
    finally:
        db.close()
    assert [tuple(x) for x in got] == [("2026-10-02", DELETED_AT_SOURCE), ("2026-10-03", LEFT_THE_FEED)]


def test_a_spool_kept_from_before_the_id_rule_is_read_again_never_published(
    tmp_path: Path, nightly: dict[str, bytes]
) -> None:
    """D-1253 deep review, finding 1: a back-fill stopped before the update keeps its spool. Resumed after it, that
    spool holds the earlier rule's ids: it is never reused (whatever its fingerprint), the source is read again, the
    report and the audit event say so, and the published snapshot is what a clean load makes."""
    from adapter.backfill import SPOOL_DONE, _fingerprint

    cfg = _cfg(tmp_path, "lake", _Rebuild(tmp_path / "lake"))
    done: list[str] = []

    def kill_after_three(bucket: str) -> None:
        done.append(bucket)
        if len(done) == 3:
            raise BackfillStop(bucket)

    feed = str(_feed(tmp_path))
    backfill(cfg, "csv", feed, snapshot=SNAP, validate=False, on_bucket=kill_after_three)
    marker = cfg.lake_dir / "backfill" / SNAP / "spool" / SPOOL_DONE
    kept = json.loads(marker.read_text())
    kept.pop("id_rule")  # as the release before D-1253 wrote it, with the fingerprint it would match today
    kept["fingerprint"] = _fingerprint(cfg, "csv", feed, SNAP)
    marker.write_text(json.dumps(kept))
    again: list[str] = []
    rep = backfill(cfg, "csv", feed, snapshot=SNAP, validate=False, on_bucket=again.append)
    assert rep.spool_of_another_id_rule and not rep.spool_reused and rep.state == "published"
    assert set(done) <= set(again)  # every year sorted again from the source
    assert _ndjson(snapshot_dir(cfg.lake_dir, SNAP)) == nightly
    assert json.loads(marker.read_text())["id_rule"] == 2
    events = [json.loads(x) for f in sorted((tmp_path / "audit").rglob("*.jsonl")) for x in f.open()]
    assert any(
        (e.get("detail") or {}).get("spool_of_another_id_rule") for e in events if e["event"] == "ingest.backfill"
    )
