"""The OMOP CDM v5.4 core (D-151): pinned DDL, the loader (pseudonyms, local concepts, source values, idempotent
re-loads, tombstones, status, provenance, conflicts), the export, the ``TB_LAKE_SOURCE`` setting, the DQD checks,
and the equivalence of the two lakes for every committed ruleset."""

from __future__ import annotations

import copy
import csv
import json
import os
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SNAP = "2026-10-04"


@pytest.fixture(scope="module")
def feed_dir(tmp_path_factory: pytest.TempPathFactory, pg_cluster_url: str) -> Path:
    """The committed synthetic site A (600 patients) through the real adapter: the snapshot's NDJSON."""
    from adapter.pipeline import AdapterConfig, run_ingest

    work = tmp_path_factory.mktemp("omop-feed")
    (work / "sec").mkdir()
    (work / "sec" / "site_hmac.key").write_bytes(b"trialbox-test-site-key-0123456789abcdef")
    cfg = AdapterConfig(
        lake_dir=work / "lake",
        secrets_dir=work / "sec",
        site_id="DEMO-A",
        tz="Asia/Taipei",
        mapping_path=ROOT / "services/adapter/mapping/tw_core/demo_his.yaml",
        db_url=f"{pg_cluster_url}{'&' if '?' in pg_cluster_url else '?'}tb_prefix=omopfeed{os.getpid()}_",
        audit_dir=work / "audit",
    )
    rep = run_ingest(
        cfg,
        "csv",
        str(ROOT / "tests/fixtures/synthetic_patients/site-a"),
        snapshot=SNAP,
        load_fhir=False,
        rebuild_lake=False,
        validate=False,
    )
    assert not rep.errors
    return work / "lake" / "ndjson" / SNAP


def _feed(feed_dir: Path) -> dict[str, list[dict[str, Any]]]:
    from adapter.ndjson import read_all

    return read_all(feed_dir)


def _legacy(feed: dict[str, Any], site: dict[str, Any] | None = None) -> dict[str, list[dict[str, Any]]]:
    from lake.source import lake_rows

    return lake_rows(feed, site or {}, tz="Asia/Taipei", snapshot=SNAP, source="legacy")


def _site(feed_dir: Path) -> dict[str, list[dict[str, Any]]]:
    from tools.omop_parity import planted_site_inputs

    return planted_site_inputs(feed_dir)


def _load(db: Any, feed: dict[str, Any], site: dict[str, Any] | None = None, snap: str = SNAP) -> list[Any]:
    from omop.load import load_batch

    return [
        load_batch(db, "feed", snap, feed, tz="Asia/Taipei"),
        load_batch(db, "site", f"site@{snap}", site or {}, tz="Asia/Taipei"),
    ]


@pytest.fixture
def db(db_url: str) -> Any:
    from omop import schema

    d = schema.connect(db_url)
    yield d
    d.close()


# ------------------------------------------------------------------------------------------------ schema
def test_ddl_is_the_pinned_official_v54_and_a_changed_file_is_refused(tmp_path: Path, monkeypatch: Any) -> None:
    from omop import schema

    pin = json.loads((schema.DDL_DIR / "pin.json").read_text())
    assert pin["tag"] == "v5.4.2" and pin["source"] == "OHDSI/CommonDataModel"
    assert set(schema.pinned()) == set(pin["files"])
    ddl = schema.cdm_ddl()
    for t in schema.CDM_TABLES:
        assert f"CREATE TABLE {t} (" in ddl, t
    assert "CREATE TABLE visit_detail" not in ddl and "@cdmDatabaseSchema" not in ddl
    assert "ADD CONSTRAINT xpk_person PRIMARY KEY (person_id)" in ddl and "FOREIGN KEY" not in ddl
    fks = schema.foreign_keys()
    assert ("condition_occurrence", "person_id", "person", "person_id") in fks
    for f in schema.DDL_DIR.iterdir():
        shutil.copy(f, tmp_path / f.name)
    (tmp_path / "OMOPCDM_postgresql_5.4_ddl.sql").write_text("CREATE TABLE x (a int);")
    monkeypatch.setattr(schema, "DDL_DIR", tmp_path)
    with pytest.raises(schema.OmopError, match="does not match its pin"):
        schema.pinned()


