"""The ``spec`` variant of the SS-MIX2 exporter (plan 10 card 10B-1, D-1262): a canonical-CSV hospital
(``tools/synth_hospital`` output) written in the shapes of the published SS-MIX2 documents, not in the shapes
TrialBox's reader expects.

Sources (JAMI, 一般社団法人 日本医療情報学会; listed at https://www.jami.jp/jamistd/ss-mix2/, cited, not copied):

* **G** SS-MIX2 標準化ストレージ 構成の説明と構築ガイドライン Ver.1.2j (2026-08-14): the folder tree (2.2,
  図2.2-1, 表2.3-1), the 診療日 of each message (表3.1-1), the データ種別 (表3.1-2), the file name (3.1.2 (1),
  表3.1-3, 3.1.2 (3)), versions and deletions (3.1.4 (2) ⑥, (3) ①).
* **S** SS-MIX2 標準化ストレージ 仕様書 Ver.1.2j (2026-08-14): segment terminators (2.1.4), the message tables
  (表3-13 to 表3-99) and segment tables (MSH 表3-34, PID 表3-36, PRB 表3-47, ZPR 表3-48, RXE 表3-57 / 表3-64, ...).
* **C** the same, 別紙 コード表 Ver.1.2j: the coding-system names (表2 to 表12) and the code tables used (表34, 35, 49,
  78, 94 to 97).
* **E** SS-MIX2 拡張ストレージ 構成の説明と構築ガイドライン Ver.1.2j and its 別紙 標準文書コード表: the extended storage
  (2.2 (3) to (7), 表2.2-1, 表2.2-2) and the LOINC document codes (表1).

Ver.1.2j's revision history says the guideline is unchanged since Ver.1.2h ("変更点なし") and the code table only
adds rows; the card names 1.2i, the current publication is 1.2j, so 1.2j is cited.

Every record is synthetic. Codes a licensed master would hold are invented in the master's shape and say so: the
病名管理番号 (8 digits, starting ``9999``), the HOT9 codes (``tools.ssmix2_export.hot9``), the study UIDs. The
exchange codes of the 病名 are the shipped sample lookup's (``jp_core/byomei_to_icd10.csv``: 4 characters, A-Z0-9).

What the documents do not settle is listed in D-1262 ("not settled") and keeps the legacy exporter's choice: the
extended storage under ``<out>/extended_storage``, the non-SS-MIX2 tables under ``<out>/extended``, the text
encoding of a document file, a name JIS X 0208 cannot write (UTF-8 under ``UNICODE UTF-8``).
"""

from __future__ import annotations

import csv
import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

ALL9 = "ALL9"  # G 表3.1-3 No.4: data no order number manages (患者基本, 病名, アレルギー)
MSH21 = "SS-MIX2_1.20^SS-MIX2^1.2.392.200250.2.1.100.1.2.120^ISO"  # S 表3-34 MSH-21
DEPT_NONE = "-"  # G 表3.1-3 No.6: a site default when there is no department code
CS_DRUG, CS_LAB, CS_USAGE, CS_DX, CS_ORDER, CS_DOC = "99DRG", "99LAB", "99USG", "99DXL", "99ORD", "99DOC"  # HL7 0396
JP_CORE = Path(__file__).resolve().parents[1] / "services" / "adapter" / "mapping" / "jp_core"

