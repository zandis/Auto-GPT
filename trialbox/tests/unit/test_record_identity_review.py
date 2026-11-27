"""Second-round publication and inventory regressions, with synthetic source records."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pytest
import yaml
from adapter.mapping.engine import Mapper, Mapping, ResourceSpec, pivot_rows
from adapter.ndjson import write_snapshot
from lake.flatten import Flattener
from tb_common.identity import HeldOwner

from tests.unit.test_id_rule_invariants import KEY, mapping, one
from tools.record_identity_check import expected_inventory, scan

ROOT = Path(__file__).resolve().parents[2]


def patient_ref(column: str) -> dict[str, Any]:
    return {"ref": {"type": "Patient", "pid": column}}


def test_chart_map_and_patient_must_bind_the_same_owner(tmp_path: Path) -> None:
    spec = mapping(tmp_path / "map.yaml")
    spec.tables["patient"] = {"key": "mrn"}
    spec.resources = [ResourceSpec("Patient", "patient", {"column": "external_id"}, {})]
    with pytest.raises(HeldOwner, match="record_identity.chart_owner"):
        one(Mapper(spec, KEY, "site"), "patient", mrn="A", external_id="E7")


def test_joined_pivot_owner_cannot_mix_measurements(tmp_path: Path) -> None:
    spec = mapping(tmp_path / "map.yaml")
    pivot = {"keys": ["person", "panel"], "item": "item", "value": "v", "columns": {"Na": "sodium", "K": "potassium"}}
    spec.tables["labs"] = {"key": "key", "join": {"person": ["branch", "number"]}, "pivot": pivot}
    spec.resources = [
        ResourceSpec(
            "Observation",
            "labs",
            {"hid": "key"},
            {
                "subject.reference": patient_ref("person"),
                "component[0].valueQuantity.value": {"column": "sodium"},
                "component[1].valueQuantity.value": {"column": "potassium"},
            },
        )
    ]
    rows = (
        spec.normalize("labs", dict(branch=b, number=n, panel="P1", item=i, v=v))
        for b, n, i, v in [("A|B", "C", "Na", "140"), ("A", "B|C", "K", "7.2")]
    )
    with pytest.raises(HeldOwner, match="record_identity.pivot_owner"):
        list(Mapper(spec, KEY, "site").map_table("labs", pivot_rows(rows, pivot, "key", tmp_path, {})))


@pytest.mark.parametrize("style", ["column", "object", "merge", "wrong_type", "typed_wrong_target"])
def test_cross_owner_clinical_reference_is_refused(tmp_path: Path, style: str) -> None:
    spec = mapping(tmp_path / "map.yaml")
    claim = ResourceSpec("Claim", "visits", {"hid": "number"}, {"patient.reference": patient_ref("chart")})
    response = ResourceSpec(
        "ClaimResponse", "diagnoses", {"hid": "number"}, {"patient.reference": patient_ref("chart")}
    )
    response.elements["outcome"] = {"column": "outcome"}
    spec.resources = [claim, response]
    original = one(Mapper(spec, KEY, "site"), "visits", number="C1", chart="A")
    foreign = original["id"]
    ref = "Claim/" + foreign
    if style == "merge":
        response.elements["$merge"] = {"const": {"request": {"reference": ref}}}
    elif style == "typed_wrong_target":
        response.elements["request.reference"] = {"ref": {"type": "Practitioner", "column": "staff"}}
    elif style == "object":
        response.elements["request"] = {"const": {"reference": ref}}
    else:
        response.elements["request.reference"] = {"column": "ref"}
    with pytest.raises(HeldOwner, match="record_identity.reference_owner"):
        one(
            Mapper(spec, KEY, "site"),
            "diagnoses",
            chart="B",
            number="R1",
            staff=foreign,
            ref=ref if style != "wrong_type" else "Practitioner/" + foreign,
            outcome="complete",
        )
    response.elements["request.reference"] = {"ref": {"type": "Claim", "hid": "claim_no"}}
    response.elements.pop("$merge", None)
    response.elements.pop("request", None)
    mapper = Mapper(spec, KEY, "site")
    own = one(mapper, "visits", chart="B", number="C1")
    checked = one(mapper, "diagnoses", chart="B", number="R1", claim_no="C1", outcome="complete")
    assert [c["outcome"] for c in Flattener("UTC").claims([original, own], [checked])] == [None, "complete"]


def test_type_cannot_change_after_key_selection(tmp_path: Path) -> None:
    spec = mapping(tmp_path / "map.yaml")
    spec.resources = [
        ResourceSpec(
            "Practitioner",
            "visits",
            {"column": "id"},
            {
                "resourceType": {"const": "Appointment"},
                "participant[0].actor.reference": {"column": "actor"},
            },
        )
    ]
    with pytest.raises(HeldOwner, match="record_identity.resource_type"):
        one(Mapper(spec, KEY, "site"), "visits", id="V1", actor="Patient/B")


def test_snapshot_refuses_changed_record_declaration(tmp_path: Path) -> None:
    path = tmp_path / "map.yaml"
    mapping(path)
    doc = yaml.safe_load(path.read_text())
    doc["resources"][0]["type"] = "Observation"
    path.write_text(yaml.safe_dump(doc))
    original = Mapper(Mapping.load(path), KEY, "site")
    old = one(original, "visits", number="L1", chart="A")
    base = tmp_path / "first"
    write_snapshot(base, {"Observation": [old]}, identity_scope=original.snapshot_scope)
    doc["resources"][0]["id"]["suffix"] = "new"
    path.write_text(yaml.safe_dump(doc))
    revised = Mapper(Mapping.load(path), KEY, "site")
    new = one(revised, "visits", number="L1", chart="A")
    assert new["id"] != old["id"]
    with pytest.raises(HeldOwner, match="record_identity.snapshot_scope"):
        write_snapshot(tmp_path / "delta", {"Observation": [new]}, base, identity_scope=revised.snapshot_scope)


@pytest.mark.parametrize("reverse", [True, False])
def test_patient_evidence_uses_the_published_birth_date(tmp_path: Path, reverse: bool) -> None:
    spec = mapping(tmp_path / "map.yaml")
    spec.resources = [
        ResourceSpec("Patient", "visits", {"pid": "chart"}, {"$merge": {"const": {"birthDate": "1980-01-01"}}}),
        ResourceSpec("Patient", "diagnoses", {"pid": "chart"}, {"birthDate": {"const": "1990-01-01"}}),
    ]
    mapper = Mapper(spec, KEY, "site")
    first, second = ("diagnoses", "visits") if reverse else ("visits", "diagnoses")
    one(mapper, first, chart="A")
    with pytest.raises(HeldOwner, match="Conflicting patient details"):
        one(mapper, second, chart="A")


def test_composite_reference_requires_component_boundaries(tmp_path: Path) -> None:
    spec = mapping(tmp_path / "map.yaml")
    spec.tables["visits"]["join"] = {"number": ["ward", "local"]}
    mapper = Mapper(spec, KEY, "site")
    visit = one(mapper, "visits", ward="W", local="7", number="W|7", chart="A")
    with pytest.raises(HeldOwner, match="record_identity.reference_parts"):
        one(mapper, "diagnoses", visit="W|7", number="D1", chart="A")
    spec.tables["diagnoses"]["join"] = {"visit": ["unit", "serial"]}
    linked = one(Mapper(spec, KEY, "site"), "diagnoses", visit="W|7", unit="W", serial="7", number="D1", chart="A")
    assert linked["encounter"]["reference"] == "Encounter/" + visit["id"]


def test_inactive_resource_supplies_no_owner_claim(tmp_path: Path) -> None:
    spec = mapping(tmp_path / "map.yaml")
    spec.resources = [
        ResourceSpec(
            t,
            "visits",
            {"hid": "number"},
            {"subject.reference": patient_ref(col)},
            where=[{"column": "kind", "equals": kind}],
        )
        for t, col, kind in [("Encounter", "admit_mrn", "admit"), ("Observation", "lab_mrn", "lab")]
    ]
    m = Mapper(spec, KEY, "site")
    visit = one(m, "visits", kind="admit", number="E1", admit_mrn="A")
    assert visit == one(m, "visits", kind="admit", number="E1", admit_mrn="A", lab_mrn="B")


def test_static_contained_resource_requires_independent_type(tmp_path: Path) -> None:
    spec = mapping(tmp_path / "map.yaml")
    spec.static = [{"resourceType": "Organization", "id": "org", "contained": [{"resourceType": "Patient", "id": "P"}]}]
    with pytest.raises(HeldOwner, match="record_identity.static_type"):
        Mapper(spec, KEY, "site").static_resources()


@pytest.mark.parametrize("value", ['row["id"]', 'row.get("id")'])
def test_direct_source_id_is_a_record_identity_bypass(tmp_path: Path, value: str) -> None:
    src = tmp_path / "services/adapter/feed.py"
    src.parent.mkdir(parents=True)
    src.write_text(f'def emit(row):\n    return {{"resourceType": "Observation", "id": {value}}}\n')
    assert scan(tmp_path) == {("services/adapter/feed.py", "emit"): {"build FHIR id": 1}}


def test_annotated_source_id_copy_is_in_the_inventory(tmp_path: Path) -> None:
    src = tmp_path / "libs/feed/map.py"
    src.parent.mkdir(parents=True)
    src.write_text(
        'def emit(source):\n    token: str = source["id"]\n    return dict(resourceType="Claim", id=token)\n'
    )
    assert scan(tmp_path) == {("libs/feed/map.py", "emit"): {"build FHIR id": 1}}


def test_composite_reference_cannot_change_a_components_chart_domain(tmp_path: Path) -> None:
    spec = mapping(tmp_path / "map.yaml")
    spec.tables["visits"]["join"] = {"number": ["chart", "local"]}
    spec.tables["diagnoses"]["join"] = {"visit": ["raw_chart", "serial"]}
    mapper = Mapper(spec, KEY, "site")
    with pytest.raises(HeldOwner, match="record_identity.reference_parts"):
        one(mapper, "diagnoses", chart="A", raw_chart=" A ", serial="7", visit=" A |7", number="D1")


@pytest.mark.parametrize(
    ("file", "function", "binding"),
    [
        ("ndjson.py", "_carried_over", "call alias_references\nalias_references(r, aliases)"),
        ("backfill.py", "_spool", "call pid_for_mrn\npid_for_mrn(key, mrn)"),
    ],
)
def test_later_slice_binding_stays_visible(tmp_path: Path, file: str, function: str, binding: str) -> None:
    rel = "services/adapter/" + file
    src = tmp_path / rel
    src.parent.mkdir(parents=True)
    src.write_bytes((ROOT / rel).read_bytes())
    inventory = expected_inventory(ROOT / "tools/record_identity_ratchet.json", detailed=True)
    listed = scan(tmp_path, detailed=True).get((rel, function), Counter[str]())
    assert listed[binding] == inventory.get((rel, function), Counter[str]())[binding]
    # A migrated call may disappear from both inventories. Reintroducing it must still be detected.
    expression = binding.split("\n", 1)[1]
    src.write_text(f"def migrated_again():\n    return {expression}\n")
    assert scan(tmp_path, detailed=True)[rel, "migrated_again"][binding] == 1


def test_incremental_resource_construction_cannot_copy_a_source_id(tmp_path: Path) -> None:
    src = tmp_path / "services/adapter/extra.py"
    src.parent.mkdir(parents=True)
    src.write_text(
        'def emit(row):\n    out = {"resourceType": "Observation"}\n    out["id"] = str(row["id"])\n    return out\n'
    )
    assert scan(tmp_path) == {("services/adapter/extra.py", "emit"): {"assign constructed id": 1}}


def test_inactive_owner_cannot_change_an_encounters_own_identifier(tmp_path: Path) -> None:
    spec = mapping(tmp_path / "map.yaml")
    visit = spec.resources[0]
    visit.where = [{"column": "kind", "equals": "admit"}]
    spec.resources = [
        visit,
        ResourceSpec(
            "Observation",
            "visits",
            {"hid": "lab"},
            {"subject.reference": patient_ref("number")},
            where=[{"column": "kind", "equals": "lab"}],
        ),
    ]
    record = one(Mapper(spec, KEY, "site"), "visits", kind="admit", number="E1", chart="A")
    assert record["identifier"][0]["value"] == record["id"]