def test_schema_has_the_cdm_tables_beside_the_extension_tables(db: Any) -> None:
    from omop import schema

    tables = {
        r[0]
        for r in db.fetchall("SELECT table_name FROM information_schema.tables WHERE table_schema = ?", (db.schema,))
    }
    assert set(schema.CDM_TABLES) <= tables
    assert {"tb_record", "tb_record_event", "tb_conflict", "tb_id_map", "tb_load"} <= tables
    cols = [
        r[0]
        for r in db.fetchall(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = ? "
            "AND table_name = 'measurement' ORDER BY ordinal_position",
            (db.schema,),
        )
    ]
    assert cols[-2:] == ["measurement_event_id", "meas_event_field_concept_id"]  # v5.4 columns
    assert db.schema.endswith("omop")
    assert db.fetchval("SELECT concept_name FROM concept WHERE concept_id = 0") == "No matching concept"
    again = schema.connect(db.url)  # a re-connect migrates nothing
    assert again.fetchval("SELECT max(version) FROM _schema_version") == 2
    again.close()


def test_local_concept_block_is_at_least_two_billion(monkeypatch: Any) -> None:
    from omop import schema

    monkeypatch.setenv("TB_OMOP_CONCEPT_BLOCK", "1999999999")
    with pytest.raises(schema.OmopError, match="2,000,000,000"):
        schema.concept_block()
    monkeypatch.setenv("TB_OMOP_CONCEPT_BLOCK", "2140000000")
    assert schema.concept_block() == (2_140_000_000, schema.INT4_MAX)  # a site block ends at the integer maximum


# ------------------------------------------------------------------------------------------------ loader
def test_export_equals_the_flattener_and_a_reload_changes_nothing(feed_dir: Path, db: Any) -> None:
    from lake.flatten import SCHEMAS
    from omop.export import export_rows

    feed = _feed(feed_dir)
    legacy = _legacy(feed)
    first = _load(db, feed)[0]
    assert first.inserted > 5000 and first.updated == first.tombstoned == 0
    ids = db.fetchall("SELECT id_kind, source_id, omop_id FROM tb_id_map ORDER BY 1, 2")
    out = export_rows(db)
    for name in SCHEMAS:
        assert out[name] == legacy[name], name
    again = _load(db, feed)[0]
    assert (again.inserted, again.updated, again.tombstoned, again.same) == (0, 0, 0, first.inserted)
    assert db.fetchall("SELECT id_kind, source_id, omop_id FROM tb_id_map ORDER BY 1, 2") == ids
    assert export_rows(db) == out


