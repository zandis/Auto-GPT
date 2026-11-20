"""Dataflow lifecycle review P0 (D-149): deletes on delta nights, validation before CURRENT moves, embeddings in one
store, the lake schema version and the sidecar hashes (review §9 P0-1, P0-2, P0-6, P0-7; WS-03.1, WS-03.7, WS-05.3,
WS-08.1)."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pytest
from adapter.ndjson import TOMBSTONES, read_type, snapshot_dir, write_snapshot
from adapter.pipeline import AdapterConfig, run_ingest
from adapter.sources.ssmix2.source import Ssmix2Source, storage_dir
from adapter.validate.validator import ValidationResult
from embed_service.embedder import HashEmbedder
from lake.store import LAKE_SCHEMA_VERSION, Lake, LakeSchemaError, schema_sha
from tb_common import id_rule
from tb_common.crypto import pid_for_mrn
from tb_contracts import RebuildResult

ROOT = Path(__file__).resolve().parents[2]
TW_MAPPING = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
KEY = b"k" * 32
EMPTY: dict[str, dict[str, dict[str, str]]] = {"medis": {}, "jlac10": {}, "yj": {}}
DIAG = ["diag_no", "enc_no", "mrn", "icd10", "diag_date", "recorded_date", "status", "deleted"]


# ---------------------------------------------------------------------------------------------- tombstones
def test_write_snapshot_drops_tombstones_and_lists_them(tmp_path: Path) -> None:
    base = tmp_path / "s1"
    write_snapshot(base, {"Condition": [{"resourceType": "Condition", "id": i} for i in ("a", "b", "c")]})
    assert not (base / TOMBSTONES).exists()
    nxt = tmp_path / "s2"
    counts = write_snapshot(
        nxt,
        {"Condition": [{"resourceType": "Condition", "id": "c", "v": 2}, {"resourceType": "Condition", "id": "d"}]},
        base,
        {"Condition": ["b", "c", "zz"]},  # c is sent again in the same run: the record wins over its tombstone
    )
    assert counts == {"Condition": 3}
    assert [r["id"] for r in read_type(nxt, "Condition")] == ["a", "c", "d"]
    assert json.loads((nxt / TOMBSTONES).read_text()) == {"Condition": ["b"]}


def _csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    with (path / "diagnosis.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=DIAG)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in DIAG})


def _row(no: str, recorded: str, deleted: str = "") -> dict[str, str]:
    return {"diag_no": no, "enc_no": "E1", "mrn": "10000001", "icd10": "E11.9", "diag_date": recorded,
            "recorded_date": recorded, "status": "A", "deleted": deleted}  # fmt: skip


class _Lakes:
    """The adapter's ``rebuild`` hook over a real lake, counting the calls."""

    def __init__(self, lake_dir: Path) -> None:
        self.lake = Lake(lake_dir)
        self.calls: list[str] = []

    def __call__(self, snap: str, nd: Path) -> RebuildResult:
        self.calls.append(snap)
        id_rule.write_snapshot_record(nd)  # D-1253: a snapshot of this release
        st = self.lake.rebuild(snap, HashEmbedder(), nd)
        return RebuildResult(snapshot=st.snapshot, tables=st.tables, chunks=st.chunks, embedded_new=st.embedded_new,
                             seconds=st.seconds)  # fmt: skip


def _cfg(tmp_path: Path, lakes: _Lakes | None = None) -> AdapterConfig:
    sec = tmp_path / "secrets"
    sec.mkdir(exist_ok=True)
    (sec / "site_hmac.key").write_bytes(KEY)
    return AdapterConfig(lake_dir=tmp_path / "lake", secrets_dir=sec, mapping_path=TW_MAPPING, site_id="T",
                         audit_dir=tmp_path / "audit", rebuild=lakes)  # fmt: skip


def _conditions(lake_dir: Path, snap: str) -> set[str]:
    return {r["id"] for r in read_type(snapshot_dir(lake_dir, snap), "Condition")}


