"""D-1253 second review. All charts and records are synthetic."""

import json
from pathlib import Path

import pytest
from adapter import site_profile
from adapter.mapping.engine import Mapping, MappingError, resource_id
from adapter.ndjson import read_type, snapshot_dir
from adapter.pipeline import HELD, PASSED, run_ingest
from adapter.publish import publish_held
from lake.flatten import Flattener
from tb_common import id_rule

from tests.unit import test_lake_ids_per_patient as ids


def test_template_patient_owns_device(tmp_path: Path) -> None:
    device = {
        "type": "Device",
        "table": "thing",
        "id": {"hid": "no", "site_wide": True},
        "elements": {"patient.reference": {"template": "Patient/{pid:mrn}"}},
    }
    with pytest.raises(MappingError, match="site-wide"):
        Mapping.load(ids._site(tmp_path, [device]))
    device["id"] = {"hid": "no"}
    _, mapper = ids._mapper(ids._site(tmp_path, [device]))
    records = list(mapper.map_table("thing", iter([{"mrn": m, "no": "D1"} for m in (ids.A, ids.B)])))
    assert {r["patient"]["reference"] for r in records} == {f"Patient/{pid}" for pid in ids.PIDS}
    assert len({r["id"] for r in records}) == 2


def test_disputed_appointments_stay_out_of_scope() -> None:
    _, mapper = ids._mapper()
    mapper.review = {("Appointment", resource_id(ids.KEY, "Appointment", "A7"))}
    rows = [dict(r, appt_no="A7") for r in ids.both()["appointment"]]
    rows.append(dict(rows[0], appt_no="A8"))
    a, b, clear = mapper.map_table("appointment", iter(rows))
    assert a["id"] != b["id"]
    assert all(id_rule.REVIEW_TAG in r["meta"]["tag"] and r["status"] == "booked" for r in (a, b))
    table = Flattener().flatten({"Appointment": [a, b, clear]})["appointment"]
    assert [(r["aid"], r["pid"]) for r in table] == [(clear["id"], ids.PID[ids.A])]


@pytest.mark.parametrize("changed_profile", [False, True])
def test_source_changing_delta_cannot_be_accepted(tmp_path: Path, changed_profile: bool) -> None:
    first, second = "2026-10-01", "2026-10-02"
    rows = ids.canonical(ids.A)
    rows["diagnosis"][0]["diag_no"] = "D1"
    assert ids.night(tmp_path, "csv", {"patient": rows["patient"], "diagnosis": rows["diagnosis"]}, first).passed
    cfg = ids._cfg(tmp_path, "csv")
    base = snapshot_dir(cfg.lake_dir, first)
    if changed_profile:
        (base / site_profile.RECORD).write_text(json.dumps({"profile": {"digest": "prior-profile"}}))
    (mapped,) = read_type(base, "Condition")
    export = tmp_path / "bulk"
    export.mkdir()
    subject = {"reference": f"Patient/{ids.A}"}
    diagnosis = {"resourceType": "Condition", "id": "D1", "subject": subject, "code": mapped["code"]}
    (export / "Condition.ndjson").write_text(json.dumps(diagnosis) + "\n")
    (export / "Device.ndjson").write_text(json.dumps({"resourceType": "Device", "id": "D2", "patient": subject}))
    held = run_ingest(
        cfg, "fhir_bulk", str(export), snapshot=second, since=first, load_fhir=False, rebuild_lake=False, validate=False
    )
    assert held.held and any(ids.SOURCE_WORDS in msg for msg in held.errors)
    folder = snapshot_dir(cfg.lake_dir, second)
    candidate_ids = {r["id"] for r in read_type(folder, "Condition")}
    acceptance = publish_held(cfg, second)
    assert not acceptance.ok, candidate_ids
    assert mapped["id"] not in candidate_ids
    assert not (folder / PASSED).exists()
    assert list(read_type(base, "Condition")) == [mapped]

    # The same refusal on disk before the upgrade. Its folder already contains the mixed snapshot.
    legacy = f"delta night from fhir_bulk over snapshot {first}, which was read from csv: a site {ids.SOURCE_WORDS}"
    (folder / HELD).write_text(json.dumps({"snapshot": second, "errors": [legacy + " (run it without since)"]}))
    with (folder / "Condition.ndjson").open("a") as fh:
        fh.write(json.dumps(mapped) + "\n")
    assert not publish_held(cfg, second).ok
    assert not (folder / PASSED).exists()
    # A full ingest on the same date replaces the held files, including types the delta alone supplied.
    (export / "Device.ndjson").unlink()
    (export / "Patient.ndjson").write_text(json.dumps({"resourceType": "Patient", "id": ids.A}))
    (export / "Coverage.ndjson").write_text(
        json.dumps({"resourceType": "Coverage", "id": "C1", "beneficiary": subject})
    )
    retry = run_ingest(
        cfg, "fhir_bulk", str(export), snapshot=second, load_fhir=False, rebuild_lake=False, validate=False
    )
    assert retry.passed, retry.errors
    assert [r["id"] for r in read_type(folder, "Condition")] == [resource_id(ids.KEY, "Condition", "D1")]
    assert not (folder / "Device.ndjson").exists()


def test_refused_delta_charts_do_not_publish_with_full_retry(tmp_path: Path) -> None:
    first, second = "2026-10-01", "2026-10-02"
    assert ids._bulk_night(tmp_path, first).passed
    assert ids.night(tmp_path, "csv", ids.canonical(ids.A), second, since=first).held
    retry = ids._bulk_night(tmp_path, second)
    assert retry.passed, retry.errors
    pm = ids._cfg(tmp_path, "csv").pidmap()
    try:
        assert pm.resolve(ids.PID[ids.A]) is None
    finally:
        pm.close()
