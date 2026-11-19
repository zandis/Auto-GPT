"""D-1253: the rule a store's lake ids were made under is recorded with the store, and never mixed.

Rule 2 (a patient's record id holds the patient) changed every id of a patient's record once. A lake snapshot, the
OMOP store of record, the derived store, the vector store, the patient twin, the candidate pool and the EDC drafts
keep such ids; one written under rule 1 is never added to. The night stops before it reads or writes anything when
the lake or a store it reads is under rule 1; every store also refuses at its own write. Synthetic rows only."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest
from adapter.ndjson import read_type, snapshot_dir, write_snapshot
from adapter.pipeline import AdapterConfig, check_id_rule, run_ingest
from tb_common import id_rule
from tb_common.db import Database

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
KEY = b"synthetic site key for D-1253 tests only"
DIAG = ["diag_no", "enc_no", "mrn", "icd10", "diag_date", "recorded_date", "status"]


def _cfg(tmp: Path, db_url: str | None = None) -> AdapterConfig:
    sec = tmp / "secrets"
    sec.mkdir(parents=True, exist_ok=True)
    (sec / "site_hmac.key").write_bytes(KEY)
    (sec / "site_hmac.key").chmod(0o600)
    return AdapterConfig(lake_dir=tmp / "lake", secrets_dir=sec, mapping_path=BASE, site_id="T", tz="Asia/Taipei",
                         audit_dir=tmp / "audit", validation_max_pct=100.0, db_url=db_url)  # fmt: skip


def _feed(path: Path, n: int) -> str:
    path.mkdir(parents=True, exist_ok=True)
    with (path / "diagnosis.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=DIAG)
        w.writeheader()
        for i in range(n):
            w.writerow({"diag_no": f"D{i}", "enc_no": "E1", "mrn": "10000001", "icd10": "M10.9",
                        "diag_date": "2026-09-01", "recorded_date": "2026-09-01", "status": "A"})  # fmt: skip
    return str(path)


# ------------------------------------------------------------------------------------------------ the snapshots
def test_every_snapshot_says_the_rule_of_its_ids(tmp_path: Path) -> None:
    write_snapshot(tmp_path / "s1", {"Condition": [{"resourceType": "Condition", "id": "a"}]})
    assert json.loads((tmp_path / "s1" / id_rule.SNAPSHOT_RECORD).read_text()) == {"rule": id_rule.RULE}
    assert id_rule.snapshot_rule(tmp_path / "s1") == 2


def test_a_snapshot_is_never_merged_over_one_of_the_earlier_rule(tmp_path: Path) -> None:
    write_snapshot(tmp_path / "s1", {"Condition": [{"resourceType": "Condition", "id": "a"}]})
    (tmp_path / "s1" / id_rule.SNAPSHOT_RECORD).unlink()  # as a snapshot written before D-1253
    assert id_rule.snapshot_rule(tmp_path / "s1") == 1
    with pytest.raises(id_rule.IdRuleError, match="s1"):
        write_snapshot(tmp_path / "s2", {"Condition": [{"resourceType": "Condition", "id": "b"}]}, tmp_path / "s1")
    assert not (tmp_path / "s2").exists()


@pytest.mark.parametrize("delta", [False, True])
def test_a_night_over_a_lake_of_the_earlier_rule_stops_before_anything_is_written(tmp_path: Path, delta: bool) -> None:
    cfg = _cfg(tmp_path)
    run_ingest(cfg, "csv", _feed(tmp_path / "f1", 3), snapshot="2026-10-01", load_fhir=False, validate=False)
    first = snapshot_dir(cfg.lake_dir, "2026-10-01")
    assert len(list(read_type(first, "Condition"))) == 3
    (first / id_rule.SNAPSHOT_RECORD).unlink()  # the box's lake as the release before D-1253 left it
    with pytest.raises(id_rule.IdRuleError) as caught:
        run_ingest(cfg, "csv", _feed(tmp_path / "f2", 4), snapshot="2026-10-02", since="2026-10-01" if delta else None,
                   load_fhir=False, validate=False)  # fmt: skip
    said = str(caught.value)
    assert "the lake (1 snapshots, the last 2026-10-01)" in said and id_rule.COMMAND in said and id_rule.RUNBOOK in said
    assert not snapshot_dir(cfg.lake_dir, "2026-10-02").exists()  # nothing written
    events = [json.loads(line) for f in sorted((tmp_path / "audit").rglob("*.jsonl")) for line in f.open()]
    assert any(e.get("event") == "ingest.failed" and (e.get("detail") or {}).get("refused") == "id_rule"
               for e in events)  # fmt: skip


# ------------------------------------------------------------------------------------------------ the stores
def _store_table(url: str, store: id_rule.Store, rows: int, stamped: bool | None) -> None:
    """The store's table with the columns its question reads, ``rows`` lake-id rows; ``stamped``: a ``tb_id_rule``
    with the current rule (True), an empty one (False), none at all (None: a store before D-1253's migration)."""
    with Database.connect(url, store.schema) as db:
        db.execute(f"CREATE TABLE {store.table} (source_kind TEXT DEFAULT 'feed', resource_type TEXT DEFAULT "
                   "'Condition', citation TEXT DEFAULT 'x', final_citation TEXT)")  # fmt: skip
        for _ in range(rows):
            db.execute(f"INSERT INTO {store.table} DEFAULT VALUES")
        if stamped is not None:
            db.execute(id_rule.DDL)
            if stamped:
                db.execute("INSERT INTO tb_id_rule (rule) VALUES (?)", (id_rule.RULE,))


@pytest.mark.parametrize("store", id_rule.STORES, ids=lambda s: s.name)
@pytest.mark.parametrize(
    ("rows", "stamped", "state"),
    [(0, None, id_rule.EMPTY), (1, None, id_rule.OLD), (1, False, id_rule.OLD), (1, True, id_rule.CURRENT),
     (0, False, id_rule.EMPTY)],
)  # fmt: skip
def test_what_a_store_says_of_its_rule(db_url: str, store: id_rule.Store, rows: int, stamped: bool | None,
                                       state: str) -> None:  # fmt: skip
    _store_table(db_url, store, rows, stamped)
    assert id_rule.probe(db_url, store) == state


def test_a_store_that_is_not_there_holds_no_lake_id(db_url: str) -> None:
    assert id_rule.probe(db_url, id_rule.VEC) == id_rule.EMPTY


@pytest.mark.parametrize("store", id_rule.STORES, ids=lambda s: s.name)
def test_a_store_stamps_itself_when_empty_and_refuses_when_it_holds_ids_of_the_earlier_rule(
    db_url: str, store: id_rule.Store
) -> None:
    _store_table(db_url, store, 0, False)
    with Database.connect(db_url, store.schema) as db:
        with db.transaction() as tx:
            id_rule.ensure(tx, store)  # empty: stamped
        assert db.fetchval("SELECT count(*) FROM tb_id_rule") == 1
        db.execute("DELETE FROM tb_id_rule")
        db.execute(f"INSERT INTO {store.table} DEFAULT VALUES")  # now it holds ids no rule says
        with pytest.raises(id_rule.IdRuleError, match=store.name), db.transaction() as tx:
            id_rule.ensure(tx, store)
        assert db.fetchval("SELECT count(*) FROM tb_id_rule") == 0


def test_the_night_names_the_stores_it_reads_that_hold_ids_of_the_earlier_rule(tmp_path: Path, db_url: str) -> None:
    from omop.schema import schema_for

    cfg = _cfg(tmp_path, db_url)
    check_id_rule(cfg)  # nothing anywhere: the night goes on
    _store_table(db_url, id_rule.DERIVED, 1, None)
    with Database.connect(db_url, schema_for(cfg.lake_dir)) as db:
        db.execute("CREATE TABLE tb_record (source_kind TEXT, resource_type TEXT)")
        db.execute("INSERT INTO tb_record VALUES ('feed', 'Patient')")  # a patient's pseudonym is the same: no matter
    with pytest.raises(id_rule.IdRuleError) as caught:
        check_id_rule(cfg)
    assert caught.value.stores == ["the derived store"]
    with Database.connect(db_url, schema_for(cfg.lake_dir)) as db:
        db.execute("INSERT INTO tb_record VALUES ('feed', 'Condition')")
    with pytest.raises(id_rule.IdRuleError) as caught:
        check_id_rule(cfg)
    assert caught.value.stores == ["the derived store", "the omop store"]


# ------------------------------------------------------------------------------------------------ each store's own write
def _stopped(exc: BaseException, name: str) -> None:
    """The stop says what the night's says: the store, the rule, the runbook step and its command."""
    said = str(exc)
    assert name in said and id_rule.RUNBOOK in said and id_rule.COMMAND in said and "nothing was written" in said


def test_the_omop_store_refuses_a_feed_of_the_new_rule_over_records_of_the_earlier_one(db_url: str) -> None:
    from omop import schema
    from omop.load import load_batch

    feed: dict[str, list[dict[str, Any]]] = {
        "Patient": [{"resourceType": "Patient", "id": "P1", "birthDate": "1960-01-01", "gender": "female"}],
        "Condition": [{"resourceType": "Condition", "id": "c1", "subject": {"reference": "Patient/P1"},
                       "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "E11.9"}]},
                       "onsetDateTime": "2024-07-01"}],
    }  # fmt: skip
    db = schema.connect(db_url, "omop_idrule")
    try:
        load_batch(db, "feed", "2026-10-01", feed, tz="Asia/Taipei")  # an empty store: stamped
        assert db.fetchval("SELECT rule FROM tb_id_rule") == id_rule.RULE
        db.execute("DELETE FROM tb_id_rule")  # its records now of no rule: the store before D-1253
        before = (db.fetchval("SELECT count(*) FROM tb_record"), db.fetchval("SELECT count(*) FROM tb_load"))
        with pytest.raises(id_rule.IdRuleError) as caught:
            load_batch(db, "feed", "2026-10-02", feed, tz="Asia/Taipei")
        _stopped(caught.value, "omop")
        assert (db.fetchval("SELECT count(*) FROM tb_record"), db.fetchval("SELECT count(*) FROM tb_load")) == before
    finally:
        db.close()


def test_the_derived_store_refuses_a_recompute_beside_scores_of_the_earlier_rule(db_url: str) -> None:
    from tb_common.derived_store import DerivedStore

    st = DerivedStore(db_url)
    st.recompute("p1", {}, mapping_version="m")  # an empty store: stamped
    with Database.connect(db_url, "derived") as db:
        assert db.fetchval("SELECT rule FROM tb_id_rule") == id_rule.RULE
        db.execute("DELETE FROM tb_id_rule")
        db.execute("INSERT INTO definition VALUES ('d1', 's', 1, 'x', '{}', 't')")
        db.execute("INSERT INTO score_row (pid, score, def_version, def_sha, mapping_version, anchor_oid, anchor_date, "
                   "value, unit, inputs, fingerprint, computed_at) VALUES ('p1', 's', 'd1', 'x', 'm', 'o1', "
                   "'2026-01-01', 1, 'u', '[]', 'f', 't')")  # fmt: skip
    with pytest.raises(id_rule.IdRuleError) as caught:
        st.recompute("p1", {}, mapping_version="m")
    _stopped(caught.value, "derived")
    with Database.connect(db_url, "derived") as db:
        assert (
            db.fetchval("SELECT count(*) FROM score_row") == 1 and db.fetchval("SELECT count(*) FROM tb_id_rule") == 0
        )


def test_the_patient_twin_refuses_a_document_beside_documents_of_the_earlier_rule(db_url: str) -> None:
    from patient_profile.twin import ProfileStore

    doc = {"pid": "p1", "profile": "v1", "basis": {"snapshot": "2026-10-01"},
           "layers": {"core": {"sex": "F", "birth": "1960-01-01"}}}  # fmt: skip
    twins = ProfileStore(db_url)
    try:
        twins.put(doc, "2026-10-01T00:00:00+00:00")
        twins.db.execute("DELETE FROM tb_id_rule")
        n = twins.db.fetchval("SELECT count(*) FROM tb_patient_profile")
        with pytest.raises(id_rule.IdRuleError) as caught:
            twins.put({**doc, "pid": "p2"}, "2026-10-02T00:00:00+00:00")
        _stopped(caught.value, "profile")
        assert twins.db.fetchval("SELECT count(*) FROM tb_patient_profile") == n
    finally:
        twins.close()


def test_the_candidate_pool_refuses_verdicts_beside_verdicts_of_the_earlier_rule(db_url: str) -> None:
    from orchestrator.db import JobDB

    jobs = JobDB(db_url)
    jobs.pool_upsert("GZQO", "1", [{"pid": "p1", "tier": "high", "verdicts": []}], "J1", "2026-10-01T00:00:00+00:00")
    with Database.connect(db_url, "orch") as db:
        db.execute("DELETE FROM tb_id_rule")
    with pytest.raises(id_rule.IdRuleError) as caught:
        jobs.pool_upsert(
            "GZQO", "1", [{"pid": "p2", "tier": "high", "verdicts": []}], "J2", "2026-10-02T00:00:00+00:00"
        )
    _stopped(caught.value, "orch")
    assert jobs.pool_count(["p1", "p2"]) == 1