def test_pseudonyms_source_values_and_local_concepts(feed_dir: Path, db: Any) -> None:
    from omop.schema import LOCAL_MIN

    _load(db, _feed(feed_dir))
    mrns = {
        r["mrn"]
        for r in csv.DictReader((ROOT / "tests/fixtures/synthetic_patients/site-a/patient.csv").open(encoding="utf-8"))
    }
    psv = [r[0] for r in db.fetchall("SELECT person_source_value FROM person")]
    assert len(psv) == 600 and not mrns & set(psv) and all(len(p) == 32 for p in psv)
    assert db.fetchval("SELECT max(person_id) FROM person") < 10_000  # minted integers, not hashes of a chart number
    icd = db.fetchall(
        "SELECT DISTINCT c.condition_source_value, k.vocabulary_id, v.vocabulary_reference, k.standard_concept "
        "FROM condition_occurrence c JOIN concept k ON k.concept_id = c.condition_source_concept_id "
        "JOIN vocabulary v USING (vocabulary_id)"
    )
    assert icd and all(
        r[1] == "TB-ICD10CM" and r[2] == "http://hl7.org/fhir/sid/icd-10-cm" and r[3] is None for r in icd
    )
    assert "M10.9" in {r[0] for r in icd}
    assert db.fetchval("SELECT count(*) FROM condition_occurrence WHERE condition_concept_id <> 0") == 0
    loinc = {
        r[0]
        for r in db.fetchall(
            "SELECT measurement_source_value FROM measurement m JOIN concept k ON "
            "k.concept_id = m.measurement_source_concept_id WHERE k.vocabulary_id = "
            "'TB-LOINC'"
        )
    }
    assert {"2160-0", "3084-1"} <= loinc
    atc = {
        r[0]
        for r in db.fetchall(
            "SELECT drug_source_value FROM drug_exposure d JOIN concept k ON "
            "k.concept_id = d.drug_source_concept_id WHERE k.vocabulary_id = 'TB-ATC'"
        )
    }
    assert "M04AA01" in atc
    for col, table in (
        ("condition_source_concept_id", "condition_occurrence"),
        ("measurement_source_concept_id", "measurement"),
        ("drug_source_concept_id", "drug_exposure"),
        ("procedure_source_concept_id", "procedure_occurrence"),
    ):
        assert db.fetchval(f"SELECT count(*) FROM {table} WHERE {col} <> 0 AND {col} < ?", (LOCAL_MIN,)) == 0
    assert (
        db.fetchval("SELECT count(*) FROM concept WHERE vocabulary_id LIKE 'TB-%' AND concept_id < ?", (LOCAL_MIN,))
        == 0
    )
    prov = db.fetchone(
        "SELECT source_kind, source_batch, source_file, source_row FROM tb_record "
        "WHERE resource_type = 'Condition' ORDER BY source_row LIMIT 1"
    )
    assert prov is not None and prov[:2] == ("feed", SNAP) and prov[3] == 1


def test_a_standard_concept_is_used_where_the_vocabulary_has_one(feed_dir: Path, db: Any) -> None:
    from omop.vocab import VALID_FROM, VALID_TO

    db.execute("INSERT INTO vocabulary VALUES ('LOINC', 'LOINC', 'http://loinc.org', '2.78', 0)")
    db.execute(
        "INSERT INTO concept VALUES (3016723, 'Creatinine [Mass/volume] in Serum or Plasma', 'Measurement', "
        "'LOINC', 'Lab Test', 'S', '2160-0', ?, ?, NULL)",
        (VALID_FROM, VALID_TO),
    )
    _load(db, _feed(feed_dir))
    got = db.fetchall(
        "SELECT DISTINCT measurement_concept_id, measurement_source_concept_id >= 2000000000 "
        "FROM measurement WHERE measurement_source_value = '2160-0'"
    )
    assert got == [(3016723, True)]
    assert (
        db.fetchval(
            "SELECT count(*) FROM measurement WHERE measurement_source_value = '3084-1' AND measurement_concept_id <> 0"
        )
        == 0
    )


