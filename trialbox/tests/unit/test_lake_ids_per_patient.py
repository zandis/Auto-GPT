"""D-1253: a lake id of a resource that belongs to a patient is that patient's; one patient's record never takes
another's place.

A record's id was ``HMAC(site key, "<type>|<number>")``: the patient was not in it. Hospital systems reuse such
numbers across patients (an SS-MIX2 order number is unique per patient, day and data type only), so two patients'
order "RX1" were one id: the lake kept one MedicationRequest, under the second patient, and the first patient's was
gone with no error and no count; a tombstone for one deleted the other's, and a reference by number (a diagnosis's
visit, a claim's response) could name another patient's record.

Here two synthetic patients share every number (visit, booking, diagnosis, lab, vital, order, procedure, report,
note, claim) through every door that reads the shared resource definitions (``tw_core/demo_his.yaml``): the CSV and
SQL site templates and SS-MIX2 (``jp_core/ssmix2_site.yaml``), each through ``run_ingest`` to the lake, a full night
and a delta night. Synthetic rows only."""

from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
import yaml
from adapter.mapping.engine import Mapper, Mapping, MappingError
from adapter.ndjson import read_type, snapshot_dir
from adapter.pipeline import AdapterConfig, bulk_id, pseudonymise_bulk, run_ingest
from tb_common.crypto import pid_for_mrn

ROOT = Path(__file__).resolve().parents[2]
MAPPINGS = ROOT / "services/adapter/mapping"
BASE = MAPPINGS / "tw_core/demo_his.yaml"
CSV_SITE = MAPPINGS / "templates/csv_site.yaml"
SQL_SITE = MAPPINGS / "templates/cgrd_sql_site.yaml"
SSMIX2_SITE = MAPPINGS / "jp_core/ssmix2_site.yaml"
KEY = b"synthetic site key for D-1253 tests only"
A, B = "10000001", "10000002"
DAY = {A: "2026-09-01", B: "2026-09-02"}  # every date of a patient's rows: what makes a record recognisably its own
#: the record types the shared definitions make with an ``hid`` id: every one belongs to a patient
PATIENT_OWNED = (
    "Encounter", "Appointment", "Condition", "Observation", "MedicationRequest", "Procedure", "DiagnosticReport",
    "DocumentReference", "Claim", "ClaimResponse", "Coverage", "Consent",
)  # fmt: skip
NOT_A_PATIENTS = {"Patient", "Practitioner", "Organization", "Location"}


# ------------------------------------------------------------------------------------------------ the feed
def canonical(mrn: str, *, lab_value: str | None = None) -> dict[str, list[dict[str, str]]]:
    """One patient's rows under the canonical column names (``templates/CANONICAL.md``), every number the same as
    the other patient's, every date the patient's own day."""
    d = DAY[mrn]
    other = mrn == B
    return {
        "patient": [{"mrn": mrn, "name": f"Synthetic {mrn[-1]}", "id_no": f"X{mrn}", "birth_date": "1960-01-01",
                     "sex": "F" if other else "M", "death_date": ""}],
        "practitioner": [{"staff_id": "S1", "name": "Synthetic Doctor", "dept_code": "MED"}],
        "encounter": [{"enc_no": "E1", "mrn": mrn, "visit_datetime": f"{d} 09:00:00", "dept_code": "MED",
                       "staff_id": "S1", "enc_type": "OPD", "updated_at": d}],
        "appointment": [{"appt_no": "AP1", "mrn": mrn, "appt_datetime": f"{d} 10:00:00", "duration_min": "15",
                         "staff_id": "S1", "dept_code": "MED", "status": "B"}],
        "diagnosis": [{"diag_no": "DX001", "enc_no": "E1", "mrn": mrn, "icd10": "E11.9" if other else "M10.9",
                       "diag_date": d, "recorded_date": d, "status": "A", "updated_at": d}],
        "lab": [{"lab_no": "L1", "mrn": mrn, "local_code": "CRE" if other else "UA", "item_name": "lab",
                 "result_value": lab_value or ("1.1" if other else "7.5"), "unit": "mg/dL",
                 "sample_datetime": f"{d} 08:00:00", "updated_at": d}],
        "vital": [{"vital_no": "V1", "enc_no": "E1", "mrn": mrn, "measure_datetime": f"{d} 08:30:00",
                   "height_cm": "150" if other else "170", "weight_kg": "50" if other else "70", "sbp": "120",
                   "dbp": "80", "updated_at": d}],
        "medication": [{"rx_no": "RX1", "enc_no": "E1", "mrn": mrn, "nhi_drug_code": "A000000100",
                        "atc": "A10BA02" if other else "M04AA01", "drug_name": "drug", "order_date": d,
                        "start_date": d, "end_date": d, "daily_dose": "1", "dose_unit": "tab", "status": "active",
                        "dept_code": "MED", "updated_at": d}],
        "procedure": [{"proc_no": "P1", "mrn": mrn, "order_code": "PX2" if other else "PX1", "proc_name": "proc",
                       "proc_date": d, "updated_at": d}],
        "report": [{"rpt_no": "R1", "mrn": mrn, "exam_code": "RAD-CXR", "exam_name": "chest X-ray",
                    "exam_date": d, "conclusion": "synthetic finding B" if other else "synthetic finding A",
                    "updated_at": d}],
        "note": [{"note_no": "N1", "mrn": mrn, "enc_no": "E1", "note_datetime": f"{d} 11:00:00",
                  "note_type": "progress", "text": f"synthetic note of {mrn}", "updated_at": d}],
        "claim": [{"claim_no": "C1", "mrn": mrn, "created_date": d, "product_code": "A000000100",
                   "apply_type": "1", "outcome": "approved", "approval_start": d, "approval_end": d,
                   "updated_at": d}],
        "registry": [{"mrn": mrn, "consent_contact": "Y", "consent_date": d}],
    }  # fmt: skip


