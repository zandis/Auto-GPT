"""A synthetic site built from a schema and code lists (T-011; WS-10.2, WS-11.2; TB-SITE-03).

The site survey (TB-SITE-01 questions 24 to 35) gives a site's structure: its input, table headers, code lists, the
lab table with units, the character set, the date format, the provider field, the appointment source and the note
types. Written down as ``site-schema.yaml`` (``schemas/site_schema.schema.json``; structure only, never a patient
value), it is enough to build a synthetic site **in the site's own layout** that a mapping YAML can be developed
against. No site data reaches the developer; the steward applies the finished mapping on the hospital's hardware,
and only the report (counts, unmapped codes, parse errors, never a value) leaves the hospital.

The synthetic site has synthetic patients (no names; chart numbers ``SYNT-0001`` that no site format can match),
the site's encoding, date format and delimiter, and two kinds of planted faults: lab codes the mapping does not know
(``plants.unmapped_lab``) and results in a unit the lookup does not expect (``plants.unit_mismatch``; the adapter must
give them no value, never a wrong one: R-31, D-215).

    python -m tools.synth_site_from_schema validate <schema.yaml>
    python -m tools.synth_site_from_schema build <schema.yaml> --out <dir> [--patients 500] [--seed 1]
    python -m tools.synth_site_from_schema check <schema.yaml> --out <dir> --mapping <mapping.yaml> [--json]
    python -m tools.synth_site_from_schema scan-pattern <schema.yaml>

``check`` reads the site's files as the schema describes them (re-encoded to UTF-8, dates to ISO, in a staging
folder beside the output when the adapter cannot read them as they are), runs ``tools/mapping_check.py`` with the
mapping, and prints the report without any value. ``scan-pattern`` prints the data-scan pattern for a bare chart
number of the site's stated form (D-203: added to ``tools/data_scan_patterns.yaml`` once a signed survey states it).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import shutil
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
for _p in ("libs", "services"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

STAMP = "20261101000000000"
REF = date(2026, 11, 1)  # the synthetic site's "today"
MAX_PATIENTS = 9999  # chart numbers SYNT-0001 .. SYNT-9999: never five digits in a row (data scan, D-203)
# keys that would carry a value of a record; a schema file has structure and code lists only
VALUE_KEYS = {"value", "values", "example", "examples", "sample", "samples", "rows", "data", "default"}
CANON = re.compile(r"[a-z_][a-z0-9_]*")  # a canonical column name (templates/CANONICAL.md)
DATE_COLS = {"birth_date", "diag_date", "recorded_date", "order_date", "start_date", "end_date", "death_date"}
DT_COLS = {"visit_datetime", "appt_datetime", "sample_datetime", "note_datetime"}
CODECS = {
    "utf-8": "utf-8",
    "shift_jis": "shift_jis",
    "cp932": "cp932",
    "big5": "big5",
    "cp950": "cp950",
    "iso-2022-jp": "iso2022_jp",
}
STANDARD_TABLES = ("patient", "encounter", "diagnosis", "medication", "lab")  # SS-MIX2 standardized storage
EXTENDED_TABLES = ("practitioner", "appointment", "note")  # <root>/extended/<table>.csv
NOTE_TEXT = {
    "progress": "Synthetic progress note. Follow-up visit; symptoms stable; plan unchanged.",
    "admission": "Synthetic admission note. Admitted for observation; vital signs stable.",
    "discharge": "Synthetic discharge summary. Course uneventful; discharged home.",
    "consult": "Synthetic consult note. Opinion requested; no change advised.",
    "nursing": "Synthetic nursing note. Comfortable overnight; no events.",
}


class SchemaError(ValueError):
    """The schema file is not a site schema (or carries a value)."""


# ------------------------------------------------------------------------------------------------ the schema
def _value_keys(node: Any, path: str = "") -> list[str]:
    """Paths of keys that would hold a record's value. A table's ``columns`` are header names (a header may well be
    called ``VALUE``), so their keys are not read as such."""
    out: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            here = f"{path}/{k}" if path else str(k)
            if str(k).lower() in VALUE_KEYS:
                out.append(here)
            if not re.fullmatch(r"tables/[^/]+/columns", here):
                out += _value_keys(v, here)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += _value_keys(v, f"{path}/{i}")
    return out


def check_schema(doc: Any) -> list[str]:
    """Every reason ``doc`` is not a valid site schema (empty when it is)."""
    if not isinstance(doc, dict):
        return ["<root>: a site schema is a mapping"]
    found = _value_keys(doc)
    if found:
        return [f"{p}: no values in a schema file (structure and code lists only)" for p in found]
    from tb_contracts.schema import schema_errors

    errs = schema_errors("site_schema", doc)
    if errs:
        return errs
    feed, tables = doc["feed"], doc.get("tables") or {}
    if feed["layout"] == "ssmix2":
        errs += [f"tables/{t}: SS-MIX2 standardized storage has no header row" for t in tables if t in STANDARD_TABLES]
        if feed["encoding"] not in ("iso-2022-jp", "utf-8"):
            errs.append("feed/encoding: SS-MIX2 messages are ISO-2022-JP (MSH-18 ~ISO IR87) or UTF-8")
    else:
        need = ["patient", "encounter", "lab"]
        errs += [f"tables/{t}: a {feed['layout']} feed needs this table" for t in need if t not in tables]
    for t, spec in tables.items():
        cols = list(spec["columns"].values())
        if len(set(cols)) != len(cols):
            errs.append(f"tables/{t}/columns: a canonical column twice")
        errs += [f"tables/{t}/columns: {c!r} is not a canonical column name" for c in cols if not CANON.fullmatch(c)]
        key = {"patient": "mrn", "lab": "lab_no", "encounter": "enc_no"}.get(t)
        if key and key not in cols:
            errs.append(f"tables/{t}/columns: no column for {key}")
    codec = CODECS[feed["encoding"]]  # the code lists' names travel in the site's character set
    for where, text in _texts(doc["code_lists"], "code_lists") + _texts(doc.get("plants") or {}, "plants"):
        try:
            text.encode(codec)
        except UnicodeEncodeError:
            errs.append(f"{where}: {feed['encoding']} cannot hold this text")
    labs = {x["code"] for x in doc["code_lists"]["lab"]}
    plants = doc.get("plants") or {}
    errs += [
        f"plants/unmapped_lab: {x['code']} is in code_lists/lab"
        for x in plants.get("unmapped_lab", [])
        if x["code"] in labs
    ]
    errs += [
        f"plants/unit_mismatch: {x['code']} is not in code_lists/lab"
        for x in plants.get("unit_mismatch", [])
        if x["code"] not in labs
    ]
    return errs


def _texts(node: Any, path: str) -> list[tuple[str, str]]:
    if isinstance(node, dict):
        return [t for k, v in node.items() for t in _texts(v, f"{path}/{k}")]
    if isinstance(node, list):
        return [t for i, v in enumerate(node) for t in _texts(v, f"{path}/{i}")]
    return [(path, node)] if isinstance(node, str) else []


def load_schema(path: Path) -> dict[str, Any]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    errs = check_schema(doc)
    if errs:
        raise SchemaError(f"{path}: " + "; ".join(errs[:20]))
    return dict(doc)


# ------------------------------------------------------------------------------------------------ formats
def fmt_date(d: date, fmt: str) -> str:
    if fmt == "roc7":
        return f"{d.year - 1911:03d}{d.month:02d}{d.day:02d}"
    if fmt == "yyyymmdd":
        return d.strftime("%Y%m%d")
    if fmt == "slash":
        return d.strftime("%Y/%m/%d")
    return d.isoformat()


def fmt_dt(t: datetime, fmt: str) -> str:
    if fmt == "roc7":
        return f"{fmt_date(t.date(), fmt)} {t:%H:%M}"
    if fmt == "yyyymmdd":
        return t.strftime("%Y%m%d%H%M%S")
    if fmt == "slash":
        return t.strftime("%Y/%m/%d %H:%M")
    return t.strftime("%Y-%m-%d %H:%M:%S")


def iso_date(raw: str, fmt: str) -> str:
    """A date in the site's format -> ISO (the staging step; anything unreadable stays as it is)."""
    raw = (raw or "").strip()
    if not raw:
        return raw
    if fmt == "roc7":
        from tb_common.refdata_tw import roc

        return roc(raw)
    return raw