def test_tombstones_restore_and_in_place_updates(feed_dir: Path, db: Any) -> None:
    from omop.export import export_rows

    feed = _feed(feed_dir)
    _load(db, feed)
    gone_c = feed["Condition"][0]
    gone_p = feed["Patient"][0]
    cid = db.fetchval(
        "SELECT record_id FROM tb_record WHERE resource_type = 'Condition' AND source_record_id = ?", (gone_c["id"],)
    )
    nxt = copy.deepcopy(feed)
    nxt["Condition"] = copy.deepcopy(feed["Condition"][1:])
    nxt["Patient"] = feed["Patient"][1:]
    changed = nxt["Condition"][0]
    old_code = changed["code"]["coding"][0]["code"]
    changed["code"]["coding"][0]["code"] = "Z99.9"
    rep = _load(db, nxt, snap="2026-10-05")[0]
    assert (rep.tombstoned, rep.updated) == (2, 1)
    assert db.fetchval("SELECT count(*) FROM condition_occurrence WHERE condition_occurrence_id = ?", (cid,)) == 0
    assert (
        db.fetchval(
            "SELECT status FROM tb_record WHERE source_record_id = ? AND resource_type = 'Condition'", (gone_c["id"],)
        )
        == "tombstoned"
    )
    ev = db.fetchone(
        "SELECT e.before ->> 'condition_source_value', e.from_status FROM tb_record_event e JOIN "
        "tb_record r USING (record_key) WHERE r.source_record_id = ? AND e.event = 'tombstone'",
        (gone_c["id"],),
    )
    assert ev == (gone_c["code"]["coding"][0]["code"], "coded")  # the before-image is kept
    upd = db.fetchone(
        "SELECT e.before ->> 'condition_source_value' FROM tb_record_event e JOIN tb_record r "
        "USING (record_key) WHERE r.source_record_id = ? AND e.event = 'update'",
        (changed["id"],),
    )
    assert upd == (old_code,)
    out = export_rows(db)
    assert gone_c["id"] not in {r["cid"] for r in out["condition"]}
    assert gone_p["id"] not in {r["pid"] for r in out["patient"]}
    assert out == _legacy(nxt)
    back = _load(db, feed, snap="2026-10-06")[0]
    assert back.restored == 2 and back.updated == 1
    assert (
        db.fetchval(
            "SELECT record_id FROM tb_record WHERE resource_type = 'Condition' AND source_record_id = ?",
            (gone_c["id"],),
        )
        == cid
    )  # restored with its id
    assert export_rows(db) == _legacy(feed)


def test_an_older_batch_is_refused(feed_dir: Path, db: Any) -> None:
    from omop.load import load_batch
    from omop.schema import OmopError

    load_batch(db, "feed", "2026-10-05", _feed(feed_dir))
    with pytest.raises(OmopError, match="older batch"):
        load_batch(db, "feed", "2026-10-04", _feed(feed_dir))


def test_site_inputs_status_and_conflicts(feed_dir: Path, db: Any) -> None:
    from omop import vocab
    from omop.export import export_rows
    from omop.load import resolve_conflict

    feed, site = _feed(feed_dir), _site(feed_dir)
    legacy = _legacy(feed, site)
    _load(db, feed, site)
    out = export_rows(db)
    assert out == legacy
    assert {r["basis"] for r in out["site_fact"]} == {"proposed", "confirmed", "suspected"}
    st = dict(
        db.fetchall(
            "SELECT source_record_id, status FROM tb_record WHERE source_kind = 'site' AND resource_type = 'Condition'"
        )
    )
    assert st["tbsf-c0"] == "proposed" and st["tbsf-c1"] == "confirmed" and st["tbsf-v1"] == "rejected"
    assert (
        db.fetchval(
            "SELECT condition_type_concept_id FROM condition_occurrence c JOIN tb_record r ON "
            "r.record_id = c.condition_occurrence_id AND r.cdm_table = 'condition_occurrence' "
            "WHERE r.source_record_id = 'tbsf-c0'"
        )
        == vocab.PROPOSED_FACT
    )
    assert (
        db.fetchval(
            "SELECT condition_status_concept_id FROM condition_occurrence c JOIN tb_record r ON "
            "r.record_id = c.condition_occurrence_id AND r.cdm_table = 'condition_occurrence' "
            "WHERE r.source_record_id = 'tbsf-v0'"
        )
        == vocab.SUSPECTED
    )
    # a proposed fact never reaches a coded table; a suspected or refuted diagnosis neither
    coded = {r["cid"] for r in out["condition"]}
    assert not {"tbsf-c0", "tbsf-v0", "tbsf-v1"} & coded and "tbsf-c1" in coded
    conf = db.fetchall(
        "SELECT conflict_id, person_id, item, claims FROM tb_conflict WHERE state = 'open' ORDER BY conflict_id"
    )
    assert len(conf) == 8 and {c[2] for c in conf} == {"birth_date"}  # every fifth of 40 patients
    pid = db.fetchval("SELECT source_id FROM tb_id_map WHERE id_kind = 'person' AND omop_id = ?", (conf[0][1],))
    by_pid = {r["pid"]: r for r in out["patient"]}
    assert by_pid[pid]["birth_date"] is None  # open: unknown, never a guess
    hospital = conf[0][3][0]["value"]
    assert conf[0][3][0]["source"][0] == "feed"
    resolve_conflict(db, conf[0][0], hospital, by="steward:ito", reason="the EMR is right; the sheet mistyped")
    assert {r["pid"]: r for r in export_rows(db)["patient"]}[pid]["birth_date"].isoformat() == hospital
    again = _load(db, feed, site)  # the same disagreement again: the resolution stands, nothing reopens
    assert again[1].same > 0 and db.fetchval("SELECT count(*) FROM tb_conflict WHERE state = 'open'") == 7
    fixed = copy.deepcopy(site)  # the sheet is corrected: the conflict is withdrawn
    fixed["Patient"] = [p for p in fixed["Patient"] if p["id"] != pid]
    _load(db, feed, fixed, snap="2026-10-05")
    assert db.fetchval("SELECT state FROM tb_conflict WHERE conflict_id = ?", (conf[0][0],)) == "withdrawn"


