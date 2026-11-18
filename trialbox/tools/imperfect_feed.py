"""imperfect_feed: imperfect hospital data through the box's own nightly ingest (card H-34, decision D-1100).

    python -m tools.imperfect_feed --out DIR                      # every case in every source format that exists
    python -m tools.imperfect_feed --out DIR --formats csv --cases cut-mid-row,big5
    python -m tools.imperfect_feed --out DIR --table             # also print the page's table (Markdown)
    python -m tools.imperfect_feed --list                         # the cases and the formats each applies to

What it does. A small clean export is made up here (``clean_export``: 50 fictional patients, every table of the
demo HIS mapping; no value is copied from anywhere). It is written in each source format the adapter reads: the CSV
site export, a CGRD-style SQL database (SQLite), a FHIR Bulk Data export and SS-MIX2 standardized storage (through
``tools.ssmix2_export``). The clean export is ingested first and its lake compared with what the generator says it
holds. Then each case makes one imperfect variant of it and runs the night on it, each in a scratch folder of its own
with its own lake, secrets, audit folder and database prefix.

The entry point is the box's own command line, as a process of its own: ``python -m adapter.cli run --source <kind>
--path <feed> --snapshot <night> --no-fhir``, configured from the environment and a settings file written by the
settings wizard (``tools.settings_wizard``, from the box rehearsal's answers) as an installed box is; the lake step
local (``TB_ADAPTER_LAKE=local``, the hash embedder). ``adapter.run_job``, which the adapter service starts at
night, calls the same ``run_ingest`` with the same ``build_config``. ``--no-fhir``: no FHIR store runs here.

What it records per case and format (D-1100 defines the words): the exit status and whether a traceback was printed;
what ``ingest_report.json`` and ``completeness.json`` say (rows read per table, rows rejected and why, the hold);
whether the good rows of the same file went into the lake; whether anything wrong went into the lake (the lake's own
Parquet tables, compared with the clean night's: a value that differs, a row twice, a patient split or merged);
whether the night's later steps ran (the lake rebuilt and served; one FEAS computation over it); what a person is
told (the report's error lines, the counts file, the steward's batch row). Nothing is fixed: the harness reads and
calls the product, it changes no product file.

The database: ``TB_DB_URL`` when set, else a throwaway cluster of ``tools.pglocal`` under ``TB_TEST_ROOT``
(``make imperfect-feed``). Synthetic data only; the bad files are made at run time in the scratch folder and never
committed. The results JSON holds counts, states and the product's own words, never a cell.
"""

from __future__ import annotations

import argparse
import base64
import csv
import functools
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
FORMATS = ("csv", "cgrd_sql", "fhir_bulk", "ssmix2")
# source formats of D-1067's release that the adapter does not read yet: said, never tested
NOT_BUILT = {
    "hl7v2_feed": "a live HL7 v2 feed (MLLP or a file drop of v2 messages outside SS-MIX2): the adapter has no "
    "such source (`adapter run --source` offers cgrd_sql, csv, fhir_bulk, ssmix2)",
    "fhir_feed": "a live FHIR feed (REST pushes or subscriptions): the adapter reads a FHIR Bulk Data export folder "
    "only (`fhir_bulk`)",
}
MAPPINGS = {
    "csv": "mapping/tw_core/demo_his.yaml",
    "cgrd_sql": "mapping/tw_core/demo_his.yaml",
    "fhir_bulk": "mapping/tw_core/demo_his.yaml",
    "ssmix2": "mapping/jp_core/ssmix2_site.yaml",
}
NIGHT, NIGHT2 = "2026-11-10", "2026-11-11"
FEAS_REF = date(2026, 11, 12)
N_PATIENTS = 50
MRN_BASE = 93400000  # eight digits, as the rehearsal's chart-number rule (digits:8) wants; made up
TABLES = (
    "patient", "practitioner", "encounter", "appointment", "diagnosis", "lab", "vital", "medication", "procedure",
    "report", "note", "claim", "registry",
)  # fmt: skip
COLUMNS: dict[str, tuple[str, ...]] = {
    "patient": ("mrn", "name", "id_no", "birth_date", "sex", "death_date", "phone"),
    "practitioner": ("staff_id", "name", "dept_code"),
    "encounter": ("enc_no", "mrn", "visit_datetime", "dept_code", "staff_id", "enc_type"),
    "appointment": ("appt_no", "mrn", "appt_datetime", "duration_min", "staff_id", "dept_code", "status"),
    "diagnosis": ("diag_no", "enc_no", "mrn", "icd10", "diag_date", "recorded_date", "status"),
    "lab": ("lab_no", "mrn", "local_code", "item_name", "result_value", "unit", "sample_datetime"),
    "vital": ("vital_no", "mrn", "measure_datetime", "height_cm", "weight_kg", "sbp", "dbp"),
    "medication": ("rx_no", "mrn", "nhi_drug_code", "atc", "drug_name", "order_date", "start_date", "end_date",
                   "daily_dose", "dose_unit", "status", "dept_code"),
    "procedure": ("proc_no", "mrn", "order_code", "proc_name", "proc_date"),
    "report": ("rpt_no", "mrn", "exam_code", "exam_name", "exam_date", "conclusion"),
    "note": ("note_no", "mrn", "enc_no", "note_datetime", "note_type", "text"),
    "claim": ("claim_no", "mrn", "created_date", "product_code", "apply_type", "outcome", "approval_start",
              "approval_end"),
    "registry": ("mrn", "consent_contact", "consent_date"),
}  # fmt: skip
KEYS = {"patient": "mrn", "practitioner": "staff_id", "encounter": "enc_no", "appointment": "appt_no",
        "diagnosis": "diag_no", "lab": "lab_no", "vital": "vital_no", "medication": "rx_no", "procedure": "proc_no",
        "report": "rpt_no", "note": "note_no", "claim": "claim_no", "registry": "mrn"}  # fmt: skip
# local lab code -> (LOINC, unit, name); factor 1 in the TW look-up, so the lake keeps the value as written
LABS = {"UA": ("3084-1", "mg/dL", "Urate"), "CRE": ("2160-0", "mg/dL", "Creatinine"),
        "HBA1C": ("4548-4", "%", "HbA1c"), "ALT": ("1742-6", "U/L", "ALT")}  # fmt: skip
ICD = ("E11.9", "C34.11", "E10.9", "B18.1", "C18.9")  # in the jp_core sample 標準病名 table too (SS-MIX2)
DRUGS = (("AC00011100", "C10AA05", "Atorvastatin 20mg"), ("AC00014100", "M04AA01", "Allopurinol 100mg"))
LAB_ZH = {"UA": "尿酸", "CRE": "肌酸酐", "HBA1C": "糖化血色素", "ALT": "肝功能指數"}  # the FHIR export's code.text
NOTE_ZH = "病人無發燒，血壓穩定，持續原處方，三個月後回診。"  # Big5-encodable clinical words, no name, no identifier
Tables = dict[str, list[dict[str, str]]]


# ----------------------------------------------------------------------------------------------- the clean export


def mrn(i: int) -> str:
    return f"{MRN_BASE + i:08d}"


def clean_export(n: int = N_PATIENTS) -> Tables:
    """The clean synthetic export: ``n`` fictional patients, every table of the demo HIS mapping, all values text.

    Every row's facts are unique where the lake keeps them (a visit time per patient, a lab value per test), so a
    value that comes back changed, twice, or under another patient can be told from the right one."""
    t: Tables = {name: [] for name in TABLES}
    for s in range(1, 4):
        t["practitioner"].append({"staff_id": f"S{s:04d}", "name": f"Synthetic clinician {s}", "dept_code": "RHEU"})
    for i in range(1, n + 1):
        m = mrn(i)
        born = date(1940 + i % 50, 1 + i % 12, 1 + i % 28)
        t["patient"].append({"mrn": m, "name": f"Synthetic {i:02d}", "id_no": "", "birth_date": born.isoformat(),
                             "sex": "M" if i % 2 else "F", "death_date": "", "phone": ""})  # fmt: skip
        t["registry"].append({"mrn": m, "consent_contact": "Y", "consent_date": "2026-04-19"})
        appt = f"2026-12-{1 + i % 27:02d} 10:00:00"
        t["appointment"].append({"appt_no": f"A{i:03d}", "mrn": m, "appt_datetime": appt, "duration_min": "20",
                                 "staff_id": "S0001", "dept_code": "RHEU", "status": "B"})  # fmt: skip
        t["vital"].append({"vital_no": f"V{i:03d}", "mrn": m, "measure_datetime": f"2026-01-{1 + i % 27:02d} 09:00:00",
                           "height_cm": f"{150 + i % 40}.5", "weight_kg": f"{50 + i % 40}.2", "sbp": f"{110 + i % 30}",
                           "dbp": f"{70 + i % 20}"})  # fmt: skip
        t["report"].append({"rpt_no": f"R{i:03d}", "mrn": m, "exam_code": "RAD-CXR", "exam_name": "Chest X-ray PA",
                            "exam_date": f"2026-06-{1 + i % 27:02d}", "conclusion": "雙側肺野清晰。"})  # fmt: skip
        if i % 5 == 0:
            t["procedure"].append({"proc_no": f"P{i:03d}", "mrn": m, "order_code": "X0001",
                                   "proc_name": "Synthetic procedure",
                                   "proc_date": f"2025-09-{1 + i % 27:02d}"})  # fmt: skip
        if i % 10 == 0:
            t["claim"].append({"claim_no": f"C{i:03d}", "mrn": m, "created_date": "2026-07-29",
                               "product_code": "KC00018248", "apply_type": "1", "outcome": "approved",
                               "approval_start": "2026-08-01", "approval_end": "2027-07-31"})  # fmt: skip
        for k in range(3):
            day = f"2026-{3 + k * 2:02d}-{1 + i % 27:02d}"
            enc = f"E{i:03d}{k}"
            t["encounter"].append({"enc_no": enc, "mrn": m, "visit_datetime": f"{day} 09:{(i * 7 + k) % 60:02d}:00",
                                   "dept_code": "RHEU", "staff_id": f"S{1 + k:04d}", "enc_type": "OPD"})  # fmt: skip
            t["diagnosis"].append({"diag_no": f"D{i:03d}{k}", "enc_no": enc, "mrn": m, "icd10": ICD[(i + k) % 5],
                                   "diag_date": day, "recorded_date": day, "status": "A"})  # fmt: skip
            text = f"{NOTE_ZH} Note {i:03d}-{k}: plan to review in {k + 1} months."
            t["note"].append({"note_no": f"N{i:03d}{k}", "mrn": m, "enc_no": enc, "note_datetime": f"{day} 12:00:00",
                              "note_type": "progress", "text": text})  # fmt: skip
        for k, code in enumerate(LABS):
            _, unit, name = LABS[code]
            day = f"2026-{2 + k * 2:02d}-{1 + i % 27:02d}"
            value = f"{1 + i % 9}.{(i * 13 + k * 7) % 89 + 10:02d}"  # two decimals: a cut digit is seen
            t["lab"].append({"lab_no": f"L{i:03d}{k}", "mrn": m, "local_code": code, "item_name": name,
                             "result_value": value, "unit": unit, "sample_datetime": f"{day} 10:30:00"})  # fmt: skip
        for k, (nhi, atc, name) in enumerate(DRUGS):
            start = date(2026, 4 + k * 3, 1 + i % 27)
            t["medication"].append({"rx_no": f"M{i:03d}{k}", "mrn": m, "nhi_drug_code": nhi, "atc": atc,
                                    "drug_name": name, "order_date": start.isoformat(), "start_date": start.isoformat(),
                                    "end_date": (start + timedelta(days=27)).isoformat(), "daily_dose": "20",
                                    "dose_unit": "mg", "status": "active", "dept_code": "RHEU"})  # fmt: skip
    return t


