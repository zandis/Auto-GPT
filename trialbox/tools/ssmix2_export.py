"""Write a canonical-CSV hospital (``tools/synth_hospital`` output) as SS-MIX2 standardized storage (D-122, D-137).

Test tooling: it lets the SS-MIX2 reader be checked against the CSV path on the same patients. Lab local codes,
drug codes and ICD-10 are turned into JLAC10, YJ and 標準病名 codes with the ``jp_core`` sample lookups; every third
diagnosis and medication message leaves out the alternate ICD-10 / ATC so the reader's fallback lookups are used.
Files are ISO-2022-JP (MSH-18 ``~ISO IR87``) and fall back to UTF-8 (``UNICODE UTF-8``) when a name does not fit
JIS X 0208. Tables SS-MIX2 does not standardize are copied to ``<out>/extended/``.

The messages of D-137 appear too, each written so that the reader gives back exactly the CSV's rows:

* **ADT-52** (patient class change, ADT^A07): every 40th visit is stored as an admission (ADT-22, class I) changed
  to outpatient two hours later, so it reads back as the CSV's outpatient visit with its class history.
* **OMP-02 / OMP-12**: injectable drugs (biologics, GLP-1) are injection orders; every fourth is stored only as an
  injection 実施 (OMP-12, RAS^O17) with no order, every third has both.
* **OMP-11**: every fifth oral order is stored only as a prescription 実施, every seventh has both.
* **HOT codes**: every other drug with a YJ code is sent with a (synthetic) HOT9 code as the primary code and the YJ
  code as the alternate; the reader keeps both.
* **Extended storage** (``<out>/extended_storage/``): a discharge summary (Shift_JIS text) for every 25th patient
  and an imaging report (PDF with a text layer) for every 30th, in the patient folders.

    python -m tools.ssmix2_export --csv <hospital dir> --out <storage root>
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
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
# a Japanese laboratory writes a presence result in words: the export does too, and the JP mapping reads them through
# the shared normaliser (tb_common.labvalue.presence, D-334) to the same LOINC answers as POS / NEG
_JP_PRESENCE = {"POS": "陽性", "NEG": "陰性"}
_RX_STATUS = {"active": "IP", "completed": "CM", "stopped": "DC"}
_CLASS = {"OPD": "O", "IPD": "I", "ER": "E"}
INJECTABLE = ("L04AB", "L04AC", "A10BJ", "A10BX")  # biologics and GLP-1: injection orders (OMP-02 / OMP-12)


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


def hot9(yj: str) -> str:
    """A synthetic, stable 9-digit HOT code for a YJ code (made up: real HOT codes come from the site's master)."""
    return str(int(hashlib.sha256(yj.encode()).hexdigest()[:12], 16))[-9:].rjust(9, "0")


def _plus_hours(ts: str, hours: int) -> str:
    from datetime import datetime, timedelta

    try:
        dt = datetime.strptime(ts[:14].ljust(14, "0"), "%Y%m%d%H%M%S")
    except ValueError:
        return ts
    return (dt + timedelta(hours=hours)).strftime("%Y%m%d%H%M%S")


def _report_pdf(lines: list[str]) -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    y = 760
    for line in lines:
        c.drawString(72, y, line)
        y -= 18
    c.save()
    return buf.getvalue()


def export(src: Path, out: Path) -> dict[str, int]:
    out.mkdir(parents=True, exist_ok=True)
    byomei = _rev(JP_CORE / "byomei_to_icd10.csv", "code", "icd10")
    yj = _rev(JP_CORE / "yj_to_atc.csv", "yj_code", "atc")
    counts = dict.fromkeys(["patient", "encounter", "diagnosis", "medication", "lab"], 0)
    counts |= dict.fromkeys(["ADT-52", "OMP-02", "OMP-11", "OMP-12", "document"], 0)
    enc_by_no = {r["enc_no"]: r for r in _read(src / "encounter.csv")}
    patients = _read(src / "patient.csv")
    for p in patients:
        family, _, given = (p.get("name") or "").partition("　")
        pid = (
            f"PID|||{_e(p['mrn'])}^^^^PI||{_e(family)}^{_e(given)}||{hl7.hl7_ts(p.get('birth_date'))}|"
            f"{p.get('sex', '')}|||||{_e(p.get('phone'))}" + "|" * 16 + hl7.hl7_ts(p.get("death_date"))
        )
        _write(out, p["mrn"], "-", "ADT-00", "-", "-", [_msh("ADT^A08^ADT_A01", f"P{p['mrn']}"), "EVN||", pid])
        counts["patient"] += 1
    for i, e in enumerate(enc_by_no.values()):
        changed = i % 40 == 7 and e.get("enc_type") == "OPD"  # admitted, then changed to outpatient (ADT-52)
        typ = "ADT-22" if e.get("enc_type") == "IPD" or changed else "ADT-12"
        pv1 = ["PV1", "", "I" if changed else _CLASS.get(e.get("enc_type", ""), "O")] + [""] * 42
        pv1[7], pv1[10], pv1[19] = _e(e.get("staff_id")), _e(e.get("dept_code")), _e(e["enc_no"])
        pv1[44] = hl7.hl7_ts(e.get("visit_datetime"))
        day = _day(e.get("visit_datetime"))
        _write(
            out, e["mrn"], day, typ, e["enc_no"], e.get("dept_code", ""), [_msh("ADT^A04", e["enc_no"]), "|".join(pv1)]
        )
        counts["encounter"] += 1
        if changed:
            pv1[2] = "O"
            when = _plus_hours(pv1[44], 2)
            segs = [_msh("ADT^A07^ADT_A06", f"C{e['enc_no']}"), f"EVN||{when}||||{when}", "|".join(pv1)]
            _write(out, e["mrn"], day, "ADT-52", e["enc_no"], e.get("dept_code", ""), segs)
            counts["ADT-52"] += 1
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
    n_inj = n_oral = 0
    for i, m in enumerate(_read(src / "medication.csv")):
        code, _name = yj.get(m.get("atc", ""), ("", ""))
        injection = (m.get("atc") or "").startswith(INJECTABLE)
        k = n_inj if injection else n_oral
        if injection:
            n_inj += 1
        else:
            n_oral += 1
        alt = f"^{_e(m.get('atc'))}^^WHOATC" if i % 3 or not code else ""
        drug = f"{code or _e(m.get('nhi_drug_code'))}^{_e(m.get('drug_name'))}^99YJ{alt}"
        if code and i % 2 == 0:  # HOT9 as the primary code, YJ as the alternate (ATC from the YJ lookup)
            drug = f"{hot9(code)}^{_e(m.get('drug_name'))}^HOT^{code}^^99YJ"
        status = _RX_STATUS.get(m.get("status", ""), "IP")
        orc = ["ORC", "NW", _e(m["rx_no"]), "", str(k % 3 + 1), status, "", "", "", ""]
        orc[9] = hl7.hl7_ts(m.get("order_date"))
        rxe = ["RXE", "", drug, _e(m.get("daily_dose")), "", _e(m.get("dose_unit"))]
        tq1 = ["TQ1", "", "", "", "", "", "", hl7.hl7_ts(m.get("start_date")), hl7.hl7_ts(m.get("end_date"))]
        rxa = [
            "RXA",
            "0",
            "1",
            hl7.hl7_ts(m.get("start_date")),
            hl7.hl7_ts(m.get("end_date")),
            drug,
            _e(m.get("daily_dose")),
            _e(m.get("dose_unit")),
        ]
        day, dept = _day(m.get("order_date")), m.get("dept_code", "")
        only_done = k % 4 == 3 if injection else k % 5 == 4
        both = k % 3 == 1 if injection else k % 7 == 3
        if not only_done:
            typ = "OMP-02" if injection else "OMP-01"
            segs = [_msh("RDE^O11", m["rx_no"]), "|".join(orc), "|".join(rxe), "|".join(tq1)]
            _write(out, m["mrn"], day, typ, m["rx_no"], dept, segs)
            counts["OMP-02"] += int(injection)
        if only_done or both:
            typ = "OMP-12" if injection else "OMP-11"
            done_orc = ["ORC", "RE", *orc[2:]]
            segs = [_msh("RAS^O17^RAS_O17", f"A{m['rx_no']}"), "|".join(done_orc), "|".join(rxa)]
            _write(out, m["mrn"], day, typ, m["rx_no"], dept, segs)
            counts[typ] += 1
        counts["medication"] += 1
    for lab in _read(src / "lab.csv"):
        jlac = _LOCAL_TO_JLAC10.get(lab["local_code"], lab["local_code"])
        system = "JC10" if lab["local_code"] in _LOCAL_TO_JLAC10 else "99HOSP"  # scores: the hospital's own code
        value = lab.get("result_value") or ""
        value = _JP_PRESENCE.get(value, value)
        obx = ["OBX", "1", "NM", f"{jlac}^{_e(lab.get('item_name'))}^{system}", "", _e(value)]
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
    counts["document"] = _documents(out / "extended_storage", patients, list(enc_by_no.values()))
    return counts


def _documents(root: Path, patients: list[dict[str, str]], encounters: list[dict[str, str]]) -> int:
    """Synthetic extended-storage documents: a discharge summary (Shift_JIS text) and an imaging report (PDF)."""
    last: dict[str, str] = {}
    for e in encounters:
        if e.get("visit_datetime", "") > last.get(e["mrn"], ""):
            last[e["mrn"]] = e["visit_datetime"]
    n = 0
    for i, p in enumerate(patients):
        day = _day(last.get(p["mrn"]))
        if day == "-":
            continue
        if i % 25 == 3:
            text = (
                "退院時サマリ\r\n入院中の経過：痛風発作に対しコルヒチンを投与し、症状は軽快した。\r\n"
                "退院時処方：アロプリノール錠100mg 1日1回。\r\n今後の方針：外来で尿酸値を確認する。\r\n"
            )
            d = storage_dir(root, p["mrn"], day, "DSC-01")
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{p['mrn']}_{day}_DSC-01_1_{STAMP}_-_1.txt").write_bytes(text.encode("cp932"))
            n += 1
        if i % 30 == 5:
            pdf = _report_pdf(
                ["Imaging report (synthetic)", "Chest X-ray: no acute findings.", "Impression: normal study."]
            )
            d = storage_dir(root, p["mrn"], day, "RPT-01")
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{p['mrn']}_{day}_RPT-01_1_{STAMP}_-_1.pdf").write_bytes(pdf)
            n += 1
    return n


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
