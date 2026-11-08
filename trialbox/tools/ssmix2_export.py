"""Write a canonical-CSV hospital (``tools/synth_hospital`` output) as SS-MIX2 standardized storage (D-122).

Test tooling: it lets the SS-MIX2 reader be checked against the CSV path on the same patients. Lab local codes,
drug codes and ICD-10 are turned into JLAC10, YJ and 標準病名 codes with the ``jp_core`` sample lookups; every third
diagnosis and medication message leaves out the alternate ICD-10 / ATC so the reader's fallback lookups are used.
Files are ISO-2022-JP (MSH-18 ``~ISO IR87``) and fall back to UTF-8 (``UNICODE UTF-8``) when a name does not fit
JIS X 0208. Tables SS-MIX2 does not standardize are copied to ``<out>/extended/``.

    python -m tools.ssmix2_export --csv <hospital dir> --out <storage root>
"""

from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path

from adapter.sources.ssmix2 import hl7
from adapter.sources.ssmix2.source import JP_CORE, TYPES, storage_dir

# the synthetic HIS lab codes -> the JLAC10 codes in jp_core/jlac10_to_loinc.csv (same order as the TW file)
_LOCAL_TO_JLAC10 = {
    "UA": "3C020000002327101",
    "CRE": "3C015000002327101",
    "HBA1C": "3D046000001906202",
    "ALT": "3B045000002327201",
    "ESR": "2A080000001930101",
    "CRP": "5C070000002306001",
    "HBSAG": "5F016141002305911",
    "AHBC": "5F018141002305911",
    "IGRA": "5E071160001905911",
    "HCGU": "4F040000001305911",
}
STAMP = "20261101000000000"
_RX_STATUS = {"active": "IP", "completed": "CM", "stopped": "DC"}
_CLASS = {"OPD": "O", "IPD": "I", "ER": "E"}


def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _rev(path: Path, key: str, value: str) -> dict[str, tuple[str, str]]:
    """value -> (key, name), first row wins."""
    out: dict[str, tuple[str, str]] = {}
    for r in _read(path):
        out.setdefault(r[value], (r[key], r.get("name", "")))
    return out


def _e(v: str | None) -> str:
    return hl7.escape(v or "")


def _write(root: Path, patient: str, day: str, typ: str, order: str, dept: str, segments: list[str]) -> None:
    msh = segments[0]
    body = "\r".join(segments) + "\r"
    try:
        data = body.encode("iso2022_jp")
    except UnicodeEncodeError:
        body = "\r".join([msh.replace("|~ISO IR87|", "|UNICODE UTF-8|"), *segments[1:]]) + "\r"
        data = body.encode("utf-8")
    d = storage_dir(root, patient, day, typ)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{patient}_{day}_{typ}_{order}_{STAMP}_{dept or '-'}_1").write_bytes(data)


def _msh(kind: str, ctl: str) -> str:
    return f"MSH|^~\\&|HIS||TRIALBOX||{STAMP[:14]}||{kind}|{ctl}|P|2.5||||||~ISO IR87||ISO 2022-1994"


def _day(value: str | None) -> str:
    return hl7.hl7_ts(value)[:8] or "-"


