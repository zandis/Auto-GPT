from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from adapter.mapping.engine import Mapper, Mapping, MappingError, resource_id
from tb_common.crypto import pid_for_mrn

KEY = b"k" * 32


def _mapping(tmp_path: Path, resources: list[dict[str, object]], lookups: str | None = None) -> Mapping:
    doc: dict[str, object] = {
        "version": 1,
        "name": "t",
        "tz": "Asia/Taipei",
        "systems": {"loinc": "http://loinc.org", "ucum": "http://unitsofmeasure.org", "dept": "urn:dept"},
        "tables": {"t": {"source": "t", "key": "id"}},
        "resources": resources,
    }
    if lookups:
        (tmp_path / "lk.csv").write_text(lookups, encoding="utf-8")
        doc["lookups"] = {"lab": {"file": "lk.csv", "key": "local_code"}}
    p = tmp_path / "m.yaml"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return Mapping.load(p)


def test_paths_types_refs_and_pruning(tmp_path: Path) -> None:
    m = _mapping(
        tmp_path,
        [
            {
                "type": "Encounter",
                "table": "t",
                "id": {"hid": "id"},
                "elements": {
                    "subject.reference": {"ref": {"type": "Patient", "pid": "mrn"}},
                    "participant[0].individual.reference": {"ref": {"type": "Practitioner", "column": "staff"}},
                    "period.start": {"column": "dt", "type": "datetime"},
                    "class.code": {"column": "typ", "map": {"OPD": "AMB"}, "default": "AMB"},
                    "serviceType.coding[0]": {"builder": "coding", "column": "dept", "system": "dept"},
                    "identifier[0].value": {"template": "{site_id}-{id}"},
                    "status": {"const": "finished"},
                    "empty.thing": {"column": "nothing"},
                },
            }
        ],
    )
    res = Mapper(m, KEY, "S1").map_row(
        m.resources[0],
        {
            "id": "E1",
            "mrn": "12345678",
            "staff": "P1",
            "dt": "2026-01-02 08:30:00",
            "typ": "XX",
            "dept": "RHEU",
            "nothing": "",
        },
    )
    assert res is not None
    assert res["id"] == resource_id(KEY, "Encounter", "E1")
    assert res["subject"]["reference"] == f"Patient/{pid_for_mrn(KEY, '12345678')}"
    assert res["participant"][0]["individual"]["reference"] == "Practitioner/P1"
    assert res["period"]["start"] == "2026-01-02T08:30:00+08:00"
    assert res["class"] == {"code": "AMB"}
    assert res["serviceType"]["coding"][0] == {"system": "urn:dept", "code": "RHEU"}
    assert res["identifier"][0]["value"] == "S1-E1"
    assert "empty" not in res


def test_lab_value_builder_quantity_conversion_and_coded(tmp_path: Path) -> None:
    lookups = (
        "local_code,system,code,display,ucum,factor,category,value_type,answers,profile,verified\n"
        "CRP,loinc,1988-5,CRP,mg/L,10,laboratory,quantity,,,yes\n"
        "HBS,loinc,5196-1,HBsAg,,1,laboratory,coded,POS:LA6576-8|Positive;NEG:LA6577-6|Negative,,yes\n"
    )
    m = _mapping(
        tmp_path,
        [
            {
                "type": "Observation",
                "table": "t",
                "id": {"hid": "id"},
                "where": [{"lookup": {"name": "lab", "key": "local_code", "field": "code"}, "not_empty": True}],
                "elements": {"$merge": {"builder": "lab_value", "lookup": "lab", "key": "local_code", "column": "v"}},
            }
        ],
        lookups,
    )
    mp = Mapper(m, KEY, "S")
    q = mp.map_row(m.resources[0], {"id": "1", "local_code": "CRP", "v": "1.25"})
    assert q is not None and q["valueQuantity"] == {
        "value": 12.5,
        "unit": "mg/L",
        "system": "http://unitsofmeasure.org",
        "code": "mg/L",
    }
    c = mp.map_row(m.resources[0], {"id": "2", "local_code": "HBS", "v": "pos"})
    assert c is not None and c["valueCodeableConcept"]["coding"][0]["code"] == "LA6576-8"
    assert mp.map_row(m.resources[0], {"id": "3", "local_code": "UNMAPPED", "v": "1"}) is None