def copy_tables(t: Tables) -> Tables:
    return {k: [dict(r) for r in v] for k, v in t.items()}


def row_of(t: Tables, table: str, key: str) -> dict[str, str]:
    return next(r for r in t[table] if r[KEYS[table]] == key)


# ------------------------------------------------------------------------------------------------- the formats


def csv_bytes(table: str, rows: list[dict[str, str]]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(COLUMNS[table]), lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue().encode("utf-8")


def write_csv(t: Tables, folder: Path) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    for table in TABLES:
        (folder / f"{table}.csv").write_bytes(csv_bytes(table, t[table]))
    return str(folder)


def write_sql(t: Tables, folder: Path, twice: bool = False, drop_column: tuple[str, str] | None = None) -> str:
    """A CGRD-style database: one table per landing table, every column TEXT (SQLite in place of the replica)."""
    folder.mkdir(parents=True, exist_ok=True)
    db = folder / "cgrd.sqlite"
    con = sqlite3.connect(db)
    for table in TABLES:
        cols = [c for c in COLUMNS[table] if (table, c) != drop_column]
        con.execute(f"CREATE TABLE {table} ({', '.join(f'{c} TEXT' for c in cols)})")
        rows = [tuple(r.get(c) for c in cols) for r in t[table]]
        for _ in range(2 if twice else 1):
            con.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' for _ in cols)})", rows)
    con.commit()
    con.close()
    return f"sqlite:///{db}"


def _ref(m: str) -> dict[str, str]:
    return {"reference": f"Patient/{m}"}


@functools.cache
def mapping_tz(fmt: str) -> str:
    """The zone the format's mapping names (its ``tz``): the site's, never one of this tool's own (D-315)."""
    import yaml

    doc = yaml.safe_load((ROOT / "services/adapter" / MAPPINGS[fmt]).read_text(encoding="utf-8"))
    return str(doc["tz"])


def _iso(local: str) -> str:
    """A local time of the CSV export with the offset the demo mapping's zone has at that instant."""
    from zoneinfo import ZoneInfo

    return datetime.fromisoformat(local).replace(tzinfo=ZoneInfo(mapping_tz("fhir_bulk"))).isoformat()


def fhir_resources(t: Tables) -> dict[str, list[dict[str, Any]]]:
    """The same patients as a FHIR Bulk Data export (one NDJSON file per type)."""
    out: dict[str, list[dict[str, Any]]] = {k: [] for k in ("Patient", "Encounter", "Condition", "Observation",
                                                            "MedicationRequest", "DocumentReference")}  # fmt: skip
    for r in t["patient"]:
        p: dict[str, Any] = {"resourceType": "Patient", "id": r["mrn"],
                             "gender": {"M": "male", "F": "female"}.get(r["sex"], "unknown")}  # fmt: skip
        if r["birth_date"]:
            p["birthDate"] = r["birth_date"]
        out["Patient"].append(p)
    for r in t["encounter"]:
        out["Encounter"].append({
            "resourceType": "Encounter", "id": r["enc_no"], "status": "finished",
            "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"},
            "subject": _ref(r["mrn"]), "period": {"start": _iso(r["visit_datetime"])},
            "serviceType": {"coding": [{"system": "https://trialbox.local/fhir/CodeSystem/department",
                                        "code": r["dept_code"]}]},
            "participant": [{"individual": {"reference": f"Practitioner/{r['staff_id']}"}}]})  # fmt: skip
    for r in t["diagnosis"]:
        out["Condition"].append({
            "resourceType": "Condition", "id": r["diag_no"], "subject": _ref(r["mrn"]),
            "encounter": {"reference": f"Encounter/{r['enc_no']}"},
            "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                                           "code": "active"}]},
            "verificationStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                                               "code": "confirmed"}]},
            "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": r["icd10"]}]},
            "onsetDateTime": r["diag_date"], "recordedDate": r["recorded_date"]})  # fmt: skip
    for r in t["lab"]:
        loinc, unit, name = LABS.get(r["local_code"], (r["local_code"], r["unit"], r["item_name"]))
        out["Observation"].append({
            "resourceType": "Observation", "id": r["lab_no"], "status": "final",
            "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                      "code": "laboratory"}]}],
            "code": {"coding": [{"system": "http://loinc.org", "code": loinc, "display": name}],
                     "text": LAB_ZH.get(r["local_code"], name)},
            "subject": _ref(r["mrn"]), "effectiveDateTime": _iso(r["sample_datetime"]),
            "valueQuantity": {"value": float(r["result_value"]), "unit": unit, "system": "http://unitsofmeasure.org",
                              "code": unit}})  # fmt: skip
    for r in t["medication"]:
        out["MedicationRequest"].append({
            "resourceType": "MedicationRequest", "id": r["rx_no"], "status": "active", "intent": "order",
            "subject": _ref(r["mrn"]), "authoredOn": r["order_date"],
            "dispenseRequest": {"validityPeriod": {"start": r["start_date"], "end": r["end_date"]}},
            "medicationCodeableConcept": {"coding": [{"system": "http://www.whocc.no/atc", "code": r["atc"]}],
                                          "text": r["drug_name"]}})  # fmt: skip
    for r in t["note"]:
        out["DocumentReference"].append({
            "resourceType": "DocumentReference", "id": r["note_no"], "status": "current", "subject": _ref(r["mrn"]),
            "date": _iso(r["note_datetime"]), "type": {"text": r["note_type"]},
            "content": [{"attachment": {"contentType": "text/plain; charset=utf-8",
                                        "data": base64.b64encode(r["text"].encode()).decode()}}]})  # fmt: skip
    return out


def ndjson_bytes(resources: list[dict[str, Any]]) -> bytes:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in resources).encode("utf-8")


def write_fhir(t: Tables, folder: Path) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    for rtype, res in fhir_resources(t).items():
        (folder / f"{rtype}.ndjson").write_bytes(ndjson_bytes(res))
    return str(folder)


def write_ssmix2(t: Tables, folder: Path, work: Path) -> str:
    """SS-MIX2 standardized storage written by ``tools.ssmix2_export`` from the CSV export (its own fixtures' path)."""
    from tools.ssmix2_export import export

    src = work / "ssmix2-csv"
    shutil.rmtree(src, ignore_errors=True)
    write_csv(t, src)
    folder.mkdir(parents=True, exist_ok=True)
    export(src, folder)
    shutil.rmtree(src, ignore_errors=True)
    return str(folder)


def write_feed(fmt: str, t: Tables, folder: Path, work: Path) -> str:
    if fmt == "csv":
        return write_csv(t, folder)
    if fmt == "cgrd_sql":
        return write_sql(t, folder)
    if fmt == "fhir_bulk":
        return write_fhir(t, folder)
    return write_ssmix2(t, folder, work)


def ssmix2_files(root: Path, patient: str, typ: str) -> list[Path]:
    """The message files of one patient and type, in name order."""
    from adapter.sources.ssmix2.source import storage_dir

    base = storage_dir(root, patient, "-", typ).parent.parent
    return sorted(p for p in base.glob(f"*/{typ}/*") if p.is_file())


# ----------------------------------------------------------------------------------------------- the cases


@dataclass
class Feed:
    """One night's input: the folder (or DSN) and, for the comparison, which source rows the case made bad."""

    path: str
    touched: dict[str, set[str]] = field(default_factory=dict)  # table -> keys of rows the case made bad
    correct: Tables = field(default_factory=dict)  # table -> the right reading of a bad row (allowed in the lake)
    as_written: Tables = field(default_factory=dict)  # table -> a bad row read as the hospital wrote it (D-1100)


Builder = Callable[[str, Tables, Path, Path], Feed]


@dataclass
class Case:
    id: str
    family: str
    words: str  # what the variant is, in words
    formats: tuple[str, ...]
    build: Builder
    expected: str  # the right outcome and its source
    nights: int = 1  # 2: the same feed again the next night
    not_applicable: dict[str, str] = field(default_factory=dict)  # format -> why the case does not apply


def _rows_edit(edit: Callable[[Tables], tuple[Any, ...]]) -> Builder:
    """A case that changes values (any format): the edited tables written in the format. ``edit`` returns the rows
    it made bad, their right reading and (optionally) their reading as the hospital wrote them."""

    def build(fmt: str, clean: Tables, folder: Path, work: Path) -> Feed:
        t = copy_tables(clean)
        touched, correct, *written = edit(t)
        return Feed(write_feed(fmt, t, folder, work), touched, correct, written[0] if written else {})

    return build


