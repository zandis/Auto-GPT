"""D-1253. Synthetic collisions at the mapper, night gate and screening table boundaries.

On e35aac74, running this file with PYTEST_ADDOPTS=--runxfail gave 26 failures and 14 passes.
The failing pytest cases, grouping only parameter combinations that failed, were

* test_reference_forms: patient and site_wide, each with column, ref_column and by_day
* test_chart_review: Consent-registry and Coverage-patient
* test_review_scope: omop
* test_full_retry: legacy and omop
* test_rebuild_hold: validation and source, each with legacy and omop
* test_order_form: per_day-backfill and per_day-night
* test_site_device_owner: expr0 and expr1
* test_old_order_hold: old-hold and unstamped-base
* test_by_day_chart_spelling, test_device_owner_from_object and test_retry_while_lake_reads
* test_identical_chart_numbers and test_historical_chart_spelling (owner decisions)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from adapter.backfill import backfill
from adapter.mapping.engine import Mapping, MappingError, patient_resource_id, resource_id
from adapter.ndjson import snapshot_dir
from adapter.pipeline import run_ingest
from adapter.publish import publish_held, publish_night
from adapter.validate.validator import StructuralValidator, ValidationResult
from embed_service.embedder import HashEmbedder
from lake.source import SOURCES, force, lake_rows
from lake.store import Lake, RebuildError
from tb_common import id_rule
from tb_common.crypto import pid_for_mrn
from tb_contracts import RebuildResult

from tests.unit import test_lake_ids_per_patient as ids
from tests.unit import test_ssmix2_key_with_day as ss

FIRST, SECOND = "2026-10-01", "2026-10-02"
WIDE = "１００００００１"
Records = dict[str, list[dict[str, Any]]]


def test_identical_chart_numbers() -> None:
    _, mapper = ids._mapper()
    patients = ids.both()["patient"]
    patients[1]["mrn"] = patients[0]["mrn"]
    records = list(mapper.map_table("patient", iter(patients)))
    assert len({r["id"] for r in records if r["resourceType"] == "Patient"}) == 2
    assert all(id_rule.REVIEW_TAG in r["meta"]["tag"] for r in records)


@pytest.mark.parametrize("mode", ["night", "backfill"])
def test_shared_chart_stays_out_of_screening(tmp_path: Path, mode: str, db_url: str) -> None:
    tables = ids.both()
    for rows in tables.values():
        for row in rows:
            if row.get("mrn") == ids.B:
                row["mrn"] = ids.A
    cfg = ids._cfg(tmp_path, "csv")
    if mode == "backfill":
        feed = tmp_path / "feed"
        ids.write_csv(ids.CSV_SITE, feed, tables)
        assert backfill(cfg, "csv", str(feed), snapshot=FIRST, validate=False, rebuild_lake=False).state == "published"
    else:
        assert ids.night(tmp_path, "csv", tables, FIRST).passed
    folder = snapshot_dir(cfg.lake_dir, FIRST)
    if mode == "night":
        assert json.loads((folder / "ingest_report.json").read_text())["ambiguous_charts"] == 1
    report = json.loads((folder / "completeness.json").read_text())
    assert report["tables"]["patient"]["ambiguous_charts"] == 1
    feed_rows = ids.lake(tmp_path, FIRST)
    review_list = id_rule.read_review(cfg.lake_dir)
    for typ in ("Patient", "Condition", "Coverage", "Observation", "Consent"):
        assert len(feed_rows[typ]) >= 2
        assert {(typ, r["id"]) for r in feed_rows[typ]} <= review_list
        assert all(id_rule.REVIEW_TAG in r["meta"]["tag"] for r in feed_rows[typ])
    for source in SOURCES:
        projection = _tables(tmp_path, FIRST, source)
        assert all(not records for table, records in projection.items() if table != "practitioner")


@pytest.mark.parametrize("form", ["pid", "column", "template", "ref_column", "by_day"])
@pytest.mark.parametrize("site_wide", [None, True, False], ids=["patient", "site_wide", "explicit_false"])
def test_reference_forms(tmp_path: Path, form: str, site_wide: bool | None) -> None:
    # A raw chart, an already pseudonymised id, a complete reference, and a join to Patient.
    by_day = {"table": "patient", "keys": ["mrn"], "day": "day", "their_day": "day"}
    expressions = {
        "pid": {"ref": {"type": "Patient", "pid": "mrn"}},
        "template": {"template": "Patient/{pid:mrn}"},
        "ref_column": {"ref": {"type": "Patient", "column": "owner_pid"}},
        "column": {"column": "owner_ref"},
        "by_day": {"ref": {"type": "Patient", "by_day": by_day}},
    }
    key: dict[str, Any] = {"hid": "no"}
    if site_wide is not None:
        key["site_wide"] = site_wide
    specs: list[dict[str, Any]] = [{"type": "Patient", "table": "patient", "id": {"pid": "mrn"}, "elements": {}}]
    for typ in (*ids.PATIENT_OWNED, "Device"):
        path = {
            "Claim": "patient.reference",
            "ClaimResponse": "patient.reference",
            "Consent": "patient.reference",
            "Coverage": "beneficiary.reference",
            "Appointment": "participant[0].actor.reference",
            "Device": "patient.reference",
        }.get(typ, "subject.reference")
        specs.append({"type": typ, "table": "thing", "id": key, "elements": {path: expressions[form]}})
    if site_wide is not None:
        # site_wide is true or omitted in the mapping grammar. Device can otherwise be a site catalogue record.
        for spec in specs[1:]:
            with pytest.raises(MappingError):
                Mapping.load(ids._site(tmp_path, [specs[0], spec]))
        return
    _, mapper = ids._mapper(ids._site(tmp_path, specs))
    for a_chart in (ids.A, WIDE):
        rows = [
            {"mrn": chart, "owner_pid": pid, "owner_ref": f"Patient/{pid}", "no": "D1", "day": FIRST}
            for chart, pid in [(a_chart, ids.PID[ids.A]), (ids.B, ids.PID[ids.B])]
        ]
        list(mapper.map_table("patient", iter(rows)))
        got = list(mapper.map_table("thing", iter(rows)))
        expected = {
            (typ, pid, patient_resource_id(ids.KEY, typ, pid, "D1"))
            for typ in (*ids.PATIENT_OWNED, "Device")
            for pid in ids.PIDS
        }
        assert {(r["resourceType"], next(iter(ids.owner(r))), r["id"]) for r in got} == expected
        assert set(mapper.tombstones("thing", iter(rows))) == {(typ, rid) for typ, _, rid in expected}


@pytest.mark.parametrize(("typ", "table"), [("Consent", "registry"), ("Coverage", "patient")])
def test_chart_review(typ: str, table: str) -> None:
    _, mapper = ids._mapper()
    mapper.review = frozenset({(typ, resource_id(ids.KEY, typ, ids.A))})
    first = ids.canonical(ids.A)[table][0]
    unchanged = None
    for chart in (ids.A, WIDE):
        rows = mapper.map_table(table, iter([{**first, "mrn": chart}, ids.canonical(ids.B)[table][0]]))
        a, b = [r for r in rows if r["resourceType"] == typ]
        assert id_rule.REVIEW_TAG in a["meta"]["tag"]
        assert id_rule.REVIEW_TAG not in b.get("meta", {}).get("tag", [])
        assert a["id"] != b["id"] and (unchanged is None or a["id"] == unchanged)
        unchanged = a["id"]


def _tables(tmp: Path, night: str, source: str) -> Records:
    return lake_rows(ids.lake(tmp, night), {}, tz="Asia/Taipei", snapshot=night, source=source, lake_dir=tmp / "lake")


@pytest.mark.parametrize("source", SOURCES)
def test_review_scope(tmp_path: Path, source: str, db_url: str) -> None:
    tables = ids.both()
    cfg = ids._cfg(tmp_path, "csv")
    cfg.lake_dir.mkdir()
    mapping, _ = ids._mapper()
    review = {
        (s.type, resource_id(ids.KEY, s.type, r[s.id["hid"]] + s.id.get("suffix", "")), "rejected")
        for s in mapping.resources
        if s.type in ids.PATIENT_OWNED
        for r in tables[s.table]
    }
    id_rule.write_review(cfg.lake_dir / id_rule.REVIEW, sorted(review))
    # One clear booking for B. A's only visit and booking with this clinician both need review.
    tables["appointment"].append({**tables["appointment"][1], "appt_no": "clear"})
    previous: dict[str, list[str]] | None = None
    for day, since in [(FIRST, None), (SECOND, FIRST)]:
        if since:
            for records in tables.values():
                for row in records:
                    if "updated_at" in row:
                        row["updated_at"] = day
        report = ids.night(tmp_path, "csv", tables, day, since=since)
        assert report.passed, report.errors
        feed = ids.lake(tmp_path, day)
        ids._check_references_stay_with_their_patient(feed, source)
        current = ids._ids(feed)
        assert previous is None or current == previous
        previous = current
        for typ in ids.PATIENT_OWNED:
            tagged = [r for r in feed[typ] if id_rule.REVIEW_TAG in r.get("meta", {}).get("tag", [])]
            assert {next(iter(ids.owner(r))) for r in tagged} == set(ids.PIDS), typ
        rows = _tables(tmp_path, day, source)
        unexpected = {
            t: len(rr) for t, rr in rows.items() if rr and t not in {"patient", "practitioner", "appointment"}
        }
        assert ([r["pid"] for r in rows["appointment"]], unexpected) == ([ids.PID[ids.B]], {})
        assert {r["pid"] for r in rows["patient"]} == set(ids.PIDS)


class _Reject(StructuralValidator):
    def validate(self, resources: list[dict[str, Any]]) -> ValidationResult:
        return ValidationResult("synthetic", len(resources), len(resources))


@pytest.mark.parametrize("source", SOURCES)
def test_full_retry(tmp_path: Path, source: str, db_url: str) -> None:
    cfg = ids._cfg(tmp_path, "csv")
    cfg.validation_max_pct = 0
    tables = ids.both()
    feed = tmp_path / "first"
    ids.write_csv(ids.CSV_SITE, feed, {t: tables[t] for t in ("patient", "appointment")})
    held = run_ingest(cfg, "csv", str(feed), snapshot=FIRST, validator=_Reject(), load_fhir=False, rebuild_lake=False)
    assert held.held and len(ids.lake(tmp_path, FIRST)["Appointment"]) == 2
    retry = ids.night(tmp_path, "csv", {"patient": tables["patient"]}, FIRST)
    assert retry.passed, retry.errors
    rows = _tables(tmp_path, FIRST, source)
    assert {r["pid"] for r in rows["patient"]} == set(ids.PIDS)
    assert rows["appointment"] == []


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("hold", ["validation", "source"])
def test_rebuild_hold(tmp_path: Path, source: str, hold: str, db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = ids._cfg(tmp_path, "csv")
    cfg.validation_max_pct = 0
    feed = tmp_path / "csv"
    ids.write_csv(ids.CSV_SITE, feed, {"patient": ids.canonical(ids.A)["patient"]})
    lake = Lake(cfg.lake_dir, cfg.tz)
    with force(source):
        assert run_ingest(cfg, "csv", str(feed), snapshot=FIRST, load_fhir=False, validate=False).passed
        lake.rebuild(FIRST, HashEmbedder())
        export = tmp_path / "bulk"
        if hold == "source":
            export.mkdir()
            bulk_rows: list[dict[str, Any]] = [
                {"resourceType": "Patient", "id": "synthetic-B"},
                {"resourceType": "Coverage", "id": "coverage", "beneficiary": {"reference": "Patient/synthetic-B"}},
            ]
            for r in bulk_rows:
                (export / f"{r['resourceType']}.ndjson").write_text(json.dumps(r) + "\n")
            held = run_ingest(
                cfg,
                "fhir_bulk",
                str(export),
                snapshot=SECOND,
                since=FIRST,
                validate=False,
                rebuild_lake=False,
                load_fhir=False,
            )
        else:
            ids.write_csv(ids.CSV_SITE, feed, {"patient": ids.canonical(ids.B)["patient"]})
            held = run_ingest(cfg, "csv", str(feed), snapshot=SECOND, validator=_Reject(), load_fhir=False)
        assert held.held
        # OMOP also checks ids removed within a type. Isolate the hold from that independent check.
        if source == "omop":
            monkeypatch.setenv("TB_FEED_DROP_OVERRIDE", f"{SECOND}: synthetic turnover")
        with pytest.raises(RebuildError):
            lake.rebuild(SECOND, HashEmbedder(), promote=True)
        assert lake.current() == FIRST
        assert lake.query("SELECT pid FROM patient").to_pylist() == [{"pid": ids.PID[ids.A]}]

        def rebuild(snap: str, folder: Path) -> RebuildResult:
            return RebuildResult.model_validate(lake.rebuild(snap, HashEmbedder(), folder), from_attributes=True)

        cfg.rebuild = rebuild
        if hold == "source":
            assert not publish_held(cfg, SECOND).ok
            report = run_ingest(cfg, "fhir_bulk", str(export), snapshot=SECOND, validate=False, load_fhir=False)
            assert report.passed, report.errors
            expected = pid_for_mrn(ids.KEY, "synthetic-B")
        else:
            assert publish_held(cfg, SECOND).ok
            expected = ids.PID[ids.B]
        assert lake.current() == SECOND
        assert lake.query("SELECT pid FROM patient").to_pylist() == [{"pid": expected}]


@pytest.mark.parametrize("first", ["backfill", "night"])
@pytest.mark.parametrize("form", ["unique", "per_day"])
def test_order_form(tmp_path: Path, first: str, form: str, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = ids._cfg(tmp_path, "ssmix2")
    storage = tmp_path / "ssmix"
    for chart in (ids.A, ids.B):
        monkeypatch.setattr(ss, "MRN", chart)
        ss._store(storage, "OML-11", "R7", ss.D1, ["OBR|1|R7", ss._obx(1, "6.0", ss.D1)])
    monkeypatch.setenv("TB_SSMIX2_ORDER_NUMBERS", "unique")
    if first == "backfill":
        history = backfill(cfg, "ssmix2", str(storage), snapshot=FIRST, rebuild_lake=False, validate=False)
        assert history.state == "published", history.errors
    else:
        assert ids.night(tmp_path, "ssmix2", {}, FIRST, ssmix2_root=storage).passed
    base = {r["id"] for r in ids.lake(tmp_path, FIRST)["Observation"]}
    assert len(base) == 2
    monkeypatch.setenv("TB_SSMIX2_ORDER_NUMBERS", form)
    day = SECOND
    # The order's day stays the same; its new transmission falls inside the delta window.
    for path in storage.rglob("*_1"):
        path.rename(path.with_name(path.name.replace("_20261001000000000_", "_20261003000000000_")))
    delta = ids.night(tmp_path, "ssmix2", {}, day, since=FIRST, ssmix2_root=storage)
    if form == "unique":
        assert delta.passed and {r["id"] for r in ids.lake(tmp_path, day)["Observation"]} == base
        return
    accepted = publish_held(cfg, day).ok if delta.held else delta.passed
    candidate = {r["id"] for r in ids.lake(tmp_path, day)["Observation"]}
    assert (delta.held, accepted, len(candidate), candidate.isdisjoint(base)) == (True, False, 2, True)


def test_by_day_chart_spelling(tmp_path: Path) -> None:
    from tests.unit import test_encounter_by_branch_patient_day as days

    visits = [days._visit("E1", "S", chart, FIRST) for chart in (ids.A, ids.B)]
    diags = [days._diag("D1", "S", chart, FIRST) for chart in (WIDE, ids.B)]
    _, got = days._run(tmp_path, visits, diags)
    key = b"k" * 32

    assert got["links"] == [
        f"Encounter/{patient_resource_id(key, 'Encounter', pid_for_mrn(key, c), 'E1')}" for c in (ids.A, ids.B)
    ]


@pytest.mark.parametrize("expr", [{"template": "{owner_ref}"}, {"const": f"Patient/{ids.PID[ids.A]}"}])
def test_site_device_owner(tmp_path: Path, expr: dict[str, str]) -> None:
    spec = {
        "type": "Device",
        "id": {"hid": "no", "site_wide": True},
        "table": "thing",
        "elements": {"patient.reference": expr},
    }
    with pytest.raises(MappingError):
        Mapping.load(ids._site(tmp_path, [spec]))


def test_historical_chart_spelling() -> None:
    # Only a one-way hash remains. No rule-2 night has ever seen the old chart spelling.
    _, mapper = ids._mapper()
    mapper.review = frozenset({("Consent", resource_id(ids.KEY, "Consent", " " + WIDE))})
    (consent,) = mapper.map_table("registry", iter(ids.canonical(ids.A)["registry"]))
    assert id_rule.REVIEW_TAG in consent.get("meta", {}).get("tag", [])


@pytest.mark.parametrize("mode", ["night", "backfill"])
def test_unresolved_chart_decision_preserves_history_and_withholds_candidates(
    tmp_path: Path, db_url: str, mode: str
) -> None:
    from omop import schema
    from omop.load import load_batch, set_status

    cfg = ids._cfg(tmp_path, "csv")
    cfg.lake_dir.mkdir()
    earlier = resource_id(ids.KEY, "Consent", " " + WIDE)
    prefs = cfg.lake_dir / id_rule.REVIEW
    id_rule.write_review(prefs, [("Consent", earlier, "rejected")])
    prior_list = prefs.read_bytes()
    with schema.connect(db_url, schema.schema_for(cfg.lake_dir)) as db:
        key = ("feed", "Consent", earlier, 0)
        load_batch(
            db,
            "feed",
            FIRST,
            {
                "Consent": [
                    {
                        "resourceType": "Consent",
                        "id": earlier,
                        "status": "active",
                        "patient": {"reference": "Patient/prior"},
                    }
                ]
            },
            tz="Asia/Taipei",
        )
        set_status(db, key, "rejected", by="steward", reason="synthetic review")
        # A kept decision under its historical source kind, in the very store that the night loads.
        db.execute(
            "UPDATE tb_record SET source_kind = 'feed:id_rule_1', cdm_table = NULL, record_id = NULL "
            "WHERE source_record_id = ?",
            (earlier,),
        )
        audit = (
            "SELECT e.* FROM tb_record_event e JOIN tb_record r USING(record_key) "
            "WHERE r.source_kind = 'feed:id_rule_1' ORDER BY event_id"
        )
        trail = db.fetchall(audit)
        assert trail
        rows = ids.both()
        if mode == "night":
            assert ids.night(tmp_path, "csv", rows, FIRST).passed
        else:
            feed = tmp_path / "feed"
            ids.write_csv(ids.CSV_SITE, feed, rows)
            assert (
                backfill(cfg, "csv", str(feed), snapshot=FIRST, validate=False, rebuild_lake=False).state == "published"
            )
        for source in SOURCES:
            assert not _tables(tmp_path, FIRST, source)["consent"]
        assert db.fetchall(audit) == trail
        assert db.fetchone("SELECT status FROM tb_record WHERE source_record_id = ?", (earlier,)) == ("rejected",)
    assert prefs.read_bytes() == prior_list
    candidates = ids.lake(tmp_path, FIRST)["Consent"]
    assert len(candidates) == 2 and all(id_rule.REVIEW_TAG in r["meta"]["tag"] for r in candidates)


@pytest.mark.parametrize("first", ["full", "backfill"])
def test_served_ids(tmp_path: Path, db_url: str, first: str) -> None:
    tables = ids.both()
    cfg = ids._cfg(tmp_path, "csv")
    if first == "backfill":
        feed = tmp_path / "history"
        ids.write_csv(ids.CSV_SITE, feed, tables)
        history = backfill(cfg, "csv", str(feed), snapshot=FIRST, validate=False, rebuild_lake=False)
        assert history.state == "published", history.errors
    else:
        assert ids.night(tmp_path, "csv", tables, FIRST).passed
    reference = ids.lake(tmp_path, FIRST)
    ids._check_each_patient_keeps_its_own(reference, first)
    for rows in tables.values():
        for row in rows:
            if row.get("mrn") == ids.A:
                row["mrn"] = WIDE
            if "updated_at" in row:
                row["updated_at"] = SECOND
    assert ids.night(tmp_path, "csv", tables, SECOND, since=FIRST).passed
    assert ids._ids(ids.lake(tmp_path, SECOND)) == ids._ids(reference)
    columns = {
        "encounter": ("Encounter", "eid"),
        "appointment": ("Appointment", "aid"),
        "condition": ("Condition", "cid"),
        "observation": ("Observation", "oid"),
        "medication": ("MedicationRequest", "mid"),
        "procedure": ("Procedure", "prid"),
        "report": ("DiagnosticReport", "rid"),
        "document": ("DocumentReference", "did"),
        "claim": ("Claim", "kid"),
        "consent": ("Consent", "consid"),
    }
    for day in (FIRST, SECOND):
        for source in SOURCES:
            projection = _tables(tmp_path, day, source)
            for table, (typ, col) in columns.items():
                got = {(r["pid"], r[col].split(".")[0]) for r in projection[table]}
                assert got == {(next(iter(ids.owner(r))), r["id"]) for r in reference[typ]}, (day, source, table)


@pytest.mark.parametrize("missing_form", [False, True], ids=["old-hold", "unstamped-base"])
def test_old_order_hold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing_form: bool) -> None:
    cfg = ids._cfg(tmp_path, "ssmix2")
    storage = tmp_path / "history"
    ss._store(storage, "OML-11", "R7", ss.D1, ["OBR|1|R7", ss._obx(1, "6.0", ss.D1)])
    monkeypatch.setenv("TB_SSMIX2_ORDER_NUMBERS", "unique")
    assert ids.night(tmp_path, "ssmix2", {}, FIRST, ssmix2_root=storage).passed
    folder = snapshot_dir(cfg.lake_dir, SECOND)
    if missing_form:
        record = snapshot_dir(cfg.lake_dir, FIRST) / id_rule.SNAPSHOT_RECORD
        metadata = json.loads(record.read_text())
        metadata.pop("keys")
        record.write_text(json.dumps(metadata))
        assert ids.night(tmp_path, "ssmix2", {}, SECOND, since=FIRST, ssmix2_root=storage).held
    else:
        # This pre-upgrade held folder already contains ids under both forms.
        folder.mkdir()
        id_rule.write_snapshot_record(folder)
        why = (
            f"delta night over snapshot {FIRST}, whose SS-MIX2 orders are keyed <number>; "
            "the reader keys them <number>@<day>"
        )
        (folder / "held.json").write_text(json.dumps({"snapshot": SECOND, "errors": [why]}))
    assert not publish_night(cfg, SECOND, folder).ok
    assert not publish_held(cfg, SECOND).ok
    assert not (folder / "passed.json").exists()


def test_device_owner_from_object(tmp_path: Path) -> None:
    # A $merge can populate patient without any dotted reference in elements.
    spec = {
        "type": "Device",
        "id": {"hid": "no", "site_wide": True},
        "table": "thing",
        "elements": {"$merge": {"const": {"patient": {"reference": f"Patient/{ids.PID[ids.A]}"}}}},
    }
    with pytest.raises(MappingError):
        _, mapper = ids._mapper(ids._site(tmp_path, [spec]))
        list(mapper.map_table("thing", iter([{"no": "D1"}])))


def test_retry_while_lake_reads(tmp_path: Path) -> None:
    from lake.store import SnapshotBuilding, building

    cfg = ids._cfg(tmp_path, "csv")
    folder = snapshot_dir(cfg.lake_dir, FIRST)
    folder.mkdir(parents=True)
    id_rule.write_snapshot_record(folder)
    old = folder / "Appointment.ndjson"
    old.write_text(json.dumps({"resourceType": "Appointment", "id": "synthetic"}) + "\n")
    with building(cfg.lake_dir, FIRST), pytest.raises(SnapshotBuilding):
        ids.night(tmp_path, "csv", {"patient": ids.both()["patient"]}, FIRST)
    assert old.exists() and not (folder / "passed.json").exists()


def test_two_identical_clinical_rows_of_a_shared_chart_both_reach_review() -> None:
    _, mapper = ids._mapper()
    patients = ids.both()["patient"]
    patients[1]["mrn"] = patients[0]["mrn"]
    list(mapper.map_table("patient", iter(patients)))
    row = ids.canonical(ids.A)["diagnosis"][0]
    records = list(mapper.map_table("diagnosis", iter([row, row])))
    assert len({record["id"] for record in records}) == 2
    assert all(id_rule.REVIEW_TAG in record["meta"]["tag"] for record in records)


def test_shared_chart_on_delta_withholds_already_screened_records(tmp_path: Path, db_url: str) -> None:
    rows = ids.canonical(ids.A)
    assert ids.night(tmp_path, "csv", rows, FIRST).passed
    for source in SOURCES:
        assert _tables(tmp_path, FIRST, source)["condition"]
    # Only the patient catalogue changes. Last night's diagnosis is still in the merged snapshot.
    rows["patient"].append({**ids.canonical(ids.B)["patient"][0], "mrn": ids.A})
    assert ids.night(tmp_path, "csv", rows, SECOND, since=FIRST).passed
    carried = ids.lake(tmp_path, SECOND)["Condition"]
    assert carried and all(id_rule.REVIEW_TAG in r["meta"]["tag"] for r in carried)
    assert {("Condition", r["id"]) for r in carried} <= id_rule.read_review(tmp_path / "lake")
    for source in SOURCES:
        assert all(not rr for t, rr in _tables(tmp_path, SECOND, source).items() if t != "practitioner")
    third = "2026-10-03"
    # The disputed chart remains listed on a fresh feed. Its candidate IDs never become decisions about B.
    assert ids.night(tmp_path, "csv", ids.both(), third).passed
    for source in SOURCES:
        clear = _tables(tmp_path, third, source)
        assert len(clear["patient"]) == len(clear["consent"]) == 1
        assert clear["patient"][0]["pid"] == pid_for_mrn(ids.KEY, ids.B)


def test_a_chart_reference_in_free_text_does_not_withhold_another_patient(tmp_path: Path) -> None:
    from adapter.ndjson import read_type, write_snapshot

    baseline = tmp_path / "first"
    clear = {
        "resourceType": "Condition",
        "id": "clear",
        "subject": {"reference": "Patient/other"},
        "code": {"text": "Patient/disputed"},
    }
    write_snapshot(baseline, {"Condition": [clear]})
    write_snapshot(tmp_path / "next", {}, baseline, shared_charts={"disputed"})
    assert list(read_type(tmp_path / "next", "Condition")) == [clear]


@pytest.mark.parametrize("mode", ["night", "backfill"])
@pytest.mark.parametrize("refresh", [FIRST, SECOND], ids=["same-night", "next-night"])
def test_full_night_replaces_a_screened_chart_with_review_records(
    tmp_path: Path, db_url: str, mode: str, refresh: str
) -> None:
    assert ids.night(tmp_path, "csv", ids.canonical(ids.A), FIRST).passed
    for source in SOURCES:
        assert _tables(tmp_path, FIRST, source)["condition"]
    rows = ids.both()
    rows["patient"].append({**rows["patient"][1], "mrn": ids.A})
    cfg = ids._cfg(tmp_path, "csv")
    feed = tmp_path / "refresh-feed"
    ids.write_csv(ids.CSV_SITE, feed, rows)
    if mode == "night":
        lake = Lake(cfg.lake_dir, cfg.tz)

        def rebuild(snap: str, folder: Path) -> RebuildResult:
            return RebuildResult.model_validate(lake.rebuild(snap, HashEmbedder(), folder), from_attributes=True)

        cfg.rebuild = rebuild
        report = run_ingest(cfg, "csv", str(feed), snapshot=refresh, validate=False, load_fhir=False)
        assert report.passed, report.errors
    else:
        result = backfill(cfg, "csv", str(feed), snapshot=refresh, validate=False, rebuild_lake=False)
        assert result.state == "published", result.errors
    for source in SOURCES:
        projected = _tables(tmp_path, refresh, source)
        assert {r["pid"] for r in projected["patient"]} == {pid_for_mrn(ids.KEY, ids.B)}
        assert {r["pid"] for r in projected["condition"]} == {pid_for_mrn(ids.KEY, ids.B)}
