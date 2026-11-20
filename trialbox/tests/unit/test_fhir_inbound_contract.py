"""T-616 (D-400): the inbound FHIR contract, widened and documented (STD-012, STD-013, STD-014, STD-015, S-17).

A death flag without a date removes the patient from the base cohort; a ``medicationReference`` is resolved (contained
or in the batch) and a MedicationStatement is read; an Observation dated by a period only is read; a source date-time
with an offset keeps it; the elements a resource carries and the box does not read are counted per resource type in
the ingest report. The OMOP path reads the same, so the two lakes stay identical."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb
import pytest
import yaml
from adapter.mapping.engine import Mapper, Mapping
from lake.flatten import SCHEMAS, Flattener, unread_elements
from tb_common import id_rule

ROOT = Path(__file__).resolve().parents[2]
TZ = "Asia/Taipei"
ATC = "http://www.whocc.no/atc"
NHI = "urn:tw:nhi:drug"
LOINC = "http://loinc.org"
SNAP = "2026-10-04"


def _patients() -> list[dict[str, Any]]:
    return [
        {"resourceType": "Patient", "id": "alive", "gender": "female", "birthDate": "1960-01-01"},
        {"resourceType": "Patient", "id": "flagged", "gender": "female", "birthDate": "1960-01-01",
         "deceasedBoolean": True},
        {"resourceType": "Patient", "id": "dated", "gender": "female", "birthDate": "1960-01-01",
         "deceasedDateTime": "2026-06-01"},
        {"resourceType": "Patient", "id": "said-alive", "gender": "male", "birthDate": "1960-01-01",
         "deceasedBoolean": False},
    ]  # fmt: skip


def _meds() -> dict[str, list[dict[str, Any]]]:
    mtx = {"coding": [{"system": NHI, "code": "A012345100"}, {"system": ATC, "code": "L04AX03"}], "text": "MTX"}
    return {
        "Medication": [{"resourceType": "Medication", "id": "med-mtx", "code": mtx}],
        "MedicationRequest": [
            {"resourceType": "MedicationRequest", "id": "by-concept", "status": "active", "intent": "order",
             "subject": {"reference": "Patient/alive"}, "authoredOn": "2026-01-10",
             "medicationCodeableConcept": mtx},
            {"resourceType": "MedicationRequest", "id": "by-bundle-ref", "status": "active", "intent": "order",
             "subject": {"reference": "Patient/alive"}, "authoredOn": "2026-02-10",
             "medicationReference": {"reference": "Medication/med-mtx"},
             "dosageInstruction": [{"text": "10 mg weekly",
                                    "timing": {"repeat": {"boundsPeriod": {"start": "2026-02-11",
                                                                           "end": "2026-05-11"}}}}],
             "dispenseRequest": {"validityPeriod": {"start": "2026-02-10", "end": "2026-03-10"}}},
            {"resourceType": "MedicationRequest", "id": "by-contained-ref", "status": "active", "intent": "order",
             "subject": {"reference": "Patient/alive"}, "authoredOn": "2026-03-01",
             "contained": [{"resourceType": "Medication", "id": "m1",
                            "code": {"coding": [{"system": ATC, "code": "L04AB01"}], "text": "etanercept"}}],
             "medicationReference": {"reference": "#m1"},
             "dispenseRequest": {"expectedSupplyDuration": {"value": 4, "unit": "weeks", "code": "wk"}}},
            {"resourceType": "MedicationRequest", "id": "dangling-ref", "status": "active", "intent": "order",
             "subject": {"reference": "Patient/alive"}, "authoredOn": "2026-03-02",
             "medicationReference": {"reference": "Medication/nowhere"}},
        ],
        "MedicationStatement": [
            {"resourceType": "MedicationStatement", "id": "stmt", "status": "active",
             "subject": {"reference": "Patient/alive"}, "dateAsserted": "2026-04-01",
             "medicationReference": {"reference": "Medication/med-mtx"},
             "effectivePeriod": {"start": "2025-12-01", "end": "2026-03-31"}},
            {"resourceType": "MedicationStatement", "id": "not-taken", "status": "not-taken",
             "subject": {"reference": "Patient/alive"}, "medicationCodeableConcept": mtx},
        ],
    }  # fmt: skip


def _observations() -> list[dict[str, Any]]:
    return [
        {"resourceType": "Observation", "id": "period-only", "status": "final",
         "subject": {"reference": "Patient/alive"},
         "code": {"coding": [{"system": LOINC, "code": "2160-0"}]},
         "effectivePeriod": {"start": "2026-04-25T10:30:00+09:00", "end": "2026-04-25T11:00:00+09:00"},
         "valueQuantity": {"value": 0.9, "unit": "mg/dL", "code": "mg/dL"}},
        {"resourceType": "Observation", "id": "dated", "status": "final",
         "subject": {"reference": "Patient/alive"},
         "code": {"coding": [{"system": LOINC, "code": "2160-0"}]},
         "effectiveDateTime": "2026-04-25T01:30:00Z", "valueQuantity": {"value": 1.0, "unit": "mg/dL"},
         "interpretation": [{"text": "H"}], "note": [{"text": "x"}]},
    ]  # fmt: skip


def _feed() -> dict[str, list[dict[str, Any]]]:
    return {"Patient": _patients(), "Observation": _observations(), **_meds()}


# ------------------------------------------------------------------------------------------------ deceased (STD-013)
def test_a_death_flag_without_a_date_is_read() -> None:
    rows = {r["pid"]: r for r in Flattener(TZ).flatten({"Patient": _patients()})["patient"]}
    assert (rows["flagged"]["deceased"], rows["flagged"]["deceased_date"]) == (True, None)
    assert (rows["dated"]["deceased"], rows["dated"]["deceased_date"]) == (True, date(2026, 6, 1))
    # "not deceased" is no evidence: unknown, as a patient whose record says nothing
    assert rows["alive"]["deceased"] is None and rows["said-alive"]["deceased"] is None


def _lake(rows: dict[str, list[dict[str, Any]]]) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    for name, spec in SCHEMAS.items():
        con.execute(f'CREATE TABLE "{name}" ({", ".join(f"{chr(34)}{c}{chr(34)} {t}" for c, t in spec)})')
        cols = [c for c, _ in spec]
        for r in rows.get(name, []):
            con.execute(
                f'INSERT INTO "{name}" ({", ".join(chr(34) + c + chr(34) for c in cols)}) '
                f"VALUES ({', '.join('?' for _ in cols)})",
                [r.get(c) for c in cols],
            )
    return con


@pytest.mark.parametrize("ruleset", ["RA-COH", "GOUT-COH"])
def test_deceased_boolean_removes_the_patient_from_the_base_cohort(ruleset: str) -> None:
    sql = (ROOT / "rulesets" / ruleset / "sql" / f"{ruleset}.sql").read_text(encoding="utf-8")
    con = _lake(Flattener(TZ).flatten({"Patient": _patients()}))
    got = {(r[0], r[1]) for r in con.execute(sql, [["2026-01-31", "2026-10-31"], None]).fetchall()}
    jan, oct_ = date(2026, 1, 31), date(2026, 10, 31)
    assert ("flagged", jan) not in got and ("flagged", oct_) not in got  # no date: out at every index date
    assert ("dated", jan) in got and ("dated", oct_) not in got  # a date still decides by the date
    assert {("alive", jan), ("alive", oct_), ("said-alive", jan), ("said-alive", oct_)} <= got


def test_the_generator_writes_the_deceased_guard() -> None:
    from criteria_compiler.compile_sql import generator

    src = Path(generator.__file__).read_text(encoding="utf-8")
    assert "(p.deceased_date IS NOT NULL OR p.deceased IS NOT TRUE)" in src
    for sql in (ROOT / "rulesets").glob("*/sql/*.sql"):
        assert "(p.deceased_date IS NOT NULL OR p.deceased IS NOT TRUE)" in sql.read_text(encoding="utf-8"), sql


def test_screen_scope_leaves_out_a_deceased_patient_without_a_date() -> None:
    from orchestrator.scenarios import screen

    sql = next(v for k, v in vars(screen).items() if isinstance(v, str) and "FROM patient p LEFT JOIN a" in v)
    con = _lake({**Flattener(TZ).flatten({"Patient": _patients()}),
                 "encounter": [{"eid": f"e-{p}", "pid": p, "start": datetime(2026, 9, 1), "practitioner_id": "D1"}
                               for p in ("alive", "flagged", "dated", "said-alive")]})  # fmt: skip
    got = {r[0] for r in con.execute(sql, [["D1"], "2026-10-01", "2026-12-31", "2026-01-01", False]).fetchall()}
    assert got == {"alive", "said-alive"}


# ------------------------------------------------------------------------------------------------ medication (STD-012/014)
def test_medication_reference_is_resolved_and_statements_are_read() -> None:
    rows = {r["mid"]: r for r in Flattener(TZ).flatten(_meds())["medication"]}
    assert set(rows) == {"by-concept", "by-bundle-ref", "by-contained-ref", "dangling-ref", "stmt"}  # not-taken: void
    assert (rows["by-concept"]["atc"], rows["by-concept"]["nhi_code"]) == ("L04AX03", "A012345100")
    ref = rows["by-bundle-ref"]
    assert (ref["atc"], ref["nhi_code"], ref["name"], ref["dose"]) == ("L04AX03", "A012345100", "MTX", "10 mg weekly")
    # STD-012: the therapy period is the dosage's boundsPeriod first, not the dispense validity
    assert (ref["authored"], ref["start"], ref["end"]) == (date(2026, 2, 10), date(2026, 2, 11), date(2026, 5, 11))
    con = rows["by-contained-ref"]
    assert (con["atc"], con["name"]) == ("L04AB01", "etanercept")
    assert (con["start"], con["end"]) == (date(2026, 3, 1), date(2026, 3, 29))  # authoredOn + 4 weeks of supply
    assert rows["dangling-ref"]["atc"] is None and rows["dangling-ref"]["nhi_code"] is None  # kept, drug unknown
    st = rows["stmt"]
    assert (st["atc"], st["authored"], st["start"], st["end"]) == (
        "L04AX03", date(2026, 4, 1), date(2025, 12, 1), date(2026, 3, 31)
    )  # fmt: skip
    order = [r["mid"] for r in Flattener(TZ).flatten(_meds())["medication"]]
    assert order[-1] == "stmt"  # orders first, then statements (the OMOP export keeps the same order)


# ------------------------------------------------------------------------------------------------ observation (S-17)
def test_an_observation_dated_by_a_period_only_is_read_and_offsets_are_kept() -> None:
    rows = {r["oid"]: r for r in Flattener(TZ).flatten({"Observation": _observations()})["observation"]}
    # 10:30 at +09:00 is 09:30 in Taipei: the same instant, never the date alone
    assert rows["period-only"]["effective"] == datetime(2026, 4, 25, 9, 30)
    assert rows["period-only"]["value_num"] == 0.9
    assert rows["dated"]["effective"] == datetime(2026, 4, 25, 9, 30)  # 01:30 Z


# ------------------------------------------------------------------------------------------------ offsets (STD-015)
def _mapping(tmp_path: Path) -> Mapping:
    doc = {"version": 1, "name": "t", "tz": TZ, "systems": {}, "tables": {"t": {"source": "t", "key": "id"}},
           "resources": [{"type": "Encounter", "table": "t", "id": {"hid": "id"},  # D-1253: a visit is its patient's
                          "elements": {"subject": {"ref": {"type": "Patient", "pid": "mrn"}},
                                       "period.start": {"column": "dt", "type": "datetime"},
                                       "period.end": {"column": "dt", "type": "datetime", "add_minutes": 30}}}]}  # fmt: skip
    p = tmp_path / "m.yaml"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return Mapping.load(p)


@pytest.mark.parametrize(
    ("raw", "start", "end"),
    [
        ("2026-04-25T10:30:00+09:00", "2026-04-25T10:30:00+09:00", "2026-04-25T11:00:00+09:00"),
        ("2026-04-25 10:30:00+0900", "2026-04-25T10:30:00+09:00", "2026-04-25T11:00:00+09:00"),
        ("2026-04-25T01:30:00Z", "2026-04-25T01:30:00+00:00", "2026-04-25T02:00:00+00:00"),
        ("2026-04-25 10:30:00", "2026-04-25T10:30:00+08:00", "2026-04-25T11:00:00+08:00"),  # naive: the mapping's tz
        ("2026-04-25", "2026-04-25T00:00:00+08:00", "2026-04-25T00:30:00+08:00"),  # a date alone: its midnight
        ("20260425103000", "2026-04-25T10:30:00+08:00", "2026-04-25T11:00:00+08:00"),
    ],
)
def test_a_source_offset_is_kept(tmp_path: Path, raw: str, start: str, end: str) -> None:
    m = _mapping(tmp_path)
    res = Mapper(m, b"k" * 32, "S").map_row(m.resources[0], {"id": "E1", "mrn": "10000001", "dt": raw})
    assert res is not None and res["period"] == {"start": start, "end": end}


# ------------------------------------------------------------------------------------------------ unread (STD-014)
def test_unread_elements_are_counted_per_resource_type() -> None:
    feed = _feed()
    feed["AllergyIntolerance"] = [{"resourceType": "AllergyIntolerance", "id": "a1"}] * 2
    feed["Patient"] = [*feed["Patient"], {**feed["Patient"][0], "id": "p9", "address": [{"city": "x"}]}]
    got = unread_elements(feed)
    assert got["AllergyIntolerance"] == {"*": 2}  # a type the box does not read at all
    assert got["Observation"] == {"interpretation": 1, "note": 1}
    assert got["MedicationRequest"] == {"intent": 4}
    assert "MedicationStatement" not in got and "Medication" not in got  # every element of them is read
    assert got["Patient"] == {"address": 1}


def test_the_ingest_report_carries_the_unread_counts(tmp_path: Path) -> None:
    from adapter.pipeline import AdapterConfig, run_ingest

    sec = tmp_path / "secrets"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(b"k" * 32)
    cfg = AdapterConfig(lake_dir=tmp_path / "lake", secrets_dir=sec, site_id="T", audit_dir=tmp_path / "audit",
                        mapping_path=ROOT / "services/adapter/mapping/tw_core/demo_his.yaml")  # fmt: skip
    exp = tmp_path / "bulk"
    exp.mkdir()
    for rtype, items in {"Observation": _observations(), "Patient": _patients()}.items():
        (exp / f"{rtype}.ndjson").write_text("\n".join(json.dumps(r) for r in items) + "\n", encoding="utf-8")
    rep = run_ingest(cfg, "fhir_bulk", str(exp), snapshot=SNAP, load_fhir=False, rebuild_lake=False, validate=False)
    assert rep.fhir_unread is not None and rep.fhir_unread["Observation"] == {"interpretation": 1, "note": 1}
    body = json.loads((tmp_path / "lake" / "ndjson" / SNAP / "ingest_report.json").read_text(encoding="utf-8"))
    assert body["fhir_unread"]["Observation"] == {"interpretation": 1, "note": 1}


# ------------------------------------------------------------------------------------------------ old snapshots
def test_a_snapshot_built_before_schema_4_reads_deceased_as_unknown(tmp_path: Path) -> None:
    from embed_service.embedder import HashEmbedder
    from lake.store import Lake

    nd = tmp_path / "nd"
    nd.mkdir()
    (nd / "Patient.ndjson").write_text("\n".join(json.dumps(p) for p in _patients()) + "\n", encoding="utf-8")
    lake = Lake(tmp_path / "lake")
    id_rule.write_snapshot_record(nd)  # D-1253: a snapshot of this release
    lake.rebuild(SNAP, HashEmbedder(), nd)
    got = {r["pid"]: r["deceased"] for r in lake.query("SELECT pid, deceased FROM patient").to_pylist()}
    assert got["flagged"] is True
    con = duckdb.connect(str(lake.db_path()))
    con.execute("ALTER TABLE patient DROP COLUMN deceased")
    con.execute("UPDATE lake_meta SET schema_version = 3")
    con.close()
    got = {r["pid"]: r["deceased"] for r in lake.query("SELECT pid, deceased FROM patient").to_pylist()}
    assert set(got) == {"alive", "flagged", "dated", "said-alive"} and set(got.values()) == {None}


# ------------------------------------------------------------------------------------------------ the OMOP path
@pytest.fixture
def db(db_url: str) -> Any:
    from omop import schema

    d = schema.connect(db_url)
    yield d
    d.close()


def test_the_omop_path_reads_the_same_and_imputes_the_death_date(db: Any) -> None:
    from lake.source import lake_rows
    from omop import vocab
    from omop.export import export_rows
    from omop.load import load_batch

    feed = _feed()
    legacy = lake_rows(feed, {}, tz=TZ, snapshot=SNAP, source="legacy")
    load_batch(db, "feed", SNAP, feed, tz=TZ)
    load_batch(db, "site", f"site@{SNAP}", {}, tz=TZ)
    out = export_rows(db)
    for name in SCHEMAS:
        assert out[name] == legacy[name], name
    deaths = db.fetchall(
        "SELECT m.source_id, d.death_date, d.death_type_concept_id FROM death d JOIN tb_id_map m "
        "ON m.omop_id = d.person_id AND m.id_kind = 'person' ORDER BY 1"
    )
    assert [tuple(r) for r in deaths] == [
        ("dated", date(2026, 6, 1), vocab.EHR),
        ("flagged", date.fromisoformat(SNAP), vocab.DEATH_DATE_IMPUTED),
    ]