def _bytes_edit(edit: Callable[[str, Path, Tables], Any]) -> Builder:
    """A case that changes bytes after the clean export is written (a file cut, re-encoded, doubled). ``edit``
    returns the rows it made bad, or those and their right reading."""

    def build(fmt: str, clean: Tables, folder: Path, work: Path) -> Feed:
        path = write_feed(fmt, clean, folder, work)
        got = edit(fmt, folder, clean)
        return Feed(path, *got) if isinstance(got, tuple) else Feed(path, got)

    return build


LAST_LAB = f"L{N_PATIENTS:03d}3"
LAST_NOTE = f"N{N_PATIENTS:03d}2"
P7 = mrn(7)


def _file_of(fmt: str, folder: Path, table: str) -> Path:
    if fmt == "csv":
        return folder / f"{table}.csv"
    rtype = {"lab": "Observation", "note": "DocumentReference", "patient": "Patient", "diagnosis": "Condition"}[table]
    return folder / f"{rtype}.ndjson"


def ssmix2_key(f: Path) -> str:
    """The source key a message file carries in its name (``<id>_<day>_<type>_<order no>_<stamp>_<dept>_<flag>``)."""
    return f.name.split("_")[3]


def _cut(fmt: str, folder: Path, t: Tables, table: str, keep: Callable[[bytes], int]) -> dict[str, set[str]]:
    """Cut the table's file at ``keep(data)`` bytes: the last row is the one cut (SS-MIX2: the last patient's last
    lab message, or for a note the last patient's last diagnosis message, whose name is in JIS)."""
    if fmt == "ssmix2":
        typ, tab = ("OML-11", "lab") if table == "lab" else ("PPR-01", "diagnosis")
        f = ssmix2_files(folder, mrn(N_PATIENTS), typ)[-1]
        data = f.read_bytes()
        f.write_bytes(data[: keep(data)])
        return {tab: {ssmix2_key(f)}}
    f = _file_of(fmt, folder, table)
    data = f.read_bytes()
    f.write_bytes(data[: keep(data)])
    return {table: {t[table][-1][KEYS[table]]}}


def _cut_mid_row(fmt: str, folder: Path, t: Tables) -> dict[str, set[str]]:
    """The lab file ends inside its last row: in the result value, after its first decimal (``3.47`` -> ``3.4``)."""
    value = t["lab"][-1]["result_value"].encode()

    def keep(data: bytes) -> int:
        at = data.rfind(value[:-1] if fmt != "fhir_bulk" else b'"value": ' + str(float(value)).encode()[:-1])
        if fmt == "fhir_bulk":
            return at + len(b'"value": ') + len(str(float(value))) - 1
        return at + len(value) - 1

    return _cut(fmt, folder, t, "lab", keep)


def _cut_mid_char(fmt: str, folder: Path, t: Tables) -> dict[str, set[str]]:
    """The note file ends inside a multibyte character of its last row's text (or, in SS-MIX2, inside a JIS
    escape of the last lab message)."""

    def keep(data: bytes) -> int:
        if fmt == "ssmix2":  # inside the JIS run of PRB-3's 標準病名 name: two bytes a character, cut after one
            esc = data.find(b"\x1b$B", data.find(b"PRB|"))
            return esc + 4
        last = data.rfind("持續".encode())  # the last row's Chinese text (three bytes a character)
        return last + 4  # one whole character and one byte of the next

    return _cut(fmt, folder, t, "note", keep)


def _cut_in_quotes(fmt: str, folder: Path, t: Tables) -> dict[str, set[str]]:
    """The note file ends inside a quoted field: the last note holds a comma, so it is quoted, and the file stops
    before its closing quote."""
    del t
    f = folder / "note.csv"
    rows = list(csv.DictReader(io.StringIO(f.read_text(encoding="utf-8"))))
    rows[-1]["text"] = rows[-1]["text"].replace("。", "。, ", 1)
    data = csv_bytes("note", rows)
    f.write_bytes(data[: len(data) - 12])
    return {"note": {LAST_NOTE}}


def _twice_other_name(fmt: str, folder: Path, t: Tables) -> dict[str, set[str]]:
    """The lab file is delivered again beside itself under another name (``lab (1).csv``, ``Observation-1.ndjson``,
    or in SS-MIX2 the same lab message again under a later time stamp)."""
    del t
    if fmt == "csv":
        shutil.copy(folder / "lab.csv", folder / "lab (1).csv")
    elif fmt == "fhir_bulk":
        shutil.copy(folder / "Observation.ndjson", folder / "Observation-1.ndjson")
    else:
        f = ssmix2_files(folder, P7, "OML-11")[0]
        parts = f.name.split("_")
        parts[4] = "20261101000001000"
        shutil.copy(f, f.with_name("_".join(parts)))
    return {}


def _twice_in_one_file(fmt: str, folder: Path, t: Tables) -> dict[str, set[str]]:
    """The lab table's content twice in one delivery: the file and its header concatenated again (CSV); every line
    twice (FHIR); every row inserted twice (SQL)."""
    del t
    f = _file_of(fmt, folder, "lab")
    data = f.read_bytes()
    f.write_bytes(data + data)
    return {}


def _line_short(fmt: str, folder: Path, t: Tables) -> dict[str, set[str]]:
    """One lab row one field short (the last field, the sample time, missing)."""
    return _edit_line(folder, "lab", t["lab"][6]["lab_no"], lambda ln: ln.rsplit(b",", 1)[0])


def _line_extra(fmt: str, folder: Path, t: Tables) -> dict[str, set[str]]:
    """One lab row one field more (a stray comma inside the value: ``2,35`` for ``2.35``)."""
    row = t["lab"][6]
    v = row["result_value"].encode()
    return _edit_line(
        folder, "lab", row["lab_no"], lambda ln: ln.replace(b"," + v + b",", b"," + v.replace(b".", b",") + b",")
    )


def _edit_line(folder: Path, table: str, key: str, edit: Callable[[bytes], bytes]) -> dict[str, set[str]]:
    f = folder / f"{table}.csv"
    lines = f.read_bytes().split(b"\n")
    lines = [edit(ln) if ln.startswith(key.encode() + b",") else ln for ln in lines]
    f.write_bytes(b"\n".join(lines))
    return {table: {key}}


def _header_renamed(fmt: str, folder: Path, t: Tables) -> dict[str, set[str]]:
    """The lab file's header names a column otherwise (``result_val`` for ``result_value``); every row as before."""
    del t
    f = folder / "lab.csv"
    data = f.read_bytes()
    f.write_bytes(data.replace(b"result_value", b"result_val", 1))
    return {"lab": set()}