def export(src: Path, out: Path) -> dict[str, int]:
    out.mkdir(parents=True, exist_ok=True)
    byomei = _rev(JP_CORE / "byomei_to_icd10.csv", "code", "icd10")
    yj = _rev(JP_CORE / "yj_to_atc.csv", "yj_code", "atc")
    counts = dict.fromkeys(["patient", "encounter", "diagnosis", "medication", "lab"], 0)
    enc_by_no = {r["enc_no"]: r for r in _read(src / "encounter.csv")}
    for p in _read(src / "patient.csv"):
        family, _, given = (p.get("name") or "").partition("　")
        pid = (
            f"PID|||{_e(p['mrn'])}^^^^PI||{_e(family)}^{_e(given)}||{hl7.hl7_ts(p.get('birth_date'))}|"
            f"{p.get('sex', '')}|||||{_e(p.get('phone'))}" + "|" * 16 + hl7.hl7_ts(p.get("death_date"))
        )
        _write(out, p["mrn"], "-", "ADT-00", "-", "-", [_msh("ADT^A08^ADT_A01", f"P{p['mrn']}"), "EVN||", pid])
        counts["patient"] += 1
    for e in enc_by_no.values():
        typ = "ADT-22" if e.get("enc_type") == "IPD" else "ADT-12"
        pv1 = ["PV1", "", _CLASS.get(e.get("enc_type", ""), "O")] + [""] * 42
        pv1[7], pv1[10], pv1[19] = _e(e.get("staff_id")), _e(e.get("dept_code")), _e(e["enc_no"])
        pv1[44] = hl7.hl7_ts(e.get("visit_datetime"))
        day = _day(e.get("visit_datetime"))
        _write(
            out, e["mrn"], day, typ, e["enc_no"], e.get("dept_code", ""), [_msh("ADT^A04", e["enc_no"]), "|".join(pv1)]
        )
        counts["encounter"] += 1
    for i, d in enumerate(_read(src / "diagnosis.csv")):
        code, name = byomei.get(d["icd10"], ("", ""))
        alt = f"^{_e(d['icd10'])}^^I10" if i % 3 or not code else ""
        cwe = f"{code}^{_e(name)}^99XYZ{alt}" if code else f"^^^{_e(d['icd10'])}^^I10"
        prb = ["PRB", "AD", hl7.hl7_ts(d.get("recorded_date")), cwe, _e(d["diag_no"])] + [""] * 12
        prb[14] = "R" if d.get("status") == "R" else "A"
        prb[16] = hl7.hl7_ts(d.get("diag_date"))
        visit = "PV1||O" + "|" * 17 + _e(d.get("enc_no"))
        day = _day(d.get("diag_date"))
        _write(out, d["mrn"], day, "PPR-01", d["diag_no"], "-", [_msh("PPR^ZD1", d["diag_no"]), visit, "|".join(prb)])
        counts["diagnosis"] += 1
    for i, m in enumerate(_read(src / "medication.csv")):
        code, name = yj.get(m.get("atc", ""), ("", ""))
        alt = f"^{_e(m.get('atc'))}^^WHOATC" if i % 3 or not code else ""
        rxe2 = f"{code or _e(m.get('nhi_drug_code'))}^{_e(m.get('drug_name'))}^99YJ{alt}"
        orc = ["ORC", "NW", _e(m["rx_no"]), "", "", _RX_STATUS.get(m.get("status", ""), "IP"), "", "", "", ""]
        orc[9] = hl7.hl7_ts(m.get("order_date"))
        rxe = ["RXE", "", rxe2, _e(m.get("daily_dose")), "", _e(m.get("dose_unit"))]
        tq1 = ["TQ1", "", "", "", "", "", "", hl7.hl7_ts(m.get("start_date")), hl7.hl7_ts(m.get("end_date"))]
        day = _day(m.get("order_date"))
        segs = [_msh("RDE^O11", m["rx_no"]), "|".join(orc), "|".join(rxe), "|".join(tq1)]
        _write(out, m["mrn"], day, "OMP-01", m["rx_no"], m.get("dept_code", ""), segs)
        counts["medication"] += 1
    for lab in _read(src / "lab.csv"):
        jlac = _LOCAL_TO_JLAC10.get(lab["local_code"], lab["local_code"])
        obx = ["OBX", "1", "NM", f"{jlac}^{_e(lab.get('item_name'))}^JC10", "", _e(lab.get("result_value"))]
        obx += [_e(lab.get("unit"))] + [""] * 15
        obx[14], obx[21] = hl7.hl7_ts(lab.get("sample_datetime")), _e(lab["lab_no"])
        day = _day(lab.get("sample_datetime"))
        obr = f"OBR|1|{_e(lab['lab_no'])}"
        _write(out, lab["mrn"], day, "OML-11", lab["lab_no"], "-", [_msh("OUL^R22", lab["lab_no"]), obr, "|".join(obx)])
        counts["lab"] += 1
    ext = out / "extended"
    ext.mkdir(exist_ok=True)
    for f in sorted(src.glob("*.csv")):
        if f.stem not in TYPES:
            shutil.copyfile(f, ext / f.name)
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", type=Path, required=True, help="canonical CSV hospital directory")
    ap.add_argument("--out", type=Path, required=True, help="SS-MIX2 storage root to write")
    args = ap.parse_args(argv)
    for table, n in export(args.csv, args.out).items():
        print(f"{table}: {n} messages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