# the synthetic HIS lab codes -> JLAC10 (the same sample mapping the legacy exporter uses, jp_core/jlac10_to_loinc.csv)
LOCAL_TO_JLAC10 = {
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
_PRESENCE = {"POS": "陽性", "NEG": "陰性"}
# a WHO ICD-10 code without its dot (S 表3-47 PRB-10 example K297)
WHO_ICD10 = re.compile(r"^[A-Z][0-9]{2}[0-9]?$")
INJECTABLE = ("L04AB", "L04AC", "A10BJ", "A10BX")  # the same split as the legacy exporter (biologics, GLP-1)


# --------------------------------------------------------------------------------------------- small HL7 helpers
def esc(value: str | None) -> str:
    """HL7 v2.5 escaping of the four delimiters and the escape character (S 表3-34 MSH-1, MSH-2: ``|^~\\&``)."""
    out = (value or "").replace("\\", "\\E\\")
    return out.replace("|", "\\F\\").replace("^", "\\S\\").replace("~", "\\R\\").replace("&", "\\T\\")


def ts(value: str | None) -> str:
    """``2026-09-03 14:00:00`` or ``2026-09-03`` as an HL7 TS (S 3.3.2: ``YYYYMMDD[HH[MM[SS]]]``)."""
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    return digits[:14]


def plus(stamp: str, *, days: int = 0, hours: int = 0, minutes: int = 0) -> str:
    dt = datetime.strptime(stamp[:14].ljust(14, "0"), "%Y%m%d%H%M%S")
    return (dt + timedelta(days=days, hours=hours, minutes=minutes)).strftime("%Y%m%d%H%M%S")


def seg(name: str, fields: dict[int, str], width: int = 0) -> str:
    """A segment from ``{field number: value}``; trailing empty fields are not written."""
    n = max([width, *fields])
    return "|".join([name] + [fields.get(i, "") for i in range(1, n + 1)]).rstrip("|") or name


def msh(when: str, kind: str, control: str) -> str:
    """S 表3-34: MSH-2 ``^~\\&``, MSH-5 ``GW``, MSH-7 to the second, MSH-9 type^event^structure, MSH-11 ``P``, MSH-12
    ``2.5``, MSH-18 ``~ISO IR87``, MSH-20 ``ISO 2022-1994``, MSH-21 the SS-MIX2 1.2 profile."""
    return (
        f"MSH|^~\\&|HIS|SENDER|GW|RECEIVER|{when[:14].ljust(14, '0')}||{kind}|{control}|P|2.5||||||"
        f"~ISO IR87||ISO 2022-1994|{MSH21}"
    )


def hot9(yj: str) -> str:
    """A synthetic, stable 9-digit HOT code for a YJ code (made up; real HOT codes come from the site's master)."""
    return str(int(hashlib.sha256(yj.encode()).hexdigest()[:12], 16))[-9:].rjust(9, "0")


def disease_number(exchange: str) -> str:
    """An invented 8-digit 病名管理番号 (MDCDX2 shape, S 表3-47 PRB-3) for a sample exchange code: ``9999`` and four
    digits from a hash. No MEDIS row is copied."""
    return "9999" + str(int(hashlib.sha256(exchange.encode()).hexdigest()[:8], 16) % 10000).rjust(4, "0")


# --------------------------------------------------------------------------------------------- the storage writer
@dataclass
class Written:
    """One file: where, and what it is (for the reader comparison and the counts)."""

    path: Path
    typ: str
    event: str
    flag: str


@dataclass
class SpecStorage:
    """The standardised storage being written (G 2.2 and 3.1)."""

    root: Path
    files: list[Written] = field(default_factory=list)
    counts: Counter[str] = field(default_factory=Counter)
    utf8: int = 0
    _seq: dict[tuple[str, str, str], int] = field(default_factory=lambda: defaultdict(int))
    _ms: int = 0

    def sequence(self, patient: str, day: str, typ: str) -> str:
        """G 表3.1-3 No.4: for admissions and transfers that can happen more than once a day, a number that tells the
        day's events apart."""
        self._seq[patient, day, typ] += 1
        return str(self._seq[patient, day, typ])

    def stamp(self, when: str) -> str:
        """G 表3.1-3 No.5: the 発生日時, ``YYYYMMDDHHMMSSFFF``, distinct for every file."""
        self._ms = (self._ms + 1) % 1000
        return when[:14].ljust(14, "0") + f"{self._ms:03d}"

    def put(
        self, patient: str, day: str, typ: str, order: str, dept: str, when: str, segments: list[str], flag: str = "1"
    ) -> Path:
        """``<root>/<pid 1-3>/<pid 4-6>/<pid>/<診療日>/<データ種別>/`` and the file
        ``<pid>_<診療日>_<データ種別>_<オーダNo>_<発生日時>_<診療科>_<flag>`` (G 図2.2-1, 3.1.2 (1)), no extension
        (3.1.2 (3) ①), JIS (3.1.2 (3) ②, S 表3-34 MSH-18), segments ended by ``<CR>`` (S 2.1.4)."""
        body = "\r".join(segments) + "\r"
        try:
            data = body.encode("iso2022_jp")
        except UnicodeEncodeError:  # not settled (D-1262): the legacy exporter's fallback is kept
            body = body.replace("|~ISO IR87||ISO 2022-1994|", "|UNICODE UTF-8|||", 1)
            data = body.encode("utf-8")
            self.utf8 += 1
        d = self.root / patient[0:3] / patient[3:6] / patient / day / typ
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{patient}_{day}_{typ}_{order}_{self.stamp(when)}_{dept or DEPT_NONE}_{flag}"
        path.write_bytes(data)
        event = segments[0].split("|")[8].split("^")[1] if segments[0].startswith("MSH|") else ""
        self.files.append(Written(path, typ, event, flag))
        self.counts[typ] += 1
        return path

    def rename(self, path: Path, flag: str) -> Path:
        """G 3.1.4 (2) ⑥: an earlier file of the record is renamed to flag 2 (過去履歴) or 0 (無効)."""
        new = path.with_name(path.name[:-1] + flag)
        path.rename(new)
        for w in self.files:
            if w.path == path:
                w.path, w.flag = new, flag
        return new


# --------------------------------------------------------------------------------------------- reading the CSVs
def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _rev(path: Path, key: str, value: str) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for r in _read(path):
        out.setdefault(r[value], (r[key], r.get("name", "")))
    return out


class Patients:
    """PID (S 表3-36): PID-3 the patient ID with type ``PI``, PID-5 the name (R), PID-7 birth (SS-MIX2 R), PID-8 sex
    (SS-MIX2 R)."""

    def __init__(self, rows: list[dict[str, str]]) -> None:
        self.rows = {r["mrn"]: r for r in rows}

    def pid(self, mrn: str, *, phone: str | None = None) -> str:
        p = self.rows.get(mrn, {})
        family, _, given = (p.get("name") or "").partition("　")
        tel = esc(p.get("phone") if phone is None else phone)
        return seg(
            "PID",
            {
                1: "0001",
                3: f"{esc(mrn)}^^^^PI",
                5: f"{esc(family)}^{esc(given)}^^^^^L^I",
                7: ts(p.get("birth_date")),
                8: p.get("sex", "") or "U",
                13: f"^PRN^PH^^^^^^^^^{tel}" if tel else "",
                29: ts(p.get("death_date")),
                30: "Y" if p.get("death_date") else "",
            },
        )


def pv1(cls: str, *, dept: str = "", doctor: str = "", visit: str = "", start: str = "", end: str = "") -> str:
    """PV1 (S 表3-38): PV1-2 patient class (R; C 表49: I 入院患者, O 外来患者), PV1-7 attending doctor, PV1-10
    department, PV1-19 visit number, PV1-44 admit / visit time, PV1-45 discharge time."""
    return seg(
        "PV1",
        {
            1: "0001",
            2: cls,
            7: f"{esc(doctor)}^^^^^^^^^L^^^^^I" if doctor else "",
            10: esc(dept),
            19: esc(visit),
            44: start,
            45: end,
        },
    )


def evn(recorded: str, occurred: str = "") -> str:
    """EVN (S 表3-35): EVN-2 the time recorded (R), EVN-6 the time the event occurred."""
    return seg("EVN", {2: recorded, 6: occurred})


# --------------------------------------------------------------------------------------------- ADT
ADT_STRUCT = {  # S 3.4.n: the message structure each ADT event uses (and HL7 v2.5 表0354)
    "A08": "ADT_A01",
    "A23": "ADT_A21",
    "A54": "ADT_A54",
    "A55": "ADT_A52",
    "A04": "ADT_A01",
    "A14": "ADT_A05",
    "A27": "ADT_A21",
    "A01": "ADT_A01",
    "A11": "ADT_A09",
    "A21": "ADT_A21",
    "A52": "ADT_A52",
    "A22": "ADT_A21",
    "A53": "ADT_A52",
    "A15": "ADT_A15",
    "A26": "ADT_A21",
    "A02": "ADT_A02",
    "A12": "ADT_A09",
    "A16": "ADT_A16",
    "A25": "ADT_A21",
    "A03": "ADT_A03",
    "A13": "ADT_A01",
    "A60": "ADT_A60",
}


def adt(when: str, event: str, control: str, pid: str, *rest: str) -> list[str]:
    return [msh(when, f"ADT^{event}^{ADT_STRUCT[event]}", control), *rest[:1], pid, *rest[1:]]


@dataclass
class Episode:
    """A synthetic admission (the CSV hospital of profile ``ci`` holds outpatient visits only)."""

    mrn: str
    visit: str
    dept: str
    doctor: str
    admit: str  # YYYYMMDDHHMMSS
    discharge: str


def _patients(st: SpecStorage, people: Patients, patients: list[dict[str, str]]) -> None:
    """ADT-00 (ADT^A08, G 表3.1-2 No.1): 診療日 "-" (G 表3.1-1 No.1), オーダNo ALL9. Every 50th patient's phone changed
    once: the earlier file is renamed to flag 2 (G 3.1.4 (2) ⑥). One patient registered by mistake is deleted
    (ADT^A23, No.2): the A08 file is renamed to 0 and the A23 written as 0."""
    for i, p in enumerate(patients):
        when = "20200101090000"
        if i % 50 == 1:
            old = st.put(
                p["mrn"],
                "-",
                "ADT-00",
                ALL9,
                DEPT_NONE,
                when,
                adt(when, "A08", f"P{p['mrn']}a", people.pid(p["mrn"], phone="000-0000-0000"), evn(when), pv1("O")),
            )
            st.rename(old, "2")
            when = "20210101090000"
        st.put(
            p["mrn"],
            "-",
            "ADT-00",
            ALL9,
            DEPT_NONE,
            when,
            adt(when, "A08", f"P{p['mrn']}", people.pid(p["mrn"]), evn(when), pv1("O")),
        )
    if patients:
        extra = str(max(int(p["mrn"]) for p in patients if p["mrn"].isdigit()) + 1)
        people.rows[extra] = {"mrn": extra, "name": "誤登録　患者", "birth_date": "1990-01-01", "sex": "F"}
        when = "20260101090000"
        old = st.put(
            extra,
            "-",
            "ADT-00",
            ALL9,
            DEPT_NONE,
            when,
            adt(when, "A08", f"P{extra}", people.pid(extra), evn(when), pv1("O")),
        )
        st.rename(old, "0")
        when = "20260101100000"
        st.put(
            extra,
            "-",
            "ADT-00",
            ALL9,
            DEPT_NONE,
            when,
            adt(when, "A23", f"D{extra}", people.pid(extra), evn(when), pv1("O")),
            flag="0",
        )


def _doctors(st: SpecStorage, people: Patients, encounters: list[dict[str, str]]) -> None:
    """ADT-01 (ADT^A54 / A55, G 表3.1-2 No.3, 4): 診療日 "-" (G 表3.1-1 No.3, 4), オーダNo ALL9 (G 表3.1-3 No.4: not
    managed by an order). Every 10th patient's doctor in charge; every third of those cancelled (A55, flag 0)."""
    seen: list[str] = []
    for e in encounters:
        if e["mrn"] in seen:
            continue
        seen.append(e["mrn"])
        if len(seen) % 10 != 1:
            continue
        when = ts(e.get("visit_datetime"))
        doc = pv1("O", dept=e.get("dept_code", ""), doctor=e.get("staff_id", ""))
        path = st.put(
            e["mrn"],
            "-",
            "ADT-01",
            ALL9,
            e.get("dept_code", ""),
            when,
            adt(when, "A54", f"T{e['enc_no']}", people.pid(e["mrn"]), evn(when), doc),
        )
        if len(seen) % 30 == 1:
            st.rename(path, "0")
            later = plus(when, hours=1)
            st.put(
                e["mrn"],
                "-",
                "ADT-01",
                ALL9,
                e.get("dept_code", ""),
                later,
                adt(later, "A55", f"U{e['enc_no']}", people.pid(e["mrn"]), evn(later), doc),
                flag="0",
            )


def _visits(st: SpecStorage, people: Patients, encounters: list[dict[str, str]]) -> list[Episode]:
    """ADT-12 (ADT^A04): 診療日 PV1-44 (G 表3.1-1 No.5), オーダNo the day's sequence (G 表3.1-3 No.4). Every 40th
    visit is followed the next day by a synthetic admission (returned)."""
    episodes: list[Episode] = []
    for i, e in enumerate(encounters):
        when = ts(e.get("visit_datetime"))
        day = when[:8]
        dept, doctor = e.get("dept_code", ""), e.get("staff_id", "")
        st.put(
            e["mrn"],
            day,
            "ADT-12",
            st.sequence(e["mrn"], day, "ADT-12"),
            dept,
            when,
            adt(
                when,
                "A04",
                e["enc_no"],
                people.pid(e["mrn"]),
                evn(when),
                pv1("O", dept=dept, doctor=doctor, visit=e["enc_no"], start=when),
            ),
        )
        if i % 40 == 7:
            admit = plus(day + "100000", days=1)
            episodes.append(Episode(e["mrn"], f"{e['enc_no']}A", dept, doctor, admit, plus(admit, days=5)))
    return episodes


def _admissions(st: SpecStorage, people: Patients, episodes: list[Episode]) -> None:
    """The inpatient ADT types of G 表3.1-2 (No.6 to 21), each under its own 診療日 (G 表3.1-1 No.6 to 21) and the day's
    sequence: planned admission (ADT-21, PV2-8), admission (ADT-22, PV1-44), leave and return (ADT-31 / 32, EVN-6),
    planned transfer and transfer (ADT-41, PV2-8 / ADT-42, EVN-6), planned discharge (ADT-51, PV2-9), discharge
    (ADT-52, PV1-45). The first episodes also carry each cancellation (A27, A11, A52, A53, A26, A12, A25, A13): the
    cancelled file is renamed to flag 0 and the cancelling message written as 0 in the same record (G 3.1.4 (2) ⑥ 2)."""

    def write(
        ep: Episode, typ: str, event: str, day: str, when: str, *extra: str, order: str = "", flag: str = "1"
    ) -> tuple[Path, str]:
        order = order or st.sequence(ep.mrn, day, typ)
        segs = adt(when, event, f"{event}{ep.visit}{when[-6:]}", people.pid(ep.mrn), evn(when, *extra[:1]), *extra[1:])
        return st.put(ep.mrn, day, typ, order, ep.dept, when, segs, flag), order

    def cancel(ep: Episode, path: Path, typ: str, event: str, day: str, order: str, when: str, *extra: str) -> None:
        st.rename(path, "0")
        write(ep, typ, event, day, when, *extra, order=order, flag="0")

    for k, ep in enumerate(episodes):
        inp = {"dept": ep.dept, "doctor": ep.doctor, "visit": ep.visit}
        planned = plus(ep.admit, days=-1, hours=-1)
        admit_day, out_day = ep.admit[:8], ep.discharge[:8]
        pv2_admit = seg("PV2", {8: ep.admit})
        p, o = write(ep, "ADT-21", "A14", admit_day, planned, "", pv1("I", **inp), pv2_admit)
        if k == 3:  # the planned admission cancelled, then planned again
            cancel(ep, p, "ADT-21", "A27", admit_day, o, plus(planned, minutes=5), "", pv1("I", **inp), pv2_admit)
            write(ep, "ADT-21", "A14", admit_day, plus(planned, minutes=10), "", pv1("I", **inp), pv2_admit)
        admission = pv1("I", start=ep.admit, **inp)
        p, o = write(ep, "ADT-22", "A01", admit_day, ep.admit, "", admission)
        if k == 4:  # an admission entered and cancelled (A11): this episode ends there
            cancel(ep, p, "ADT-22", "A11", admit_day, o, plus(ep.admit, hours=1), "", admission)
            continue
        if k % 3 == 0:  # leave and return on the third day
            out = plus(ep.admit, days=2, hours=3)
            back = plus(out, hours=5)
            p, o = write(ep, "ADT-31", "A21", out[:8], out, out, admission)
            if k == 0:
                cancel(ep, p, "ADT-31", "A52", out[:8], o, plus(out, minutes=30), out, admission)
            else:
                pv2_back = seg("PV2", {47: back})
                p, o = write(ep, "ADT-32", "A22", back[:8], back, back, admission, pv2_back)
                if k == 6:
                    cancel(ep, p, "ADT-32", "A53", back[:8], o, plus(back, minutes=30), back, admission, pv2_back)
        if k % 2 == 0:  # a planned transfer and the transfer on the second day
            move = plus(ep.admit, days=1, hours=4)
            pv2_move = seg("PV2", {8: move})
            p, o = write(ep, "ADT-41", "A15", move[:8], plus(move, hours=-2), "", admission, pv2_move)
            if k == 2:
                cancel(ep, p, "ADT-41", "A26", move[:8], o, plus(move, hours=-1), "", admission, pv2_move)
            p, o = write(ep, "ADT-42", "A02", move[:8], move, move, admission)
            if k == 8:
                cancel(ep, p, "ADT-42", "A12", move[:8], o, plus(move, minutes=20), move, admission)
        pv2_out = seg("PV2", {9: ep.discharge})
        p, o = write(ep, "ADT-51", "A16", out_day, plus(ep.discharge, days=-1), "", admission, pv2_out)
        if k == 2:
            cancel(ep, p, "ADT-51", "A25", out_day, o, plus(ep.discharge, days=-1, hours=1), "", admission, pv2_out)
        discharged = pv1("I", start=ep.admit, end=ep.discharge, **inp)
        p, o = write(ep, "ADT-52", "A03", out_day, ep.discharge, "", discharged)
        if k == 2:  # the discharge cancelled (A13), and the patient discharged the next day
            cancel(ep, p, "ADT-52", "A13", out_day, o, plus(ep.discharge, hours=2), "", discharged)
            later = plus(ep.discharge, days=1)
            write(ep, "ADT-52", "A03", later[:8], later, "", pv1("I", start=ep.admit, end=later, **inp))


def _allergies(st: SpecStorage, people: Patients, patients: list[dict[str, str]]) -> None:
    """ADT-61 (ADT^A60, G 表3.1-2 No.22): 診療日 "-" (G 表3.1-1 No.22), ALL9. IAM (S 表3-45): IAM-1 set id, IAM-2
    allergen type (HL7 0127), IAM-3 the allergen (R; a local code here), IAM-4 severity (HL7 0128), IAM-6 the action
    (R; HL7 0323). Every 10th patient; every 20th has an earlier version kept as flag 2."""
    for i, p in enumerate(patients):
        if i % 10 != 4:
            continue
        when = "20250401090000"
        iam = "IAM|1|DA^薬剤アレルギー^HL70127|L0001^ペニシリン系抗菌薬^99ALG|MO^中等度^HL70128|発疹|A^追加^HL70323"
        if i % 20 == 4:
            old = st.put(
                p["mrn"],
                "-",
                "ADT-61",
                ALL9,
                DEPT_NONE,
                when,
                adt(when, "A60", f"G{p['mrn']}a", people.pid(p["mrn"]), evn(when), iam),
            )
            st.rename(old, "2")
            when = "20250601090000"
            iam += "\rIAM|2|FA^食物アレルギー^HL70127|L0102^そば^99ALG|MI^軽度^HL70128|蕁麻疹|A^追加^HL70323"
        st.put(
            p["mrn"],
            "-",
            "ADT-61",
            ALL9,
            DEPT_NONE,
            when,
            adt(when, "A60", f"G{p['mrn']}", people.pid(p["mrn"]), evn(when), *iam.split("\r")),
        )


# --------------------------------------------------------------------------------------------- PPR-01
def prb(
    action: str,
    when: str,
    number: str,
    name: str,
    instance: str,
    *,
    icd10: str = "",
    diagnosed: str = "",
    onset: str = "",
    rank: str = "2",
    outcome: str = "",
    ended: str = "",
) -> str:
    """PRB (S 表3-47): PRB-1 action (R; HL7 0287, C 表35), PRB-2 its time (R), PRB-3 the 病名管理番号 under ``MDCDX2``
    (R), PRB-4 the instance id (R), PRB-7 診断日, PRB-9 終了日, PRB-10 ``<ICD-10>^^I10^<診断種別>^<text>^JHSD0004``
    (C 表94: O 外来時), PRB-14 転帰 (HL7 0241, C 表34), PRB-15 転帰日 (equal to PRB-9 for death, recovery and full
    recovery), PRB-16 onset, PRB-18 病名区分 (JHSD0007, C 表97: 1 主診断, 2 副診断). PRB-10 only for a WHO ICD-10
    code (I10, HL7 table 0396): the synthetic hospital also holds ICD-10-CM codes (M10.071), left to the exchange
    code."""
    who = icd10.replace(".", "") if WHO_ICD10.match(icd10.replace(".", "")) else ""
    return seg(
        "PRB",
        {
            1: action,
            2: when,
            3: f"{number}^{esc(name)}^MDCDX2",
            4: esc(instance),
            7: diagnosed,
            9: ended,
            10: f"{who}^^I10^O^外来時^JHSD0004" if who else "",
            14: outcome,
            15: ended if outcome else "",
            16: onset,
            18: {"1": "1^主診断^JHSD0007", "2": "2^副診断^JHSD0007"}[rank],
        },
    )


def zpr(number: str, name: str, exchange: str) -> str:
    """ZPR (S 表3-48): ZPR-2 the 病名管理番号 (R, ``MDCDX2``), ZPR-5 the 病名交換用コード (``MDCDX2``)."""
    return seg("ZPR", {2: f"{number}^{esc(name)}^MDCDX2", 5: f"{exchange}^{esc(name)}^MDCDX2" if exchange else ""})


def _diagnoses(st: SpecStorage, people: Patients, rows: list[dict[str, str]]) -> None:
    """PPR-01 (PPR^ZD1, S 表3-46): one file per patient holding all its diagnoses, 診療日 "-", ALL9 (G 3.1.2 (2),
    表3.1-1 No.23). A patient with several diagnoses has an earlier snapshot (all but the newest) renamed to flag 2;
    every 25th such patient's earlier snapshot also holds an invented diagnosis the newer one deletes (PRB-1 ``DE``)."""
    byomei = _rev(JP_CORE / "byomei_to_icd10.csv", "code", "icd10")
    per: dict[str, list[dict[str, str]]] = defaultdict(list)
    for d in rows:
        per[d["mrn"]].append(d)

    def line(d: dict[str, str], action: str, when: str, first: bool) -> list[str]:
        exchange, name = byomei.get(d["icd10"], ("", ""))
        number = disease_number(exchange or d["icd10"])
        name = name or d["icd10"]
        out = prb(
            action,
            when,
            number,
            name,
            d["diag_no"],
            icd10=d["icd10"],
            diagnosed=ts(d.get("recorded_date")),
            onset=ts(d.get("diag_date")),
            rank="1" if first else "2",
            outcome="F^完全に回復した^HL70241" if d.get("status") == "R" else "",
        )
        return [out, zpr(number, name, exchange)]

    for n, (mrn, dx) in enumerate(per.items()):
        dx.sort(key=lambda d: (ts(d.get("recorded_date")), d["diag_no"]))
        newest = ts(dx[-1].get("recorded_date")) or "20260101"
        when = plus(newest[:8] + "120000", minutes=0)
        if len(dx) > 1:
            before = ts(dx[-2].get("recorded_date"))[:8] + "120000"
            segs = [msh(before, "PPR^ZD1^PPR_ZD1", f"Z{mrn}a"), people.pid(mrn)]
            for j, d in enumerate(dx[:-1]):
                segs += line(d, "AD", before, j == 0)
            gone = {"diag_no": f"X{mrn}", "icd10": "J06.9", "recorded_date": before, "diag_date": before}
            if n % 25 == 0:
                segs += line(gone, "AD", before, False)
            old = st.put(mrn, "-", "PPR-01", ALL9, DEPT_NONE, before, segs)
            st.rename(old, "2")
            if before >= when:
                when = plus(before, minutes=1)
        segs = [msh(when, "PPR^ZD1^PPR_ZD1", f"Z{mrn}"), people.pid(mrn)]
        for j, d in enumerate(dx):
            segs += line(d, "AD" if j == len(dx) - 1 or len(dx) == 1 else "UC", when, j == 0)
        if len(dx) > 1 and n % 25 == 0:
            segs += line(gone, "DE", when, False)
        st.put(mrn, "-", "PPR-01", ALL9, DEPT_NONE, when, segs)


# --------------------------------------------------------------------------------------------- medicines
def _days(start: str, end: str) -> int:
    try:
        a = datetime.strptime(start[:8], "%Y%m%d")
        b = datetime.strptime(end[:8], "%Y%m%d")
    except ValueError:
        return 0
    return max((b - a).days + 1, 0)


def _medicines(st: SpecStorage, people: Patients, rows: list[dict[str, str]]) -> None:
    """OMP-01 (RDE^O11, S 表3-55): ORC (S 表3-56: ORC-1, ORC-2, ORC-4 R; ORC-9 the order time, the 診療日 of G 表3.1-1
    No.25), RXE (S 表3-57: RXE-2 ``HOT9`` with the local code as its alternate, RXE-3 one dose, RXE-5 its unit, RXE-10 /
    RXE-11 the amount dispensed, RXE-31 ``<local>^^<local system>^<YJ>^^YJ``), TQ1 (TQ1-3 the 用法, a local code here,
    TQ1-6 the days), RXR (RXR-1 the route, R). OMP-11 (RAS^O17, S 表3-60): ORC, RXA (S 表3-61: RXA-1, 2, 4, 5, 6 R;
    RXA-3 the 診療日, G 表3.1-1 No.26), RXR. Injections (OMP-02 / OMP-12, S 表3-62, 表3-70): RXE-2 the 注射種別 (C 表78,
    ``99I02``), the drug in RXC (S 表3-67: RXC-1, 2, 4 R), ORC-17 and ORC-29 (S 表3-63, R). Every 30th order also has
    an extra order entered and cancelled (ORC-1 ``CA``; the order renamed to 0, the cancel written as 0)."""
    yj_of = _rev(JP_CORE / "yj_to_atc.csv", "yj_code", "atc")
    for i, m in enumerate(rows):
        mrn, number, dept = m["mrn"], m["rx_no"], m.get("dept_code", "")
        yj, _ = yj_of.get(m.get("atc", ""), ("", ""))
        injection = (m.get("atc") or "").startswith(INJECTABLE)
        local = esc(m.get("nhi_drug_code")) or f"D{i:05d}"
        name = esc(m.get("drug_name"))
        drug = f"{hot9(yj)}^{name}^HOT9^{local}^{name}^{CS_DRUG}" if yj else f"{local}^{name}^{CS_DRUG}"
        extra = f"{local}^^{CS_DRUG}^{yj}^^YJ" if yj else ""
        unit = f"{esc(m.get('dose_unit')) or 'TAB'}^{esc(m.get('dose_unit')) or '錠'}^MR9P"
        start, end = ts(m.get("start_date")), ts(m.get("end_date"))
        days = _days(start, end) or 1
        ordered = (ts(m.get("order_date")) or start)[:8] + "090000"
        dose = esc(m.get("daily_dose")) or "1"
        try:
            total = f"{float(dose) * days:g}"
        except ValueError:
            total = dose
        typ, done_typ = ("OMP-02", "OMP-12") if injection else ("OMP-01", "OMP-11")
        cls = "O"
        # ORC-5 the order status (HL7 0038): SS-MIX2 "O", sent when the HIS has it (S 表3-4)
        status = {"active": "IP", "completed": "CM", "stopped": "DC"}.get(m.get("status", ""), "")
        orc = {1: "NW", 2: number, 4: number, 5: status, 9: ordered, 17: f"{esc(dept)}^^{CS_ORDER}"}
        if injection:
            orc[29] = "O^外来^HL70482"
            body = [
                seg("RXE", {2: "00^一般^99I02", 3: dose, 5: unit, 10: "1", 11: unit}),
                seg("TQ1", {1: "1", 6: f"{days}^d", 7: start}),
                "RXR|SC^皮下^HL70162",
                seg(
                    "RXC",
                    {1: "B", 2: drug, 3: dose, 4: unit},
                ),
            ]
        else:
            body = [
                seg("RXE", {2: drug, 3: dose, 5: unit, 10: total, 11: unit, 31: extra}),
                seg("TQ1", {1: "1", 3: f"U01&１日１回&{CS_USAGE}", 6: f"{days}^d", 7: start}),
                "RXR|PO^口^HL70162",
            ]
        segs = [
            msh(ordered, "RDE^O11^RDE_O11", f"R{number}"),
            people.pid(mrn),
            pv1(cls, dept=dept),
            seg("ORC", orc),
            *body,
        ]
        st.put(mrn, ordered[:8], typ, number, dept, ordered, segs)
        if i % 5 == 4:  # given: the 実施 (RAS^O17) on the start day
            given = (start or ordered)[:8] + "100000"
            rxa = seg("RXA", {1: "0", 2: "1", 3: given, 4: given, 5: drug, 6: dose, 7: unit})
            done = [
                msh(given, "RAS^O17^RAS_O17", f"A{number}"),
                people.pid(mrn),
                pv1(cls, dept=dept),
                seg("ORC", {**orc, 1: "RE"}),
                rxa,
                "RXR|SC^皮下^HL70162" if injection else "RXR|PO^口^HL70162",
            ]
            st.put(mrn, given[:8], done_typ, number, dept, given, done)
        if i % 30 == 7:  # an order entered by mistake and cancelled the same morning
            wrong = f"{number}X"
            o2 = {**orc, 2: wrong, 4: wrong}
            segs = [
                msh(ordered, "RDE^O11^RDE_O11", f"R{wrong}"),
                people.pid(mrn),
                pv1(cls, dept=dept),
                seg("ORC", o2),
                *body,
            ]
            path = st.put(mrn, ordered[:8], typ, wrong, dept, ordered, segs)
            st.rename(path, "0")
            later = plus(ordered, minutes=30)
            segs = [
                msh(later, "RDE^O11^RDE_O11", f"C{wrong}"),
                people.pid(mrn),
                pv1(cls, dept=dept),
                seg("ORC", {**o2, 1: "CA"}),
                *body,
            ]
            st.put(mrn, ordered[:8], typ, wrong, dept, later, segs, flag="0")


# --------------------------------------------------------------------------------------------- laboratory
def _labs(st: SpecStorage, people: Patients, rows: list[dict[str, str]]) -> None:
    """OML-01 (OML^O33, S 表3-72): SPM (SPM-4 the specimen, R), ORC (ORC-1, ORC-2), TQ1, OBR (OBR-2, OBR-4 R); 診療日
    ORC-9 (G 表3.1-1 No.29). OML-11 (OUL^R22, S 表3-78): SPM (SPM-17 the collection time, the 診療日 of No.30), OBR,
    ORC, OBX (S 表3-77: OBX-2, OBX-3, OBX-11 R). The order number is the lab number (ORC-2, G 表3.1-3 No.4). Every
    10th result first arrives preliminary (OBX-11 P) and is then final; the preliminary file is renamed to flag 2
    (G 3.1.2 (3) ③, 3.1.4 (2) ⑥ 1))."""
    for i, lab in enumerate(rows):
        mrn, number = lab["mrn"], lab["lab_no"]
        sampled = ts(lab.get("sample_datetime")) or "20260101080000"
        ordered = sampled[:8] + "070000" if sampled[8:] > "070000" else sampled
        code = LOCAL_TO_JLAC10.get(lab["local_code"])
        test = (
            f"{code}^{esc(lab.get('item_name'))}^JC10"
            if code
            else f"{esc(lab['local_code'])}^{esc(lab.get('item_name'))}^{CS_LAB}"
        )
        spm = seg("SPM", {1: "1", 4: "023^血清^JC10", 17: sampled})
        orc = seg("ORC", {1: "NW", 2: number, 9: ordered})
        obr = seg("OBR", {1: "1", 2: number, 4: test, 7: sampled})
        st.put(
            mrn,
            ordered[:8],
            "OML-01",
            number,
            DEPT_NONE,
            ordered,
            [
                msh(ordered, "OML^O33^OML_O33", f"O{number}"),
                people.pid(mrn),
                pv1("O"),
                spm,
                orc,
                seg("TQ1", {1: "1"}),
                obr,
            ],
        )
        value = _PRESENCE.get(lab.get("result_value") or "", lab.get("result_value") or "")
        try:
            float(value)
            vt = "NM"
        except ValueError:
            vt = "ST"

        unit = esc(lab.get("unit"))
        versions = [("P", plus(sampled, hours=1)), ("F", plus(sampled, hours=3))] if i % 10 == 3 else []
        for status, when in versions or [("F", plus(sampled, hours=3))]:
            obx = seg("OBX", {1: "1", 2: vt, 3: test, 5: esc(value), 6: unit, 11: status, 14: sampled})
            orc_done = seg("ORC", {1: "SC", 2: number, 5: "CM", 9: when})
            segs = [msh(when, "OUL^R22^OUL_R22", f"{status}{number}"), people.pid(mrn), pv1("O"), spm, obr, orc_done]
            path = st.put(mrn, sampled[:8], "OML-11", number, DEPT_NONE, when, [*segs, obx])
            if status == "P":
                st.rename(path, "2")


# --------------------------------------------------------------------------------------------- examinations
EXAMS = {  # データ種別: (order type, done type, done message, OBR-4 local code and name)
    "rad": ("OMG-01", "OMG-11", "OMI^Z23^OMI_Z23", "R0001^胸部単純X線撮影", "CR"),
    "endo": ("OMG-02", "OMG-12", "OMI^Z23^OMI_Z23", "E0001^上部消化管内視鏡検査", "ES"),
    "phys": ("OMG-03", "OMG-13", "ORU^R01^ORU_R01", "P0001^標準12誘導心電図", ""),
}


def _exams(st: SpecStorage, people: Patients, reports: list[dict[str, str]], encounters: list[dict[str, str]]) -> None:
    """OMG-01/02/03 (OMG^O19, S 表3-79, 3-88, 3-94): ORC (ORC-1, 2, 9, 12 R; ORC-9 the 診療日, G 表3.1-1 No.31, 33, 35),
    TQ1 (TQ1-1, TQ1-9 R), OBR (OBR-2, OBR-4 R). OMG-11/12 (OMI^Z23, S 表3-84, 3-92): ORC, TQ1, OBR (OBR-7 the 診療日,
    No.32, 34), ZE1 (S 表3-86 / 3-93: ZE1-1 to 3 R), IPC (S 表3-85: IPC-1, 3, 5 R). OMG-13 (ORU^R01, S 表3-99): OBR
    (OBR-7, No.36), OBX. Imaging from ``report.csv``; endoscopy for every 50th and physiology for every 30th visit."""
    jobs: list[tuple[str, str, str, str, str]] = []  # (kind, mrn, number, day, finding)
    for r in reports:
        jobs.append(("rad", r["mrn"], r["rpt_no"], ts(r.get("exam_date"))[:8], r.get("conclusion", "")))
    for i, e in enumerate(encounters):
        day = ts(e.get("visit_datetime"))[:8]
        if i % 50 == 11:
            jobs.append(("endo", e["mrn"], f"{e['enc_no']}E", day, "胃体部に発赤を認める。"))
        if i % 30 == 13:
            jobs.append(("phys", e["mrn"], f"{e['enc_no']}P", day, "洞調律、異常なし。"))
    for kind, mrn, number, day, finding in jobs:
        order_typ, done_typ, done_kind, test, modality = EXAMS[kind]
        if not day:
            continue
        ordered, done = plus(day + "090000", days=-1), day + "110000"
        obr = {1: "1", 2: number, 4: f"{test}^{CS_ORDER}"}
        orc = {1: "NW", 2: number, 9: ordered, 12: "D0001^医師^一郎^^^^^^^L^^^^^I", 17: f"01^^{CS_ORDER}"}
        tq1 = seg("TQ1", {1: "1", 9: "R^^HL70485"})
        st.put(
            mrn,
            ordered[:8],
            order_typ,
            number,
            DEPT_NONE,
            ordered,
            [
                msh(ordered, "OMG^O19^OMG_O19", f"G{number}"),
                people.pid(mrn),
                pv1("O"),
                seg("ORC", orc),
                tq1,
                seg("OBR", obr),
            ],
        )
        if kind == "phys":
            segs = [
                msh(done, done_kind, f"H{number}"),
                people.pid(mrn),
                pv1("O"),
                seg("ORC", {**orc, 1: "SC"}),
                seg("OBR", {**obr, 7: done}),
                seg("OBX", {1: "1", 2: "ST", 3: f"{test}^{CS_ORDER}", 5: esc(finding), 11: "F"}),
            ]
        else:
            uid = "2.25." + str(int(hashlib.sha256(number.encode()).hexdigest()[:24], 16))
            segs = [
                msh(done, done_kind, f"H{number}"),
                people.pid(mrn),
                pv1("O"),
                seg("ORC", {**orc, 1: "SC"}),
                tq1,
                seg("OBR", {**obr, 7: done}),
                seg("ZE1", {1: "1", 2: "1^実施^JSHR003", 3: f"{test}^{CS_ORDER}"}),
                seg("IPC", {1: number, 3: uid, 5: f"{modality}^^DCM"}),
            ]
        st.put(mrn, day, done_typ, number, DEPT_NONE, done, segs)


def _diets(st: SpecStorage, people: Patients, episodes: list[Episode]) -> None:
    """OMD (OMD^O03, S 表3-51): ORC (S 表3-52: ORC-1, ORC-2 R; ORC-9 the 診療日, G 表3.1-1 No.24), TQ1, ODS (S 表3-54:
    ODS-1 the type, R; ODS-3 the diet, R: a local code here, or the SS-MIX2 TF table's ``NPO``, C 表107). One diet
    order per admission; every fourth admission is nil by mouth first."""
    for k, ep in enumerate(episodes):
        ordered = plus(ep.admit, minutes=-30)
        number = f"{ep.visit}D"
        ods = "ODS|D||NPO^食止め^SSMIXTF01" if k % 4 == 1 else "ODS|D||L0001^常食^99DIE"
        st.put(
            ep.mrn,
            ordered[:8],
            "OMD",
            number,
            ep.dept,
            ordered,
            [
                msh(ordered, "OMD^O03^OMD_O03", f"M{number}"),
                people.pid(ep.mrn),
                pv1("I", dept=ep.dept),
                seg("ORC", {1: "NW", 2: number, 9: ordered}),
                seg("TQ1", {1: "1", 7: ep.admit}),
                ods,
            ],
        )


# --------------------------------------------------------------------------------------------- extended storage
DOCS = {  # E 2.2 (4) ③: [local code]^local name^[local system]^LOINC^standard name^LN (E 別紙 表1)
    "summary": "L0101^退院時サマリー^99DOC^18842-5^退院時サマリ^LN",
    "imaging": "L0201^画像診断報告書^99DOC^18748-4^画像検査報告書^LN",
}


def contents_xml(created: str, name: str, mime: str) -> bytes:
    """E 2.2 (7), 表2.2-2: ``_contents.xml`` with the root ``Contents`` (createDateTime, createVender) and one
    ``Document`` (name, mime, relDir)."""
    when = datetime.strptime(created[:14], "%Y%m%d%H%M%S").strftime("%Y-%m-%dT%H:%M:%S+09:00")
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<Contents createDateTime="{when}" createVender="TrialBox synthetic">\n'
        f'  <Document name="{name}" mime="{mime}" relDir="" />\n'
        "</Contents>\n"
    ).encode()