def _header_dropped(fmt: str, folder: Path, t: Tables) -> dict[str, set[str]]:
    """The lab table has no sample-time column at all (the export left it out)."""
    if fmt == "cgrd_sql":
        Path(folder / "cgrd.sqlite").unlink()
        write_sql(t, folder, drop_column=("lab", "sample_datetime"))
        return {"lab": set()}
    f = folder / "lab.csv"
    rows = list(csv.DictReader(io.StringIO(f.read_text(encoding="utf-8"))))
    cols = [c for c in COLUMNS["lab"] if c != "sample_datetime"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n", extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    f.write_bytes(buf.getvalue().encode("utf-8"))
    return {"lab": set()}


def hkscs_char() -> str:
    """The first CJK character Big5-HKSCS encodes and CP950 (Big5) does not: an HKSCS-only character."""
    for cp in range(0x3400, 0x9FFF):
        ch = chr(cp)
        try:
            ch.encode("big5hkscs")
        except UnicodeEncodeError:
            continue
        try:
            ch.encode("cp950")
        except UnicodeEncodeError:
            return ch
    raise RuntimeError("no HKSCS-only character")


def _recode(codec: str, bom: bytes = b"", table: str = "note") -> Callable[[str, Path, Tables], Any]:
    def edit(fmt: str, folder: Path, t: Tables) -> Any:
        if fmt == "ssmix2":  # one diagnosis message of patient 7 in another character set, MSH-18 unchanged
            f = ssmix2_files(folder, P7, "PPR-01")[0]
            text = f.read_bytes().decode("iso2022_jp")
            f.write_bytes(bom + text.encode(codec))
            return {"diagnosis": {ssmix2_key(f)}}
        f = _file_of(fmt, folder, "lab" if fmt == "fhir_bulk" else table)  # FHIR notes are base64: the lab file
        text = f.read_bytes().decode("utf-8")
        f.write_bytes(
            bom + (text.replace("持續", f"持續{hkscs_char()}", 1) if codec == "big5hkscs" else text).encode(codec)
        )
        if codec == "big5hkscs":  # the first note's text holds the character: its right reading has it
            first = t[table][0]
            right = dict(first, text=first["text"].replace("持續", f"持續{hkscs_char()}", 1))
            return {table: {first[KEYS[table]]}}, {table: [right]}
        return {}

    return edit


def _one_big5_row(fmt: str, folder: Path, t: Tables) -> dict[str, set[str]]:
    """A UTF-8 note file with one row whose text is Big5 (a row pasted from another system)."""
    f = folder / "note.csv"
    lines = f.read_bytes().split(b"\n")
    key = t["note"][9]["note_no"].encode()
    lines = [ln.decode("utf-8").encode("cp950") if ln.startswith(key + b",") else ln for ln in lines]
    f.write_bytes(b"\n".join(lines))
    return {"note": {key.decode()}}


def _crlf(fmt: str, folder: Path, t: Tables) -> dict[str, set[str]]:
    del t
    for f in _all_files(fmt, folder):
        data = f.read_bytes()
        if fmt == "ssmix2":
            f.write_bytes(data.replace(b"\r", b"\r\n"))
        else:
            f.write_bytes(data.replace(b"\n", b"\r\n"))
    return {}


def _lone_cr(fmt: str, folder: Path, t: Tables) -> dict[str, set[str]]:
    del t
    for f in _all_files(fmt, folder):
        data = f.read_bytes()
        if fmt == "ssmix2":
            f.write_bytes(data.replace(b"\r", b"\n"))  # SS-MIX2's own separator is CR: the other way, LF only
        else:
            f.write_bytes(data.replace(b"\n", b"\r"))
    return {}


def _all_files(fmt: str, folder: Path) -> list[Path]:
    if fmt == "csv":
        return sorted(folder.glob("*.csv"))
    if fmt == "fhir_bulk":
        return sorted(folder.glob("*.ndjson"))
    return sorted(p for p in folder.rglob("*")
                  if p.is_file() and not p.relative_to(folder).parts[0].startswith("extended"))  # fmt: skip


def _zero_bytes(fmt: str, folder: Path, t: Tables) -> dict[str, set[str]]:
    if fmt == "ssmix2":
        for f in ssmix2_files(folder, P7, "OML-11"):
            f.write_bytes(b"")
        return {"lab": {r["lab_no"] for r in t["lab"] if r["mrn"] == P7}}
    f = _file_of(fmt, folder, "lab")
    f.write_bytes(b"")
    return {"lab": {r["lab_no"] for r in t["lab"]}}


def _header_only(fmt: str, folder: Path, t: Tables) -> dict[str, set[str]]:
    f = folder / "lab.csv"
    f.write_bytes(f.read_bytes().split(b"\n", 1)[0] + b"\n")
    return {"lab": {r["lab_no"] for r in t["lab"]}}


def _folder_empty(fmt: str, folder: Path, t: Tables) -> dict[str, set[str]]:
    if fmt == "cgrd_sql":  # a database with no table at all
        Path(folder / "cgrd.sqlite").unlink()
        sqlite3.connect(folder / "cgrd.sqlite").close()
    else:
        for p in list(folder.iterdir()):
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    return {table: {r[KEYS[table]] for r in t[table]} for table in TABLES}


def _ssmix2_pid_field(index: int, value: str) -> Callable[[str, Path, Tables], Any]:
    """Replace PID-<index> of patient 7's ADT-00 message (birth date 7). The right reading: the patient kept with no
    birth date; as written: the date as it stands, where it is a date."""

    def edit(fmt: str, folder: Path, t: Tables) -> Any:
        f = ssmix2_files(folder, P7, "ADT-00")[0]
        raw = f.read_bytes()
        utf8 = b"UNICODE UTF-8" in raw[:200]
        text = raw.decode("utf-8" if utf8 else "iso2022_jp")
        segs = text.split("\r")
        for n, s in enumerate(segs):
            if s.startswith("PID|"):
                fields = s.split("|")
                fields[index] = value
                segs[n] = "|".join(fields)
        f.write_bytes("\r".join(segs).encode("utf-8" if utf8 else "iso2022_jp"))
        row = row_of(t, "patient", P7)
        day = f"{value[:4]}-{value[4:6]}-{value[6:8]}"
        return {"patient": {P7}}, {"patient": [dict(row, birth_date="")]}, {"patient": [dict(row, birth_date=day)]}

    return edit


# value edits (every format): each returns (touched, correct)


def _set(t: Tables, table: str, key: str, col: str, value: str) -> tuple[dict[str, set[str]], Tables]:
    row = row_of(t, table, key)
    right = dict(row)
    row[col] = value
    return {table: {key}}, {table: [right]}


def _diag_date(value: str, right: str | None) -> Callable[[Tables], tuple[Any, ...]]:
    """Diagnosis D0071's date (onset and record) written as ``value``; ``right``: its true reading, if it has one."""

    def edit(t: Tables) -> tuple[Any, ...]:
        row = row_of(t, "diagnosis", "D0071")
        row["diag_date"] = row["recorded_date"] = value
        fixed = dict(row, diag_date=right, recorded_date=right) if right else None
        return {"diagnosis": {"D0071"}}, ({"diagnosis": [fixed]} if fixed else {}), {"diagnosis": [dict(row)]}

    return edit


def _birth(value: str) -> Callable[[Tables], tuple[Any, ...]]:
    def edit(t: Tables) -> tuple[dict[str, set[str]], Tables, Tables]:
        touched, _ = _set(t, "patient", P7, "birth_date", value)
        no_birth = dict(row_of(t, "patient", P7), birth_date="")  # the patient kept, the birth date left out
        return touched, {"patient": [no_birth]}, {"patient": [dict(row_of(t, "patient", P7))]}

    return edit


def _note_text(text: str) -> Callable[[Tables], tuple[dict[str, set[str]], Tables]]:
    def edit(t: Tables) -> tuple[dict[str, set[str]], Tables]:
        key = t["note"][12]["note_no"]
        row = row_of(t, "note", key)
        row["text"] = text
        return {"note": {key}}, {"note": [dict(row)]}  # the right reading: the text as it is, whole

    return edit


def _lab_code(code: str, right: str | None) -> Callable[[Tables], tuple[dict[str, set[str]], Tables]]:
    def edit(t: Tables) -> tuple[dict[str, set[str]], Tables]:
        row = t["lab"][5]
        key = row["lab_no"]
        fixed = dict(row, local_code=right) if right else None
        row["local_code"] = code
        return {"lab": {key}}, ({"lab": [fixed]} if fixed else {})

    return edit


def _diag_code(code: str) -> Callable[[Tables], tuple[dict[str, set[str]], Tables]]:
    def edit(t: Tables) -> tuple[dict[str, set[str]], Tables]:
        row = row_of(t, "diagnosis", "D0102")
        row["icd10"] = code
        return {"diagnosis": {"D0102"}}, {"diagnosis": [dict(row)]}  # kept as itself (D-130) is right

    return edit


def _drug_code(t: Tables) -> tuple[dict[str, set[str]], Tables]:
    row = row_of(t, "medication", "M0101")
    row["nhi_drug_code"], row["atc"] = "ZZ99999999", ""
    return {"medication": {"M0101"}}, {"medication": [dict(row)]}


def _two_charts_one_person(t: Tables) -> tuple[dict[str, set[str]], Tables, Tables]:
    """Patient 7 has a second chart number (a re-registration): a second patient row with the same name, birth date
    and sex, and their third visit with its diagnosis, note and lab filed under it."""
    first = row_of(t, "patient", P7)
    second = dict(first, mrn=mrn(N_PATIENTS + 1))
    t["patient"].append(second)
    moved: dict[str, set[str]] = {}
    written: Tables = {"patient": [second]}
    for table, key in (("encounter", "E0072"), ("diagnosis", "D0072"), ("note", "N0072"), ("lab", "L0073")):
        row = row_of(t, table, key)
        moved.setdefault(table, set()).add(key)
        row["mrn"] = second["mrn"]
        written.setdefault(table, []).append(dict(row))
    return moved, {}, written  # the right reading (one patient) needs a person's merge: none is "correct" here


def _one_chart_two_people(t: Tables) -> tuple[dict[str, set[str]], Tables]:
    """Chart number of patient 7 given also to another, new person (a different birth date and sex) with a visit of
    their own: two patient rows with one chart number."""
    other = {"mrn": P7, "name": "Synthetic 77", "id_no": "", "birth_date": "1999-09-09", "sex": "M" if
             row_of(t, "patient", P7)["sex"] == "F" else "F", "death_date": "", "phone": ""}  # fmt: skip
    t["patient"].append(other)
    enc = {"enc_no": "E0779", "mrn": P7, "visit_datetime": "2026-10-09 11:11:00", "dept_code": "RHEU",
           "staff_id": "S0001", "enc_type": "OPD"}  # fmt: skip
    t["encounter"].append(enc)
    return {"patient": {P7}, "encounter": {"E0779"}}, {}


def _ssmix2_second_person(fmt: str, folder: Path, t: Tables) -> Any:
    """SS-MIX2: patient 7's folder gets a second person's ADT-00 (another birth date and sex) under a later time
    stamp, as a registration of another person under the same ID writes it."""
    f = ssmix2_files(folder, P7, "ADT-00")[0]
    raw = f.read_bytes()
    utf8 = b"UNICODE UTF-8" in raw[:200]
    segs = raw.decode("utf-8" if utf8 else "iso2022_jp").split("\r")
    row = row_of(t, "patient", P7)
    other = "M" if row["sex"] == "F" else "F"
    for n, s in enumerate(segs):
        if s.startswith("PID|"):
            fields = s.split("|")
            fields[7], fields[8] = "19990909", other
            segs[n] = "|".join(fields)
    parts = f.name.split("_")
    parts[4] = "20261101000001000"
    f.with_name("_".join(parts)).write_bytes("\r".join(segs).encode("utf-8" if utf8 else "iso2022_jp"))
    return {"patient": {P7}}


def build_cases() -> list[Case]:
    every, files = FORMATS, ("csv", "fhir_bulk", "ssmix2")
    no_sql = {"cgrd_sql": "the CGRD source is a database read through its driver: no file to cut, no bytes to "
              "decode, no line ending (the driver gives typed values)"}  # fmt: skip
    no_rows = {"fhir_bulk": "a FHIR export has no columns", "ssmix2": "an HL7 v2 message has no header row"}
    hl7 = {"fhir_bulk": "FHIR dates are typed: no ROC form is a valid FHIR date",
           "ssmix2": "HL7 v2 dates are typed (DTM): no ROC form is a valid HL7 date"}  # fmt: skip
    rows = _rows_edit
    raw = _bytes_edit
    c = [
        Case(
            "cut-mid-row",
            "cut off",
            "the file ends inside its last row, in a lab value (3.47 kept as 3.4)",
            files,
            raw(_cut_mid_row),
            "the cut row rejected and counted, or the file set aside; never a lab value "
            "short of its digits in the lake (STD-025, T-615a; T-615b)",
            not_applicable=no_sql,
        ),
        Case(
            "cut-mid-char",
            "cut off",
            "the file ends inside a multibyte character of its last row",
            files,
            raw(_cut_mid_char),
            "the file set aside with its reason (T-615b: no U+FFFD reaches a record) or "
            "the cut row rejected and counted; never a cut text in the lake",
            not_applicable=no_sql,
        ),
        Case(
            "cut-in-quotes",
            "cut off",
            "the file ends inside a quoted field (no closing quote)",
            ("csv",),
            raw(_cut_in_quotes),
            "the file set aside as not a readable CSV (T-615b), or the row rejected and counted",
            not_applicable={**no_sql, **no_rows},
        ),
        Case(
            "twice-same-name",
            "same file twice",
            "the same export delivered again the next night (same names)",
            every,
            raw(lambda f, d, t: {}),
            "the second night's lake equal to the first: no row twice (DATA-017: a "
            "duplicate key is counted; the last row wins)",
            nights=2,
        ),
        Case(
            "twice-other-name",
            "same file twice",
            "the lab file delivered again beside itself under another name",
            files,
            raw(_twice_other_name),
            "no row twice in the lake; the extra file read or said to be ignored",
            not_applicable=no_sql,
        ),
        Case(
            "twice-in-one-file",
            "same file twice",
            "the lab table's content twice in one delivery (concatenated "
            "with its header; SQL: every row inserted twice)",
            ("csv", "fhir_bulk", "cgrd_sql"),
            lambda fmt, cl, fo, wo: (
                Feed(write_sql(cl, fo, twice=True)) if fmt == "cgrd_sql" else raw(_twice_in_one_file)(fmt, cl, fo, wo)
            ),
            "no row twice in the lake; the duplicate keys counted (DATA-017); a header line read as a row is a row "
            "the mapping cannot read: rejected and counted",
            not_applicable={"ssmix2": "one message per file"},
        ),
        Case(
            "column-short",
            "wrong column count",
            "one lab row one field short",
            ("csv",),
            raw(_line_short),
            "the short row rejected and counted (STD-025), never mapped with an empty field taken as given",
            not_applicable={**no_sql, **no_rows},
        ),
        Case(
            "column-extra",
            "wrong column count",
            "one lab row one field more (a decimal comma: 2,35)",
            ("csv",),
            raw(_line_extra),
            "the row rejected and counted; never 2 for 2.35 in the lake",
            not_applicable={**no_sql, **no_rows},
        ),
        Case(
            "header-renamed",
            "wrong column count",
            "the lab file's header names the value column otherwise",
            ("csv",),
            raw(_header_renamed),
            "the table refused or held with its reason (a column the mapping "
            "needs is missing); never 200 results without a value served as complete",
            not_applicable={**no_sql, **no_rows},
        ),
        Case(
            "header-dropped",
            "wrong column count",
            "the lab table has no sample-time column",
            ("csv", "cgrd_sql"),
            raw(_header_dropped),
            "the table refused or held with its reason; never results without a date served as complete",
            not_applicable=no_rows,
        ),
        Case(
            "big5",
            "encoding",
            "the note file in Big5 (CP950) where UTF-8 is expected",
            files,
            raw(_recode("cp950")),
            "read as Big5, the same text in the lake (T-615b, D-215); or set aside with its reason; never mojibake",
            not_applicable=no_sql,
        ),
        Case(
            "big5-hkscs",
            "encoding",
            "the note file in Big5-HKSCS with one HKSCS-only character",
            ("csv",),
            raw(_recode("big5hkscs")),
            "read whole with that character, or set aside with its reason; never a "
            "replacement or a wrong character in the lake",
            not_applicable={
                **no_sql,
                "fhir_bulk": "JSON is Unicode by RFC 8259",
                "ssmix2": "SS-MIX2's character sets are ISO-2022-JP and UTF-8",
            },
        ),
        Case(
            "utf8-bom",
            "encoding",
            "UTF-8 with a byte-order mark",
            files,
            raw(_recode("utf-8", b"\xef\xbb\xbf")),
            "read as UTF-8, the first column's name not changed by the mark",
            not_applicable=no_sql,
        ),
        Case(
            "utf16",
            "encoding",
            "the note file in UTF-16 (with its byte-order mark)",
            files,
            raw(_recode("utf-16")),
            "read as UTF-16 or set aside with its reason; never mojibake",
            not_applicable=no_sql,
        ),
        Case(
            "big5-one-row",
            "encoding",
            "a UTF-8 note file with one row in Big5",
            ("csv",),
            raw(_one_big5_row),
            "the file set aside with the line (T-615b) or the row rejected and counted; never mojibake",
            not_applicable={**no_sql, "fhir_bulk": "JSON is Unicode by RFC 8259", "ssmix2": "one message per file"},
        ),
        Case(
            "date-zero",
            "dates",
            "a diagnosis dated 0000-00-00",
            ("csv", "cgrd_sql", "fhir_bulk"),
            rows(_diag_date("0000-00-00", None)),
            "the row rejected and counted, or the date left out and counted "
            "(D-589: a placeholder is empty); never a date of year 0 or 1",
            not_applicable={"ssmix2": "PPR-01 dates are written by the exporter from the CSV; see ssmix2-birth-zero"},
        ),
        Case(
            "date-roc-slash",
            "dates",
            "a diagnosis dated 113/02/29 (ROC year 113: 2024-02-29)",
            ("csv", "cgrd_sql"),
            rows(_diag_date("113/02/29", "2024-02-29")),
            "read as 2024-02-29 where the site declared ROC "
            "dates (D-589), else rejected and counted; never year 113 or 0113",
            not_applicable=hl7,
        ),
        Case(
            "date-roc-compact",
            "dates",
            "a diagnosis dated 1130229 (ROC, seven digits)",
            ("csv", "cgrd_sql"),
            rows(_diag_date("1130229", "2024-02-29")),
            "as date-roc-slash (DIN-001: seven digits are never the year 1130)",
            not_applicable=hl7,
        ),
        Case(
            "date-roc-words",
            "dates",
            "a diagnosis dated 民國113年2月29日",
            ("csv", "cgrd_sql"),
            rows(_diag_date("民國113年2月29日", "2024-02-29")),
            "as date-roc-slash",
            not_applicable=hl7,
        ),
        Case(
            "date-9999",
            "dates",
            "a diagnosis dated 9999-12-31",
            ("csv", "cgrd_sql", "fhir_bulk"),
            rows(_diag_date("9999-12-31", None)),
            "rejected and counted, or the date left out and counted (DIN-012: a placeholder is not a fact)",
            not_applicable={"ssmix2": "see ssmix2-birth-9999"},
        ),
        Case(
            "birth-after-visit",
            "dates",
            "a patient born after their visits (2026-10-01)",
            ("csv", "cgrd_sql", "fhir_bulk"),
            rows(_birth("2026-10-01")),
            "the birth date left out and counted, or "
            "the patient's rows held for a person; never served as is with no word",
            not_applicable={"ssmix2": "see ssmix2-birth-after-visit"},
        ),
        Case(
            "birth-zero",
            "dates",
            "a birth date 0000-00-00",
            ("csv", "cgrd_sql", "fhir_bulk"),
            rows(_birth("0000-00-00")),
            "the birth date left out and counted; the patient kept",
            not_applicable={"ssmix2": "see ssmix2-birth-zero"},
        ),
        Case(
            "ssmix2-birth-zero",
            "dates",
            "PID-7 (birth) 00000000",
            ("ssmix2",),
            raw(_ssmix2_pid_field(7, "00000000")),
            "the birth date left out and counted; the patient kept",
            not_applicable=dict.fromkeys(("csv", "cgrd_sql", "fhir_bulk"), "the same case for them: birth-zero"),
        ),
        Case(
            "ssmix2-birth-9999",
            "dates",
            "PID-7 (birth) 99991231",
            ("ssmix2",),
            raw(_ssmix2_pid_field(7, "99991231")),
            "the birth date left out and counted (DIN-012)",
            not_applicable=dict.fromkeys(("csv", "cgrd_sql", "fhir_bulk"), "the same case for them: date-9999"),
        ),
        Case(
            "ssmix2-birth-after-visit",
            "dates",
            "PID-7 (birth) 20261001, after the visits",
            ("ssmix2",),
            raw(_ssmix2_pid_field(7, "20261001")),
            "the birth date left out and counted, or held for a person",
            not_applicable=dict.fromkeys(("csv", "cgrd_sql", "fhir_bulk"), "the same case for them: birth-after-visit"),
        ),
        Case(
            "note-2mb",
            "notes",
            "a note of two megabytes",
            ("csv", "cgrd_sql", "fhir_bulk"),
            rows(_note_text(("病人無發燒。" * 120_000)[:700_000])),
            "the note kept whole, or rejected and counted; never cut, never the whole file set aside for one note",
            not_applicable={"ssmix2": "notes are extended storage (a CSV source): see the csv row"},
        ),
        Case(
            "note-nul",
            "notes",
            "a note with NUL bytes inside",
            ("csv", "cgrd_sql", "fhir_bulk"),
            rows(_note_text("before\x00after\x00 the NUL bytes")),
            "the note kept with the NULs taken out and "
            "counted, or rejected and counted; never the file set aside without the line",
            not_applicable={"ssmix2": "see the csv row"},
        ),
        Case(
            "note-blank",
            "notes",
            "a note of whitespace only",
            ("csv", "cgrd_sql", "fhir_bulk"),
            rows(_note_text("   \t  ")),
            "no empty document in the lake, or kept as it is; either said",
            not_applicable={"ssmix2": "see the csv row"},
        ),
        Case(
            "long-line",
            "line endings",
            "a note of 100,000 characters (a long line under the CSV field limit)",
            ("csv", "cgrd_sql", "fhir_bulk"),
            rows(_note_text("x" * 100_000)),
            "the note kept whole",
            not_applicable={"ssmix2": "see the csv row"},
        ),
        Case(
            "code-unknown-lab",
            "unknown code",
            "a lab local code in no table (ZZLAB)",
            ("csv", "cgrd_sql"),
            rows(_lab_code("ZZLAB", None)),
            "left out and counted by code (NEW-DIN-6, D-580: unmapped_codes.json)",
            not_applicable={
                "fhir_bulk": "FHIR carries LOINC itself: see code-unknown-loinc",
                "ssmix2": "the exporter writes only codes it knows",
            },
        ),
        Case(
            "code-trailing-space",
            "unknown code",
            "a lab local code with a trailing space (CRE )",
            ("csv", "cgrd_sql"),
            rows(_lab_code("CRE ", "CRE")),
            "read as CRE (D-587: blanks around a site's code are not part of it), or left out and counted",
            not_applicable={"fhir_bulk": "typed codes", "ssmix2": "typed codes"},
        ),
        Case(
            "code-lower-case",
            "unknown code",
            "a lab local code in lower case (cre)",
            ("csv", "cgrd_sql"),
            rows(_lab_code("cre", None)),
            "left out and counted, or read as CRE; either said",
            not_applicable={"fhir_bulk": "typed codes", "ssmix2": "typed codes"},
        ),
        Case(
            "code-unknown-dx",
            "unknown code",
            "a diagnosis code in no table (Q99.99X)",
            ("csv", "cgrd_sql", "fhir_bulk"),
            rows(_diag_code("Q99.99X")),
            "kept as itself (D-130: never an empty code), counted when a map was asked",
            not_applicable={"ssmix2": "the exporter writes only codes it knows"},
        ),
        Case(
            "code-unknown-drug",
            "unknown code",
            "a drug code in no table, no ATC (ZZ99999999)",
            ("csv", "cgrd_sql"),
            rows(_drug_code),
            "kept with its code, counted as not mapped (NEW-STD-5, D-689)",
            not_applicable={"fhir_bulk": "typed codes", "ssmix2": "the exporter writes only codes it knows"},
        ),
        Case(
            "code-unknown-loinc",
            "unknown code",
            "an Observation with a LOINC code the box does not know",
            ("fhir_bulk",),
            rows(_lab_code("ZZLAB", "ZZLAB")),
            "kept as itself, or left out; either counted (as NEW-DIN-6 counts a mapped source's codes)",
            not_applicable={
                "csv": "the same case for it: code-unknown-lab",
                "cgrd_sql": "code-unknown-lab",
                "ssmix2": "the exporter writes only codes it knows",
            },
        ),
        Case(
            "two-charts-one-person",
            "chart numbers",
            "one person with two chart numbers (a re-registration: same name, birth date and sex)",
            every,
            rows(_two_charts_one_person),
            "two patients in the lake, as the "
            "hospital's records are, until a person merges them (`adapter pid-merge`, T-659b); said if the box "
            "can see it",
        ),
        Case(
            "one-chart-two-people",
            "chart numbers",
            "one chart number on two patient rows of different people "
            "(SS-MIX2: a second person's ADT-00 in the same patient folder, newer)",
            every,
            lambda fmt, cl, fo, wo: (
                raw(_ssmix2_second_person)(fmt, cl, fo, wo)
                if fmt == "ssmix2"
                else rows(_one_chart_two_people)(fmt, cl, fo, wo)
            ),
            "the duplicate key counted and the night held for a person, or the "
            "chart refused; never one patient served with the other's birth date or visit (DATA-017 counts it)",
        ),
        Case(
            "empty-zero-bytes",
            "empty export",
            "the lab file of zero bytes",
            files,
            raw(_zero_bytes),
            "the table missing or empty: the night held with its reason (T-611); nothing removed silently",
            not_applicable=no_sql,
        ),
        Case(
            "empty-header-only",
            "empty export",
            "the lab file with its header only",
            ("csv",),
            raw(_header_only),
            "the night held: a table empty on the first night (NEW-DIN-8, T-611)",
            not_applicable={**no_sql, **no_rows},
        ),
        Case(
            "empty-folder",
            "empty export",
            "the export folder empty (SQL: a database with no table)",
            every,
            raw(_folder_empty),
            "the night held with every table named missing (T-611); H-32 found that an empty "
            "feed shows on no surface: cited, not repeated",
        ),
        Case(
            "crlf",
            "line endings",
            "every line ends CRLF (SS-MIX2: CR LF after each segment)",
            files,
            raw(_crlf),
            "read as the clean export",
            not_applicable=no_sql,
        ),
        Case(
            "lone-cr",
            "line endings",
            "every line ends with a lone CR (SS-MIX2: LF only)",
            files,
            raw(_lone_cr),
            "read as the clean export, or set aside with its reason; never one row of everything",
            not_applicable=no_sql,
        ),
        Case(
            "newline-in-field",
            "line endings",
            "a quoted note with a newline inside",
            ("csv", "cgrd_sql", "fhir_bulk"),
            rows(_note_text("first line\nsecond line, after a newline")),
            "the note kept whole with its newline",
            not_applicable={"ssmix2": "see the csv row"},
        ),
    ]
    return c


CASES = build_cases()
FAMILIES = ("cut off", "same file twice", "wrong column count", "encoding", "dates", "notes", "unknown code",
            "chart numbers", "empty export", "line endings")  # fmt: skip


# ------------------------------------------------------------------------------------------ the lake compared


def pid_of(fmt: str, key: bytes, m: str) -> str:
    """The lake's patient id of chart number ``m`` in format ``fmt`` (a bulk export's id is pseudonymised by type)."""
    if fmt == "fhir_bulk":
        from adapter.pipeline import bulk_id

        return bulk_id(key, "Patient", m)
    from tb_common.crypto import pid_for_mrn

    return pid_for_mrn(key, m)


def _num(v: Any) -> str:
    try:
        return f"{float(v):g}"
    except (TypeError, ValueError):
        return str(v)


def _t16(v: Any) -> str:
    return "" if v is None else str(v).replace(" ", "T")[:16]


def truth_tuples(fmt: str, key: bytes, t: Tables, only: dict[str, set[str]] | None = None) -> Counter[tuple[str, ...]]:
    """What the lake should hold of the rows of ``t`` (all, or only the keys in ``only``), as tuples."""
    out: Counter[tuple[str, ...]] = Counter()

    def want(table: str, r: dict[str, str]) -> bool:
        return only is None or r.get(KEYS[table]) in only.get(table, set())

    for r in t.get("patient", []):
        if want("patient", r):
            sex = {"M": "male", "F": "female"}.get(r.get("sex") or "", "unknown")
            out[("patient", pid_of(fmt, key, r["mrn"]), (r.get("birth_date") or "")[:10], sex)] += 1
    for r in t.get("encounter", []):
        if want("encounter", r):
            out[("encounter", pid_of(fmt, key, r["mrn"]), _t16(r["visit_datetime"]))] += 1
    for r in t.get("diagnosis", []):
        if want("diagnosis", r):
            out[("condition", pid_of(fmt, key, r["mrn"]), r["icd10"].strip(), (r.get("diag_date") or "")[:10])] += 1
    for r in t.get("lab", []):
        if want("lab", r):
            loinc = LABS.get(r["local_code"], (r["local_code"] if fmt == "fhir_bulk" else "",))[0]
            out[("lab", pid_of(fmt, key, r["mrn"]), loinc, _t16(r["sample_datetime"]), _num(r["result_value"]))] += 1
    for r in t.get("medication", []):
        if want("medication", r):
            out[("medication", pid_of(fmt, key, r["mrn"]), r["order_date"][:10])] += 1
    for r in t.get("note", []):
        if want("note", r):
            out[("document", pid_of(fmt, key, r["mrn"]), r["text"])] += 1
    return out


def lake_tuples(lake_dir: Path, snap: str) -> Counter[tuple[str, ...]] | None:
    """The same tuples read from the lake's own Parquet tables of ``snap``; None when the lake has no such night."""
    import pyarrow.parquet as pq

    folder = lake_dir / "parquet" / f"snapshot={snap}"
    if not folder.is_dir():
        return None
    out: Counter[tuple[str, ...]] = Counter()

    def rows(name: str) -> list[dict[str, Any]]:
        p = folder / f"{name}.parquet"
        return pq.read_table(p).to_pylist() if p.exists() else []

    for r in rows("patient"):
        out[("patient", r["pid"], "" if r["birth_date"] is None else str(r["birth_date"])[:10], str(r["sex"]))] += 1
    for r in rows("encounter"):
        out[("encounter", r["pid"], _t16(r["start"]))] += 1
    for r in rows("condition"):
        out[("condition", r["pid"], str(r["code"] or ""), "" if r["onset"] is None else str(r["onset"])[:10])] += 1
    for r in rows("observation"):
        if r.get("category") == "laboratory":
            out[("lab", r["pid"], str(r["code"] or ""), _t16(r["effective"]), _num(r["value_num"]))] += 1
    for r in rows("medication"):
        out[("medication", r["pid"], "" if r["authored"] is None else str(r["authored"])[:10])] += 1
    for r in rows("document"):
        out[("document", r["pid"], str(r["text"] or ""))] += 1
    return out


def _odd(text: str) -> bool:
    return "\ufffd" in text or any("\uff61" <= ch <= "\uff9f" for ch in text)


def garbled(folder: Path) -> int:
    """Strings in the snapshot's NDJSON (what the FHIR store and every reader of the night get) holding a replacement
    character or half-width katakana: the marks of bytes read in the wrong character set. The clean export has none."""
    n = 0

    def walk(x: Any) -> None:
        nonlocal n
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str) and _odd(x):
            n += 1

    for f in sorted(folder.glob("*.ndjson")):
        with f.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    walk(json.loads(line))
    return n


