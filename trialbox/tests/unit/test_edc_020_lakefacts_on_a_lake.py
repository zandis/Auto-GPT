"""EDC-020 (D-855): ``edc.prefill.LakeFacts`` is tested on a lake, not only on its stand-in.

Deep review EDC-020 (Medium, E-24): the SQL that feeds every EDC draft ran only against ``tests/edc_kit.FakeFacts``.
Here a lake is built by the lake's own rebuild from synthetic FHIR files holding the stand-in's patient, and
``LakeFacts`` must read back what the stand-in gives: the patient, the observations, the condition and the note.
A draft built on the lake then holds the same values as a draft built on the stand-in."""

from __future__ import annotations

import base64
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from edc.prefill import LakeFacts
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from lake.store import Lake
from tb_common import id_rule

from tests import edc_kit as k

SNAP = "2026-11-02"
LOINC, ICD10CM = "http://loinc.org", "http://hl7.org/fhir/sid/icd-10-cm"


def _obs(oid: str, code: str, on: str, value: float, unit: str) -> dict[str, Any]:
    return {"resourceType": "Observation", "id": oid, "status": "final", "subject": {"reference": f"Patient/{k.PID}"},
            "code": {"coding": [{"system": LOINC, "code": code}]}, "effectiveDateTime": f"{on}T09:00:00+09:00",
            "valueQuantity": {"value": value, "unit": unit}}  # fmt: skip


@pytest.fixture(scope="module")
def lake(tmp_path_factory: pytest.TempPathFactory) -> LakeLocal:
    tmp = tmp_path_factory.mktemp("edc020")
    nd = tmp / "ndjson"
    nd.mkdir()
    files = {
        "Patient": [{"resourceType": "Patient", "id": k.PID, "birthDate": "1960-05-01", "gender": "male"}],
        "Observation": [_obs("o1", "29463-7", "2026-11-01", 72.5, "kg"), _obs("o2", "3084-1", "2026-10-20", 8.4, "mg/dL"),
                        _obs("o3", "3084-1", "2026-06-01", 9.1, "mg/dL")],
        "Condition": [{"resourceType": "Condition", "id": "c1", "subject": {"reference": f"Patient/{k.PID}"},
                       "code": {"coding": [{"system": ICD10CM, "code": "M10.9"}]}, "onsetDateTime": "2024-01-10",
                       "clinicalStatus": {"coding": [{"code": "active"}]}}],
        "DocumentReference": [{"resourceType": "DocumentReference", "id": "n1", "status": "current",
                               "subject": {"reference": f"Patient/{k.PID}"}, "date": "2026-10-20T09:00:00+09:00",
                               "type": {"text": "progress"},
                               "content": [{"attachment": {"contentType": "text/plain", "data": base64.b64encode(
                                   b"Gout clinic.\nTophus on the right ear.").decode()}}]}],
    }  # fmt: skip
    for name, rows in files.items():
        (nd / f"{name}.ndjson").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    id_rule.write_snapshot_record(nd)  # D-1253: a snapshot of this release
    Lake(tmp / "lake", "Asia/Taipei").rebuild(SNAP, HashEmbedder(), nd)
    return LakeLocal(tmp / "lake", HashEmbedder(), "Asia/Taipei")


def test_the_patient_reads_as_the_stand_in_gives_it(lake: LakeLocal) -> None:
    got = LakeFacts(lake).patient(k.PID)
    # the lake writes FHIR's word ("male"); the stand-in writes "M": the draft reads both as one (prefill's sex map)
    assert got is not None and (str(got["birth_date"])[:10], got["sex"]) == ("1960-05-01", "male")
    assert LakeFacts(lake).patient("nobody") is None


def test_the_observations_and_the_condition_read_with_their_systems(lake: LakeLocal) -> None:
    facts = LakeFacts(lake)
    obs = {
        (r["code"], str(r["d"]), float(r["value_num"]), r["unit"], r["system"])
        for r in facts.rows(k.PID, "observation")
    }
    assert obs == {("29463-7", "2026-11-01", 72.5, "kg", LOINC), ("3084-1", "2026-10-20", 8.4, "mg/dL", LOINC),
                   ("3084-1", "2026-06-01", 9.1, "mg/dL", LOINC)}  # fmt: skip
    cond = facts.rows(k.PID, "condition")
    assert [(r["code"], r["system"], str(r["d"])[:10]) for r in cond] == [("M10.9", ICD10CM, "2024-01-10")]
    assert facts.rows(k.PID, "medication") == [] and facts.rows(k.PID, "no_such_source") == []


def test_the_note_reads_whole_and_dated(lake: LakeLocal) -> None:
    notes = LakeFacts(lake).notes(k.PID, date(2026, 11, 2))
    assert [(str(n["d"]), n["text"]) for n in notes] == [("2026-10-20", "Gout clinic.\nTophus on the right ear.")]
    assert LakeFacts(lake).notes(k.PID, date(2026, 10, 1)) == []


def test_a_draft_on_the_lake_holds_the_stand_ins_values(lake: LakeLocal, tmp_path: Path) -> None:
    def values(facts: Any, where: Path) -> dict[str, str]:
        svc, _sim, _tok = k.service(where, facts=facts)
        k.ready(svc)
        return {d["item"]: str(d["value"]) for d in svc.build(k.STUDY, k.RECORD, k.PID, "", k.VISIT_DATE, "crc")
                if d["item"] in ("weight", "urate", "brthdat", "sex", "mh_gout")}  # fmt: skip

    stand_in = k.FakeFacts()
    stand_in.facts = []  # the lake here holds no site facts
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    assert values(LakeFacts(lake), tmp_path / "a") == values(stand_in, tmp_path / "b")
