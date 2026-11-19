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

* **Hard cases** (``--hard-cases``, :func:`hard_cases`, T-615a): the bytes and fields vendor files hold that the
  plain export never writes, on synthetic patients ``9900000x``: the five byte patterns of STD-020 (half-width
  katakana, NEC row 13 and IBM extension characters inside ``ESC $ B``, JIS X 0212, Shift_JIS with the wrong and with
  the right MSH-18) and a file no codec reads; OBX-2 ``CWE`` and ``SN``; OBX-11 ``C`` and ``D``; the sample-time
  fallbacks (OBR-7, SPM-17, the folder's date); a 10-digit time; PID-30 ``Y`` without PID-29; PID-3 and PID-5
  repetitions.

    python -m tools.ssmix2_export --csv <hospital dir> --out <storage root> [--hard-cases]
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
    if not any(s.startswith("PID|") for s in segments):  # every SS-MIX2 message carries its patient (PR #1095)
        segments = [segments[0], f"PID|||{_e(patient)}^^^^PI", *segments[1:]]
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
        # RXE-3 is one dose and TQ1-3 the 用法 (10B-4): the CSV knows only the daily dose, so it is written as one dose
        # once a day ("1日1回", a local usage code with no code), which the reader multiplies back to the same number
        tq1 = ["TQ1", "", "", "&1日1回&99XYZ", "", "", "", hl7.hl7_ts(m.get("start_date"))]
        tq1.append(hl7.hl7_ts(m.get("end_date")))
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


# ----------------------------------------------------------------------------------------------- hard cases (T-615a)
HARD_STAMP = "20261102000000000"


def cp50220(text: str) -> bytes:
    """``text`` as Windows writes ISO-2022-JP (CP50220): every double-byte character, NEC row 13 and the NEC-selected
    IBM extension (①, ㈱, 髙) too, inside ``ESC $ B`` as its JIS cell; half-width katakana in ``ESC ( I``."""
    out, mode = bytearray(), "ascii"
    for ch in text:
        b = ch.encode("cp932")
        if len(b) == 2:
            s1, s2 = b
            j1 = (s1 - (0xB0 if s1 >= 0xE0 else 0x70)) * 2 - (1 if s2 < 0x9F else 0)
            j2 = s2 - (0x1F + (s2 > 0x7F) if s2 < 0x9F else 0x7E)
            want, cell = "jis", bytes((j1, j2))
        elif b[0] > 0x7F:
            want, cell = "kana", bytes((b[0] - 0x80,))
        else:
            want, cell = "ascii", b
        if want != mode:
            out += {"jis": b"\x1b$B", "kana": b"\x1b(I", "ascii": b"\x1b(B"}[want]
            mode = want
        out += cell
    if mode != "ascii":
        out += b"\x1b(B"
    return bytes(out)


def _put(root: Path, patient: str, day: str, typ: str, order: str, data: bytes) -> str:
    d = storage_dir(root, patient, day, typ)
    d.mkdir(parents=True, exist_ok=True)
    name = f"{patient}_{day}_{typ}_{order}_{HARD_STAMP}_-_1"
    (d / name).write_bytes(data)
    return name


def _hmsh(kind: str, ctl: str, charset: str) -> str:
    return f"MSH|^~\\&|HIS||TRIALBOX||{HARD_STAMP[:14]}||{kind}|{ctl}|P|2.5||||||{charset}"


def _adt00(mrn: str, name: str, extra: str = "") -> list[str]:
    return ["EVN||", f"PID|||{mrn}^^^^PI||{name}||19600101|F{extra}"]


def hard_cases(root: Path) -> dict[str, str]:
    """Write the hard cases into the storage at ``root``; ``{file name: what it shows}``. All synthetic."""
    root.mkdir(parents=True, exist_ok=True)
    made: dict[str, str] = {}

    def adt(mrn: str, what: str, data: bytes) -> None:
        made[_put(root, mrn, "-", "ADT-00", "-", data)] = what

    def seg(*lines: str) -> str:
        return "\r".join(lines) + "\r"

    jis = "~ISO IR87"
    adt(
        "99000001",
        "half-width katakana (ESC ( I)",
        seg(_hmsh("ADT^A08", "H1", jis), *_adt00("99000001", "ﾔﾏﾀﾞ^ﾊﾅｺ")).encode("iso2022_jp_ext"),
    )
    adt(
        "99000002",
        "NEC row 13 and IBM extension inside ESC $ B (CP50220)",
        cp50220(seg(_hmsh("ADT^A08", "H2", jis), *_adt00("99000002", "髙橋^①子㈱"))),
    )
    adt(
        "99000003",
        "JIS X 0212 (ESC $ ( D)",
        seg(_hmsh("ADT^A08", "H3", jis), *_adt00("99000003", "丂田^花子")).encode("iso2022_jp_ext"),
    )
    adt(
        "99000004",
        "Shift_JIS under MSH-18 ~ISO IR87 (the wrong charset)",
        seg(_hmsh("ADT^A08", "H4", jis), *_adt00("99000004", "佐藤^ﾊﾅｺ")).encode("cp932"),
    )
    adt(
        "99000005",
        "Shift_JIS under MSH-18 SJIS",
        seg(_hmsh("ADT^A08", "H5", "SJIS"), *_adt00("99000005", "鈴木^①子")).encode("cp932"),
    )
    adt(
        "99000006",
        "no codec reads it: quarantined",
        seg(_hmsh("ADT^A08", "H6", jis), *_adt00("99000006", "X")).encode("ascii") + b"\x80\xff\xfe\r",
    )
    # PID-30 Y without PID-29; PID-3 with a medical-record number before the PI; PID-5 kana before kanji
    pid = "PID|||K-1^^^^MR~99000007^^^^PI||ヤマダ^ハナコ^^^^^L^P~山田^花子^^^^^L^I||19500101|F" + "|" * 21 + "|Y"
    adt(
        "99000007",
        "PID-30 Y without PID-29; PID-3 and PID-5 repetitions",
        seg(_hmsh("ADT^A08", "H7", jis), "EVN||", pid).encode("iso2022_jp"),
    )

    def obx(
        n: int,
        vt: str,
        code: str,
        name: str,
        value: str,
        unit: str,
        *,
        sub: str = "",
        ref: str = "",
        flag: str = "",
        status: str = "F",
        when: str = "",
        lab_no: str = "",
    ) -> str:
        f = ["OBX", str(n), vt, f"{code}^{name}^JC10", sub, value, unit, ref, flag, "", "", status, "", "", when]
        f += [""] * 6 + [lab_no]
        return "|".join(f)

    hbs, cre, crp, a1c = "5F016141002305911", "3C015000002327101", "5C070000002306001", "3D046000001906202"
    lab = seg(
        _hmsh("OUL^R22", "L1", jis),
        "PID|||99000008^^^^PI",  # every SS-MIX2 message carries its patient (PR #1095)
        "SPM|1|||" + "|" * 13 + "20261001080000",
        "OBR|1|ORD-1|FIL-1||||202610010830",
        obx(1, "CWE", hbs, "HBs抗原", "1^陰性^JHSD0001", "", lab_no="H-CWE"),
        obx(2, "SN", crp, "CRP", "<^0.03", "mg/dL", when="20261001090000", lab_no="H-SN"),
        obx(3, "NM", cre, "クレアチニン", "9.99", "mg/dL", sub="1", when="20261001090000", lab_no="H-ORIG"),
        obx(
            4,
            "NM",
            cre,
            "クレアチニン",
            "0.82",
            "mg/dL",
            sub="1",
            ref="0.46-0.79",
            flag="H",
            status="C",
            when="20261001090000",
            lab_no="H-CORR",
        ),
        obx(5, "NM", a1c, "HbA1c", "11.0", "%", status="D", when="20261001090000", lab_no="H-DEL"),
        obx(6, "NM", a1c, "HbA1c", "6.1", "%", when="2026100110", lab_no="H-10DIGIT"),
    )
    made[_put(root, "99000008", "20261001", "OML-11", "L1", lab.encode("iso2022_jp"))] = (
        "OBX-2 CWE and SN; OBX-11 C replaces, D a tombstone; OBR-7 time; a 10-digit time"
    )
    spm_only = seg(
        _hmsh("OUL^R22", "L2", jis),
        "PID|||99000008^^^^PI",
        "SPM|1|||" + "|" * 13 + "20261002070000",
        "OBR|1|ORD-2",
        obx(1, "NM", crp, "CRP", "0.10", "mg/dL", lab_no="H-SPM"),
    )
    made[_put(root, "99000008", "20261002", "OML-11", "L2", spm_only.encode("iso2022_jp"))] = "SPM-17 time"
    folder = seg(
        _hmsh("OUL^R22", "L3", jis),
        "PID|||99000008^^^^PI",
        "OBR|1|ORD-3",
        obx(1, "NM", crp, "CRP", "0.20", "mg/dL", lab_no="H-DIR"),
    )
    made[_put(root, "99000008", "20261003", "OML-11", "L3", folder.encode("iso2022_jp"))] = "the folder's date"
    return made


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", type=Path, required=True, help="canonical CSV hospital directory")
    ap.add_argument("--out", type=Path, required=True, help="SS-MIX2 storage root to write")
    ap.add_argument("--hard-cases", action="store_true", help="also write the hard cases of T-615a")
    args = ap.parse_args(argv)
    for table, n in export(args.csv, args.out).items():
        print(f"{table}: {n} messages")
    if args.hard_cases:
        for name, what in hard_cases(args.out).items():
            print(f"hard case {name}: {what}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