def describe(tup: tuple[str, ...]) -> str:
    """A tuple in words for the results: its kind and the shape of its values, never a whole note or a pid."""
    kind = tup[0]
    if kind == "patient":
        return f"patient birth={tup[2] or 'none'} sex={tup[3]}"
    if kind == "lab":
        return f"lab {tup[2] or 'no LOINC'} at {tup[3]} value={tup[4]}"
    if kind == "document":
        text = tup[2]
        bad = sum(1 for ch in text if ch == "\ufffd" or (0x80 <= ord(ch) < 0x2E80 and ch not in "，。："))
        return f"document of {len(text)} characters ({bad} not from the file's script)"
    if kind == "condition":
        return f"condition {tup[2]!r} onset={tup[3] or 'none'}"
    return f"{kind} {' '.join(tup[2:])}"


# ------------------------------------------------------------------------------------------------- running


@dataclass
class Run:
    case: str
    family: str
    fmt: str
    exit: int | None = None
    traceback: bool = False
    exception: str = ""
    passed: bool | None = None
    held: bool | None = None
    errors: list[str] = field(default_factory=list)
    read: dict[str, int] = field(default_factory=dict)  # table -> rows read
    counted: dict[str, dict[str, Any]] = field(default_factory=dict)  # table -> what completeness.json counted
    told: dict[str, Any] = field(default_factory=dict)  # the report, the steward's row, the audit
    served: bool = False
    good_kept: str = ""  # "all", "held", "n of m lost"
    wrong: list[str] = field(default_factory=list)  # silently wrong in the lake (described)
    doubled: int = 0
    lost: int = 0
    bad_rows: int = 0  # source rows the case made bad
    bad_in_lake: int = 0  # of those, how many reached the lake in their right reading
    bad_as_written: int = 0  # of those, how many reached the lake as the hospital wrote them (D-1100)
    bad_absent: int = 0  # of those, how many are not in the lake at all
    wrong_total: int = 0
    garbled: int = 0  # strings of the served snapshot with U+FFFD or half-width katakana (none in the clean export)
    lake_rebuilt: bool = False
    feas: str = ""
    seconds: float = 0.0
    verdict: dict[str, str] = field(default_factory=dict)


