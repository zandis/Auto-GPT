"""NEW-B-36 (D-677; deep review DATA-006): a delta night applies the chart merges to what it carries over.

A delta night is the night before merged with tonight's changed rows. A chart merged between the two nights
(``pid-merge A -> B``) was applied only to tonight's rows: the records carried over from the night before kept
patient A, and A's diagnoses stayed under ``Patient/A``. Screening on B missed A's history and the patient counted
twice, until the next full night. The night after a merge must hold what a full night after it holds."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest
from adapter.ndjson import read_type, snapshot_dir
from adapter.pipeline import AdapterConfig, run_ingest

from tests.unit.test_dataflow_lake_p0 import KEY, _cfg, _Lakes

PATIENT = ["mrn", "name", "id_no", "birth_date", "sex", "death_date", "phone"]
DIAG = ["diag_no", "enc_no", "mrn", "icd10", "diag_date", "recorded_date", "status", "deleted"]
A, B = "10000002", "10000003"  # made-up chart numbers: A is merged into B between the two nights
FULL, DELTA = "2026-10-01", "2026-10-02"


def _write(path: Path, name: str, cols: list[str], rows: list[dict[str, str]]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    with (path / f"{name}.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})


def _patient(mrn: str) -> dict[str, str]:
    return {"mrn": mrn, "name": f"TEST {mrn[-1]}", "id_no": f"Z{mrn}", "birth_date": "1960-01-01", "sex": "F"}


def _diag(no: str, mrn: str, icd10: str) -> dict[str, str]:
    return {"diag_no": no, "enc_no": "E1", "mrn": mrn, "icd10": icd10, "diag_date": "2026-09-01",
            "recorded_date": "2026-09-01", "status": "A"}  # fmt: skip


def _merge(cfg: AdapterConfig) -> tuple[str, str]:
    pm = cfg.pidmap()
    try:
        return pm.merge(KEY, A, B, "duplicate chart", "HIS-1")
    finally:
        pm.close()


def _held(cfg: AdapterConfig, snap: str) -> dict[str, Any]:
    """What a reader of the snapshot sees: the patients, and per record of every other type the patient it is
    about (the night it was ingested differs between a carried-over record and a re-read one: not compared)."""
    d = snapshot_dir(cfg.lake_dir, snap)
    patients = sorted(r["id"] for r in read_type(d, "Patient"))
    about: dict[str, dict[str, str]] = {}
    for f in sorted(d.glob("*.ndjson")):
        if f.stem == "Patient":
            continue
        for r in read_type(d, f.stem):
            ref = json.dumps(r.get("subject") or r.get("patient") or r.get("beneficiary") or {}, sort_keys=True)
            about.setdefault(f.stem, {})[r["id"]] = ref
    text = "".join(p.read_text(encoding="utf-8") for p in sorted(d.glob("*.ndjson")))
    return {"patients": patients, "about": about, "text": text}


@pytest.mark.parametrize("patients_tonight", [[B], [A, B]], ids=["B only", "both still sent"])
def test_the_night_after_a_merge_holds_what_a_full_night_after_it_holds(
    tmp_path: Path, patients_tonight: list[str] | None
) -> None:
    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    _write(tmp_path / "full", "patient", PATIENT, [_patient(A), _patient(B)])
    _write(tmp_path / "full", "diagnosis", DIAG, [_diag("D1", A, "C50.9"), _diag("D2", B, "E11.9")])
    rep = run_ingest(cfg, "csv", str(tmp_path / "full"), snapshot=FULL, load_fhir=False, validate=False)
    assert rep.passed, rep.errors
    old, new = _merge(cfg)
    # the delta export of the next night: one new diagnosis of B; the patient table as the hospital sends it
    if patients_tonight is not None:
        _write(tmp_path / "delta", "patient", PATIENT, [_patient(m) for m in patients_tonight])
    _write(tmp_path / "delta", "diagnosis", DIAG, [_diag("D3", B, "I10")])
    rep = run_ingest(cfg, "csv", str(tmp_path / "delta"), since=FULL, snapshot=DELTA, load_fhir=False,
                     validate=False)  # fmt: skip
    assert rep.passed, rep.errors
    delta = _held(cfg, DELTA)

    # a full night after the merge, of every row the box received (a delta night keeps what the night before held
    # for a row it is not sent again, merged or not: the patient file without A takes nothing away), on a lake of
    # its own and the same pid map
    (tmp_path / "w").mkdir(exist_ok=True)
    whole = _cfg(tmp_path / "w", None)
    _write(tmp_path / "all", "patient", PATIENT, [_patient(A), _patient(B)])
    _write(tmp_path / "all", "diagnosis", DIAG,
           [_diag("D1", A, "C50.9"), _diag("D2", B, "E11.9"), _diag("D3", B, "I10")])  # fmt: skip
    rep = run_ingest(whole, "csv", str(tmp_path / "all"), snapshot=DELTA, load_fhir=False, validate=False)
    assert rep.passed, rep.errors
    full = _held(whole, DELTA)

    assert delta["patients"] == full["patients"] == [new]
    assert delta["about"] == full["about"]
    assert f"Patient/{old}" not in delta["text"] and f'"{old}"' not in delta["text"]
    # and the lake built from it, which screening reads: one patient, A's diagnosis under B
    pids = {r["pid"] for r in lakes.lake.query("SELECT pid FROM condition").to_pylist()}
    assert pids == {new}
    assert [r["pid"] for r in lakes.lake.query("SELECT pid FROM patient").to_pylist()] == [new]


def test_a_delta_night_without_a_patient_record_applies_the_merges_too(tmp_path: Path) -> None:
    """A FHIR bulk delta sends only what changed: tonight no Patient. The merges were read only when the night had
    patient rows; the records carried over kept the merged patient."""
    from tb_common.crypto import pid_for_mrn

    cfg = _cfg(tmp_path)
    exp = tmp_path / "bulk1"
    exp.mkdir()
    people = [{"resourceType": "Patient", "id": m} for m in ("M1", "M2")]
    conds = [{"resourceType": "Condition", "id": c, "subject": {"reference": f"Patient/{m}"}}
             for c, m in (("c1", "M1"), ("c2", "M2"))]  # fmt: skip
    (exp / "Patient.ndjson").write_text("\n".join(json.dumps(p) for p in people) + "\n")
    (exp / "Condition.ndjson").write_text("\n".join(json.dumps(c) for c in conds) + "\n")
    run_ingest(cfg, "fhir_bulk", str(exp), snapshot=FULL, load_fhir=False, rebuild_lake=False, validate=False)
    pm = cfg.pidmap()
    try:
        old, new = pm.merge(KEY, "M1", "M2", "duplicate chart", "HIS-2")
    finally:
        pm.close()
    assert (old, new) == (pid_for_mrn(KEY, "M1"), pid_for_mrn(KEY, "M2"))
    delta = tmp_path / "bulk2"
    delta.mkdir()
    (delta / "Condition.ndjson").write_text(
        json.dumps({"resourceType": "Condition", "id": "c3", "subject": {"reference": "Patient/M1"}}) + "\n"
    )
    rep = run_ingest(cfg, "fhir_bulk", str(delta), since=FULL, snapshot=DELTA, load_fhir=False, rebuild_lake=False,
                     validate=False)  # fmt: skip
    assert rep.passed, rep.errors
    held = _held(cfg, DELTA)
    assert held["patients"] == [new]
    assert set(held["about"]["Condition"].values()) == {json.dumps({"reference": f"Patient/{new}"})}
    assert len(held["about"]["Condition"]) == 3 and old not in held["text"]


# ------------------------------------------------------------------------------------------- the writer itself
def _base(tmp_path: Path, patients: list[dict[str, Any]], others: dict[str, list[dict[str, Any]]]) -> Path:
    from adapter.ndjson import write_snapshot

    base = tmp_path / "base"
    write_snapshot(base, {"Patient": patients, **others})
    return base


def test_the_writer_moves_carried_over_references_and_keeps_the_surviving_patients_own_record(tmp_path: Path) -> None:
    from adapter.ndjson import write_snapshot

    base = _base(
        tmp_path,
        [{"resourceType": "Patient", "id": "pa", "gender": "female", "identifier": [{"value": "pa"}]},
         {"resourceType": "Patient", "id": "pb", "gender": "male"}],
        {"Condition": [{"resourceType": "Condition", "id": "c1", "subject": {"reference": "Patient/pa"}},
                       {"resourceType": "Condition", "id": "c2", "subject": {"reference": "Patient/pb"}}],
         "Encounter": [{"resourceType": "Encounter", "id": "e1", "subject": {"reference": "Patient/pb"}}]},
    )  # fmt: skip
    before = {f.name: f.read_bytes() for f in base.glob("*.ndjson")}
    moved: dict[str, int] = {}
    out = tmp_path / "out"
    counts = write_snapshot(out, {}, base, aliases={"pa": "pb"}, moved=moved)
    assert counts == {"Condition": 2, "Encounter": 1, "Patient": 1}
    assert list(read_type(out, "Patient")) == [{"resourceType": "Patient", "id": "pb", "gender": "male"}]
    assert {r["id"]: r["subject"]["reference"] for r in read_type(out, "Condition")} == {
        "c1": "Patient/pb", "c2": "Patient/pb"
    }  # fmt: skip
    assert moved == {"Condition": 1, "Patient": 1}
    assert (out / "Encounter.ndjson").read_bytes() == before["Encounter.ndjson"]  # a line naming no merge: as it was
    # the next delta night over it: nothing left to move, the same bytes
    again: dict[str, int] = {}
    write_snapshot(tmp_path / "out2", {}, out, aliases={"pa": "pb"}, moved=again)
    assert again == {} and all(
        (tmp_path / "out2" / f.name).read_bytes() == f.read_bytes() for f in out.glob("*.ndjson")
    )


def test_the_writer_gives_a_merged_patient_the_surviving_id_when_no_one_else_holds_it(tmp_path: Path) -> None:
    from adapter.ndjson import write_snapshot

    base = _base(
        tmp_path,
        [{"resourceType": "Patient", "id": "pa", "identifier": [{"value": "pa"}], "gender": "female"},
         {"resourceType": "Patient", "id": "pz", "gender": "male"}],
        {},
    )  # fmt: skip
    out = tmp_path / "out"
    write_snapshot(out, {}, base, aliases={"pa": "pc"})
    assert list(read_type(out, "Patient")) == [
        {"resourceType": "Patient", "id": "pc", "identifier": [{"value": "pc"}], "gender": "female"},
        {"resourceType": "Patient", "id": "pz", "gender": "male"},
    ]
    # tonight's record of the surviving patient wins over the merged one carried over
    tonight = [{"resourceType": "Patient", "id": "pc", "gender": "other"}]
    write_snapshot(tmp_path / "out2", {"Patient": tonight}, base, aliases={"pa": "pc"})
    assert [r.get("gender") for r in read_type(tmp_path / "out2", "Patient")] == ["other", "male"]


def test_a_chain_of_merges_and_a_reference_in_a_list_are_moved(tmp_path: Path) -> None:
    from adapter.ndjson import write_snapshot

    base = _base(
        tmp_path,
        [{"resourceType": "Patient", "id": "pc"}],
        {"Observation": [{"resourceType": "Observation", "id": "o1", "subject": {"reference": "Patient/pa"},
                          "performer": [{"reference": "Practitioner/x"}, {"reference": "Patient/pb"}]}]},
    )  # fmt: skip
    write_snapshot(tmp_path / "out", {}, base, aliases={"pa": "pc", "pb": "pc"})  # pidmap.aliases follows chains
    (o,) = read_type(tmp_path / "out", "Observation")
    assert o["subject"]["reference"] == "Patient/pc"
    assert [p["reference"] for p in o["performer"]] == ["Practitioner/x", "Patient/pc"]