def _report_pdf(lines: list[str]) -> bytes:
    import io

    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, invariant=1)
    y = 760
    for line in lines:
        c.drawString(72, y, line)
        y -= 18
    c.save()
    return buf.getvalue()


def _documents(root: Path, patients: list[dict[str, str]], encounters: list[dict[str, str]]) -> Counter[str]:
    """E 2.2 (3) to (6), 図2.2-2:
    ``<root>/<pid 1-3>/<pid 4-6>/<pid>/<診療日>/<データ種別>/<コンテンツ>/<files>``, the content folder named
    ``pid_診療日_データ種別コード_特定キー_発生日時_診療科_flag`` (E 2.2 (5) ②), each file with its extension
    (E 2.2 (6) ⑤, 表2.2-1). A discharge summary for every 25th patient (one corrected: the first content folder renamed
    to flag 2, E 2.2 (5) ④) and an imaging report for every 30th."""
    last: dict[str, str] = {}
    for e in encounters:
        if e.get("visit_datetime", "") > last.get(e["mrn"], ""):
            last[e["mrn"]] = e["visit_datetime"]
    made: Counter[str] = Counter()
    ms = 0

    def put(
        p: str, day: str, kind: str, key: str, when: str, name: str, mime: str, data: bytes, flag: str = "1"
    ) -> Path:
        nonlocal ms
        ms = (ms + 1) % 1000
        code = DOCS[kind].split("^")[3]
        folder = root / p[0:3] / p[3:6] / p / day / DOCS[kind] / f"{p}_{day}_{code}_{key}_{when}{ms:03d}_-_{flag}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)
        (folder / "_contents.xml").write_bytes(contents_xml(when, name, mime))
        made[kind] += 1
        return folder

    for i, p in enumerate(patients):
        day = ts(last.get(p["mrn"]))[:8]
        if not day:
            continue
        if i % 25 == 3:
            text = (
                "退院時サマリ\r\n入院中の経過：痛風発作に対しコルヒチンを投与し、症状は軽快した。\r\n"
                "退院時処方：アロプリノール錠100mg 1日1回。\r\n今後の方針：外来で尿酸値を確認する。\r\n"
            )
            if i == 3:
                first = put(
                    p["mrn"],
                    day,
                    "summary",
                    f"S{p['mrn']}",
                    day + "150000",
                    "summary.txt",
                    "text/plain",
                    "退院時サマリ（作成中）\r\n".encode("cp932"),
                )
                first.rename(first.with_name(first.name[:-1] + "2"))
            put(
                p["mrn"],
                day,
                "summary",
                f"S{p['mrn']}",
                day + "170000",
                "summary.txt",
                "text/plain",
                text.encode("cp932"),
            )
        if i % 30 == 5:
            pdf = _report_pdf(["Imaging report (synthetic)", "Chest X-ray: no acute findings.", "Impression: normal."])
            put(p["mrn"], day, "imaging", f"R{p['mrn']}", day + "160000", "report.pdf", "application/pdf", pdf)
    return made


