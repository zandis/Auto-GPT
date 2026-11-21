"""Mapping's publication boundary, using only synthetic source rows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from adapter.mapping.engine import Mapper, Mapping, ResourceSpec, pivot_rows
from adapter.ndjson import snapshot_dir
from adapter.pipeline import run_ingest
from lake.flatten import Flattener
from tb_common.crypto import pid_for_mrn
from tb_common.identity import HeldOwner

from tests.unit.test_dataflow_lake_p0 import _cfg

KEY = bytes(range(32))
REF = {"ref": {"type": "Patient", "pid": "chart"}}


def mapping(path: Path, *, check_owner: bool = False) -> Mapping:
    resources = [
        {
            "type": "Encounter",
            "table": "visits",
            "id": {"hid": "number"},
            "elements": {"subject.reference": REF, "identifier[0].value": {"hid": "number"}},
        },
        {
            "type": "Condition",
            "table": "diagnoses",
            "id": {"column": "number"},
            "elements": {
                "subject.reference": REF,
                "encounter.reference": {"ref": {"type": "Encounter", "hid": "visit"}},
                "code.text": {"column": "diagnosis"},
            },
        },
    ]
    if check_owner:
        resources.append(
            {
                "type": "Observation",
                "table": "diagnoses",
                "id": {"hid": "number"},
                "elements": {"subject.reference": {"ref": {"type": "Patient", "pid": "second_chart"}}},
            }
        )
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "name": "test",
                "tz": "UTC",
                "tables": {t: {"source": t, "key": "number"} for t in ("visits", "diagnoses")},
                "resources": resources,
            },
            sort_keys=False,
        )
    )
    return Mapping.load(path)


def one(mapper: Mapper, table: str, **row: str) -> dict[str, Any]:
    (resource,) = mapper.map_table(table, iter([row]))
    return resource


def test_two_patients_reusing_numbers_have_distinct_records_and_correct_links(tmp_path: Path) -> None:
    m = Mapper(mapping(tmp_path / "map.yaml"), KEY, "site")
    visits = [one(m, "visits", number="same", chart=c) for c in ("A", "B")]
    dx = [one(m, "diagnoses", number="same", visit="same", chart=c) for c in ("B", "A")]
    flat = Flattener("UTC").flatten({"Encounter": visits, "Condition": dx})
    assert len({r["cid"] for r in flat["condition"]}) == len({r["eid"] for r in flat["encounter"]}) == 2
    assert {r["pid"]: r["eid"] for r in flat["condition"]} == {r["pid"]: r["eid"] for r in flat["encounter"]}
    assert all(v["id"] == v["identifier"][0]["value"] for v in visits)


def test_one_record_keeps_one_id_on_replay_correction_and_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TB_CHARTNO_RULE", "digits:4")
    spec = mapping(tmp_path / "map.yaml")
    old = one(Mapper(spec, KEY, "site"), "diagnoses", number="id", chart="００１", diagnosis="old")
    new = Mapper(spec, KEY, "site", ingest_time="2026-01-03T12:00:00Z")
    corrected = one(new, "diagnoses", number="id", chart="1", diagnosis="corrected")
    assert old["subject"] == corrected["subject"]
    assert old["code"] != corrected["code"]
    assert corrected["id"] == old["id"] != "id"
    assert list(new.tombstones("diagnoses", iter([{"number": "id", "chart": "0001"}]))) == [("Condition", old["id"])]


def test_conflict_holds_the_owner_in_other_tables_and_aborts_before_screening(tmp_path: Path) -> None:
    spec = mapping(tmp_path / "map.yaml", check_owner=True)
    m = Mapper(spec, KEY, "site")
    with pytest.raises(HeldOwner):
        one(m, "diagnoses", number="d", chart="A", second_chart="B")
    for c in ("A", "B"):
        with pytest.raises(HeldOwner):
            one(m, "visits", number="v", chart=c)
    assert one(m, "visits", number="v", chart="C")

    # Reverse the discovery order through a real nightly run. The first table already staged a visit.
    feed = tmp_path / "feed"
    feed.mkdir()
    (feed / "visits.csv").write_text("number,chart\nv,A\n")
    (feed / "diagnoses.csv").write_text("number,chart,second_chart\nd,A,B\n")
    cfg = _cfg(tmp_path)
    cfg.mapping_path = spec.path
    with pytest.raises(HeldOwner):
        run_ingest(cfg, "csv", str(feed), snapshot="2026-01-03", validate=False, load_fhir=False)
    assert not snapshot_dir(cfg.lake_dir, "2026-01-03").exists()
    assert not (cfg.lake_dir / "CURRENT").exists()


def test_two_patient_rows_under_one_chart_stop_the_night(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    feed = tmp_path / "feed"
    feed.mkdir()
    (feed / "patient.csv").write_text("mrn,birth_date,sex\nSYN-A,1980-01-02,F\nSYN-A,1999-09-09,M\n")
    (feed / "encounter.csv").write_text("enc_no,mrn,visit_datetime\nV,SYN-A,2026-01-02\n")
    with pytest.raises(HeldOwner):
        run_ingest(cfg, "csv", str(feed), snapshot="2026-01-03", validate=False, load_fhir=False)
    assert not snapshot_dir(cfg.lake_dir, "2026-01-03").exists()


def test_opaque_patient_reference_matches_patient_resource(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_CHARTNO_RULE", "digits:4")
    p = tmp_path / "opaque.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "tz": "UTC",
                "tables": {"people": {"key": "id"}, "labs": {"key": "id"}},
                "resources": [
                    {"type": "Patient", "table": "people", "id": {"column": "id"}},
                    {
                        "type": "Observation",
                        "table": "labs",
                        "id": {"hid": "id"},
                        "elements": {"subject.reference": {"template": "Patient/{external}"}},
                    },
                ],
            }
        )
    )
    m = Mapper(Mapping.load(p), KEY, "S")
    for owner in ("001", "1"):
        pat = one(m, "people", id=owner)
        obs = one(m, "labs", id="obs", external=owner)
        assert obs["subject"]["reference"] == "Patient/" + pat["id"]


def test_a_merged_element_cannot_replace_the_key_or_override_the_owner(tmp_path: Path) -> None:
    spec = mapping(tmp_path / "map.yaml")
    rs = spec.resources[0]
    row = {"number": "same", "chart": "A"}
    mapper = Mapper(spec, KEY, "site")
    expected = one(mapper, "visits", **row)
    rs.elements["$merge"] = {"const": {"id": "local", "status": "planned"}}
    assert one(mapper, "visits", **row)["id"] == expected["id"]
    rs.elements["$merge"] = {"const": {"subject": {"reference": "Patient/B"}}}
    with pytest.raises(HeldOwner):
        one(mapper, "visits", **row)
    with pytest.raises(HeldOwner):
        one(mapper, "diagnoses", **row)


def test_deletion_without_owner_cannot_retract_another_patients_record(tmp_path: Path) -> None:
    mapper = Mapper(mapping(tmp_path / "map.yaml"), KEY, "site")
    with pytest.raises(HeldOwner):
        list(mapper.tombstones("visits", iter([{"number": "shared"}])))


def test_without_an_owner_only_elements_can_be_projected(tmp_path: Path) -> None:
    spec = mapping(tmp_path / "map.yaml")
    rs = spec.resources[1]
    rs.elements = {"code.text": {"column": "diagnosis"}}
    mapper = Mapper(spec, KEY, "site")
    row = {"number": "raw", "diagnosis": "example"}
    assert mapper.map_row(rs, row) == {"resourceType": "Condition", "code": {"text": "example"}}
    with pytest.raises(HeldOwner):
        list(mapper.map_table(rs.table, iter([row])))
    with pytest.raises(HeldOwner):
        mapper.row_id(rs, row)


def test_pivot_preserves_opaque_component_boundaries_before_mapping(tmp_path: Path) -> None:
    spec = mapping(tmp_path / "map.yaml")
    pivot = {"keys": ["chart", "visit"], "item": "code", "value": "v", "columns": {"Q": "diagnosis"}}
    spec.tables["diagnoses"]["pivot"] = pivot
    rows = iter(
        [
            {"chart": "A|B", "visit": "C", "code": "Q", "v": "first"},
            {"chart": "A", "visit": "B|C", "code": "Q", "v": "second"},
        ]
    )
    wide = pivot_rows(rows, pivot, "number", tmp_path, {})
    mapped = list(Mapper(spec, KEY, "site").map_table("diagnoses", wide))
    assert len({r["id"] for r in mapped}) == 2
    assert {r["code"]["text"] for r in mapped} == {"first", "second"}


def test_missing_record_number_cannot_hide_conflicting_owner_evidence(tmp_path: Path) -> None:
    mapper = Mapper(mapping(tmp_path / "map.yaml", check_owner=True), KEY, "site")
    with pytest.raises(HeldOwner):
        one(mapper, "diagnoses", chart="A", second_chart="B")
    with pytest.raises(HeldOwner):
        one(mapper, "visits", chart="B", number="v")


def test_practitioner_emitted_by_visit_row_keeps_its_independent_key(tmp_path: Path) -> None:
    spec = mapping(tmp_path / "map.yaml")
    spec.resources.append(ResourceSpec("Practitioner", "visits", {"column": "staff"}, {}))
    mapper = Mapper(spec, KEY, "site")
    rows = ({"chart": chart, "number": "same", "staff": "staff-1"} for chart in ("A", "B"))
    resources = list(mapper.map_table("visits", rows))
    assert [r["id"] for r in resources if r["resourceType"] == "Practitioner"] == ["staff-1", "staff-1"]
    assert len({r["id"] for r in resources if r["resourceType"] == "Encounter"}) == 2


def test_review_legacy_snapshot_cannot_accept_a_mapped_delta(tmp_path: Path) -> None:
    from adapter.mapping.engine import resource_id
    from adapter.ndjson import read_type, write_snapshot
    from adapter.pipeline import PASSED

    cfg = _cfg(tmp_path)
    base = snapshot_dir(cfg.lake_dir, "2026-01-02")
    legacy = resource_id(cfg.site_key(), "Observation", "L1")
    observation = {
        "resourceType": "Observation",
        "id": legacy,
        "subject": {"reference": "Patient/" + pid_for_mrn(cfg.site_key(), "A")},
    }
    write_snapshot(base, {"Observation": [observation]})
    (base / PASSED).write_text("{}")
    feed = tmp_path / "delta"
    feed.mkdir()
    (feed / "lab.csv").write_text("mrn,lab_no,deleted,updated_at\nA,L1,1,2026-01-03\n")
    with pytest.raises(HeldOwner, match="record_identity.snapshot_scope"):
        run_ingest(
            cfg,
            "csv",
            str(feed),
            since="2026-01-02",
            snapshot="2026-01-03",
            validate=False,
            load_fhir=False,
            rebuild_lake=False,
        )
    assert list(read_type(base, "Observation")) == [observation]
    assert not snapshot_dir(cfg.lake_dir, "2026-01-03").exists()


def test_review_pivot_must_preserve_all_owner_columns(tmp_path: Path) -> None:
    spec = mapping(tmp_path / "site.yaml")
    pv = {"keys": ["panel"], "item": "item", "value": "result", "columns": {"Na": "sodium", "K": "potassium"}}
    spec.tables["diagnoses"]["pivot"] = pv
    spec.resources[1] = ResourceSpec(
        "Observation",
        "diagnoses",
        {"hid": "number"},
        {"subject.reference": REF, "valueQuantity.value": {"column": "potassium"}},
    )
    rows = iter(
        [
            {"chart": "A", "panel": "P1", "item": "Na", "result": "141"},
            {"chart": "B", "panel": "P1", "item": "K", "result": "7.2"},
        ]
    )
    with pytest.raises(HeldOwner, match="record_identity.pivot_owner"):
        list(Mapper(spec, KEY, "site").map_table("diagnoses", pivot_rows(rows, pv, "number", tmp_path, {})))


def test_review_appointment_column_actor_cannot_override_owner(tmp_path: Path) -> None:
    spec = mapping(tmp_path / "site.yaml")
    spec.resources[0] = ResourceSpec(
        "Appointment",
        "visits",
        {"hid": "number"},
        {"participant[0].actor.reference": REF, "participant[1].actor.reference": {"column": "other"}},
    )

    b = pid_for_mrn(KEY, "B")
    with pytest.raises(HeldOwner, match="record_identity.actor_owner"):
        one(Mapper(spec, KEY, "site"), "visits", chart="A", number="V1", other="Patient/" + b)


def test_review_static_patient_owned_resource_is_refused(tmp_path: Path) -> None:
    spec = mapping(tmp_path / "site.yaml")
    spec.static.append({"resourceType": "Observation", "id": "L1", "subject": {"reference": "Patient/B"}})
    with pytest.raises(HeldOwner, match="record_identity.static_type"):
        Mapper(spec, KEY, "site").static_resources()


def test_review_unscoped_writer_cannot_replay_mapped_tombstone(tmp_path: Path) -> None:
    from adapter.mapping.engine import resource_id
    from adapter.ndjson import write_snapshot

    cfg = _cfg(tmp_path)
    mapper = Mapper(Mapping.load(cfg.mapping_path), KEY, "site")
    legacy = resource_id(KEY, "Observation", "L1")
    base = tmp_path / "legacy"
    write_snapshot(
        base,
        {
            "Observation": [
                {
                    "resourceType": "Observation",
                    "id": legacy,
                    "subject": {"reference": "Patient/" + pid_for_mrn(KEY, "A")},
                }
            ]
        },
    )
    ((kind, rid),) = mapper.tombstones("lab", iter([{"mrn": "A", "lab_no": "L1"}]))
    with pytest.raises(HeldOwner, match="record_identity.snapshot_scope"):
        write_snapshot(tmp_path / "next", {}, base, {kind: [rid]})


def test_unreadable_scope_uses_the_same_migration_refusal(tmp_path: Path) -> None:
    from adapter.ndjson import write_snapshot
    from tb_common.identity import SCOPE_FILE

    base = tmp_path / "base"
    base.mkdir()
    (base / SCOPE_FILE).write_bytes(b"\xff")
    mapper = Mapper(mapping(tmp_path / "site.yaml"), KEY, "site")
    with pytest.raises(HeldOwner, match="record_identity.snapshot_scope"):
        write_snapshot(tmp_path / "next", {}, base, identity_scope=mapper.snapshot_scope)