def test_bad_dates_raise(tmp_path: Path) -> None:
    m = _mapping(
        tmp_path,
        [
            {
                "type": "Patient",
                "table": "t",
                "id": {"pid": "id"},
                "elements": {"birthDate": {"column": "b", "type": "date"}},
            }
        ],
    )
    with pytest.raises(MappingError):
        Mapper(m, KEY, "S").map_row(m.resources[0], {"id": "1", "b": "13/45/2020"})


def test_undeclared_table_rejected(tmp_path: Path) -> None:
    p = tmp_path / "m.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "tables": {},
                "resources": [{"type": "Patient", "table": "x", "id": {"pid": "id"}}],
            }
        )
    )
    with pytest.raises(MappingError, match="undeclared table"):
        Mapping.load(p)


def test_demo_mapping_loads(repo_root: Path) -> None:
    m = Mapping.load(repo_root / "services/adapter/mapping/tw_core/demo_his.yaml")
    types = {r.type for r in m.resources}
    for t in [
        "Patient",
        "Encounter",
        "Appointment",
        "Condition",
        "Observation",
        "MedicationRequest",
        "Procedure",
        "DiagnosticReport",
        "DocumentReference",
        "Claim",
        "ClaimResponse",
        "Practitioner",
        "Coverage",
    ]:
        assert t in types


def test_fhir_store_follows_the_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """fhir-store mirrors each snapshot: resources that left the source are deleted (dependents first), from a ledger
    of loaded ids that survives a failed run (CQL and SQL must see the same data)."""
    import httpx
    from adapter import load_fhir
    from adapter.ndjson import write_snapshot

    sent: list[tuple[str, str]] = []
    fail = {"on": False}

    def handler(req: httpx.Request) -> httpx.Response:
        if fail["on"]:
            return httpx.Response(500, text="down")
        for e in json.loads(req.content)["entry"]:
            sent.append((e["request"]["method"], e["request"]["url"]))
        return httpx.Response(200, json={"resourceType": "Bundle", "type": "transaction-response"})

    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))

    def snap(name: str, conds: list[str], pats: list[str]) -> Path:
        d = tmp_path / name
        write_snapshot(
            d,
            {
                "Patient": [{"resourceType": "Patient", "id": p} for p in pats],
                "Condition": [{"resourceType": "Condition", "id": c} for c in conds],
            },
        )
        return d

    ledger = tmp_path / "ledger"
    assert load_fhir.sync_snapshot("http://hapi/fhir", snap("s1", ["c1", "c2"], ["p1", "p2"]), ledger) == (4, 0)
    sent.clear()
    # c2 (a diagnosis deleted in the HIS) and p2 with it disappear; the Condition goes before the Patient
    assert load_fhir.sync_snapshot("http://hapi/fhir", snap("s2", ["c1", "c3"], ["p1"]), ledger) == (3, 2)
    assert [x for x in sent if x[0] == "DELETE"] == [("DELETE", "Condition/c2"), ("DELETE", "Patient/p2")]
    # a load that fails half way still remembers c4, so the next run removes it
    fail["on"] = True
    with pytest.raises(RuntimeError):
        load_fhir.sync_snapshot("http://hapi/fhir", snap("s3", ["c1", "c4"], ["p1"]), ledger)
    fail["on"] = False
    sent.clear()
    assert load_fhir.sync_snapshot("http://hapi/fhir", snap("s4", ["c1"], ["p1"]), ledger)[1] == 2
    assert sorted(x[1] for x in sent if x[0] == "DELETE") == ["Condition/c3", "Condition/c4"]
    # without a ledger yet (first run after the upgrade) the previous snapshot stands in for it
    sent.clear()
    fresh = tmp_path / "ledger2"
    load_fhir.sync_snapshot("http://hapi/fhir", snap("s5", ["c1"], ["p1"]), fresh, previous=tmp_path / "s2")
    assert sorted(x[1] for x in sent if x[0] == "DELETE") == ["Condition/c3"]
