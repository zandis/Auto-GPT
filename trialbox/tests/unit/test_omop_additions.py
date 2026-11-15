"""OMOP additions (T-106b): all 39 CDM v5.4 tables (STD-032); rows routed by their concept's domain and standard
value concepts (STD-031); the visit's end (STD-018); row provenance from the mapper to every lake row and through
OMOP (DATA-010); a late re-run of an older night never becomes ``CURRENT`` (DATA-007). Each OMOP case checks parity:
the lake exported from OMOP equals the lake flattened from the same NDJSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

ICD = "http://hl7.org/fhir/sid/icd-10-cm"
LOINC = "http://loinc.org"
TZ = "Asia/Taipei"
# Athena-shaped rows (ids below 2e9, as the bundle has them): synthetic ids, the real codes and domains
ATHENA = (
    # (concept_id, code, domain, vocabulary, standard)
    (1_500_000_001, "Z87.891", "Observation", "ICD10CM", None),  # history of nicotine dependence: OBSERVATION
    (1_500_000_002, "E11.9", "Condition", "ICD10CM", None),
    (1_500_000_003, "72166-2", "Observation", "LOINC", "S"),  # tobacco smoking status: a survey item
    (1_500_000_004, "LA18978-9", "Meas Value", "LOINC", "S"),  # "Never smoker"
    (1_500_000_005, "2345-7", "Measurement", "LOINC", "S"),  # glucose
)


@pytest.fixture
def store(db_url: str) -> Any:
    from omop import schema

    db = schema.connect(db_url, "omop_t106b")
    yield db
    db.close()


def _athena(db: Any) -> None:
    with db.transaction() as tx:
        for cid, code, dom, voc, std in ATHENA:
            tx.execute(
                "INSERT INTO concept (concept_id, concept_name, domain_id, vocabulary_id, concept_class_id, "
                "standard_concept, concept_code, valid_start_date, valid_end_date) VALUES "
                "(?, ?, ?, ?, 'Clinical', ?, ?, DATE '1970-01-01', DATE '2099-12-31')",
                (cid, code, dom, voc, std, code),
            )


def _prov(night: str) -> dict[str, Any]:
    return {
        "source": "S1/diagnosis#abc123",
        "lastUpdated": f"{night}T00:00:00+08:00",
        "tag": [{"system": "urn:trialbox:mapping-version", "code": "t@0123456789ab"}],
    }


def _feed(night: str = "2026-10-05") -> dict[str, list[dict[str, Any]]]:
    subj = {"reference": "Patient/P1"}
    return {
        "Patient": [
            {"resourceType": "Patient", "id": "P1", "birthDate": "1960-01-01", "gender": "female", "meta": _prov(night)}
        ],
        "Encounter": [
            {
                "resourceType": "Encounter",
                "id": "e-in",
                "status": "finished",
                "class": {"code": "IMP"},
                "subject": subj,
                "period": {"start": "2026-09-01T10:00:00+08:00", "end": "2026-09-04T09:30:00+08:00"},
            },
            {
                "resourceType": "Encounter",
                "id": "e-now",
                "status": "in-progress",
                "class": {"code": "IMP"},
                "subject": subj,
                "period": {"start": "2026-10-03T08:00:00+08:00"},
            },
        ],
        "Condition": [
            {
                "resourceType": "Condition",
                "id": "c-z",
                "subject": subj,
                "onsetDateTime": "2026-09-02",
                "code": {"coding": [{"system": ICD, "code": "Z87.891"}]},
                "meta": _prov(night),
                "encounter": {"reference": "Encounter/e-in"},
            },
            {
                "resourceType": "Condition",
                "id": "c-dm",
                "subject": subj,
                "onsetDateTime": "2026-09-02",
                "code": {"coding": [{"system": ICD, "code": "E11.9"}]},
                "meta": _prov(night),
            },
        ],
        "Observation": [
            {
                "resourceType": "Observation",
                "id": "o-smoke",
                "status": "final",
                "subject": subj,
                "effectiveDateTime": "2026-09-02T11:00:00+08:00",
                "code": {"coding": [{"system": LOINC, "code": "72166-2"}]},
                "valueCodeableConcept": {"coding": [{"system": LOINC, "code": "LA18978-9"}], "text": "Never smoker"},
            },
            {
                "resourceType": "Observation",
                "id": "o-glu",
                "status": "final",
                "subject": subj,
                "effectiveDateTime": "2026-09-02T11:00:00+08:00",
                "code": {"coding": [{"system": LOINC, "code": "2345-7"}]},
                "valueQuantity": {"value": 5.4, "comparator": "<", "unit": "mmol/L"},
            },
        ],
    }


def _legacy(feed: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    from lake.source import lake_rows

    return lake_rows(feed, {}, tz=TZ, snapshot="2026-10-05", source="legacy")


def _parity(db: Any, feed: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    from lake.flatten import SCHEMAS
    from omop.export import export_rows

    out = export_rows(db)
    legacy = _legacy(feed)
    for name in SCHEMAS:
        assert out[name] == legacy[name], name
    return out


def _where(db: Any, srcid: str) -> tuple[str, int]:
    row = db.fetchone("SELECT cdm_table, record_id FROM tb_record WHERE source_record_id = ?", (srcid,))
    return str(row[0]), int(row[1])


# ------------------------------------------------------------------------------------------------ 39 tables
def test_the_store_holds_all_39_cdm_tables(store: Any) -> None:
    from omop import schema

    ddl = (schema.DDL_DIR / "OMOPCDM_postgresql_5.4_ddl.sql").read_text(encoding="utf-8")
    assert ddl.count("CREATE TABLE @cdmDatabaseSchema.") == 39 == len(schema.ALL_CDM_TABLES)
    tables = {
        str(r[0])
        for r in store.fetchall(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"
        )
    }
    assert set(schema.ALL_CDM_TABLES) <= tables
    keys = {str(r[0]) for r in store.fetchall("SELECT conname FROM pg_constraint WHERE contype = 'p'")}
    assert {"xpk_visit_detail", "xpk_specimen", "xpk_location", "xpk_metadata", "xpk_episode"} <= keys
    assert (
        store.fetchval("SELECT max(version) FROM _schema_version") == 9
    )  # D-441 tb_withheld; D-655 family; D-753 bigint


# ------------------------------------------------------------------------------------------------ domain routing
def test_without_a_vocabulary_the_resource_type_decides(store: Any) -> None:
    from omop.load import load_batch

    feed = _feed()
    load_batch(store, "feed", "2026-10-05", feed, tz=TZ)
    assert _where(store, "c-z")[0] == "condition_occurrence"
    assert _where(store, "o-smoke")[0] == "measurement"
    _parity(store, feed)


def test_rows_go_to_the_table_of_their_domain_and_the_lake_does_not_move(store: Any) -> None:
    from omop.load import load_batch

    feed = _feed()
    first = load_batch(store, "feed", "2026-10-05", feed, tz=TZ)  # no vocabulary: by resource type
    ids = {s: _where(store, s)[1] for s in ("c-z", "o-smoke", "c-dm")}
    _athena(store)
    rep = load_batch(store, "feed", "2026-10-06", feed, tz=TZ)
    # the Z code (an Observation-domain source concept) and the survey item (a standard Observation concept) move
    assert _where(store, "c-z") == ("observation", ids["c-z"])  # same OMOP id in its new table
    assert _where(store, "o-smoke") == ("observation", ids["o-smoke"])
    assert _where(store, "c-dm") == ("condition_occurrence", ids["c-dm"])
    assert _where(store, "o-glu")[0] == "measurement"
    assert rep.skipped["routed:condition_occurrence:observation"] == 1
    assert rep.skipped["routed:measurement:observation"] == 1
    assert first.inserted == rep.updated + rep.same
    z = store.fetchone(
        "SELECT observation_source_value, observation_date, visit_occurrence_id FROM observation "
        "WHERE observation_id = ?",
        (ids["c-z"],),
    )
    assert z[0] == "Z87.891" and str(z[1]) == "2026-09-02" and z[2] is not None
    smoke = store.fetchone(
        "SELECT observation_concept_id, value_as_concept_id FROM observation WHERE observation_id = ?",
        (ids["o-smoke"],),
    )
    assert tuple(smoke) == (1_500_000_003, 1_500_000_004)  # standard concept and standard answer concept
    gone = store.fetchval("SELECT count(*) FROM condition_occurrence WHERE condition_occurrence_id = ?", (ids["c-z"],))
    assert gone == 0
    out = _parity(store, feed)  # read back by resource type: the same lake as the flattener's
    assert {r["cid"] for r in out["condition"]} == {"c-z", "c-dm"}
    assert {r["oid"]: r["value_code"] for r in out["observation"]}["o-smoke"] == "LA18978-9"
    again = load_batch(store, "feed", "2026-10-07", feed, tz=TZ)
    assert (again.inserted, again.updated, again.same) == (0, 0, first.inserted)


def test_a_censored_lab_routed_to_observation_keeps_its_operator(store: Any) -> None:
    from omop.load import load_batch

    _athena(store)
    with store.transaction() as tx:  # make glucose an Observation-domain concept for this case
        tx.execute("UPDATE concept SET domain_id = 'Observation' WHERE concept_id = 1500000005")
    feed = _feed()
    load_batch(store, "feed", "2026-10-05", feed, tz=TZ)
    assert _where(store, "o-glu")[0] == "observation"
    out = _parity(store, feed)
    glu = next(r for r in out["observation"] if r["oid"] == "o-glu")
    assert (glu["value_num"], glu["value_cmp"]) == (5.4, "<")


def test_value_as_concept_id_is_standard_or_zero_never_local(store: Any) -> None:
    from omop.load import load_batch

    feed = _feed()
    load_batch(store, "feed", "2026-10-05", feed, tz=TZ)
    assert store.fetchval("SELECT count(*) FROM measurement WHERE value_as_concept_id > 0") == 0  # never a local id
    assert store.fetchval("SELECT value_as_concept_id FROM measurement WHERE measurement_source_value = '72166-2'") == 0
    _parity(store, feed)


# ------------------------------------------------------------------------------------------------ visit end
def test_an_inpatient_visit_has_its_end_and_status(store: Any) -> None:
    from omop.load import load_batch

    feed = _feed()
    load_batch(store, "feed", "2026-10-05", feed, tz=TZ)
    got = {
        str(r[0]): (r[1], str(r[2]), str(r[3]))
        for r in store.fetchall(
            "SELECT r.source_record_id, v.visit_end_datetime, v.visit_end_date, v.visit_start_date FROM tb_record r "
            "JOIN visit_occurrence v ON v.visit_occurrence_id = r.record_id"
        )
    }
    assert str(got["e-in"][0]) == "2026-09-04 09:30:00" and got["e-in"][1] == "2026-09-04"
    assert got["e-now"][0] is None and got["e-now"][1] == got["e-now"][2] == "2026-10-03"  # still in
    out = _parity(store, feed)
    enc = {r["eid"]: r for r in out["encounter"]}
    assert enc["e-in"]["status"] == "finished" and str(enc["e-in"]["end"]) == "2026-09-04 09:30:00"
    assert enc["e-now"]["status"] == "in-progress" and enc["e-now"]["end"] is None


# ------------------------------------------------------------------------------------------------ provenance
def test_mapper_stamps_row_provenance_and_the_lake_carries_it(tmp_path: Path) -> None:
    from adapter.mapping.engine import Mapper, Mapping
    from lake.flatten import PROVENANCE_COLS, SCHEMAS, Flattener

    doc = {
        "version": 1,
        "name": "t",
        "tz": TZ,
        "systems": {"icd": ICD},
        "tables": {"diagnosis": {"source": "diagnosis", "key": "id"}},
        "resources": [
            {
                "type": "Condition",
                "table": "diagnosis",
                "id": {"hid": "id"},
                "elements": {
                    "subject.reference": {"ref": {"type": "Patient", "pid": "mrn"}},
                    "code.coding[0].system": {"const": ICD},
                    "code.coding[0].code": {"column": "icd"},
                },
            }
        ],
    }
    p = tmp_path / "m.yaml"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    m = Mapping.load(p)
    assert m.version.startswith("t@") and len(m.version) == 14
    row = {"id": "D1", "mrn": "10000001", "icd": "E11.9"}
    plain = next(Mapper(m, b"k" * 32, "S1").map_table("diagnosis", iter([row])))
    assert "meta" not in plain  # stamped only when the night is given (the pipeline)
    res = next(Mapper(m, b"k" * 32, "S1", "2026-10-05T00:00:00+08:00").map_table("diagnosis", iter([row])))
    src = res["meta"]["source"]
    assert src.startswith("S1/diagnosis#") and "10000001" not in json.dumps(res["meta"])
    other_key = next(Mapper(m, b"j" * 32, "S1", "2026-10-05T00:00:00+08:00").map_table("diagnosis", iter([row])))
    assert other_key["meta"]["source"] != src  # keyed: the hash alone does not reveal the row
    rows = Flattener(TZ).flatten({"Condition": [res]})
    assert all(c in dict(SCHEMAS[t]) for t in SCHEMAS for c in PROVENANCE_COLS)
    cond = rows["condition"][0]
    assert cond["src_table"] == "diagnosis" and cond["src_row_hash"] == src.rsplit("#", 1)[1]
    assert str(cond["ingested_at"]) == "2026-10-05 00:00:00" and cond["mapping_version"] == m.version


def test_ingest_instant_is_the_night_in_the_source_zone() -> None:
    from zoneinfo import ZoneInfo

    from adapter.pipeline import ingest_instant

    assert ingest_instant("2026-10-05", ZoneInfo("Asia/Tokyo")) == "2026-10-05T00:00:00+09:00"


def test_a_new_night_alone_is_no_update_and_the_export_carries_the_new_night(store: Any) -> None:
    from omop.load import load_batch

    first = load_batch(store, "feed", "2026-10-05", _feed("2026-10-05"), tz=TZ)
    feed = _feed("2026-10-06")
    rep = load_batch(store, "feed", "2026-10-06", feed, tz=TZ)
    assert (rep.inserted, rep.updated, rep.same) == (0, 0, first.inserted)
    out = _parity(store, feed)
    assert {str(r["ingested_at"]) for r in out["condition"]} == {"2026-10-06 00:00:00"}
    assert out["patient"][0]["src_table"] == "diagnosis" and out["patient"][0]["mapping_version"] == "t@0123456789ab"
    assert out["encounter"][0]["src_table"] is None  # a resource no mapping stamped: no provenance, not a guess


# ------------------------------------------------------------------------------------------------ out of order
def _ndjson(d: Path, feed: dict[str, list[dict[str, Any]]]) -> Path:
    d.mkdir(parents=True)
    for rtype, items in feed.items():
        (d / f"{rtype}.ndjson").write_text("".join(json.dumps(r) + "\n" for r in items), encoding="utf-8")
    return d


def test_a_late_rerun_of_an_older_night_is_built_but_never_current(tmp_path: Path, monkeypatch: Any) -> None:
    from embed_service.embedder import HashEmbedder
    from lake.store import Lake

    monkeypatch.setenv("TB_LAKE_SOURCE", "legacy")
    monkeypatch.delenv("TB_DB_URL", raising=False)
    lake = Lake(tmp_path / "lake", TZ)
    new = lake.rebuild("2026-11-07", HashEmbedder(), _ndjson(tmp_path / "n7", _feed("2026-11-07")))
    assert new.promoted and lake.current() == "2026-11-07"
    old = lake.rebuild("2026-10-30", HashEmbedder(), _ndjson(tmp_path / "n30", _feed("2026-10-30")))
    assert not old.promoted and "2026-10-30" in lake.snapshots()  # built: its DuckDB is there
    assert lake.current() == "2026-11-07"  # the box does not move back in time
    again = lake.rebuild("2026-11-07", HashEmbedder(), tmp_path / "n7")  # a re-run of CURRENT itself still promotes
    assert again.promoted and lake.current() == "2026-11-07"