def test_a_person_confirms_a_proposed_fact_within_the_state_machine(feed_dir: Path, db: Any) -> None:
    from omop.export import export_rows
    from omop.load import set_status
    from omop.schema import OmopError

    feed, site = _feed(feed_dir), _site(feed_dir)
    _load(db, feed, site)
    key = ("site", "Condition", "tbsf-c0", 0)
    with pytest.raises(OmopError, match="cannot become"):
        set_status(db, ("site", "Condition", "tbsf-c1", 0), "proposed", "crc:x", "undo")
    with pytest.raises(OmopError, match="reason"):
        set_status(db, key, "confirmed", "steward:ito", " ")
    set_status(db, key, "confirmed", "steward:ito", "read in the chart of 2026-01-10")
    out = export_rows(db)
    assert "tbsf-c0" in {r["cid"] for r in out["condition"]}
    assert {r["fid"]: r["basis"] for r in out["site_fact"]}["tbsf-c0"] == "confirmed"
    _load(db, feed, site)  # the source did not change: the person's decision stands
    assert db.fetchval("SELECT status FROM tb_record WHERE source_record_id = 'tbsf-c0'") == "confirmed"
    assert (
        db.fetchval(
            "SELECT actor FROM tb_record_event e JOIN tb_record r USING (record_key) WHERE "
            "r.source_record_id = 'tbsf-c0' AND e.event = 'status'"
        )
        == "steward:ito"
    )


# ------------------------------------------------------------------------------------------------ the setting
def test_lake_source_setting(monkeypatch: Any) -> None:
    from lake.source import lake_source

    monkeypatch.delenv("TB_LAKE_SOURCE", raising=False)
    assert lake_source() == "legacy"
    monkeypatch.setenv("TB_LAKE_SOURCE", " OMOP ")
    assert lake_source() == "omop"
    monkeypatch.setenv("TB_LAKE_SOURCE", "fhir")
    with pytest.raises(ValueError, match="TB_LAKE_SOURCE"):
        lake_source()