def test_a_diagnosis_deleted_at_the_source_is_gone_after_a_delta_night(tmp_path: Path) -> None:
    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    _csv(tmp_path / "full", [_row("D1", "2026-09-01"), _row("D2", "2026-09-02")])
    run_ingest(cfg, "csv", str(tmp_path / "full"), snapshot="2026-10-01", load_fhir=False, validate=False)
    first = _conditions(cfg.lake_dir, "2026-10-01")
    assert len(first) == 2
    # the delta export of the next night: D2 deleted at the hospital, D3 new
    _csv(tmp_path / "delta", [_row("D2", "2026-10-01", deleted="1"), _row("D3", "2026-10-01")])
    rep = run_ingest(cfg, "csv", str(tmp_path / "delta"), since="2026-10-01", snapshot="2026-10-02",
                     load_fhir=False, validate=False)  # fmt: skip
    assert rep.passed and rep.tombstoned == 1 and not rep.held
    second = _conditions(cfg.lake_dir, "2026-10-02")
    assert len(second) == 2 and len(second & first) == 1  # D1 kept, D2 gone, D3 added
    # ... and absent from the lake the next morning, which is what screening reads
    assert {x["cid"] for x in lakes.lake.query("SELECT cid FROM condition").to_pylist()} == second
    gone = json.loads((snapshot_dir(cfg.lake_dir, "2026-10-02") / TOMBSTONES).read_text())["Condition"]
    assert len(gone) == 1 and gone[0] in first and gone[0] not in second