def _db_url(base: str) -> str:
    """``base`` with a table prefix of this run's own (one given already, as the test suite's, is replaced)."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    u = urlsplit(base)
    q = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if k != "tb_prefix"]
    q.append(("tb_prefix", f"h34{uuid.uuid4().hex[:10]}_"))
    return urlunsplit(u._replace(query=urlencode(q, safe="/")))


def _env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def box_env(work: Path, fmt: str, feed: str, db_base: str) -> dict[str, str]:
    """The environment of one box: a settings file written by the settings wizard (the rehearsal's answers, this
    feed and mapping), its .env, and the folders of this run. No secret of any real box is read."""
    import yaml

    from tools import settings_wizard

    answers = yaml.safe_load((ROOT / "tools/rehearse_box/site_answers.yaml").read_text(encoding="utf-8"))
    answers.update({"data_source_type": fmt, "data_source_path": feed if fmt != "cgrd_sql" else "",
                    "data_source_host_dir": feed if fmt != "cgrd_sql" else "", "mapping": MAPPINGS[fmt],
                    "llm_mode": "stub"})  # fmt: skip
    if fmt == "ssmix2":  # a Japanese site: the wizard refuses a zone other than the mapping's
        answers.update({"tz": mapping_tz(fmt), "locale": "ja"})
    if fmt == "cgrd_sql":
        answers["data_source_type"] = "csv"  # the DSN is given on the command line (`--dsn`), as a night's run may
        answers.update({"data_source_path": str(work), "data_source_host_dir": str(work)})
    settings, env, _ = settings_wizard.build(answers, [ROOT / "services/adapter"])
    settings_wizard.write(settings, env, work / "settings.yaml", work / ".env")
    out = {k: v for k, v in os.environ.items() if not k.startswith("TB_")}
    out.update({k: v for k, v in _env_file(work / ".env").items() if k == "TB_CHARTNO_RULE"})
    out.update({
        "TB_ENV": "TEST", "TB_SETTINGS": str(work / "settings.yaml"), "TB_SETTINGS_FILE": str(work / "settings.yaml"),
        "TB_LAKE_DIR": str(work / "lake"), "TB_SECRETS_DIR": str(work / "secrets"), "TB_AUDIT_DIR": str(work / "audit"),
        "TB_ADAPTER_LAKE": "local", "TB_LAKE_EMBEDDER": "hash", "TB_MAPPING_DIR": str(work / "no-site-mapping"),
        "PYTHONPATH": "libs:services:.", "TB_DB_URL": _db_url(db_base), "TMPDIR": str(work / "tmp"),
    })  # fmt: skip
    (work / "tmp").mkdir(exist_ok=True)
    return out


def _night(env: dict[str, str], fmt: str, feed: str, snap: str) -> subprocess.CompletedProcess[str]:
    where = ["--dsn", feed] if fmt == "cgrd_sql" else ["--path", feed]
    cmd = [PY, "-m", "adapter.cli", "run", "--source", fmt, *where, "--snapshot", snap, "--no-fhir"]
    return subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=900, check=False)


def _exception(stderr: str) -> str:
    """The traceback's last line, its type and at most 120 characters (a parser's message may quote bytes)."""
    lines = [ln for ln in stderr.splitlines() if ln and not ln.startswith((" ", "{", "Traceback"))]
    return lines[-1][:120] if lines else ""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


READER_USUAL = ("ADT-52:class change", "OMP-11:with its order", "OMP-11:without an order", "medication:ingredient")
COUNT_KEYS = ("rejected", "duplicate_keys", "set_aside", "implausible_dates", "unmapped", "rows_of_other_tables",
              "read_as_western", "mapped", "change_time_not_a_date")  # fmt: skip


def _steward(env: dict[str, str]) -> dict[str, Any]:
    """The night's batch row as the steward's page reads it (state and the detail keys it keeps)."""
    try:
        from datacore.dataops import DataOps

        ops = DataOps(env["TB_DB_URL"])
        try:
            rows = ops.history(limit=1)
        finally:
            ops.close()
    except Exception as exc:  # the row is what a person is told; a failure to read it is recorded, not raised
        return {"error": type(exc).__name__}
    if not rows:
        return {"state": "no batch row"}
    b = rows[0]
    return {"state": b.state, "detail": sorted(k for k, v in (b.detail or {}).items() if v)}


def _feas(lake_dir: Path, tz: str) -> str:
    """One FEAS computation over the served lake, as the orchestrator's job computes it (GOUT-COH, 36 months)."""
    try:
        from embed_service.embedder import HashEmbedder
        from lake.client import LakeLocal
        from orchestrator.scenarios.feas_compute import FeasParams, compute
        from tb_common.ruleset import Ruleset

        snap = (lake_dir / "CURRENT").read_text(encoding="utf-8").strip() if (lake_dir / "CURRENT").exists() else ""
        if not snap:
            return "no night served: FEAS has no lake to read"
        rs = Ruleset.load(ROOT / "rulesets" / "GOUT-COH")
        _, raw = compute(LakeLocal(lake_dir, HashEmbedder(), tz), rs,
                         FeasParams(run_date=FEAS_REF, snapshot=snap, lookback_months=36))  # fmt: skip
        return f"ran: {raw.start_n} patients in the funnel's start"
    except Exception as exc:
        return f"failed: {type(exc).__name__}"