# --------------------------------------------------------------------------------------------- the whole export
def export(src: Path, out: Path) -> dict[str, int]:
    """Write ``src`` (a canonical-CSV hospital) as SS-MIX2 storage in the specification's shapes under ``out``.
    Returns files written per データ種別 and per extended-storage kind."""
    import shutil

    out.mkdir(parents=True, exist_ok=True)
    st = SpecStorage(out)
    patients = _read(src / "patient.csv")
    people = Patients(patients)
    encounters = _read(src / "encounter.csv")
    _patients(st, people, patients)
    _doctors(st, people, encounters)
    episodes = _visits(st, people, encounters)
    _admissions(st, people, episodes)
    _allergies(st, people, patients)
    _diagnoses(st, people, _read(src / "diagnosis.csv"))
    _medicines(st, people, _read(src / "medication.csv"))
    _labs(st, people, _read(src / "lab.csv"))
    _exams(st, people, _read(src / "report.csv"), encounters)
    _diets(st, people, episodes)
    ext = out / "extended"  # not SS-MIX2: the tables it does not standardise (the legacy exporter's place, kept)
    ext.mkdir(exist_ok=True)
    standard = {"patient", "encounter", "diagnosis", "medication", "lab"}
    for f in sorted(src.glob("*.csv")):
        if f.stem not in standard:
            shutil.copyfile(f, ext / f.name)
    counts: dict[str, int] = dict(sorted(st.counts.items()))
    for kind, n in _documents(out / "extended_storage", patients, encounters).items():
        counts[f"extended:{kind}"] = n
    if st.utf8:
        counts["files in UTF-8 (a character JIS X 0208 cannot write)"] = st.utf8
    return counts