def test_a_row_marked_deleted_never_becomes_a_record_on_a_full_run(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _csv(tmp_path / "full", [_row("D1", "2026-09-01"), _row("D2", "2026-09-02", deleted="Y")])
    rep = run_ingest(cfg, "csv", str(tmp_path / "full"), snapshot="2026-10-01", load_fhir=False,
                     rebuild_lake=False, validate=False)  # fmt: skip
    assert rep.counts["Condition"] == 1


def test_fhir_bulk_deleted_bundles_are_tombstones(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    exp = tmp_path / "bulk1"
    exp.mkdir()
    conds = [{"resourceType": "Condition", "id": c, "subject": {"reference": "Patient/M1"}} for c in ("c1", "c2")]
    (exp / "Condition.ndjson").write_text("\n".join(json.dumps(c) for c in conds) + "\n")
    run_ingest(cfg, "fhir_bulk", str(exp), snapshot="2026-10-01", load_fhir=False, rebuild_lake=False,
               validate=False)  # fmt: skip
    delta = tmp_path / "bulk2"
    (delta / "deleted").mkdir(parents=True)
    bundle = {"resourceType": "Bundle", "type": "transaction",
              "entry": [{"request": {"method": "DELETE", "url": "Condition/c2"}},
                        {"request": {"method": "DELETE", "url": "Patient/M1"}}]}  # fmt: skip
    (delta / "deleted" / "del.ndjson").write_text(json.dumps(bundle) + "\n")
    rep = run_ingest(cfg, "fhir_bulk", str(delta), since="2026-10-01", snapshot="2026-10-02", load_fhir=False,
                     rebuild_lake=False, validate=False)  # fmt: skip
    assert rep.tombstoned == 1  # the Condition; a Patient is never removed by a feed delta (opt-out's job)
    left = list(read_type(snapshot_dir(cfg.lake_dir, "2026-10-02"), "Condition"))
    assert len(left) == 1 and left[0]["subject"]["reference"] == f"Patient/{pid_for_mrn(KEY, 'M1')}"
    assert "Bundle" not in rep.counts


def _ss(root: Path, order: str, stamp: str, flag: str) -> None:
    msh = f"MSH|^~\\&|HIS||TB||20261101||PPR^ZD1|{order}|P|2.5||||||~ISO IR87"
    prb = f"PRB|AD|20260101|M109^痛風^99XYZ^M109^痛風^I10|{order}||||||||||||20260101"
    d = storage_dir(root, "10000001", "20260101", "PPR-01")
    d.mkdir(parents=True, exist_ok=True)
    name = f"10000001_20260101_PPR-01_{order}_{stamp}_-_{flag}"
    pid = "PID|||10000001^^^^PI"  # every SS-MIX2 message carries its patient (PR #1095 fourth review b)
    (d / name).write_bytes(("\r".join([msh, pid, "PV1||O", prb]) + "\r").encode("iso2022_jp"))


def test_ssmix2_flag_zero_is_read_as_a_deleted_row(tmp_path: Path) -> None:
    _ss(tmp_path, "D1", "20261101000000000", "1")
    _ss(tmp_path, "D2", "20261101000000000", "1")
    _ss(tmp_path, "D2", "20261102000000000", "0")  # the newest version of D2 says: deleted
    src = Ssmix2Source(tmp_path, licensed=EMPTY)
    assert [r["diag_no"] for r in src.rows("diagnosis", "diagnosis", None, None)] == ["D1"]
    assert [r["diag_no"] for r in src.deleted_rows("diagnosis", "diagnosis", None, None)] == ["D2"]


# ---------------------------------------------------------------------------------------------- held nights
class _Bad:
    def validate(self, picked: list[dict[str, Any]]) -> ValidationResult:
        return ValidationResult(validator="stub", sampled=100, errors=7, messages=["7 bad resources"])


def test_a_night_over_the_validation_limit_leaves_current_unchanged(tmp_path: Path) -> None:
    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    _csv(tmp_path / "n1", [_row("D1", "2026-09-01")])
    assert run_ingest(cfg, "csv", str(tmp_path / "n1"), snapshot="2026-10-01", load_fhir=False, validate=False).passed
    assert lakes.lake.current() == "2026-10-01"
    _csv(tmp_path / "n2", [_row("D1", "2026-09-01"), _row("D9", "2026-10-01")])
    rep = run_ingest(
        cfg,
        "csv",
        str(tmp_path / "n2"),
        snapshot="2026-10-02",
        load_fhir=False,
        validator=_Bad(),  # type: ignore[arg-type]
    )
    assert not rep.passed and rep.held and rep.lake is None
    assert lakes.calls == ["2026-10-01"]  # the lake was never rebuilt for the held night
    assert lakes.lake.current() == "2026-10-01" and lakes.lake.snapshots() == ["2026-10-01"]
    events = [json.loads(ln)["event"] for f in sorted(cfg.audit_dir.glob("*.jsonl")) for ln in f.open()]  # type: ignore[union-attr]
    assert events[-1] == "ingest.held"


# ---------------------------------------------------------------------------------------------- the lake files
def _one_patient_lake(tmp_path: Path) -> Lake:
    nd = tmp_path / "nd"
    nd.mkdir()
    pat = {"resourceType": "Patient", "id": "P1", "birthDate": "1960-01-01", "gender": "female"}
    docs = [
        {
            "resourceType": "DocumentReference",
            "id": f"d{i}",
            "subject": {"reference": "Patient/P1"},
            "date": f"2026-0{i}-01T09:00:00+09:00",
            "type": {"text": "progress"},
            "content": [{"attachment": {"contentType": "text/plain", "data": _b64(text)}}],
        }
        for i, text in enumerate(
            ["関節リウマチ。メトトレキサート 10mg 継続。", "痛風発作なし。尿酸 6.2。", "腎機能 低下傾向 eGFR 52。"],
            start=1,
        )
    ]
    (nd / "Patient.ndjson").write_text(json.dumps(pat) + "\n")
    (nd / "DocumentReference.ndjson").write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in docs) + "\n")
    lake = Lake(tmp_path / "lake")
    id_rule.write_snapshot_record(nd)  # D-1253: a snapshot of this release
    lake.rebuild("2026-10-05", HashEmbedder(), nd)
    return lake


def _b64(text: str) -> str:
    import base64

    return base64.b64encode(text.encode("utf-8")).decode()