def both(**kw: Any) -> dict[str, list[dict[str, str]]]:
    a, b = canonical(A, **kw), canonical(B, **kw)
    out = {t: a[t] + b[t] for t in a}
    out["practitioner"] = a["practitioner"]  # one clinician of the site, not one per patient
    return out


def _as_source(mapping: Path, table: str, rows: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
    """The site's own table name and column names and codes for canonical rows (the mapping's ``rename`` and
    ``values`` turned round)."""
    doc = yaml.safe_load(mapping.read_text(encoding="utf-8"))
    spec = (doc.get("tables") or {})[table]
    back = {canon: src for src, canon in (spec.get("rename") or {}).items()}
    codes = {col: {canon: src for src, canon in m.items()} for col, m in (spec.get("values") or {}).items()}
    out = []
    for r in rows:
        out.append({back.get(k, k): codes.get(k, {}).get(v, v) for k, v in r.items()})
    return str(spec.get("source") or table), out


def write_csv(mapping: Path, feed: Path, tables: dict[str, list[dict[str, str]]]) -> None:
    feed.mkdir(parents=True, exist_ok=True)
    for table, rows in tables.items():
        name, src = _as_source(mapping, table, rows)
        cols = list(dict.fromkeys(k for r in src for k in r))
        with (feed / f"{name}.csv").open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(src)


CREATE = "CREATE TABLE {} ({})"  # a synthetic source table: its name and columns quoted as identifiers
INSERT = "INSERT INTO {} VALUES ({})"


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def write_sql(mapping: Path, db: Path, tables: dict[str, list[dict[str, str]]]) -> str:
    db.unlink(missing_ok=True)
    con = sqlite3.connect(db)
    for table, rows in tables.items():
        name, src = _as_source(mapping, table, rows)
        cols = list(dict.fromkeys(k for r in src for k in r))
        con.execute(CREATE.format(_ident(name), ", ".join(f"{_ident(c)} TEXT" for c in cols)))
        con.executemany(INSERT.format(_ident(name), ", ".join("?" for _ in cols)),
                        [[r.get(c, "") for c in cols] for r in src])  # fmt: skip
    con.commit()
    con.close()
    return f"sqlite:///{db}"


def write_ssmix2(work: Path, tables: dict[str, list[dict[str, str]]]) -> Path:
    from tools.ssmix2_export import export

    hospital = work / "hospital"
    write_csv(BASE, hospital, tables)
    root = work / "storage"
    export(hospital, root)
    return root


# ------------------------------------------------------------------------------------------------ a night
DOORS = ("csv", "sql", "ssmix2")
SITE = {"csv": CSV_SITE, "sql": SQL_SITE, "ssmix2": SSMIX2_SITE}


def _placed(tmp: Path, door: str) -> Path:
    """A template as a site places it beside the base mapping (its look-up files are the base's)."""
    if door == "ssmix2":
        return SITE[door]
    doc = yaml.safe_load(SITE[door].read_text(encoding="utf-8"))
    doc["extends"] = str(BASE)
    doc["lookups"] = {"lab": {"file": str(BASE.parent / "lab_local_to_loinc.csv"), "key": "local_code"}}
    path = tmp / f"{door}_site.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _cfg(tmp: Path, door: str) -> AdapterConfig:
    tmp.mkdir(parents=True, exist_ok=True)
    sec = tmp / "secrets"
    sec.mkdir(exist_ok=True)
    (sec / "site_hmac.key").write_bytes(KEY)
    (sec / "site_hmac.key").chmod(0o600)
    return AdapterConfig(lake_dir=tmp / "lake", secrets_dir=sec, mapping_path=_placed(tmp, door), site_id="T",
                         tz="Asia/Tokyo" if door == "ssmix2" else "Asia/Taipei", audit_dir=tmp / "audit",
                         validation_max_pct=100.0)  # fmt: skip


def night(tmp: Path, door: str, tables: dict[str, list[dict[str, str]]], snap: str, since: str | None = None,
          ssmix2_root: Path | None = None) -> Any:  # fmt: skip
    cfg = _cfg(tmp, door)
    work = tmp / f"feed-{snap}"
    if door == "csv":
        write_csv(CSV_SITE, work, tables)
        where = str(work)
        kind = "csv"
    elif door == "sql":
        work.mkdir(parents=True, exist_ok=True)
        where = write_sql(SQL_SITE, work / "his.db", tables)
        kind = "cgrd_sql"
    else:
        where = str(ssmix2_root or write_ssmix2(work, tables))
        kind = "ssmix2"
    return run_ingest(cfg, kind, where, snapshot=snap, since=since, load_fhir=False, rebuild_lake=False,
                      validate=False)  # fmt: skip


def lake(tmp: Path, snap: str) -> dict[str, list[dict[str, Any]]]:
    folder = snapshot_dir(tmp / "lake", snap)
    return {p.stem: list(read_type(folder, p.stem)) for p in sorted(folder.glob("*.ndjson"))}


def owner(res: dict[str, Any]) -> set[str]:
    """The patients a record names (its subject, patient, beneficiary or participant)."""
    text = json.dumps(res)
    return {pid for pid in PIDS if f"Patient/{pid}" in text}


PIDS = {pid_for_mrn(KEY, A): A, pid_for_mrn(KEY, B): B}
PID = {mrn: pid for pid, mrn in PIDS.items()}


def per_patient(records: dict[str, list[dict[str, Any]]], rtype: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {A: [], B: []}
    for r in records.get(rtype, []):
        names = owner(r)
        assert len(names) == 1, f"{rtype}/{r['id']} names {len(names)} patients"
        out[PIDS[next(iter(names))]].append(r)
    return out


def _check_each_patient_keeps_its_own(records: dict[str, list[dict[str, Any]]], door: str) -> None:
    for rtype in PATIENT_OWNED:
        mine = per_patient(records, rtype)
        assert mine[A] and len(mine[A]) == len(mine[B]), (
            f"{door}: {rtype}: patient A has {len(mine[A])}, patient B {len(mine[B])}"
        )
        assert not {r["id"] for r in mine[A]} & {r["id"] for r in mine[B]}, f"{door}: {rtype}: one id, two patients"
        for mrn, other in ((A, B), (B, A)):
            for r in mine[mrn]:
                text = json.dumps(r)
                assert DAY[other] not in text, f"{door}: {rtype} of {mrn} holds the other patient's content"


def _check_references_stay_with_their_patient(records: dict[str, list[dict[str, Any]]], door: str) -> int:
    index = {(t, r["id"]): r for t, rs in records.items() for r in rs}
    seen = 0
    for rtype, rs in records.items():
        for r in rs:
            for ref in _references(r):
                t, _, rid = ref.partition("/")
                if t in NOT_A_PATIENTS:
                    continue
                target = index.get((t, rid))
                assert target is not None, f"{door}: {rtype}/{r['id']} -> {ref}: no such record"
                assert owner(target) == owner(r), f"{door}: {rtype} of one patient names {t} of another"
                seen += 1
    return seen


def _references(node: Any) -> list[str]:
    if isinstance(node, dict):
        out = [v for k, v in node.items() if k == "reference" and isinstance(v, str)]
        for k, v in node.items():
            if k != "reference":
                out += _references(v)
        return out
    if isinstance(node, list):
        return [x for v in node for x in _references(v)]
    return []


# ------------------------------------------------------------------------------------------------ the full night
@pytest.mark.parametrize("door", DOORS)
def test_two_patients_sharing_every_number_keep_two_records_each_their_own(tmp_path: Path, door: str) -> None:
    rep = night(tmp_path, door, both(), "2026-10-01")
    assert not rep.errors, rep.errors
    records = lake(tmp_path, "2026-10-01")
    _check_each_patient_keeps_its_own(records, door)
    # the visit of a diagnosis, an order, a note; the claim of a response; the coverage of a claim (an SS-MIX2 order
    # message names no visit: four there)
    assert _check_references_stay_with_their_patient(records, door) == 2 * (4 if door == "ssmix2" else 5)


@pytest.mark.parametrize("door", DOORS)
def test_one_patients_feed_alone_gives_what_it_gives_beside_another(tmp_path: Path, door: str) -> None:
    """The same numbers beside another patient change nothing of a patient's records: as many, and their content."""
    night(tmp_path / "alone", door, {t: rs for t, rs in canonical(A).items()}, "2026-10-01")
    night(tmp_path / "both", door, both(), "2026-10-01")
    alone, two = lake(tmp_path / "alone", "2026-10-01"), lake(tmp_path / "both", "2026-10-01")
    for rtype in PATIENT_OWNED:
        assert sorted(r["id"] for r in alone.get(rtype, [])) == sorted(r["id"] for r in per_patient(two, rtype)[A])


# ------------------------------------------------------------------------------------------------ the delta night
@pytest.fixture(autouse=True)
def _one_of_two_may_go(monkeypatch: pytest.MonkeyPatch) -> None:
    """One record of two leaving is what these nights do (D-271's limit is about whole extracts going missing)."""
    monkeypatch.setenv("TB_FEED_MAX_DROP_PCT", "100")


def _deleted(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{**r, "deleted": "1"} for r in rows]


@pytest.mark.parametrize("door", ("csv", "sql"))
def test_a_tombstone_for_one_patients_record_leaves_the_others(tmp_path: Path, door: str) -> None:
    night(tmp_path, door, both(), "2026-10-01")
    first = lake(tmp_path, "2026-10-01")
    # the next night: patient A's diagnosis DX001 deleted at the hospital; patient B's lab L1 corrected
    a, b = canonical(A), canonical(B, lab_value="2.2")
    delta = both()  # every table, as an export gives it; only the two changed rows are newer than the last night
    delta["diagnosis"] = [{**_deleted(a["diagnosis"])[0], "updated_at": "2026-10-02"}, b["diagnosis"][0]]
    delta["lab"] = [a["lab"][0], {**b["lab"][0], "updated_at": "2026-10-02"}]
    rep = night(tmp_path, door, delta, "2026-10-02", since="2026-10-01")
    assert not rep.errors, rep.errors
    second = lake(tmp_path, "2026-10-02")
    cond = per_patient(second, "Condition")
    assert not cond[A] and len(cond[B]) == 1, (len(cond[A]), len(cond[B]))
    assert cond[B][0] == per_patient(first, "Condition")[B][0]
    labs = per_patient(second, "Observation")
    lab_a = [r for r in labs[A] if "valueQuantity" in r and r.get("category", [{}])[0].get("coding", [{}])[0]
             .get("code") == "laboratory"]  # fmt: skip
    lab_b = [r for r in labs[B] if "valueQuantity" in r and r.get("category", [{}])[0].get("coding", [{}])[0]
             .get("code") == "laboratory"]  # fmt: skip
    assert [r["valueQuantity"]["value"] for r in lab_a] == [7.5]
    assert [r["valueQuantity"]["value"] for r in lab_b] == [2.2]
    _check_references_stay_with_their_patient(second, door)


def test_an_ssmix2_delete_of_one_patients_order_leaves_the_others(tmp_path: Path) -> None:
    """SS-MIX2: the newest version of patient A's diagnosis DX001 carries flag 0 (deleted at the hospital)."""
    from adapter.sources.ssmix2.source import storage_dir

    root = write_ssmix2(tmp_path / "feed", both())
    night(tmp_path, "ssmix2", {}, "2026-10-01", ssmix2_root=root)
    (live,) = list(storage_dir(root, A, "20260901", "PPR-01").glob(f"{A}_20260901_PPR-01_DX001_*_1"))
    gone = live.with_name(live.name.replace("_20261101000000000_", "_20261102000000000_")[:-1] + "0")
    gone.write_bytes(live.read_bytes())
    rep = night(tmp_path, "ssmix2", {}, "2026-10-02", since="2026-10-01", ssmix2_root=root)
    assert not rep.errors, rep.errors
    second = lake(tmp_path, "2026-10-02")
    cond = per_patient(second, "Condition")
    assert not cond[A] and len(cond[B]) == 1, (len(cond[A]), len(cond[B]))
    for rtype in (t for t in PATIENT_OWNED if t != "Condition"):
        mine = per_patient(second, rtype)
        assert mine[A] and len(mine[A]) == len(mine[B]), rtype


@pytest.mark.parametrize("door", ("csv", "sql"))
def test_a_delta_night_resending_both_patients_keeps_both(tmp_path: Path, door: str) -> None:
    night(tmp_path, door, both(), "2026-10-01")
    again = both()
    for rows in again.values():
        for r in rows:
            if "updated_at" in r:
                r["updated_at"] = "2026-10-02"
    rep = night(tmp_path, door, again, "2026-10-02", since="2026-10-01")
    assert not rep.errors, rep.errors
    _check_each_patient_keeps_its_own(lake(tmp_path, "2026-10-02"), door)


def _merge_a_into_b(tmp: Path) -> None:
    pm = _cfg(tmp, "csv").pidmap()
    try:
        pm.merge(KEY, A, B, "synthetic merge", "T-1")
    finally:
        pm.close()


def _ids(records: dict[str, list[dict[str, Any]]]) -> dict[str, list[str]]:
    return {t: sorted(str(r["id"]) for r in rs) for t, rs in records.items()}


@pytest.mark.parametrize("since", [None, "2026-10-01"], ids=["full", "delta"])
def test_a_merged_chart_keeps_its_records_under_its_own_ids_now_the_surviving_patients(
    tmp_path: Path, since: str | None
) -> None:
    """D-1253 review C: chart A merged into chart B (``pidmap.merge``). Both charts had a visit E1, a diagnosis
    DX001 and so on. After the merge every record of A names patient B, and none takes B's record's place: the ids
    stay made under the chart that sent the row (the Patient's pid derives from the chart number the same way),
    so a full night and a delta night after the merge hold the same records (the full NEW-B-36 comparison:
    ``tests/unit/test_delta_night_chart_merge.py``)."""
    from adapter.mapping.engine import patient_resource_id

    night(tmp_path, "csv", both(), "2026-10-01")
    _merge_a_into_b(tmp_path)
    again = both()
    if since:
        for rows in again.values():
            for r in rows:
                if "updated_at" in r:
                    r["updated_at"] = "2026-10-02"
    rep = night(tmp_path, "csv", again, "2026-10-02", since=since)
    assert not rep.errors, rep.errors
    held = lake(tmp_path, "2026-10-02")
    assert [p["id"] for p in held["Patient"]] == [PID[B]]
    visits = sorted(e["id"] for e in held["Encounter"])
    assert visits == sorted(patient_resource_id(KEY, "Encounter", PID[m], "E1") for m in (A, B))
    assert all(owner(r) == {PID[B]} for t in PATIENT_OWNED for r in held.get(t, []))
    assert all(PID[A] not in json.dumps(r) for rs in held.values() for r in rs)


def test_a_record_re_filed_to_another_chart_is_corrected_by_the_next_full_night_not_by_a_delta(tmp_path: Path) -> None:
    """The stated limit (D-1253 round 3; ``unique: site`` is no choice): a record the hospital re-files from chart A
    to chart B is a new record of B. A delta night does not see that A's copy left (the delta sends changed rows
    only), so the lake holds both until the next full night, which holds B's only. Pinned, not hidden: the night
    deletes and links within one patient only, so A's stale copy never takes B's place or B's links."""
    moved = canonical(A)
    moved["diagnosis"] = []
    to_b = canonical(B)
    rows = {t: moved[t] + (to_b[t] if t in ("patient", "diagnosis") else []) for t in moved}
    night(tmp_path, "csv", canonical(A), "2026-10-01")
    delta = {t: (to_b[t] if t in ("patient", "diagnosis") else []) for t in moved}
    for r in delta["diagnosis"]:
        r["updated_at"] = "2026-10-02"  # changed at the source: a delta sends it
    rep = night(tmp_path, "csv", delta, "2026-10-02", since="2026-10-01")
    assert not rep.errors, rep.errors
    stale = lake(tmp_path, "2026-10-02")["Condition"]
    assert sorted(min(owner(c)) for c in stale) == sorted([PID[A], PID[B]])  # A's stale copy and B's, each its own
    assert all(len(owner(c)) == 1 for c in stale)
    night(tmp_path, "csv", rows, "2026-10-03")
    conditions = lake(tmp_path, "2026-10-03")["Condition"]
    assert [owner(c) for c in conditions] == [{PID[B]}]


# ------------------------------------------------------------------------------------------------ the mapper's rule
def _mapper(path: Path = BASE) -> tuple[Mapping, Mapper]:
    m = Mapping.load(path)
    return m, Mapper(m, KEY, "T")


@pytest.mark.parametrize("visits_first", [True, False])
def test_a_reference_by_number_is_always_the_rows_own_patients_record_in_any_order(visits_first: bool) -> None:
    """Patient A's diagnosis names visit E1, and E1 is only patient B's visit: the link is to A's E1, whatever order
    the tables come in, and never to B's visit (it is a link to a record the lake does not hold, counted by the night
    over the merged snapshot: :func:`test_a_link_to_a_record_not_in_the_lake_is_counted_over_the_merged_snapshot`)."""
    from adapter.mapping.engine import patient_resource_id

    _m, mp = _mapper()
    enc_b, diag_a = canonical(B)["encounter"][0], canonical(A)["diagnosis"][0]
    if visits_first:
        (visit,) = [r for r in mp.map_table("encounter", iter([enc_b])) if r["resourceType"] == "Encounter"]
    (cond,) = [r for r in mp.map_table("diagnosis", iter([diag_a])) if r["resourceType"] == "Condition"]
    if not visits_first:
        (visit,) = [r for r in mp.map_table("encounter", iter([enc_b])) if r["resourceType"] == "Encounter"]
    assert cond["encounter"]["reference"] == f"Encounter/{patient_resource_id(KEY, 'Encounter', PID[A], 'E1')}"
    assert cond["encounter"]["reference"] != f"Encounter/{visit['id']}"


def test_a_link_to_a_record_not_in_the_lake_is_counted_over_the_merged_snapshot(tmp_path: Path) -> None:
    """Order-free: the night counts, over the merged snapshot, each link to a patient's record it does not hold, per
    source table and type; a delta night whose visit came an earlier night links and counts nothing."""
    rows = canonical(A)
    rows["encounter"] = []  # A's diagnosis, order and note name visit E1, which the feed never sent for A
    night(tmp_path, "csv", rows, "2026-10-01")
    comp = json.loads((snapshot_dir(tmp_path / "lake", "2026-10-01") / "completeness.json").read_text())
    assert comp["links_to_absent_records"] == {"diagnosis": {"Encounter": 1}, "medication": {"Encounter": 1},
                                               "note": {"Encounter": 1}}  # fmt: skip
    full = canonical(A)
    night(tmp_path / "b", "csv", full, "2026-10-01")  # the visit on the first night
    late = canonical(A)
    for t in late:
        if t != "patient":
            late[t] = [{**r, "updated_at": "2026-10-02"} for r in late[t]] if t != "encounter" else full[t]
    night(tmp_path / "b", "csv", late, "2026-10-02", since="2026-10-01")
    comp = json.loads((snapshot_dir(tmp_path / "b" / "lake", "2026-10-02") / "completeness.json").read_text())
    assert "links_to_absent_records" not in comp


def test_a_row_whose_patient_cannot_be_derived_is_refused_never_given_a_shared_id() -> None:
    _m, mp = _mapper()
    row = {**canonical(A)["diagnosis"][0], "mrn": ""}
    with pytest.raises(MappingError, match="no patient"):
        list(mp.map_table("diagnosis", iter([row])))


def test_a_tombstone_row_without_its_patient_removes_nothing_and_is_counted() -> None:
    _m, mp = _mapper()
    assert list(mp.tombstones("diagnosis", iter([{"diag_no": "DX001", "deleted": "1"}]))) == []
    assert mp.tombstones_without_patient() == {"diagnosis": 1}


def _site(tmp_path: Path, resources: list[dict[str, Any]]) -> Path:
    doc = {"version": 1, "name": "s", "tz": "Asia/Taipei",
           "tables": {"patient": {"source": "patient", "key": "mrn"},
                      "practitioner": {"source": "practitioner", "key": "staff_id"},
                      "thing": {"source": "thing", "key": "no"}},
           "resources": resources}  # fmt: skip
    path = tmp_path / "m.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


def test_a_mapping_cannot_forget_the_patient_of_an_hid_id(tmp_path: Path) -> None:
    """An ``hid`` id on a record with no patient in it, and not declared site-wide, is refused at load."""
    path = _site(tmp_path, [{"type": "Procedure", "table": "thing", "id": {"hid": "no"},
                             "elements": {"status": {"const": "completed"}}}])  # fmt: skip
    with pytest.raises(MappingError, match="patient"):
        Mapping.load(path)


def test_a_site_wide_hid_id_is_declared_and_only_for_a_record_of_no_patient(tmp_path: Path) -> None:
    ok = _site(tmp_path, [{"type": "Location", "table": "thing", "id": {"hid": "no", "site_wide": True},
                           "elements": {"name": {"column": "name"}}}])  # fmt: skip
    _m, mp = _mapper(Mapping.load(ok).path)
    (loc,) = list(mp.map_table("thing", iter([{"no": "W1", "name": "ward"}])))
    from adapter.mapping.engine import resource_id

    assert loc["id"] == resource_id(KEY, "Location", "W1")
    bad = _site(tmp_path, [{"type": "Condition", "table": "thing", "id": {"hid": "no", "site_wide": True},
                            "elements": {"subject.reference": {"ref": {"type": "Patient", "pid": "mrn"}}}}])  # fmt: skip
    with pytest.raises(MappingError, match="site.wide"):
        Mapping.load(bad)


SUBJECT = {"subject.reference": {"ref": {"type": "Patient", "pid": "mrn"}}}
STAFF = {"performer.reference": {"ref": {"type": "Practitioner", "hid": "staff_id"}}}


@pytest.mark.parametrize(
    ("resources", "words"),
    [
        # a raw source number as a patient's record id: two patients with one number would be one record
        ([{"type": "Condition", "table": "thing", "id": {"column": "no"}, "elements": SUBJECT}], "column"),
        # an id made by a template (no form of id carries the patient through one)
        ([{"type": "Condition", "table": "thing", "id": {"template": "{mrn}-{no}"}, "elements": SUBJECT}], "one of"),
        # id.patient that is not a chart number of a patient the record names (a clinician's id)
        ([{"type": "Condition", "table": "thing", "id": {"hid": "no", "patient": "staff_id"},
           "elements": {**SUBJECT, **STAFF}}], "not a chart number"),
        # a record of no patient (site-wide) that names a patient's record by number
        ([{"type": "Location", "table": "thing", "id": {"hid": "no", "site_wide": True},
           "elements": {"partOf.reference": {"ref": {"type": "Encounter", "hid": "enc_no"}}}}], "names no patient"),
        # a clinician is no patient's: its hid id says site-wide
        ([{"type": "Practitioner", "table": "practitioner", "id": {"hid": "staff_id"},
           "elements": {"name": {"column": "name"}}}], "site-wide"),
        # a drug declared site-wide that a patient's order names by number (its record is per order)
        ([{"type": "Medication", "table": "thing", "id": {"hid": "no", "site_wide": True},
           "elements": {"code.text": {"column": "name"}}},
          {"type": "MedicationRequest", "table": "thing", "id": {"hid": "no"},
           "elements": {**SUBJECT, "medicationReference.reference": {"ref": {"type": "Medication", "hid": "no"}}}}],
         "declares site-wide"),
        # one type, two id rules
        ([{"type": "Device", "table": "thing", "id": {"hid": "no", "site_wide": True}, "elements": {}},
          {"type": "Device", "table": "thing", "id": {"hid": "no2"}, "elements": SUBJECT}], "id rules"),
        # a suffix that would blur the parts of the HMAC input
        ([{"type": "Condition", "table": "thing", "id": {"hid": "no", "suffix": "a|b"}, "elements": SUBJECT}], "suffix"),
        # round 3: unique is no choice at all (a site-wide id of a patient's record lets a delete, a link and a
        # suffix reach another patient's record)
        ([{"type": "Condition", "table": "thing", "id": {"hid": "no", "unique": "site"}, "elements": SUBJECT}],
         "not a choice"),
        ([{"type": "Encounter", "table": "thing", "id": {"hid": "no", "unique": "site"}, "elements": SUBJECT}],
         "not a choice"),
        # round 3: a site-wide id has no suffix, nor does a link to one
        ([{"type": "Location", "table": "thing", "id": {"hid": "no", "site_wide": True, "suffix": "-W"},
           "elements": {}}], "no suffix"),
        ([{"type": "Location", "table": "practitioner", "id": {"hid": "staff_id", "site_wide": True}, "elements": {}},
          {"type": "Encounter", "table": "thing", "id": {"hid": "no"},
           "elements": {**SUBJECT, "location.0.location.reference": {"ref": {"type": "Location", "hid": "ward",
                                                                              "suffix": "-W"}}}}], "no suffix"),
    ],
    ids=["column", "template", "patient-not-named", "site-names-patient-record", "practitioner", "site-drug-per-order",
         "two-rules", "suffix", "unique-site", "unique-site-encounter", "site-wide-suffix", "site-wide-link-suffix"],
)  # fmt: skip
def test_a_mapping_that_would_let_two_patients_share_an_id_is_refused_at_load(
    tmp_path: Path, resources: list[dict[str, Any]], words: str
) -> None:
    """D-1253 review D: every form that would give a patient's record an id without its patient is refused when the
    mapping loads, with words that say which."""
    with pytest.raises(MappingError, match=words):
        Mapping.load(_site(tmp_path, resources))


def test_a_device_or_drug_that_names_its_patient_has_its_patients_id(tmp_path: Path) -> None:
    """A Medication or Device of one patient's order (it names the patient) has a per-patient hid id; one of no
    patient, that no patient's record names by number, may be declared site-wide."""
    from adapter.mapping.engine import patient_resource_id, resource_id

    path = _site(tmp_path, [
        {"type": "Device", "table": "thing", "id": {"hid": "no"}, "elements": SUBJECT},
        {"type": "Medication", "table": "thing", "id": {"hid": "drug", "site_wide": True},
         "elements": {"code.text": {"column": "name"}}},
    ])  # fmt: skip
    _m, mp = _mapper(path)
    out = list(mp.map_table("thing", iter([{"no": "D1", "drug": "M1", "name": "x", "mrn": A}])))
    ids = {r["resourceType"]: r["id"] for r in out}
    assert ids["Device"] == patient_resource_id(KEY, "Device", PID[A], "D1")
    assert ids["Medication"] == resource_id(KEY, "Medication", "M1")


def test_a_suffix_has_its_own_part_and_never_equals_a_plain_number() -> None:
    """``<type>|<pid>|<suffix>|<number>``: number "1" with suffix "a" is not number "a1" (nor "1a") without one."""
    from adapter.mapping.engine import patient_resource_id

    pid = PID[A]
    with_suffix = patient_resource_id(KEY, "Observation", pid, "1", "a")
    assert with_suffix not in {patient_resource_id(KEY, "Observation", pid, v) for v in ("a1", "1a", "a|1", "1")}


def test_two_rows_of_one_patient_with_one_number_and_other_content_are_counted(tmp_path: Path) -> None:
    """The source says two different things under one number of one patient tonight: still one record (the last
    row, as DATA-017 always had it), and now counted in the night's report, never silent."""
    rows = canonical(A)
    second = {**rows["diagnosis"][0], "icd10": "E11.9"}
    rows["diagnosis"] = [rows["diagnosis"][0], second]
    rep = night(tmp_path, "csv", rows, "2026-10-01")
    comp = json.loads((snapshot_dir(tmp_path / "lake", "2026-10-01") / "completeness.json").read_text())
    assert comp["id_collisions"] == {"Condition": 1}
    assert len(lake(tmp_path, "2026-10-01")["Condition"]) == 1
    assert rep is not None
    # the night's own record (the audit event the data-ops batch row keeps its counts from) says it too
    events = [json.loads(line) for f in sorted((tmp_path / "audit").rglob("*.jsonl")) for line in f.open()]
    (night_event,) = [e for e in events if str(e.get("event", "")).startswith("ingest.")]
    assert night_event["detail"]["id_collisions"] == {"Condition": 1}
    from datacore.dataops import DETAIL_KEYS

    assert {"id_collisions", "links_to_absent_records", "deletes_without_patient"} <= set(DETAIL_KEYS)


def test_one_row_sent_twice_is_not_a_collision(tmp_path: Path) -> None:
    rows = canonical(A)
    rows["diagnosis"] = rows["diagnosis"] * 2
    night(tmp_path, "csv", rows, "2026-10-01")
    comp = json.loads((snapshot_dir(tmp_path / "lake", "2026-10-01") / "completeness.json").read_text())
    assert not comp.get("id_collisions")


# ------------------------------------------------------------------------------------------------ fhir_bulk: untouched
def test_fhir_bulk_ids_stay_the_servers_unique_ids() -> None:
    """A FHIR server's id is unique per server and type: the bulk door's ids keep their rule (D-1253 leaves them)."""
    from adapter.mapping.engine import resource_id

    res: list[dict[str, Any]] = [{"resourceType": "Condition", "id": "c1", "subject": {"reference": "Patient/p1"}},
                                  {"resourceType": "Observation", "id": "o1", "subject": {"reference": "Patient/p2"},
                                   "hasMember": [{"reference": "Condition/c1"}]}]  # fmt: skip
    out = list(pseudonymise_bulk(iter(res), KEY))
    assert out[0]["id"] == bulk_id(KEY, "Condition", "c1") == resource_id(KEY, "Condition", "c1")
    assert out[1]["id"] == resource_id(KEY, "Observation", "o1")
    assert out[1]["hasMember"][0]["reference"] == f"Condition/{out[0]['id']}"
    assert Counter(r["resourceType"] for r in out) == {"Condition": 1, "Observation": 1}


def _bulk_night(tmp: Path, snap: str, since: str | None = None) -> Any:
    """A FHIR bulk export night over the same lake (``fhir_bulk``: the server's own ids)."""
    exp = tmp / f"bulk-{snap}"
    exp.mkdir()
    rows = [{"resourceType": "Patient", "id": "srv-1", "gender": "female", "birthDate": "1960-01-01"}]
    (exp / "Patient.ndjson").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return run_ingest(_cfg(tmp, "csv"), "fhir_bulk", str(exp), snapshot=snap, since=since, load_fhir=False,
                      rebuild_lake=False, validate=False)  # fmt: skip


SOURCE_WORDS = "changes its source only with a full night"


@pytest.mark.parametrize("first", ["csv", "fhir_bulk"])
def test_a_delta_night_from_another_source_than_its_base_is_held(tmp_path: Path, first: str) -> None:
    """D-1253 review ruling 7: one record from a mapped feed and from a FHIR bulk export has two ids (the feed's is
    the patient's hash, the bulk export's the server's). A site changes its source only with a full night: a delta
    night read from another source than the snapshot it would merge over is held, with that message, both ways. A
    full night from the new source is not held for it."""
    if first == "csv":
        assert night(tmp_path, "csv", canonical(A), "2026-10-01").passed
        held = _bulk_night(tmp_path, "2026-10-02", since="2026-10-01")
    else:
        assert _bulk_night(tmp_path, "2026-10-01").passed
        held = night(tmp_path, "csv", canonical(A), "2026-10-02", since="2026-10-01")
    assert not held.passed and any(SOURCE_WORDS in e for e in held.errors), held.errors
    full = (night(tmp_path, "csv", canonical(A), "2026-10-03") if first == "fhir_bulk"
            else _bulk_night(tmp_path, "2026-10-03"))  # fmt: skip
    assert not any(SOURCE_WORDS in e for e in full.errors), full.errors


def test_an_absent_link_is_counted_under_a_table_of_the_mapping_never_under_a_records_source_text(
    tmp_path: Path,
) -> None:
    """D-1253 second review, finding 10: the count label came from ``meta.source``. A bulk FHIR resource's source is
    the sender's text (here it holds a synthetic chart number): it is never a label. A label is a table of the
    mapping, else the record's type."""
    from adapter.ndjson import absent_links

    snap = tmp_path / "snap"
    snap.mkdir()
    cond = {"resourceType": "Condition", "id": "c1", "subject": {"reference": "Patient/p1"},
            "encounter": {"reference": "Encounter/e-missing"},
            "meta": {"source": "urn:hospital:chart/MRN12345#visit"}}  # fmt: skip
    mapped = {"resourceType": "Condition", "id": "c2", "subject": {"reference": "Patient/p1"},
              "encounter": {"reference": "Encounter/e-gone"}, "meta": {"source": "T/diagnosis#ab12"}}  # fmt: skip
    (snap / "Condition.ndjson").write_text(
        "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in (cond, mapped)), encoding="utf-8"
    )
    got = absent_links(snap, tables=["diagnosis"])
    assert got == {"Condition": {"Encounter": 1}, "diagnosis": {"Encounter": 1}}
    assert "MRN12345" not in json.dumps(got)