def iso_dt(raw: str, fmt: str) -> str:
    raw = (raw or "").strip()
    if fmt != "roc7" or not raw:
        return raw
    day, _, time = raw.partition(" ")
    return f"{iso_date(day, fmt)} {time}:00".strip() if time else iso_date(day, fmt)


# ------------------------------------------------------------------------------------------------ generation
def _sid(tag: str, n: int) -> str:
    """A record id with no five digits in a row (the data scan reads runs of digits as identifiers)."""
    return f"{tag}{n // 10000}-{n % 10000:04d}"


def mrn(n: int) -> str:
    return f"SYNT-{n:04d}"


def generate(schema: dict[str, Any], patients: int = 500, seed: int = 1) -> dict[str, list[dict[str, str]]]:
    """Canonical rows per table (``templates/CANONICAL.md`` column names), values in the site's codes, dates still
    as ``date`` / ``datetime`` objects (the writer formats them)."""
    if not 1 <= patients <= MAX_PATIENTS:
        raise SchemaError(f"patients: 1 to {MAX_PATIENTS}")
    rng = random.Random(int(hashlib.sha256(f"{schema['site']}:{seed}".encode()).hexdigest()[:12], 16))
    cl = schema["code_lists"]
    sex = cl.get("sex") or {"M": "M", "F": "F"}
    etype = {"OPD": "OPD", "IPD": "IPD", "ER": "ER", **(cl.get("encounter_type") or {})}
    depts = [d["code"] for d in cl.get("department") or [{"code": "IM"}]]
    labs = cl["lab"]
    dxs = cl.get("diagnosis") or []
    drugs = cl.get("drug") or []
    plants = schema.get("plants") or {}
    share = float(plants.get("share", 0.05))
    unmapped, mismatch = plants.get("unmapped_lab") or [], plants.get("unit_mismatch") or []
    lab_by_code = {x["code"]: x for x in labs}
    provider = schema.get("provider") or {"in_encounter": True, "directory": True}
    note_types = (schema.get("notes") or {}).get("types") or []
    out: dict[str, list[dict[str, Any]]] = {t: [] for t in ("patient", "practitioner", "encounter", "appointment")}
    out |= {t: [] for t in ("diagnosis", "lab", "medication", "note")}
    staff = [f"SYN-DR-{i:02d}" for i in range(1, 9)]
    if provider.get("directory", True):
        for i, s in enumerate(staff):
            out["practitioner"].append(
                {"staff_id": s, "name": f"Dr SYN-{i + 1:02d}", "dept_code": depts[i % len(depts)]}
            )
    plant_cycle = [("unmapped", x) for x in unmapped] + [("mismatch", x) for x in mismatch]
    every = max(1, round(1 / share)) if plant_cycle else 0
    n_lab = n_enc = n_dx = n_rx = n_note = n_appt = 0
    for p in range(1, patients + 1):
        m = mrn(p)
        born = date(rng.randint(1940, 2005), rng.randint(1, 12), rng.randint(1, 28))
        out["patient"].append({"mrn": m, "name": "", "birth_date": born, "sex": sex[rng.choice("MF")]})
        encs: list[tuple[str, datetime, str]] = []
        for _ in range(rng.randint(1, 4)):
            n_enc += 1
            when = datetime.combine(REF - timedelta(days=rng.randint(1, 700)), datetime.min.time()) + timedelta(
                hours=rng.randint(8, 17), minutes=rng.choice((0, 15, 30, 45))
            )
            kind = rng.choices(("OPD", "IPD", "ER"), (8, 1, 1))[0]
            dept, doc = rng.choice(depts), rng.choice(staff)
            e = {
                "enc_no": _sid("E", n_enc),
                "mrn": m,
                "visit_datetime": when,
                "dept_code": dept,
                "enc_type": etype[kind],
            }
            if provider.get("in_encounter", True):
                e["staff_id"] = doc
            out["encounter"].append(e)
            encs.append((e["enc_no"], when, dept))
        for enc_no, when, _dept in encs:
            for item in rng.sample(labs, k=min(len(labs), rng.randint(1, 3))):
                n_lab += 1
                code, unit, factor = item["code"], item.get("unit", ""), 1.0
                if every and n_lab % every == 0:
                    what, plant = plant_cycle[(n_lab // every - 1) % len(plant_cycle)]
                    if what == "unmapped":
                        item = plant
                        code, unit = plant["code"], plant.get("unit", "")
                    else:
                        item = lab_by_code[plant["code"]]
                        code, unit, factor = plant["code"], plant["unit"], float(plant["factor"])
                lo, hi = (item.get("range") or [1, 100])[:2]
                value = round(rng.uniform(float(lo), float(hi)) * factor, 1)
                out["lab"].append({
                    "lab_no": _sid("L", n_lab), "mrn": m, "local_code": code, "item_name": item.get("name", ""),
                    "result_value": f"{value:g}", "unit": unit, "sample_datetime": when + timedelta(minutes=20),
                })  # fmt: skip
            if note_types and rng.random() < 0.5:
                n_note += 1
                kind = rng.choice(note_types)
                out["note"].append({
                    "note_no": _sid("N", n_note), "mrn": m, "enc_no": enc_no,
                    "note_datetime": when + timedelta(hours=1), "note_type": kind, "text": NOTE_TEXT[kind],
                })  # fmt: skip
        for _ in range(rng.randint(0, 2) if dxs else 0):
            n_dx += 1
            enc_no, when, _dept = rng.choice(encs)
            dx = rng.choice(dxs)
            out["diagnosis"].append({
                "diag_no": _sid("D", n_dx), "enc_no": enc_no, "mrn": m, "icd10": dx.get("icd10") or dx["code"],
                "byomei_code": dx["code"] if dx.get("icd10") else "", "byomei_name": dx.get("name", ""),
                "diag_date": when.date(), "recorded_date": when.date(), "status": "A",
            })  # fmt: skip
        for _ in range(rng.randint(0, 2) if drugs else 0):
            n_rx += 1
            enc_no, when, dept = rng.choice(encs)
            drug = rng.choice(drugs)
            out["medication"].append({
                "rx_no": _sid("R", n_rx), "enc_no": enc_no, "mrn": m, "nhi_drug_code": drug["code"],
                "atc": drug.get("atc", ""), "drug_name": drug.get("name", ""), "order_date": when.date(),
                "start_date": when.date(), "end_date": when.date() + timedelta(days=28), "daily_dose": "1",
                "dose_unit": "tab", "status": "active", "dept_code": dept,
            })  # fmt: skip
        if schema.get("appointments") and rng.random() < 0.3:
            n_appt += 1
            when = datetime.combine(REF + timedelta(days=rng.randint(1, 60)), datetime.min.time()) + timedelta(hours=10)
            out["appointment"].append({
                "appt_no": _sid("A", n_appt), "mrn": m, "appt_datetime": when, "duration_min": "15",
                "staff_id": rng.choice(staff), "dept_code": rng.choice(depts), "status": "B",
            })  # fmt: skip
    return out


# ------------------------------------------------------------------------------------------------ writers
def _cell(col: str, v: Any, fmt: str) -> str:
    if isinstance(v, datetime):
        return fmt_dt(v, fmt)
    if isinstance(v, date):
        return fmt_date(v, fmt)
    return "" if v is None else str(v)


def _local_rows(
    schema: dict[str, Any], table: str, rows: list[dict[str, Any]], fmt: str
) -> tuple[list[str], list[list[str]]]:
    cols: dict[str, str] = schema["tables"][table]["columns"]
    header = list(cols)
    return header, [[_cell(cols[h], r.get(cols[h]), fmt) for h in header] for r in rows]


def write_csv(path: Path, header: list[str], rows: list[list[str]], codec: str, delimiter: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=codec, newline="") as fh:
        w = csv.writer(fh, delimiter=delimiter, lineterminator="\r\n")
        w.writerow(header)
        w.writerows(rows)


def build(schema: dict[str, Any], out: Path, patients: int = 500, seed: int = 1) -> dict[str, int]:
    """Write the synthetic site into ``out`` in the site's layout; returns the rows per table."""
    data = generate(schema, patients, seed)
    feed = schema["feed"]
    out.mkdir(parents=True, exist_ok=True)
    if feed["layout"] == "ssmix2":
        _write_ssmix2(schema, data, out)
    else:
        codec, delim, fmt = CODECS[feed["encoding"]], feed.get("delimiter", ","), feed["date_format"]
        ext = feed.get("extension", ".csv")
        db = sqlite3.connect(out / "site.sqlite") if feed["layout"] == "sql" else None
        for table in schema["tables"]:
            header, rows = _local_rows(schema, table, data[table], fmt)
            src = schema["tables"][table]["source"]
            if db is None:
                write_csv(out / f"{src}{ext}", header, rows, codec, delim)
            else:
                db.execute(f"CREATE TABLE {src} ({', '.join(f'{_q(h)} TEXT' for h in header)})")
                db.executemany(f"INSERT INTO {src} VALUES ({', '.join('?' * len(header))})", rows)
        if db is not None:
            db.commit()
            (out / "site.sql").write_text("\n".join(db.iterdump()) + "\n", encoding="utf-8")
            db.close()
    counts = {t: len(v) for t, v in data.items() if v}
    (out / "site_build.json").write_text(
        json.dumps({"site": schema["site"], "layout": feed["layout"], "patients": patients, "seed": seed,
                    "rows": counts}, indent=1, sort_keys=True) + "\n", encoding="utf-8",
    )  # fmt: skip
    return counts


def _q(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise SchemaError(f"not a column name: {name!r}")
    return name


def _write_ssmix2(schema: dict[str, Any], data: dict[str, list[dict[str, Any]]], root: Path) -> None:
    from adapter.sources.ssmix2 import hl7
    from adapter.sources.ssmix2.source import storage_dir

    charset = "~ISO IR87" if schema["feed"]["encoding"] == "iso-2022-jp" else "UNICODE UTF-8"
    codec = CODECS[schema["feed"]["encoding"]]
    e = hl7.escape

    def ts(v: Any) -> str:
        return hl7.hl7_ts(_cell("", v, "iso"))

    def write(patient: str, day: str, typ: str, order: str, dept: str, kind: str, segs: list[str]) -> None:
        msh = f"MSH|^~\\&|HIS||TRIALBOX||{STAMP[:14]}||{kind}|{order}|P|2.5||||||{charset}||ISO 2022-1994"
        d = storage_dir(root, patient, day, typ)
        d.mkdir(parents=True, exist_ok=True)
        body = "\r".join([msh, *segs]) + "\r"
        (d / f"{patient}_{day}_{typ}_{order}_{STAMP}_{dept or '-'}_1").write_bytes(body.encode(codec))

    for p in data["patient"]:
        pid = f"PID|||{e(p['mrn'])}^^^^PI||^||{ts(p['birth_date'])}|{'M' if p['sex'] == _code(schema, 'M') else 'F'}"
        write(p["mrn"], "-", "ADT-00", "-", "-", "ADT^A08^ADT_A01", ["EVN||", pid])
    etype = {v: k for k, v in ((schema["code_lists"].get("encounter_type")) or {}).items()}
    for r in data["encounter"]:
        cls = {"OPD": "O", "IPD": "I", "ER": "E"}.get(etype.get(r["enc_type"], r["enc_type"]), "O")
        pv1 = ["PV1", "", cls] + [""] * 42
        pv1[7], pv1[10], pv1[19] = e(r.get("staff_id", "")), e(r["dept_code"]), e(r["enc_no"])
        pv1[44] = ts(r["visit_datetime"])
        typ = "ADT-22" if cls == "I" else "ADT-12"
        write(r["mrn"], pv1[44][:8], typ, r["enc_no"], r["dept_code"], "ADT^A04", ["|".join(pv1)])
    for r in data["diagnosis"]:
        cwe = (
            f"{e(r['byomei_code'])}^{e(r['byomei_name'])}^99XYZ^{e(r['icd10'])}^{e(r['byomei_name'])}^I10"
            if r["byomei_code"]
            else f"^^^{e(r['icd10'])}^^I10"
        )
        prb = ["PRB", "AD", ts(r["recorded_date"]), cwe, e(r["diag_no"])] + [""] * 12
        prb[14], prb[16] = "A", ts(r["diag_date"])
        visit = "PV1||O" + "|" * 17 + e(r["enc_no"])
        write(r["mrn"], ts(r["diag_date"])[:8], "PPR-01", r["diag_no"], "-", "PPR^ZD1", [visit, "|".join(prb)])
    for r in data["medication"]:
        alt = f"^{e(r['atc'])}^^WHOATC" if r["atc"] else ""
        orc = ["ORC", "NW", e(r["rx_no"]), "", "1", "IP", "", "", "", ts(r["order_date"])]
        rxe = ["RXE", "", f"{e(r['nhi_drug_code'])}^{e(r['drug_name'])}^99YJ{alt}", e(r["daily_dose"]), "",
               e(r["dose_unit"])]  # fmt: skip
        # RXE-3 is one dose: the CSV's daily dose is written as one dose once a day (10B-4)
        tq1 = ["TQ1", "", "", "&1日1回&99XYZ", "", "", "", ts(r["start_date"]), ts(r["end_date"])]
        segs = ["|".join(orc), "|".join(rxe), "|".join(tq1)]
        write(r["mrn"], ts(r["order_date"])[:8], "OMP-01", r["rx_no"], r["dept_code"], "RDE^O11", segs)
    for r in data["lab"]:
        system = "JC10" if re.fullmatch(r"[0-9A-Z]{15}([0-9A-Z]{2})?", r["local_code"]) else "99HOSP"
        obx = ["OBX", "1", "NM", f"{e(r['local_code'])}^{e(r['item_name'])}^{system}", "", e(r["result_value"])]
        obx += [e(r["unit"])] + [""] * 15
        obx[14], obx[21] = ts(r["sample_datetime"]), e(r["lab_no"])
        segs = [f"OBR|1|{e(r['lab_no'])}", "|".join(obx)]
        write(r["mrn"], obx[14][:8], "OML-11", r["lab_no"], "-", "OUL^R22", segs)
    for table in EXTENDED_TABLES:
        if table in schema.get("tables", {}) and data[table]:
            header, rows = _local_rows(schema, table, data[table], "iso")
            write_csv(root / "extended" / f"{schema['tables'][table]['source']}.csv", header, rows, "utf-8", ",")


def _code(schema: dict[str, Any], canon: str) -> str:
    return str(((schema["code_lists"].get("sex")) or {}).get(canon, canon))


# ------------------------------------------------------------------------------------------------ reading it back
def read_tables(schema: dict[str, Any], out: Path) -> dict[str, list[dict[str, str]]]:
    """The site's csv or sql files read back as the schema describes them (local headers, dates as written)."""
    feed = schema["feed"]
    got: dict[str, list[dict[str, str]]] = {}
    if feed["layout"] == "sql":
        db = sqlite3.connect(out / "site.sqlite")
        db.row_factory = sqlite3.Row
        for table, spec in schema["tables"].items():
            got[table] = [dict(r) for r in db.execute(f"SELECT * FROM {_q(spec['source'])}")]
        db.close()
        return got
    codec, delim, ext = CODECS[feed["encoding"]], feed.get("delimiter", ","), feed.get("extension", ".csv")
    for table, spec in schema["tables"].items():
        path = out / f"{spec['source']}{ext}"
        if path.exists():
            with path.open(encoding=codec, newline="") as fh:
                got[table] = list(csv.DictReader(fh, delimiter=delim))
    return got


def adapter_ready(schema: dict[str, Any]) -> bool:
    """The adapter's csv source reads UTF-8, comma-separated ``<table>.csv`` with ISO, YYYY/MM/DD or YYYYMMDD
    dates; anything else is staged first."""
    f = schema["feed"]
    return bool(
        f["layout"] == "ssmix2"
        or (
            f["layout"] == "csv"
            and f["encoding"] == "utf-8"
            and f["date_format"] != "roc7"
            and f.get("delimiter", ",") == ","
            and f.get("extension", ".csv") == ".csv"
        )
    )


def stage(schema: dict[str, Any], out: Path, staged: Path) -> tuple[str, Path]:
    """``(source kind, path)`` the adapter can read: the output itself when it can, else a UTF-8 comma-separated copy
    with ISO dates in ``staged`` (the same headers: the mapping's ``rename`` still does the rest)."""
    if adapter_ready(schema):
        return ("ssmix2" if schema["feed"]["layout"] == "ssmix2" else "csv"), out
    fmt = schema["feed"]["date_format"]
    shutil.rmtree(staged, ignore_errors=True)
    for table, rows in read_tables(schema, out).items():
        cols = schema["tables"][table]["columns"]
        header = list(cols)
        conv = []
        for r in rows:
            line = []
            for h in header:
                v, canon = r.get(h) or "", cols[h]
                line.append(iso_date(v, fmt) if canon in DATE_COLS else iso_dt(v, fmt) if canon in DT_COLS else v)
            conv.append(line)
        write_csv(staged / f"{schema['tables'][table]['source']}.csv", header, conv, "utf-8", ",")
    return "csv", staged


_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")


def site_report(schema: dict[str, Any], out: Path, mapping: Path, staged: Path | None = None) -> dict[str, Any]:
    """The report that may leave a site: per table rows read, resources, missing columns, unmapped codes and the
    count of structural errors; a parse error's message with its quoted value removed. Never a value."""
    from tools.mapping_check import check

    kind, path = stage(schema, out, staged or out.parent / f"{out.name}.staged")
    rep: dict[str, Any] = {"site": schema["site"], "layout": schema["feed"]["layout"], "mapping": mapping.name,
                           "tables": {}, "parse_errors": []}  # fmt: skip
    try:
        raw = check(mapping, kind, str(path), rows=10**9, stop_at_refused=True)
    except ValueError as exc:  # MappingError: an unparseable date or number stops the check; its value is cut out
        rep["parse_errors"].append(_QUOTED.sub("'…'", str(exc)))
        rep["passed"] = False
        return rep
    for table, t in raw["tables"].items():
        rep["tables"][table] = {
            "rows_read": t.get("rows_read", 0),
            "resources": t.get("resources", 0),
            "missing_columns": t.get("missing_columns", []),
            "unmapped_codes": t.get("unmapped_codes", {}),
            "structural_errors": len(t.get("structural_errors", [])),
        }
    rep["unit_mismatch"] = unit_mismatches(mapping, kind, path)
    rep["passed"] = bool(raw["passed"])
    return rep


def unit_mismatches(mapping: Path, kind: str, where: str | Path) -> dict[str, int]:
    """Lab results per local code that the mapping gives no value because their unit is not the lookup's (R-31,
    D-215): the steward fixes the lookup's ``source_unit`` / ``factor`` or the export, never the value."""
    from adapter.mapping.engine import Mapper, Mapping
    from adapter.pipeline import make_source
    from tb_common import labvalue

    m = Mapping.load(mapping)
    if "lab" not in m.tables:
        return {}
    spec = m.tables["lab"]
    rows = (m.normalize("lab", r) for r in make_source(kind, str(where)).rows("lab", spec["source"], None, None))
    local = m.systems.get("lab_local")
    out: dict[str, int] = {}
    for res in Mapper(m, b"site-report-key-0123456789abcdef", "CHECK").map_table("lab", rows):
        if (res.get("dataAbsentReason") or {}).get("text") != labvalue.UNIT_MISMATCH:
            continue
        code = next((c.get("code") for c in res["code"]["coding"] if c.get("system") == local), "?")
        out[str(code)] = out.get(str(code), 0) + 1
    return dict(sorted(out.items()))


# ------------------------------------------------------------------------------------------------ data scan (D-203)
def scan_pattern(schema: dict[str, Any]) -> dict[str, Any] | None:
    """A ``tools/data_scan_patterns.yaml`` entry for a bare chart number of the site's stated form, or ``None`` when
    the form has nothing to anchor on (digits only and no check digit: a bare pattern would hit every date and
    count; the label-anchored ``chart_number`` pattern stays the control)."""
    form = (schema.get("identifiers") or {}).get("chart_number")
    if not form:
        return None
    letters, digits, check = int(form.get("letters", 0)), int(form["digits"]), form.get("check", "none")
    if not letters and check == "none":
        return None
    regex = rf"(?<![A-Za-z0-9])({'[A-Z]' * letters}\d{{{digits}}})(?![A-Za-z0-9])"
    entry: dict[str, Any] = {
        "id": f"chart_number_{schema['site'].replace('-', '_')}",
        "what": f"a chart number of {schema['site']} without its label ({letters} letters, {digits} digits"
        + (", Luhn check digit)" if check == "luhn" else ")"),
        "regex": regex,
        "digits": [digits, digits],
    }
    if check == "luhn":
        entry["check"] = "luhn"
    return entry


# ------------------------------------------------------------------------------------------------ CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="check a site schema")
    v.add_argument("schema", type=Path)
    b = sub.add_parser("build", help="write the synthetic site")
    b.add_argument("schema", type=Path)
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--patients", type=int, default=500)
    b.add_argument("--seed", type=int, default=1)
    c = sub.add_parser("check", help="the site report of a built site against a mapping (no values)")
    c.add_argument("schema", type=Path)
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--mapping", type=Path, required=True)
    c.add_argument("--json", action="store_true")
    s = sub.add_parser("scan-pattern", help="the data-scan pattern for the site's chart-number form")
    s.add_argument("schema", type=Path)
    a = ap.parse_args(argv)
    try:
        schema = load_schema(a.schema)
    except (SchemaError, OSError, yaml.YAMLError) as exc:
        print(f"synth_site_from_schema: {exc}", file=sys.stderr)
        return 1
    if a.cmd == "validate":
        print(f"{a.schema}: a valid site schema ({schema['feed']['layout']}, {schema['feed']['encoding']})")
        return 0
    if a.cmd == "build":
        counts = build(schema, a.out, a.patients, a.seed)
        print(json.dumps(counts, sort_keys=True))
        return 0
    if a.cmd == "scan-pattern":
        entry = scan_pattern(schema)
        if entry is None:
            print("no bare pattern: the stated form has no letters and no check digit (the labelled pattern stays)")
            return 0
        print(yaml.safe_dump({"patterns": [entry]}, allow_unicode=True, sort_keys=False), end="")
        return 0
    rep = site_report(schema, a.out, a.mapping)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        for table, t in rep["tables"].items():
            line = f"{table:13s} {t['rows_read']:>6} rows → {t['resources']} resources"
            if t["missing_columns"]:
                line += f"  MISSING {', '.join(t['missing_columns'])}"
            if t["unmapped_codes"]:
                line += f"  unmapped: {', '.join(f'{k} ×{n}' for k, n in t['unmapped_codes'].items())}"
            print(line)
        for code, n in rep.get("unit_mismatch", {}).items():
            print(f"unit mismatch: lab {code} ×{n} (no value: the unit is not the lookup's)")
        for err in rep["parse_errors"]:
            print(f"parse error: {err}")
        print("PASSED" if rep["passed"] else "FAILED")
    return 0 if rep["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