def test_snapshot_has_no_vectors_and_search_reads_the_one_store(tmp_path: Path) -> None:
    lake = _one_patient_lake(tmp_path)
    con = lake.connect()
    try:
        cols = [r[0] for r in con.execute("DESCRIBE document_chunk").fetchall()]
        chunks = con.execute("SELECT chunk_key, sha, text FROM document_chunk ORDER BY chunk_key").fetchall()
        meta = con.execute("SELECT schema_version, schema_sha, embed_store FROM lake_meta").fetchone()
    finally:
        con.close()
    assert "embedding" not in cols and "sha" in cols and len(chunks) >= 3
    assert meta == (LAKE_SCHEMA_VERSION, schema_sha(), "embed_cache.duckdb")
    # search gives the brute-force answer: cosine over the stored vectors, fused with BM25
    emb = HashEmbedder()
    hits = lake.search("P1", "腎機能 eGFR", emb, k=3)
    q = np.asarray(emb.embed(["腎機能 eGFR"])[0], dtype=np.float32)
    vec = lake.vectors([s for _, s, _ in chunks], emb.model)
    assert set(vec) == {s for _, s, _ in chunks}
    cos = {k: float(vec[s] @ q / (np.linalg.norm(vec[s]) * np.linalg.norm(q))) for k, s, _ in chunks}
    assert max(cos, key=lambda kk: (cos[kk], kk)) in {f"{h['did']}#{h['chunk_no']}" for h in hits}
    assert hits[0]["text"].startswith("腎機能")


def test_a_version_1_snapshot_with_its_own_vectors_is_still_searched(tmp_path: Path) -> None:
    lake = _one_patient_lake(tmp_path)
    emb = HashEmbedder()
    new_hits = lake.search("P1", "尿酸", emb, k=3)
    # rewrite the snapshot in the old layout: embedding column, no sha, lake_meta without a version
    path = lake.db_path()
    con = duckdb.connect(str(path))
    rows = con.execute("SELECT chunk_key, sha FROM document_chunk").fetchall()
    vec = lake.vectors([s for _, s in rows], emb.model)
    con.execute("ALTER TABLE document_chunk ADD COLUMN embedding FLOAT[1024]")
    for key, sha in rows:
        con.execute(
            "UPDATE document_chunk SET embedding = ?::FLOAT[1024] WHERE chunk_key = ?", [vec[sha].tolist(), key]
        )
    con.execute("ALTER TABLE lake_meta DROP COLUMN schema_version")
    con.close()
    (tmp_path / "lake" / "embed_cache.duckdb").unlink()  # the old layout needs no vector store
    assert lake.search("P1", "尿酸", emb, k=3) == new_hits


def test_unknown_lake_schema_is_refused_with_a_plain_message(tmp_path: Path) -> None:
    lake = _one_patient_lake(tmp_path)
    con = duckdb.connect(str(lake.db_path()))
    con.execute("UPDATE lake_meta SET schema_version = 99")
    con.close()
    with pytest.raises(LakeSchemaError, match="LAKE-SCHEMA: lake snapshot 2026-10-05 was built by a newer"):
        lake.query("SELECT count(*) FROM patient")
    con = duckdb.connect(str(lake.db_path()))
    con.execute("DROP TABLE lake_meta")
    con.close()
    with pytest.raises(LakeSchemaError, match="older TrialBox .*Rebuild it"):
        lake.query("SELECT count(*) FROM patient")


def test_sidecar_hashes_catch_a_changed_file(tmp_path: Path) -> None:
    lake = _one_patient_lake(tmp_path)
    assert lake.verify() == []
    side = (tmp_path / "lake" / "db" / "2026-10-05.duckdb.sha256").read_text()
    assert side.endswith("  2026-10-05.duckdb\n")
    pq = tmp_path / "lake" / "parquet" / "snapshot=2026-10-05" / "patient.parquet"
    pq.write_bytes(pq.read_bytes() + b"x")
    assert lake.verify() == ["patient.parquet: content does not match its .sha256 sidecar"]
    # retention removes the sidecars with their snapshot (``<snap>.duckdb*``; ``.source``: the folder read, D-271)
    assert sorted(p.name for p in (tmp_path / "lake" / "db").iterdir()) == [
        "2026-10-05.duckdb",
        "2026-10-05.duckdb.id_rule",  # D-1253: the id rule of the ids it holds, read when no NDJSON is left
        "2026-10-05.duckdb.sha256",
        "2026-10-05.duckdb.source",
        "gen",  # T-724 (D-490): the date's generations; db/2026-10-05.duckdb is a link to the newest
    ]


