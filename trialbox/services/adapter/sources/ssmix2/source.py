"""``ssmix2`` source: a reader for SS-MIX2 standardized storage (TB-PLAN-03 step 7, D-122; was a stub under D-28) and
its extended storage (TB-PLAN-04 step 7, D-137).

Layout (SS-MIX2 標準化ストレージ仕様書 v1.2): ``<root>/<id[0:3]>/<id[3:6]>/<patient id>/<YYYYMMDD | ->/<type>/<file>``
with file names ``<patient id>_<date>_<type>_<order no>_<timestamp>_<dept>_<flag>``. Every change writes a new file;
the newest timestamp per (patient, type, order no) wins and flag ``0`` means the record was deleted.

The message types read, and the canonical tables (``mapping/templates/CANONICAL.md``) they become:

* ``ADT-00`` (ADT^A08, PID) -> patient: PID-3 id, PID-5 name, PID-7 birth, PID-8 sex, PID-13 phone, PID-29 death.
* ``ADT-12`` outpatient visit / ``ADT-22`` admission (PV1) -> encounter: PV1-19 visit no, PV1-44 time, PV1-10 dept,
  PV1-7 doctor, PV1-2 class O/I/E -> OPD/IPD/ER. An admission without a discharge is ``in-progress``.
* ``ADT-52`` (D-137) -> changes to the encounter of PV1-19, in time order (EVN-6, else EVN-2, else MSH-7), chosen by
  the trigger event of MSH-9: ``A03`` discharge (PV1-45 the end, the encounter ``finished``); ``A06`` / ``A07`` and any
  other event that carries PV1-2 a patient class change (患者区分変更): the new class from PV1-2, the old one kept as
  ``prev_enc_type`` with the time of the change (``Encounter.classHistory``). A change for a visit the storage does not
  hold is counted (``stats``), never turned into a visit.
* ``PPR-01`` (PPR^ZD1, PRB) -> diagnosis: PRB-3 標準病名 ``code^name^99XYZ^ICD-10^name^I10``, PRB-4 id, PRB-2
  recorded, PRB-16 onset, PRB-14 status, PRB-13 the 疑い flag (``suspected``, D-142), PV1-19 visit no. The 標準病名
  code is kept (``byomei_code``) beside the ICD-10, so a code nothing can read reaches the lake as
  itself, not as an empty code (D-130, D-137).
* ``OMP-01`` prescription / ``OMP-02`` injection orders (RDE^O11, ORC/RXE/TQ1) -> medication: ORC-2 order no, ORC-4
  Rp group, ORC-9 date, ORC-5 status, RXE-2 the drug (YJ or HOT, with an alternate ATC, YJ or HOT), RXE-3 dose,
  RXE-5 unit, TQ1-7/8 start/end, file dept.
* ``OMP-11`` prescription / ``OMP-12`` injection 実施 (RAS^O17, ORC/RXA) (D-137) -> medication, YJ / HOT kept coded:
  folded into the order with the same ORC-2 when the storage has it (only empty fields are filled), else a
  medication of its own: RXA-5 the drug, RXA-3/4 start/end, RXA-6/7 amount and unit, ORC-9 date, ORC-5 status.
* ``OML-11`` lab results (OUL^R22, OBR/OBX) -> lab: OBX-21 result id, OBX-3 ``JLAC10^name^JC10``, OBX-5 value,
  OBX-6 unit, OBX-14 sample time; ``local_code`` is the JLAC10 code (the JP mapping looks it up to LOINC); the
  specimen comes from the JLAC10 material code.

ICD-10 comes from PRB-3's alternate coding; when a vendor sends only the 標準病名 code it is looked up in the site's
licensed MEDIS release (``adapter.licensed``; only to a code in the ICD-10-CM list) and then in
``byomei_to_icd10.csv`` (``code,icd10``). ATC works the same way from ``yj_to_atc.csv`` (``yj_code,atc``) and a
licensed YJ release that carries ATC. Codes that resolve nowhere are counted in :attr:`Ssmix2Source.missed` and reach
the mapping without a standard code (D-130 keeps them unknown).

Extended storage (拡張ストレージ, D-137): documents (reports, discharge summaries, PDFs, text) under
``<root>/extended_storage/`` (or ``extended_storage=``), in the same patient folders:
``<id[0:3]>/<id[3:6]>/<id>/<YYYYMMDD>/<kind>/<file>``. File names in the standardized form (with any extension) are
versioned the same way; other names are one document each. Each becomes a ``note`` row (DocumentReference and note
text for the two models); a file whose text cannot be read is kept as a document without text and counted.

Tables SS-MIX2 does not standardize (practitioner, appointment, vital, procedure, report, note, claim, registry)
also come from ``<root>/extended/<table>.csv`` (or ``extended=``), read like the ``csv`` source.
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adapter.sources.base import Row, after
from adapter.sources.csv.source import CsvSource
from adapter.sources.ssmix2 import hl7

TYPES = {
    "patient": ("ADT-00",),
    "encounter": ("ADT-12", "ADT-22"),
    "diagnosis": ("PPR-01",),
    "medication": ("OMP-01", "OMP-02"),
    "lab": ("OML-11",),
}
CHANGES = {"encounter": ("ADT-52",), "medication": ("OMP-11", "OMP-12")}  # read after the table's own types
INJECTION = ("OMP-02", "OMP-12")
JP_CORE = Path(__file__).resolve().parents[2] / "mapping" / "jp_core"
NOT_PATIENT_DIRS = ("extended", "extended_storage")
_CLASS = {"O": "OPD", "I": "IPD", "E": "ER"}
_RX_STATUS = {"IP": "active", "SC": "active", "CM": "completed", "DC": "stopped", "CA": "stopped"}
# coding-system names vendors write in CWE-3 / CWE-6
_YJ_SYS = ("99YJ", "YJ", "99YJC")
_HOT_SYS = ("HOT", "HOT9", "99HOT", "HOT13", "99HOT9", "99HOT13")
_ATC_SYS = ("WHOATC", "ATC")
_JLAC_SYS = ("JC10", "JLAC10", "JC11")
_JLAC_SHAPE = re.compile(r"^[0-9A-Z]{15}([0-9A-Z]{2})?$")
# JLAC10 material code (characters 10-12) -> specimen name (the JP Core lab profile needs a specimen)
_MATERIAL = {"001": "尿", "019": "全血", "022": "血漿", "023": "血清", "040": "便", "071": "髄液"}
# extended-storage folder kinds -> canonical note types (prefix match, upper case; anything else: "document")
_DOC_KINDS = (("DSC", "discharge"), ("SUM", "discharge"), ("RPT", "report"), ("REP", "report"),
              ("PRG", "progress"), ("NOTE", "progress"), ("ADM", "admission"), ("CON", "consult"),
              ("NRS", "nursing"))  # fmt: skip
_TEXT_EXT = (".txt", ".text", ".csv", ".tsv")
_MARKUP_EXT = (".html", ".htm", ".xml")


@dataclass(frozen=True)
class StoredFile:
    path: Path
    patient: str
    day: str
    type: str
    order: str
    stamp: str
    dept: str
    deleted: bool


def parse_name(path: Path) -> StoredFile | None:
    parts = path.name.split("_")
    if len(parts) != 7:
        return None
    pid, day, typ, order, stamp, dept, flag = parts
    return StoredFile(path, pid, day, typ, order, stamp, dept, flag == "0")


def storage_dir(root: Path, patient: str, day: str, typ: str) -> Path:
    return root / patient[0:3] / patient[3:6] / patient / day / typ


def _lookup(path: Path, key: str, field: str) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return {r[key]: r[field] for r in csv.DictReader(fh) if r.get(key) and r.get(field)}


def _suspected(prb: hl7.Segment) -> bool:
    """A suspected diagnosis: PRB-13 ``1^疑いあり^JHSD0005`` (any coding system name, as vendors vary), or a 病名
    whose text carries the 修飾語 "の疑い" / "疑い" when the vendor sends no flag."""
    flag, text, system = prb.comp(13, 1).strip(), prb.comp(13, 2), prb.comp(13, 3).strip().upper()
    if (flag == "1" and system in ("", "JHSD0005")) or "疑いあり" in text:
        return True
    return "疑い" in prb.comp(3, 2)


def _alt(seg: hl7.Segment, n: int, systems: tuple[str, ...]) -> str:
    """The alternate code (components 4-6) of a CWE field when its coding system is one of ``systems``."""
    return seg.comp(n, 4) if seg.comp(n, 6) in systems else ""


def drug_codes(seg: hl7.Segment, n: int) -> dict[str, str]:
    """``{yj, hot, atc, name}`` from a drug CWE (RXE-2, RXA-5): the primary code and the alternate, by coding system.
    A primary code with no recognised system is taken as the YJ / local drug code, as OMP-01 always was."""
    out = {"yj": "", "hot": "", "atc": "", "name": seg.comp(n, 2)}
    for i, (code, system) in enumerate(((seg.comp(n, 1), seg.comp(n, 3)), (seg.comp(n, 4), seg.comp(n, 6)))):
        if not code:
            continue
        if system in _ATC_SYS:
            out["atc"] = out["atc"] or code
        elif system in _HOT_SYS:
            out["hot"] = out["hot"] or code
        elif system in _YJ_SYS or i == 0:
            out["yj"] = out["yj"] or code
    return out


def _icd10cm() -> set[str]:
    """Every ICD-10-CM code (D-122's full list), so a licensed WHO ICD-10 code is used only where it is one."""
    import pyarrow.parquet as pq

    path = Path(__file__).resolve().parents[3] / "criteria_compiler" / "terminology" / "icd10cm_full.parquet"
    if not path.exists():
        return set()
    return {str(c) for c in pq.read_table(path, columns=["code"]).column("code").to_pylist()}


def document_text(name: str, data: bytes) -> tuple[str, str]:
    """``(text, how)`` of one extended-storage file; ``("", why)`` when it has no readable text."""
    low = name.lower()
    ext = low[low.rfind(".") :] if "." in low else ""
    if ext in _TEXT_EXT or ext in _MARKUP_EXT or not ext:
        text = ""
        if b"\x1b$" in data:  # ISO-2022-JP escapes
            try:
                text = data.decode("iso2022_jp")
            except UnicodeDecodeError:
                text = ""
        if not text:
            for enc in ("utf-8-sig", "cp932", "euc_jp"):
                try:
                    text = data.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
        if not text:
            return "", "unreadable text"
        if ext in _MARKUP_EXT:
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"[ \t]+", " ", text)
        return text.strip(), "text"
    if ext == ".pdf" or data[:4] == b"%PDF":
        try:
            from pypdf import PdfReader

            pages = [p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages]
        except Exception:
            return "", "unreadable pdf"
        text = "\n\n".join(pages).strip()
        return (text, "pdf") if text else ("", "pdf without text (a scan)")
    if ext == ".docx":
        try:
            import docx

            d = docx.Document(io.BytesIO(data))
            return "\n".join(p.text for p in d.paragraphs if p.text.strip()), "docx"
        except Exception:
            return "", "unreadable docx"
    return "", f"no text in a {ext} file"


