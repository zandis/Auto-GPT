"""OMOP second slice (T-106, D-339): the large clinical tables partitioned by year, and the adapter's dual write into
the CDM (the ``omop.dual_write`` flag): off writes nothing, a between-nights feed reaches the CDM at once and not
``CURRENT``, a failed ``COPY`` rolls the batch back and leaves the NDJSON night as it was, and the foreign-key checks
run after every load and are in the ingest report."""

from __future__ import annotations

import json
import shutil
import time
from datetime import date
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
ICD = "http://hl7.org/fhir/sid/icd-10-cm"
ATC = "http://www.whocc.no/atc"
SITE_A = ROOT / "tests/fixtures/synthetic_patients/site-a"
NIGHT1, NIGHT2 = "2026-10-04", "2026-10-05"


# ------------------------------------------------------------------------------------------------ partitions
def _cond(cid: str, onset: str | None) -> dict[str, Any]:
    c: dict[str, Any] = {
        "resourceType": "Condition",
        "id": cid,
        "subject": {"reference": "Patient/P1"},
        "code": {"coding": [{"system": ICD, "code": "E11.9"}]},
    }
    if onset:
        c["onsetDateTime"] = onset
    return c


def _feed() -> dict[str, list[dict[str, Any]]]:
    return {
        "Patient": [{"resourceType": "Patient", "id": "P1", "birthDate": "1960-01-01", "gender": "female"}],
        "Condition": [_cond("c2019", "2019-03-01"), _cond("c2024a", "2024-07-01"), _cond("c2024b", "2024-12-31")],
        # no date at all (D-275: kept): its required date is imputed from the batch, and flagged
        "MedicationRequest": [
            {
                "resourceType": "MedicationRequest",
                "id": "m-undated",
                "status": "active",
                "intent": "order",
                "subject": {"reference": "Patient/P1"},
                "medicationCodeableConcept": {"coding": [{"system": ATC, "code": "A10BA02"}]},
            }
        ],
    }


@pytest.fixture
def store(db_url: str) -> Any:
    from omop import schema

    db = schema.connect(db_url, "omop_t106")
    yield db
    db.close()


def _rows(db: Any, table: str) -> dict[str, int]:
    from omop.partitions import partitions

    with db.transaction() as tx:
        return {p: int(tx.fetchval(f"SELECT count(*) FROM {p}")) for p in partitions(tx, table)}


def test_rows_are_routed_to_their_year_partition_and_a_reload_changes_nothing(store: Any) -> None:
    from omop.load import load_batch
    from omop.partitions import PARTITIONED

    rep = load_batch(store, "feed", "2026-10-05", _feed(), tz="Asia/Taipei")
    assert rep.inserted == 5 and rep.by_table["condition_occurrence"] == 3
    assert _rows(store, "condition_occurrence") == {
        "condition_occurrence_y2019": 1,
        "condition_occurrence_y2024": 2,
        "condition_occurrence_ydefault": 0,
    }
    # every large table is partitioned, with its default partition, and the official indexes on the parent
    for table in PARTITIONED:
        kind = store.fetchval("SELECT c.relkind FROM pg_class c WHERE c.oid = to_regclass(?)", (table,))
        assert kind == "p", table
    idx = {str(r[0]) for r in store.fetchall("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()")}
    assert {"idx_condition_person_id_1", "idx_measurement_person_id_1", "xpk_condition_occurrence"} <= idx
    again = load_batch(store, "feed", "2026-10-05", _feed(), tz="Asia/Taipei")
    assert (again.inserted, again.updated, again.same) == (0, 0, 5)
    assert sum(_rows(store, "condition_occurrence").values()) == 3


def test_an_imputed_date_lands_in_the_batch_year_partition_and_is_flagged(store: Any) -> None:
    from omop.load import load_batch

    load_batch(store, "feed", "2026-10-05", _feed(), tz="Asia/Taipei")
    assert _rows(store, "drug_exposure") == {"drug_exposure_y2026": 1, "drug_exposure_ydefault": 0}
    got = store.fetchone(
        "SELECT d.drug_exposure_start_date, r.date_imputed FROM drug_exposure_y2026 d JOIN tb_record r "
        "ON r.cdm_table = 'drug_exposure' AND r.record_id = d.drug_exposure_id"
    )
    assert got == (date(2026, 10, 5), True)
    from omop import dqd

    with store.transaction() as tx:
        rel = dqd.relational_violations(tx)
    assert rel["isPrimaryKey drug_exposure.drug_exposure_id"] == 0  # the id alone is still unique


def test_rows_in_the_default_partition_move_to_their_year(store: Any) -> None:
    """Rows written before migration 4 sit in the default partition; the first load of their year moves them."""
    from omop.partitions import ensure_years

    store.execute(
        "INSERT INTO condition_occurrence (condition_occurrence_id, person_id, condition_concept_id, "
        "condition_start_date, condition_type_concept_id) VALUES (900001, 1, 0, '2015-05-05', 0)"
    )
    assert _rows(store, "condition_occurrence") == {"condition_occurrence_ydefault": 1}
    with store.transaction() as tx:
        assert ensure_years(tx, "condition_occurrence", {2015, 2016}) == [
            "condition_occurrence_y2015",
            "condition_occurrence_y2016",
        ]
        assert ensure_years(tx, "condition_occurrence", {2015}) == []  # made once
    assert _rows(store, "condition_occurrence") == {
        "condition_occurrence_y2015": 1,
        "condition_occurrence_y2016": 0,
        "condition_occurrence_ydefault": 0,
    }