# ---------------------------------------------------------------------------------------------- D-271 (DI-7, DI-8)
def test_a_rebuild_from_a_missing_or_empty_folder_is_refused_and_current_stays(tmp_path: Path) -> None:
    """DI-7: an empty lake made CURRENT would screen every patient out; the rebuild is refused before anything is
    written and the previous CURRENT keeps serving."""
    lake = _one_patient_lake(tmp_path)
    assert lake.current() == "2026-10-05"
    with pytest.raises(RuntimeError, match="no NDJSON folder"):
        lake.rebuild("2026-11-09", HashEmbedder())  # a wrong date on POST /rebuild
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "Patient.ndjson").write_text("\n")
    with pytest.raises(RuntimeError, match="holds no patient or clinical record"):
        id_rule.write_snapshot_record(empty)  # D-1253: a snapshot of this release
        lake.rebuild("2026-11-09", HashEmbedder(), empty)
    assert lake.current() == "2026-10-05" and lake.snapshots() == ["2026-10-05"]
    # a practice site's lake holds only the site's own inputs: allowed when asked for
    id_rule.write_snapshot_record(empty)  # D-1253: a snapshot of this release
    lake.rebuild("2026-11-09", HashEmbedder(), empty, promote=False, allow_empty=True)
    # the snapshot's own folder is remembered: rebuilding it again (site set-up "Publish") reads the same NDJSON
    assert lake.rebuild("2026-10-05", HashEmbedder()).tables["patient"] == 1


def test_the_lake_service_answers_409_for_a_rebuild_without_data(tmp_path: Path, monkeypatch: Any) -> None:
    from fastapi.testclient import TestClient
    from lake import app as lake_app

    lake = _one_patient_lake(tmp_path)
    monkeypatch.setattr(lake_app, "lake", lambda: lake)
    r = TestClient(lake_app.app).post("/rebuild", json={"snapshot": "2026-11-09"})
    assert r.status_code == 409 and "no NDJSON folder" in r.json()["detail"]
    assert lake.current() == "2026-10-05"


def test_a_held_nights_records_never_reach_current_through_the_next_delta(tmp_path: Path) -> None:
    """DI-8: night 1 promoted, night 2 held (bad data), night 3 a good delta: the delta merges over night 1, so
    night 2's rejected rows are not in CURRENT."""
    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    _csv(tmp_path / "n1", [_row("D1", "2026-09-01")])
    assert run_ingest(cfg, "csv", str(tmp_path / "n1"), snapshot="2026-10-01", load_fhir=False, validate=False).passed
    n1 = _conditions(cfg.lake_dir, "2026-10-01")
    _csv(tmp_path / "n2", [_row("DBAD", "2026-10-01")])
    rep = run_ingest(cfg, "csv", str(tmp_path / "n2"), since="2026-10-01", snapshot="2026-10-02", load_fhir=False,
                     validator=_Bad())  # type: ignore[arg-type]  # fmt: skip
    assert rep.held and lakes.lake.current() == "2026-10-01"
    bad = _conditions(cfg.lake_dir, "2026-10-02") - n1
    assert len(bad) == 1
    _csv(tmp_path / "n3", [_row("D3", "2026-10-02")])
    rep = run_ingest(cfg, "csv", str(tmp_path / "n3"), since="2026-10-02", snapshot="2026-10-03", load_fhir=False,
                     validate=False)  # fmt: skip
    assert rep.passed and lakes.lake.current() == "2026-10-03"
    served = {x["cid"] for x in lakes.lake.query("SELECT cid FROM condition").to_pylist()}
    assert n1 <= served and not (bad & served) and len(served) == 2
    assert not (bad & _conditions(cfg.lake_dir, "2026-10-03"))