# ------------------------------------------------------------------------------------------------ DQD
def test_dqd_passes_on_the_loaded_site_and_catches_a_broken_reference(feed_dir: Path, db: Any) -> None:
    from omop import dqd

    _load(db, _feed(feed_dir), _site(feed_dir))
    res = dqd.run(db)
    names = {r["checkName"] for r in res}
    assert {
        "isRequired",
        "isPrimaryKey",
        "isForeignKey",
        "fkDomain",
        "isStandardValidConcept",
        "measurePersonCompleteness",
        "sourceConceptRecordCompleteness",
        "standardConceptRecordCompleteness",
        "plausibleValueLow",
        "plausibleAfterBirth",
        "plausibleBeforeDeath",
        "plausibleStartBeforeEnd",
        "tbLocalConceptRange",
        "tbProvenance",
    } <= names
    assert [r for r in res if r["status"] == "fail"] == []
    known = {(r["checkName"], r["cdmTableName"]) for r in res if r["status"] == "known"}
    assert ("standardConceptRecordCompleteness", "condition_occurrence") in known  # no Athena yet: said so
    db.execute(
        "UPDATE condition_occurrence SET person_id = 999999 WHERE condition_occurrence_id = "
        "(SELECT min(condition_occurrence_id) FROM condition_occurrence)"
    )
    bad = [r for r in dqd.run(db) if r["status"] == "fail"]
    assert [(r["checkName"], r["cdmTableName"], r["cdmFieldName"], r["numViolatedRows"]) for r in bad] == [
        ("isForeignKey", "condition_occurrence", "person_id", 1)
    ]


# ------------------------------------------------------------------------------------------------ equivalence
def test_every_committed_ruleset_screens_the_same_on_both_lakes(feed_dir: Path, db_url: str, tmp_path: Path) -> None:
    from tools import omop_parity as op

    assert len(op.RULESETS) == 7
    ds = op.DataSet("site-a", feed_dir, _site(feed_dir), SNAP, date(2026, 10, 5), "Asia/Taipei")
    lakes = op.build_lakes(ds, tmp_path, db_url)
    tables = op.compare_tables(lakes, SNAP)
    assert all(t["identical"] for t in tables.values()), {k: v for k, v in tables.items() if not v["identical"]}
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal

    duck = {s: LakeLocal(d, HashEmbedder(), "Asia/Taipei") for s, d in lakes.items()}  # through Lake.rebuild
    for t in ("site_fact", "document_chunk", "patient"):
        got = [duck[s].query(f"SELECT * FROM {t}").to_pylist() for s in ("legacy", "omop")]
        assert got[0] == got[1] and got[0], t
    res = op.compare_screening(lakes, ds)
    assert set(res) == {"GOUT-COH", "GZQO", "ONC-OSI", "RA-BIO", "RA-COH", "EMPULSE", "STARRT-AKI"}
    for rid, r in res.items():
        assert r["feas_identical"] and r["patients_different"] == 0, (rid, r)
        assert r["patients_evaluated"] == r["patients"] == 600
    assert sum(r["verdicts"].get("met", 0) for r in res.values()) > 0


def test_the_parity_tool_only_touches_its_own_schemas(tmp_path: Path) -> None:
    """Review H2/H4: a TB_DB_URL with no prefix (a box, CI) must not let the parity run write to, or drop, every
    schema; the run's prefix is private to its work directory and never empty."""
    from tb_common.db import split_url

    from tools import omop_parity as op
    from tools import pglocal

    bare = "postgresql://u@localhost/tb"
    url, prefix = op.private_url(bare, tmp_path / "a")
    assert prefix.startswith("par") and split_url(url) == ("postgresql://u@localhost/tb", prefix)
    url2, prefix2 = op.private_url("postgresql://u@h/tb?sslmode=disable&tb_prefix=w1_", tmp_path / "a")
    assert prefix2 == "w1_" + prefix and split_url(url2)[1] == prefix2 and "sslmode=disable" in url2
    assert op.private_url(bare, tmp_path / "b")[1] != prefix
    assert split_url(f"{url}omop0_")[1] == prefix + "omop0_"
    with pytest.raises(ValueError, match="empty prefix"):
        pglocal.drop_prefix(bare, "")