def run_one(case: Case, fmt: str, clean: Tables, scratch: Path, db_base: str,
            reference: dict[str, Counter[tuple[str, ...]]] | None = None) -> Run:  # fmt: skip
    """One case in one format: the feed made, the night(s) run through the CLI, the lake compared."""
    started = time.monotonic()
    work = scratch / f"{case.id}--{fmt}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    feed = case.build(fmt, clean, work / "feed", work)
    env = box_env(work, fmt, feed.path, db_base)
    run = Run(case.id, case.family, fmt)
    keys = subprocess.run([PY, "-m", "adapter.cli", "keys-init"], cwd=ROOT, env=env, capture_output=True, text=True,
                          check=False)  # fmt: skip
    if keys.returncode != 0:
        run.exception = "keys-init failed"
        return run
    snap = NIGHT
    if case.nights == 2:
        _night(env, fmt, feed.path, NIGHT)
        snap = NIGHT2
    proc = _night(env, fmt, feed.path, snap)
    (work / "stderr.txt").write_text(proc.stderr, encoding="utf-8")
    run.exit = proc.returncode
    run.traceback = "Traceback (most recent call last)" in proc.stderr
    if run.traceback:
        run.exception = _exception(proc.stderr)
    lake_dir = work / "lake"
    night = lake_dir / "ndjson" / snap
    report = _read_json(night / "ingest_report.json") or {}
    comp = _read_json(night / "completeness.json") or {}
    if report:
        run.passed, run.held = bool(report.get("passed")), bool(report.get("held"))
        run.errors = [str(e).replace(str(work), "<run folder>")[:300] for e in report.get("errors") or []]
        run.lake_rebuilt = report.get("lake") is not None
    for table, info in sorted((comp.get("tables") or {}).items()):
        run.read[table] = int(info.get("rows") or 0)
        said = {k: info[k] for k in COUNT_KEYS if info.get(k)}
        if said:
            run.counted[table] = said
    reader = _reader(night / "reader.json")
    odd = {k: v for k, v in (reader.get("read") or {}).items() if ":" in k and k not in READER_USUAL}
    if odd:  # the SS-MIX2 reader's own counts of files it set aside or read otherwise (reader.json)
        run.counted["reader.json"] = odd
    unmapped = _read_json(night / "unmapped_codes.json")
    run.told = {
        "report_errors": len(run.errors),
        "counts_file": sorted(run.counted),
        "unmapped_codes_file": sorted(unmapped) if isinstance(unmapped, dict) else [],
        "steward": _steward(env),
        "quarantine_folder": sorted(p.name for p in (Path(feed.path) / "quarantine").glob("*"))
        if fmt != "cgrd_sql" and (Path(feed.path) / "quarantine").is_dir() else [],
        "audit": _audit(work / "audit"),
        "reader": reader,
    }  # fmt: skip
    cur = (lake_dir / "CURRENT").read_text(encoding="utf-8").strip() if (lake_dir / "CURRENT").exists() else ""
    run.served = cur == snap
    site_key = (work / "secrets" / "site_hmac.key").read_bytes()
    ref = (reference or {}).get(fmt)
    if ref is None:
        ref = truth_tuples(fmt, site_key, clean)
    else:  # the clean night's lake, re-keyed: each run has its own site key
        ref = _rekey(ref, fmt, site_key, clean)
    touched = truth_tuples(fmt, site_key, clean, feed.touched) if feed.touched else Counter()
    good = ref - touched
    allowed = truth_tuples(fmt, site_key, feed.correct) if feed.correct else Counter()
    written = truth_tuples(fmt, site_key, feed.as_written) if feed.as_written else Counter()
    run.bad_rows = sum(len(v) for v in feed.touched.values()) or sum(len(v) for v in feed.as_written.values())
    if run.served:
        got = lake_tuples(lake_dir, snap) or Counter()
        extra = got - good - allowed - touched - written
        run.doubled = sum(n - 1 for tup, n in got.items() if n > 1)
        lost = good - got
        run.lost = sum(lost.values())
        run.wrong = [describe(tup) for tup in sorted(extra)][:8]
        run.wrong_total = sum(extra.values())
        run.bad_in_lake = sum(((touched + allowed) & got).values())
        run.bad_as_written = sum((written & got).values())
        run.bad_absent = max(
            0, run.bad_rows - run.bad_in_lake - run.bad_as_written - min(run.bad_rows, run.wrong_total)
        )
        run.good_kept = "all" if not lost else f"{run.lost} of {sum(good.values())} lost"
        run.garbled = garbled(night)
    else:
        run.good_kept = "held: nothing served" if run.held else "no night served"
    run.feas = _feas(lake_dir, mapping_tz(fmt))
    run.seconds = round(time.monotonic() - started, 1)
    run.verdict = judge(run)
    return run