def test_merge_base_is_the_last_promoted_snapshot(tmp_path: Path) -> None:
    from adapter import pipeline

    lake = tmp_path / "lake"
    for s in ("2026-10-01", "2026-10-02", "2026-10-03"):
        snapshot_dir(lake, s).mkdir(parents=True)
    assert pipeline.merge_base(lake, "2026-10-04") is None  # nothing ever promoted: no base
    (lake / "CURRENT").write_text("2026-10-02")  # folders from before the marker: CURRENT is the base
    assert pipeline.merge_base(lake, "2026-10-04") == "2026-10-02"
    (snapshot_dir(lake, "2026-10-01") / pipeline.PASSED).write_text("{}")
    assert pipeline.merge_base(lake, "2026-10-04") == "2026-10-02"
    (snapshot_dir(lake, "2026-10-03") / pipeline.PASSED).write_text("{}")
    assert pipeline.merge_base(lake, "2026-10-04") == "2026-10-03"
    assert pipeline.merge_base(lake, "2026-10-03") == "2026-10-02"  # a night run again never merges over itself


def test_a_delta_night_with_no_promoted_base_is_held(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _csv(tmp_path / "n1", [_row("D1", "2026-09-01")])
    rep = run_ingest(cfg, "csv", str(tmp_path / "n1"), snapshot="2026-10-01", load_fhir=False,
                     rebuild_lake=False, validator=_Bad())  # type: ignore[arg-type]  # fmt: skip
    assert rep.held
    _csv(tmp_path / "n2", [_row("D2", "2026-10-01")])
    rep = run_ingest(cfg, "csv", str(tmp_path / "n2"), since="2026-10-01", snapshot="2026-10-02", load_fhir=False,
                     rebuild_lake=False, validate=False)  # fmt: skip
    assert rep.held and not rep.passed and any("no earlier snapshot passed" in e for e in rep.errors or [])


# ---------------------------------------------------------------------------------------------- D-271 review
def _served(lakes: _Lakes) -> set[str]:
    return {x["cid"] for x in lakes.lake.query("SELECT cid FROM condition").to_pylist()}


def _night1(tmp_path: Path, rows: list[dict[str, str]] | None = None) -> tuple[_Lakes, AdapterConfig]:
    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    _csv(tmp_path / "n1", rows or [_row("D1", "2026-09-01"), _row("D2", "2026-09-02")])
    assert run_ingest(cfg, "csv", str(tmp_path / "n1"), snapshot="2026-10-01", load_fhir=False, validate=False).passed
    return lakes, cfg


def test_an_empty_export_is_held_not_promoted(tmp_path: Path) -> None:
    """Review B1: the mapping's static Organization rows are written on every night; an export with only a header
    must still be held, not promoted as a lake with no patient and no diagnosis."""
    lakes, cfg = _night1(tmp_path)
    good = _served(lakes)
    assert len(good) == 2
    _csv(tmp_path / "n2", [])  # header only: the HIS export came back empty
    rep = run_ingest(cfg, "csv", str(tmp_path / "n2"), snapshot="2026-10-02", load_fhir=False)
    assert rep.held and not rep.passed and any("Condition: 2 of 2" in e for e in rep.errors or [])
    assert lakes.lake.current() == "2026-10-01" and _served(lakes) == good
    # the lake itself refuses the folder too (a hand-made POST /rebuild): only static rows is no data
    with pytest.raises(RuntimeError, match="holds no patient or clinical record"):
        lakes.lake.rebuild("2026-10-02", HashEmbedder(), snapshot_dir(cfg.lake_dir, "2026-10-02"))
    assert lakes.lake.current() == "2026-10-01"


def test_a_night_that_drops_most_records_of_a_kind_needs_an_override_naming_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review H2 (legacy lake): a full night with 4 of 10 diagnoses is held; an override naming another night does
    nothing; one naming this night lets it through and is audited."""
    lakes, cfg = _night1(tmp_path, [_row(f"D{i}", "2026-09-01") for i in range(10)])
    _csv(tmp_path / "n2", [_row(f"D{i}", "2026-09-01") for i in range(4)])
    monkeypatch.setenv("TB_FEED_DROP_OVERRIDE", "2026-09-30: an old reason")
    rep = run_ingest(cfg, "csv", str(tmp_path / "n2"), snapshot="2026-10-02", load_fhir=False, validate=False)
    assert rep.held and any("Condition: 6 of 10" in e for e in rep.errors or [])
    assert lakes.lake.current() == "2026-10-01"
    monkeypatch.setenv("TB_FEED_DROP_OVERRIDE", "2026-10-02: the hospital purged test patients (ticket 7)")
    rep = run_ingest(cfg, "csv", str(tmp_path / "n2"), snapshot="2026-10-02", load_fhir=False, validate=False)
    assert rep.passed and lakes.lake.current() == "2026-10-02" and len(_served(lakes)) == 4
    events = [json.loads(ln) for f in sorted(cfg.audit_dir.glob("*.jsonl")) for ln in f.open()]  # type: ignore[union-attr]
    assert "ticket 7" in str(events[-1]["detail"]["drop_override"])


def test_a_held_rerun_of_the_current_night_never_reaches_current(tmp_path: Path) -> None:
    """Review C1: re-running the night CURRENT names with bad data is held without touching that night's NDJSON, so
    neither the next delta nor a site set-up Publish (rebuild of CURRENT) serves the rejected rows."""
    lakes, cfg = _night1(tmp_path, [_row("D1", "2026-09-01")])
    good = _served(lakes)
    _csv(tmp_path / "n1b", [_row("DBAD", "2026-09-01")])
    rep = run_ingest(cfg, "csv", str(tmp_path / "n1b"), snapshot="2026-10-01", load_fhir=False,
                     validator=_Bad())  # type: ignore[arg-type]  # fmt: skip
    assert rep.held and lakes.lake.current() == "2026-10-01"
    assert _conditions(cfg.lake_dir, "2026-10-01") == good  # the promoted folder is untouched
    lakes.lake.rebuild("2026-10-01", HashEmbedder())  # Publish: rebuild(CURRENT)
    assert _served(lakes) == good
    _csv(tmp_path / "n2", [_row("D3", "2026-10-01")])
    rep = run_ingest(cfg, "csv", str(tmp_path / "n2"), since="2026-10-01", snapshot="2026-10-02", load_fhir=False,
                     validate=False)  # fmt: skip
    assert rep.passed and good <= _served(lakes) and len(_served(lakes)) == 2


def test_a_passing_rerun_of_the_current_night_replaces_it(tmp_path: Path) -> None:
    lakes, cfg = _night1(tmp_path, [_row("D1", "2026-09-01")])
    _csv(tmp_path / "n1b", [_row("D1", "2026-09-01"), _row("D2", "2026-09-01")])
    rep = run_ingest(cfg, "csv", str(tmp_path / "n1b"), snapshot="2026-10-01", load_fhir=False, validate=False)
    assert rep.passed and len(_served(lakes)) == 2 and len(_conditions(cfg.lake_dir, "2026-10-01")) == 2
    assert not (cfg.lake_dir / "ndjson-rerun" / "2026-10-01").exists()


def test_a_delta_on_a_lake_with_current_but_no_ndjson_is_held(tmp_path: Path) -> None:
    """Review H1: CURRENT exists but no NDJSON folder (a lake built by dataplat, NDJSON not restored): the delta alone
    must not replace the lake."""
    lakes, cfg = _night1(tmp_path)
    shutil.rmtree(cfg.lake_dir / "ndjson")
    _csv(tmp_path / "n2", [_row("D3", "2026-10-01")])
    rep = run_ingest(cfg, "csv", str(tmp_path / "n2"), since="2026-10-01", snapshot="2026-10-02", load_fhir=False,
                     validate=False)  # fmt: skip
    assert rep.held and lakes.lake.current() == "2026-10-01" and len(_served(lakes)) == 2


def test_a_lake_from_before_the_marker_counts_as_fed(tmp_path: Path) -> None:
    """Review M1: a lake built before D-271 from a folder outside the lake has no FEED, no ndjson/ and no .source; a
    Publish (rebuild of CURRENT) must not turn it into a site-only lake."""
    lake = _one_patient_lake(tmp_path)
    (tmp_path / "lake" / "FEED").unlink()
    for p in (tmp_path / "lake" / "db").glob("*.source"):
        p.unlink()
    shutil.rmtree(tmp_path / "lake" / "ndjson")
    assert lake.fed()
    with pytest.raises(RuntimeError, match="no NDJSON folder"):
        lake.rebuild(str(lake.current()), HashEmbedder())
    site_only = Lake(tmp_path / "practice")  # a lake that never had a feed: built from the site's inputs
    site_only.rebuild("2026-10-05", HashEmbedder())
    assert not site_only.fed() and site_only.current() == "2026-10-05"


def test_a_busy_lake_is_retried_not_a_held_night(tmp_path: Path) -> None:
    """T-722 (D-462), review 4: a lake that is busy (a job holds the snapshot, or another rebuild of it runs) wrote
    nothing and refused no data: the night ends "lake busy", is not held and gets no held.json; the same in process
    and over HTTP (409 with ``X-TB-Lake-Busy``)."""
    from lake.store import LakeBusy, SnapshotBuilding, SnapshotHeld

    for exc in (SnapshotBuilding("lake snapshot 2026-10-01 is already building"), SnapshotHeld("running job"),
                LakeBusy("the lake is busy with snapshot 2026-10-01")):  # fmt: skip

        def busy(snap: str, nd: Path, exc: Exception = exc) -> RebuildResult:
            raise exc

        cfg = _cfg(tmp_path)
        cfg.rebuild = busy
        _csv(tmp_path / "n1", [_row("D1", "2026-09-01")])
        rep = run_ingest(cfg, "csv", str(tmp_path / "n1"), snapshot="2026-10-01", load_fhir=False, validate=False)
        assert not rep.held and not rep.passed and any(e.startswith("lake busy") for e in rep.errors or [])
        assert not (snapshot_dir(cfg.lake_dir, "2026-10-01") / "held.json").exists()


def test_a_refusal_by_the_lake_holds_the_night_with_its_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review M2: a refusal reaches the ingest report with the lake's reason and holds the night; the lake service
    answers 409 with the detail for an OMOP refusal too (no bare 500)."""
    from adapter.pipeline import RebuildRefused
    from fastapi.testclient import TestClient
    from lake import app as lake_app
    from omop.schema import OmopError

    def refuse(snap: str, nd: Path) -> RebuildResult:
        raise RebuildRefused(f"the lake refused snapshot {snap}: would tombstone person: 600 of 600")

    cfg = _cfg(tmp_path)
    cfg.rebuild = refuse
    _csv(tmp_path / "n1", [_row("D1", "2026-09-01")])
    rep = run_ingest(cfg, "csv", str(tmp_path / "n1"), snapshot="2026-10-01", load_fhir=False, validate=False)
    assert rep.held and not rep.passed and any("person: 600 of 600" in e for e in rep.errors or [])

    class _Omop:
        def start_rebuild(self, *a: Any, **k: Any) -> Any:  # T-690: the service starts a job (refused at its start)
            raise OmopError("OMOP feed batch 2026-10-02 would tombstone person: 600 of 600")

        def current(self) -> str:
            return "2026-10-01"

    monkeypatch.setattr(lake_app, "lake", _Omop)
    r = TestClient(lake_app.app).post("/rebuild", json={"snapshot": "2026-10-02"})
    assert r.status_code == 409 and "person: 600 of 600" in r.json()["detail"]