class Ssmix2Source:
    name = "ssmix2"

    def __init__(
        self,
        directory: Path,
        *,
        extended: Path | None = None,
        extended_storage: Path | None = None,
        byomei_to_icd10: Path | None = None,
        yj_to_atc: Path | None = None,
        licensed: dict[str, dict[str, dict[str, str]]] | None = None,
    ) -> None:
        if not directory.is_dir():
            raise FileNotFoundError(f"ssmix2 storage not found: {directory}")
        self.root = directory
        ext = extended or directory / "extended"
        self.extended = CsvSource(ext) if ext.is_dir() else None
        self.ext_storage = extended_storage or directory / "extended_storage"
        self.byomei = _lookup(byomei_to_icd10 or JP_CORE / "byomei_to_icd10.csv", "code", "icd10")
        self.yj = _lookup(yj_to_atc or JP_CORE / "yj_to_atc.csv", "yj_code", "atc")
        if licensed is None:
            from adapter import licensed as lic

            licensed = lic.tables()
        self.licensed = licensed
        self._cm: set[str] | None = None
        self.missed: Counter[str] = Counter()  # "diagnosis:<標準病名 code>", "medication:<YJ code>"
        self.stats: Counter[str] = Counter()  # messages and documents read, by type and outcome
        self._index: dict[str, list[StoredFile]] | None = None

    # ------------------------------------------------------------------ storage index
    def _files(self) -> dict[str, list[StoredFile]]:
        """The current version of every record by message type (latest timestamp wins, flag 0 = deleted)."""
        if self._index is None:
            latest: dict[tuple[str, str, str, str], StoredFile] = {}
            for top in sorted(p for p in self.root.iterdir() if p.is_dir() and p.name not in NOT_PATIENT_DIRS):
                for f in top.glob("*/*/*/*/*"):
                    sf = parse_name(f)
                    if sf is None or not f.is_file():
                        continue
                    key = (sf.patient, sf.type, sf.order, sf.day if sf.order == "-" else "")
                    cur = latest.get(key)
                    if cur is None or sf.stamp > cur.stamp:
                        latest[key] = sf
            index: dict[str, list[StoredFile]] = {}
            for sf in sorted(latest.values(), key=lambda s: (s.type, s.patient, s.day, s.order)):
                if not sf.deleted:
                    index.setdefault(sf.type, []).append(sf)
            self._index = index
        return self._index

    def _messages(self, typ: str) -> Iterator[tuple[StoredFile, hl7.Message]]:
        for sf in self._files().get(typ, []):
            self.stats[typ] += 1
            yield sf, hl7.parse(hl7.decode(sf.path.read_bytes()))

    def rows(self, table: str, source_name: str, delta_column: str | None, since: str | None) -> Iterator[Row]:
        if table not in TYPES:
            if self.extended is not None:
                yield from self.extended.rows(table, source_name, delta_column, since)
            if table == "note":
                for row in self._documents():
                    if delta_column and not after(row.get(delta_column), since):
                        continue
                    yield row
            return
        build: Callable[[StoredFile, hl7.Message], Iterator[Row]] = getattr(self, f"_{table}")
        out: list[Row] = []
        for typ in TYPES[table]:
            for sf, msg in self._messages(typ):
                out.extend(build(sf, msg))
        if table == "encounter":
            out = self._encounter_changes(out)
        elif table == "medication":
            out = self._administrations(out)
        for row in out:
            stamp = max(str(row.get(c) or "") for c in (delta_column, "class_changed_at", "end_datetime") if c)
            if delta_column and not after(stamp or None, since):
                continue
            yield row

    # ------------------------------------------------------------------ code lookups
    def _icd(self, byomei: str) -> str:
        """標準病名 -> ICD-10 through the licensed MEDIS release (only a code in the ICD-10-CM list), then the site's
        lookup file."""
        hit = self.licensed.get("medis", {}).get(byomei.upper()) if byomei else None
        if hit and hit.get("target_code"):
            if self._cm is None:
                self._cm = _icd10cm()
            code = hit["target_code"]
            if code in self._cm:
                self.stats["diagnosis:licensed"] += 1
                return code
            self.stats["diagnosis:licensed code not in ICD-10-CM"] += 1
        return self.byomei.get(byomei, "")

    def _atc(self, yj: str) -> str:
        hit = self.licensed.get("yj", {}).get(yj.upper()) if yj else None
        if hit and hit.get("target_code"):
            return hit["target_code"]
        return self.yj.get(yj, "")

    # ------------------------------------------------------------------ tables
    def _patient(self, sf: StoredFile, msg: hl7.Message) -> Iterator[Row]:
        pid = msg.first("PID")
        if pid is None:
            return
        family, given = pid.comp(5, 1), pid.comp(5, 2)
        yield {
            "mrn": pid.comp(3, 1) or sf.patient,
            "name": f"{family}　{given}" if given else family,
            "id_no": "",
            "birth_date": hl7.ts(pid.field(7)) or "",
            "sex": pid.field(8) if pid.field(8) in ("M", "F") else "",
            "death_date": hl7.ts(pid.field(29)) or "",
            "phone": pid.comp(13, 1),
        }

    def _encounter(self, sf: StoredFile, msg: hl7.Message) -> Iterator[Row]:
        pv1 = msg.first("PV1")
        if pv1 is None:
            return
        enc_type = _CLASS.get(pv1.field(2), "OPD")
        end = hl7.ts(pv1.field(45)) or ""
        yield {
            "enc_no": pv1.comp(19, 1),
            "mrn": sf.patient,
            "visit_datetime": hl7.ts(pv1.field(44)) or "",
            "dept_code": pv1.comp(10, 1) or sf.dept,
            "staff_id": pv1.comp(7, 1),
            "enc_type": enc_type,
            "end_datetime": end,
            "enc_status": "in-progress" if enc_type == "IPD" and not end else "finished",
            "prev_enc_type": "",
            "class_changed_at": "",
        }

    def _encounter_changes(self, rows: list[Row]) -> list[Row]:
        """ADT-52: discharge (A03) or patient class change (A06/A07, or any event with PV1-2), in time order."""
        by_no = {(r["mrn"], r["enc_no"]): r for r in rows}
        events: list[tuple[str, str, str, hl7.Message]] = []
        for typ in CHANGES["encounter"]:
            for sf, msg in self._messages(typ):
                msh, evn = msg.first("MSH"), msg.first("EVN")
                when = (hl7.ts(evn.field(6)) or hl7.ts(evn.field(2)) or "") if evn else ""
                when = when or ((hl7.ts(msh.field(7)) or "") if msh else "")
                events.append((when, sf.patient, sf.path.name, msg))
        for when, patient, _name, msg in sorted(events, key=lambda e: (e[0], e[1], e[2])):
            pv1, msh = msg.first("PV1"), msg.first("MSH")
            if pv1 is None:
                self.stats["ADT-52:no PV1"] += 1
                continue
            row = by_no.get((patient, pv1.comp(19, 1)))
            if row is None:
                self.stats["ADT-52:visit not in storage"] += 1
                continue
            trigger = msh.comp(9, 2) if msh else ""
            if trigger == "A03":
                row["end_datetime"] = hl7.ts(pv1.field(45)) or when
                row["enc_status"] = "finished"
                self.stats["ADT-52:discharge"] += 1
            elif pv1.field(2):
                new = _CLASS.get(pv1.field(2), row["enc_type"])
                if new != row["enc_type"]:
                    row["prev_enc_type"], row["enc_type"], row["class_changed_at"] = row["enc_type"], new, when
                    if new != "IPD" and row["enc_status"] == "in-progress":
                        row["enc_status"] = "finished"
                self.stats["ADT-52:class change"] += 1
            else:
                self.stats[f"ADT-52:event {trigger or '?'} not read"] += 1
        return rows

    def _diagnosis(self, sf: StoredFile, msg: hl7.Message) -> Iterator[Row]:
        """PPR-01 PRB segments. PRB-13 is the 疑い病名フラグ (SS-MIX2 標準化ストレージ仕様書 v1.2h 表 3-47,
        JHSD 表 0005: ``1`` 疑いあり), read into ``suspected``: the diagnosis becomes ``verificationStatus =
        provisional`` and never excludes (D-142)."""
        pv1 = msg.first("PV1")
        enc = pv1.comp(19, 1) if pv1 else ""
        for prb in msg.all("PRB"):
            code = prb.comp(3, 1)
            icd = _alt(prb, 3, ("I10", "ICD10")) or self._icd(code)
            if not icd:
                self.missed[f"diagnosis:{code}"] += 1
            yield {
                "diag_no": prb.comp(4, 1),
                "enc_no": enc,
                "mrn": sf.patient,
                "icd10": icd,
                "byomei_code": code if prb.comp(3, 3) not in ("I10", "ICD10") else "",
                "byomei_name": prb.comp(3, 2),
                "diag_date": hl7.ts(prb.field(16)) or "",
                "recorded_date": hl7.ts(prb.field(2)) or hl7.ts(prb.field(7)) or "",
                "status": "R" if prb.comp(14, 1) in ("R", "resolved") else "A",
                "suspected": "Y" if _suspected(prb) else "",
            }

    def _drug_row(self, sf: StoredFile, orc: hl7.Segment, codes: dict[str, str]) -> Row:
        atc = codes["atc"] or self._atc(codes["yj"])
        if not atc:
            self.missed[f"medication:{codes['yj'] or codes['hot']}"] += 1
        return {
            "rx_no": orc.comp(2, 1),
            "mrn": sf.patient,
            "nhi_drug_code": codes["yj"],
            "hot_code": codes["hot"],
            "atc": atc,
            "drug_name": codes["name"],
            "order_date": hl7.ts(orc.field(9)) or "",
            "rp_no": orc.comp(4, 1),
            "rx_kind": "injection" if sf.type in INJECTION else "prescription",
            "status": _RX_STATUS.get(orc.field(5), "active"),
            "dept_code": "" if sf.dept == "-" else sf.dept,
        }

    def _medication(self, sf: StoredFile, msg: hl7.Message) -> Iterator[Row]:
        orc, rxe, tq1 = msg.first("ORC"), msg.first("RXE"), msg.first("TQ1")
        if orc is None or rxe is None:
            return
        row = self._drug_row(sf, orc, drug_codes(rxe, 2))
        row.update(
            start_date=(hl7.ts(tq1.field(7)) or "") if tq1 else "",
            end_date=(hl7.ts(tq1.field(8)) or "") if tq1 else "",
            daily_dose=rxe.comp(3, 1),
            dose_unit=rxe.comp(5, 1),
        )
        yield row

    def _administrations(self, rows: list[Row]) -> list[Row]:
        """OMP-11/12 (実施): fill the order's empty fields, or become a medication of its own."""
        by_no = {(r["mrn"], r["rx_no"]): r for r in rows}
        for typ in CHANGES["medication"]:
            for sf, msg in self._messages(typ):
                orc, rxa = msg.first("ORC"), msg.first("RXA")
                if orc is None or rxa is None:
                    self.stats[f"{typ}:no ORC/RXA"] += 1
                    continue
                codes = drug_codes(rxa, 5)
                done = {
                    "start_date": hl7.ts(rxa.field(3)) or "",
                    "end_date": hl7.ts(rxa.field(4)) or "",
                    "daily_dose": rxa.comp(6, 1),
                    "dose_unit": rxa.comp(7, 1),
                }
                order = by_no.get((sf.patient, orc.comp(2, 1)))
                if order is not None:
                    for k, v in {**done, "hot_code": codes["hot"], "nhi_drug_code": codes["yj"]}.items():
                        if v and not order.get(k):
                            order[k] = v
                    self.stats[f"{typ}:with its order"] += 1
                    continue
                row = self._drug_row(sf, orc, codes)
                row.update(done)
                rows.append(row)
                by_no[(sf.patient, row["rx_no"])] = row
                self.stats[f"{typ}:without an order"] += 1
        return rows

    def _lab(self, sf: StoredFile, msg: hl7.Message) -> Iterator[Row]:
        for obx in msg.all("OBX"):
            code, system = obx.comp(3, 1), obx.comp(3, 3)
            is_jlac = system in _JLAC_SYS or (not system and bool(_JLAC_SHAPE.match(code)))
            jlac = code if is_jlac else ""
            yield {
                "lab_no": obx.comp(21, 1) or f"{sf.order}-{obx.field(1)}",
                "mrn": sf.patient,
                "local_code": code,  # the lookup key (jlac10_to_loinc.csv), JLAC10 or the hospital's own code
                "jlac10_code": jlac,
                "hosp_lab_code": "" if is_jlac else code,
                "item_name": obx.comp(3, 2),
                "result_value": hl7.unescape(obx.field(5)),
                "unit": obx.comp(6, 1),
                "sample_datetime": hl7.ts(obx.field(14)) or "",
                "specimen": _MATERIAL.get(jlac[9:12], "") if len(jlac) >= 12 else "",
            }

    # ------------------------------------------------------------------ extended storage
    def _documents(self) -> Iterator[Row]:
        """Documents of the extended storage as ``note`` rows (the newest version of a standardized name wins)."""
        root = self.ext_storage
        if not root.is_dir():
            return
        latest: dict[tuple[str, ...], tuple[str, Path, str, str, str, bool]] = {}
        for f in sorted(root.glob("*/*/*/*/*/*")):
            if not f.is_file():
                continue
            patient, day, kind = f.parts[-4], f.parts[-3], f.parts[-2]
            stem = f.name.rsplit(".", 1)[0] if "." in f.name else f.name
            sf = parse_name(Path(stem))
            if sf is not None and sf.patient == patient:
                key: tuple[str, ...] = (patient, day, kind, sf.order)
                stamp, deleted = sf.stamp, sf.deleted
            else:
                key, stamp, deleted = (patient, day, kind, f.name), "", False
            cur = latest.get(key)
            if cur is None or stamp > cur[0]:
                latest[key] = (stamp, f, patient, day, kind, deleted)
        for key, (_stamp, f, patient, day, kind, deleted) in sorted(latest.items()):
            if deleted:
                self.stats["document:deleted"] += 1
                continue
            text, how = document_text(f.name, f.read_bytes())
            self.stats["document" if text else f"document without text ({how})"] += 1
            when = hl7.ts(day) or ""
            note_type = next((t for p, t in _DOC_KINDS if kind.upper().startswith(p)), "document")
            yield {
                "note_no": "ext/" + "/".join(key),  # becomes a keyed hash: the path never leaves the adapter
                "mrn": patient,
                "enc_no": "",
                "note_datetime": when if len(when) > 10 else (f"{when} 00:00:00" if when else ""),
                "note_type": note_type,
                "text": text,
            }


def reader_summary(src: Any) -> dict[str, Any]:
    """What a reader saw, for the ingest record: messages and documents by type, codes that resolved nowhere."""
    missed: Counter[str] = Counter()
    for k, n in dict(getattr(src, "missed", {}) or {}).items():
        missed[k.split(":", 1)[0]] += int(n)
    return {"read": dict(sorted(dict(getattr(src, "stats", {}) or {}).items())), "missed": dict(missed)}