def test_migration_4_keeps_the_rows_of_a_store_made_before_it(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from omop import load, schema
    from omop.load import load_batch
    from tb_common.db import Database

    old = Database.connect(db_url, "omop_t106old")
    old.migrate(schema.migrations()[:3])  # a box from before T-106
    from omop import vocab

    vocab.seed(old)
    # today's loader writes tb_record_event.record_before (migration 6, T-202): give the old store the column for
    # this one load and take it away after, so the store is again one from before T-106 when migrations 4 to 6 run
    old.execute("ALTER TABLE tb_record_event ADD COLUMN record_before JSONB")
    with monkeypatch.context() as m:
        m.setattr(load, "PARTITIONED", {})  # the loader before T-106 knew no partition
        load_batch(old, "feed", "2026-10-04", _feed(), tz="Asia/Taipei")
    old.execute("ALTER TABLE tb_record_event DROP COLUMN record_before")
    before = old.fetchall("SELECT * FROM condition_occurrence ORDER BY condition_occurrence_id")
    old.close()
    db = schema.connect(db_url, "omop_t106old")  # migration 4 runs
    try:
        assert db.fetchall("SELECT * FROM condition_occurrence ORDER BY condition_occurrence_id") == before
        assert _rows(db, "condition_occurrence") == {"condition_occurrence_ydefault": 3}
        rep = load_batch(db, "feed", "2026-10-05", _feed(), tz="Asia/Taipei")
        assert rep.same == 5  # nothing changed, so nothing moved yet
        load_batch(
            db,
            "feed",
            "2026-10-06",
            {**_feed(), "Condition": [*_feed()["Condition"], _cond("c2024c", "2024-02-02")]},
            tz="Asia/Taipei",
        )
        got = _rows(db, "condition_occurrence")
        assert got["condition_occurrence_y2024"] == 3 and got["condition_occurrence_ydefault"] == 1  # 2019 stays
    finally:
        db.close()


# ------------------------------------------------------------------------------------------------ the dual write
def _cfg(work: Path, db_url: str) -> Any:
    from adapter.pipeline import AdapterConfig

    (work / "sec").mkdir(parents=True, exist_ok=True)
    (work / "sec" / "site_hmac.key").write_bytes(b"trialbox-test-site-key-0123456789abcdef")
    return AdapterConfig(
        lake_dir=work / "lake",
        secrets_dir=work / "sec",
        site_id="DEMO-A",
        tz="Asia/Taipei",
        mapping_path=ROOT / "services/adapter/mapping/tw_core/demo_his.yaml",
        db_url=db_url,
        audit_dir=work / "audit",
    )


def _night(cfg: Any, src: Path, snap: str) -> Any:
    from adapter.pipeline import run_ingest

    return run_ingest(cfg, "csv", str(src), snapshot=snap, load_fhir=False, rebuild_lake=False, validate=False)


def _omop(cfg: Any, db_url: str) -> Any:
    from omop import schema

    return schema.connect(db_url, schema.schema_for(cfg.lake_dir))


def _schemas(db_url: str) -> set[str]:
    from tb_common.db import Database

    with Database.connect(db_url, "probe") as db:
        return {str(r[0]) for r in db.fetchall("SELECT nspname FROM pg_namespace")}


def test_dual_write_off_writes_nothing(tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from omop import schema

    monkeypatch.delenv("TB_OMOP_DUAL_WRITE", raising=False)
    cfg = _cfg(tmp_path, db_url)
    rep = _night(cfg, SITE_A, NIGHT1)
    assert rep.passed and rep.omop is None
    assert not any(n.endswith(schema.schema_for(cfg.lake_dir)) for n in _schemas(db_url))  # no OMOP store at all
    body = json.loads((cfg.lake_dir / "ndjson" / NIGHT1 / "ingest_report.json").read_text(encoding="utf-8"))
    assert "omop" not in body


def test_dual_write_loads_the_night_and_reports_the_foreign_key_checks(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from adapter.ndjson import read_all

    monkeypatch.setenv("TB_OMOP_DUAL_WRITE", "on")
    cfg = _cfg(tmp_path, db_url)
    rep = _night(cfg, SITE_A, NIGHT1)
    assert rep.passed and rep.omop is not None and rep.omop.state == "loaded", rep.omop
    assert rep.omop.batch == NIGHT1 and rep.omop.counts and rep.omop.counts["inserted"] > 0
    assert rep.omop.relational_checks and rep.omop.relational_checks > 50  # isRequired, isPrimaryKey, isForeignKey
    feed = read_all(cfg.lake_dir / "ndjson" / NIGHT1)
    db = _omop(cfg, db_url)
    try:
        assert db.fetchval("SELECT count(*) FROM person") == len(feed["Patient"])
        n_cond = db.fetchval("SELECT count(*) FROM tb_record WHERE resource_type = 'Condition'")
        assert n_cond == len(feed["Condition"])
        assert db.fetchval("SELECT count(*) FROM condition_occurrence_ydefault") == 0
    finally:
        db.close()
    body = json.loads((cfg.lake_dir / "ndjson" / NIGHT1 / "ingest_report.json").read_text(encoding="utf-8"))
    assert body["omop"]["state"] == "loaded" and "relational_failed" in body["omop"]
    events = [json.loads(x) for f in sorted((tmp_path / "audit").rglob("*.jsonl")) for x in f.read_text().splitlines()]
    done = [e for e in events if e.get("event") == "ingest.done"]
    assert done and done[-1]["detail"]["omop"]["state"] == "loaded"


def test_a_feed_between_nights_is_in_the_cdm_at_once_and_not_in_current(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TB_OMOP_DUAL_WRITE", "on")
    cfg = _cfg(tmp_path, db_url)
    assert _night(cfg, SITE_A, NIGHT1).omop.state == "loaded"
    (cfg.lake_dir / "CURRENT").write_text(NIGHT1 + "\n")  # the night's rebuild published NIGHT1
    src = tmp_path / "src"
    shutil.copytree(SITE_A, src)
    with (src / "diagnosis.csv").open("a", encoding="utf-8") as fh:  # a diagnosis entered during the day
        fh.write("D19999999,E10000005,10000001,I10,2026-10-05,2026-10-05,A\n")
    t0 = time.monotonic()
    rep = _night(cfg, src, NIGHT2)  # the feed file of 10:00, run on its own (no lake rebuild)
    elapsed = time.monotonic() - t0
    assert rep.passed and rep.omop.state == "loaded" and rep.omop.counts["inserted"] == 1, rep.omop
    assert elapsed < 300  # within five minutes of the file
    db = _omop(cfg, db_url)
    try:
        got = db.fetchone(
            "SELECT c.condition_source_value, c.condition_start_date FROM tb_record r JOIN condition_occurrence c "
            "ON c.condition_occurrence_id = r.record_id WHERE r.cdm_table = 'condition_occurrence' "
            "AND r.first_batch = ?",
            (NIGHT2,),
        )
        assert got == ("I10", date(2026, 10, 5))
    finally:
        db.close()
    assert (cfg.lake_dir / "CURRENT").read_text().strip() == NIGHT1  # screening still reads the last night


def test_a_copy_failure_rolls_the_batch_back_and_leaves_the_night_alone(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tb_common.db import Tx

    monkeypatch.setenv("TB_OMOP_DUAL_WRITE", "on")
    real = Tx.copy_rows

    def broken(self: Any, table: str, columns: Any, rows: Any) -> int:
        if table == "measurement":
            raise OSError("disk full during COPY")
        return real(self, table, columns, rows)

    monkeypatch.setattr(Tx, "copy_rows", broken)
    cfg = _cfg(tmp_path, db_url)
    rep = _night(cfg, SITE_A, NIGHT1)
    monkeypatch.setattr(Tx, "copy_rows", real)
    assert rep.passed and not rep.held and not rep.errors  # the NDJSON night is as without the dual write
    assert rep.omop is not None and rep.omop.state == "failed" and rep.omop.error == "OSError"
    assert (cfg.lake_dir / "ndjson" / NIGHT1 / "passed.json").exists()
    db = _omop(cfg, db_url)
    try:  # never half-loaded
        assert [db.fetchval(f"SELECT count(*) FROM {t}") for t in ("person", "condition_occurrence", "tb_record")] == [
            0,
            0,
            0,
        ]
        assert db.fetchall("SELECT source_kind, batch FROM tb_load") == [("feed-failed", NIGHT1)]
    finally:
        db.close()


def test_an_undeclared_dual_write_seed_is_refused_not_guessed(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from adapter.dual_write import load_night

    monkeypatch.setenv("TB_OMOP_DUAL_WRITE", "maybe")
    cfg = _cfg(tmp_path, db_url)
    got = load_night(cfg, NIGHT1, tmp_path)
    assert got is not None and got.state == "failed" and got.error == "ValueError"


def test_cdm_source_names_the_athena_release_once_loaded(store: Any) -> None:
    """``cdm_source.vocabulary_version`` is the active Athena release (its ``None`` vocabulary row, T-105b), cut to
    the CDM's 20 characters; before any Athena load it says the vocabulary is local."""
    from omop import vocab_load
    from omop.load import load_batch

    load_batch(store, "feed", "2026-10-05", _feed(), tz="Asia/Taipei")
    assert store.fetchval("SELECT vocabulary_version FROM cdm_source") == "TB local, no Athena"
    vocab_load.load_athena(store, ROOT / "tests/fixtures/vocab/athena-test", by="test")
    load_batch(store, "feed", "2026-10-06", _feed(), tz="Asia/Taipei")
    assert store.fetchval("SELECT vocabulary_version FROM cdm_source") == "v5.0 TEST-SYNTHETIC 10-NOV-26"[:20]