def _rekey(ref: Counter[tuple[str, ...]], fmt: str, key: bytes, clean: Tables) -> Counter[tuple[str, ...]]:
    """The reference tuples carry the reference run's pids; give them this run's (the same chart numbers)."""
    old_to_new: dict[str, str] = {}
    for r in clean["patient"]:
        old_to_new[_REF_PIDS[fmt][r["mrn"]]] = pid_of(fmt, key, r["mrn"])
    out: Counter[tuple[str, ...]] = Counter()
    for tup, n in ref.items():
        out[(tup[0], old_to_new.get(tup[1], tup[1]), *tup[2:])] += n
    return out


_REF_PIDS: dict[str, dict[str, str]] = {}


def _said(k: str, v: Any) -> str:
    if k == "rejected" and isinstance(v, dict):
        return "rejected " + ", ".join(f'{n} "{why}"' for why, n in v.items())
    if k == "set_aside":
        return "file set aside"
    return f"{k} {sum(_flat(v)) if isinstance(v, dict) else v}"


def judge(run: Run) -> dict[str, str]:
    """The page's cells for one run (D-1100's words)."""
    states = {0: "0 published", 1: "1 held" if run.held else "1 failed", 2: "2 refused"}
    exit_cell = "crash (traceback)" if run.traceback else states.get(run.exit or 0, str(run.exit))
    counted = "; ".join(f"{t}: " + ", ".join(_said(k, v) for k, v in said.items()) for t, said in run.counted.items())
    reason = " \u2016 ".join(e for e in run.errors if not e.startswith("night held:"))[:400]
    if not run.served:
        wrong = "not served"
    elif run.wrong_total or run.doubled or run.garbled:
        parts = [f"{run.wrong_total} wrong"] if run.wrong_total else []
        parts += [f"{run.doubled} doubled"] if run.doubled else []
        parts += [f"{run.garbled} garbled texts in the snapshot"] if run.garbled else []
        wrong = "YES: " + ", ".join(parts)
    elif run.bad_as_written:
        wrong = f"kept as written: {run.bad_as_written}" + ("" if run.counted else ", not counted")
    else:
        wrong = "no"
    if run.served and run.bad_absent and not run.counted:
        counted = f"UNCOUNTED: {run.bad_absent} bad rows absent, nothing counted"
    goes_on = ("yes" if run.served and run.lake_rebuilt and run.feas.startswith("ran") else
               "held (lake keeps the previous night)" if run.held else
               "no: " + (run.exception or "the night did not end"))  # fmt: skip
    return {
        "exit": exit_cell,
        "counted": counted or "nothing counted",
        "reason": reason or "none (no error line)",
        "good_kept": run.good_kept,
        "wrong": wrong,
        "goes_on": goes_on,
        "feas": run.feas,
    }


def _reader(path: Path) -> dict[str, Any]:
    """The SS-MIX2 reader's own counts (``reader.json``), only what is not zero."""
    doc = _read_json(path)
    if not isinstance(doc, dict):
        return {}

    def keep(v: Any) -> Any:
        if isinstance(v, dict):
            out = {k: keep(x) for k, x in v.items()}
            return {k: x for k, x in out.items() if x not in (0, None, {}, [], "")}
        return v

    kept: dict[str, Any] = keep(doc)
    return kept


def _audit(folder: Path) -> dict[str, Any]:
    """The night's last ``ingest.*`` audit event: its name and the detail keys that hold something."""
    last: dict[str, Any] = {}
    for f in sorted(folder.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if str(ev.get("event", "")).startswith("ingest."):
                last = ev
    if not last:
        return {}
    return {"event": last.get("event"), "detail": sorted(k for k, v in (last.get("detail") or {}).items() if v)}


def _flat(v: Any) -> Iterable[int]:
    if isinstance(v, dict):
        for x in v.values():
            yield from _flat(x)
    elif isinstance(v, bool | int | float):
        yield int(v)


def reference_run(fmt: str, clean: Tables, scratch: Path, db_base: str) -> tuple[Run, Counter[tuple[str, ...]]]:
    """The clean export through the night: the lake compared with the generator's own truth."""
    case = Case("clean", "clean", "the clean export", FORMATS, _rows_edit(lambda t: ({}, {})), "every row in the lake")
    run = run_one(case, fmt, clean, scratch, db_base)
    work = scratch / f"clean--{fmt}"
    key = (work / "secrets" / "site_hmac.key").read_bytes()
    _REF_PIDS[fmt] = {r["mrn"]: pid_of(fmt, key, r["mrn"]) for r in clean["patient"]}
    got = lake_tuples(work / "lake", NIGHT) or Counter()
    return run, got


def db_base_url(scratch: Path) -> tuple[str, Path | None]:
    """``TB_DB_URL`` when set; else a throwaway cluster of ``tools.pglocal`` in the scratch folder (and its root, to
    stop it after the run). Every run gets its own table prefix on it."""
    url = os.environ.get("TB_DB_URL")
    if url:
        return url, None
    from tools import pglocal

    return pglocal.ensure(scratch / "pg"), scratch / "pg"


def run_all(scratch: Path, formats: Iterable[str] = FORMATS, cases: Iterable[str] | None = None,
            workers: int = 4) -> dict[str, Any]:  # fmt: skip
    scratch.mkdir(parents=True, exist_ok=True)
    db, cluster = db_base_url(scratch)
    try:
        return _run_all(scratch, db, formats, cases, workers)
    finally:
        if cluster is not None:
            from tools import pglocal

            pglocal.stop(cluster)


def _run_all(scratch: Path, db: str, formats: Iterable[str], cases: Iterable[str] | None,
             workers: int) -> dict[str, Any]:  # fmt: skip
    clean = clean_export()
    fmts = [f for f in formats if f in FORMATS]
    wanted = [c for c in CASES if cases is None or c.id in set(cases)]
    refs: dict[str, Counter[tuple[str, ...]]] = {}
    clean_runs: dict[str, dict[str, Any]] = {}
    for fmt in fmts:
        run, got = reference_run(fmt, clean, scratch, db)
        truth = truth_tuples(fmt, (scratch / f"clean--{fmt}" / "secrets" / "site_hmac.key").read_bytes(), clean)
        refs[fmt] = got
        clean_runs[fmt] = {**asdict(run), "equal_to_truth": got == truth,
                           "missing_from_lake": sum((truth - got).values()),
                           "extra_in_lake": sum((got - truth).values()),
                           "missing_kinds": sorted({t[0] for t in truth - got}),
                           "extra_kinds": sorted({t[0] for t in got - truth})}  # fmt: skip
    jobs = [(c, f) for c in wanted for f in fmts if f in c.formats]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        runs = list(pool.map(lambda cf: run_one(cf[0], cf[1], clean, scratch, db, refs), jobs))
    na = [{"case": c.id, "format": f, "why": c.not_applicable.get(f, "not built for this format")}
          for c in wanted for f in fmts if f not in c.formats]  # fmt: skip
    return {
        "card": "H-34",
        "decision": "D-1100",
        "entry_point": "python -m adapter.cli run --source <kind> --path|--dsn <feed> --snapshot <night> --no-fhir "
        "(the box's settings from the settings wizard; TB_ADAPTER_LAKE=local)",
        "patients": N_PATIENTS,
        "clean": clean_runs,
        "runs": [asdict(r) for r in runs],
        "not_applicable": na,
        "not_built": NOT_BUILT,
    }


def table_markdown(results: dict[str, Any]) -> str:
    """The page's one table: case x format -> exit, counted, reason, good rows kept, silently wrong, night goes on."""
    head = (
        "| Case | Format | Exit | Counted (completeness.json, reader.json) | Reason given (ingest_report.json) "
        "| Good rows kept | Silently wrong in the lake | Night goes on |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
    )
    lines = []
    for r in results["runs"]:
        v = r["verdict"]
        cells = [r["case"], r["fmt"], v["exit"], v["counted"], v["reason"], v["good_kept"], v["wrong"], v["goes_on"]]
        lines.append("| " + " | ".join(str(c).replace("|", "\\|").replace("\n", " ") for c in cells) + " |")
    for n in results["not_applicable"]:
        lines.append(f"| {n['case']} | {n['format']} | not applicable: {n['why']} | | | | | |")
    for fmt, why in results["not_built"].items():
        lines.append(f"| every case | {fmt} | does not exist yet: {why} | | | | | |")
    return head + "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="imperfect_feed", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    ap.add_argument("--out", type=Path, help="the scratch folder (feeds, lakes, results.json)")
    ap.add_argument("--formats", default=",".join(FORMATS))
    ap.add_argument("--cases", help="comma-separated case ids (default: all)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--table", action="store_true", help="print the page's table")
    ap.add_argument("--list", action="store_true", help="list the cases")
    args = ap.parse_args(argv)
    if args.list:
        for c in CASES:
            print(f"{c.id:24} {c.family:20} {','.join(c.formats)}")
        return 0
    if args.out is None:
        ap.error("--out is required")
    sys.path[:0] = [str(ROOT / "libs"), str(ROOT / "services"), str(ROOT)]
    results = run_all(args.out, args.formats.split(","), args.cases.split(",") if args.cases else None,
                      args.workers)  # fmt: skip
    out = args.out / "results.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    crashes = sum(1 for r in results["runs"] if r["traceback"])
    wrong = sum(1 for r in results["runs"] if r["verdict"]["wrong"].startswith("YES"))
    print(f"imperfect_feed: {len(results['runs'])} runs; {crashes} crashed; {wrong} with silently wrong data in the "
          f"lake; results in {out}")  # fmt: skip
    for fmt, c in results["clean"].items():
        print(
            f"  clean {fmt}: exit {c['exit']}, equal to the generator's truth: {c['equal_to_truth']} "
            f"(missing {c['missing_from_lake']} {c['missing_kinds']}, extra {c['extra_in_lake']} {c['extra_kinds']})"
        )
    if args.table:
        print(table_markdown(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
