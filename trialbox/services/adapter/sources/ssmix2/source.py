"""``ssmix2`` source: a reader for SS-MIX2 standardized storage (TB-PLAN-03 step 7, D-122; was a stub under D-28).

Layout (SS-MIX2 標準化ストレージ仕様書 v1.2): ``<root>/<id[0:3]>/<id[3:6]>/<patient id>/<YYYYMMDD | ->/<type>/<file>``
with file names ``<patient id>_<date>_<type>_<order no>_<timestamp>_<dept>_<flag>``. Every change writes a new file;
the newest timestamp per (patient, type, order no) wins and flag ``0`` means the record was deleted.

The message types read, and the canonical tables (``mapping/templates/CANONICAL.md``) they become:

* ``ADT-00`` (ADT^A08, PID) -> patient: PID-3 id, PID-5 name, PID-7 birth, PID-8 sex, PID-13 phone, PID-29 death.
* ``ADT-12`` outpatient visit / ``ADT-22`` admission (PV1) -> encounter: PV1-19 visit no, PV1-44 time, PV1-10 dept,
  PV1-7 doctor, PV1-2 class O/I/E -> OPD/IPD/ER.
* ``PPR-01`` (PPR^ZD1, PRB) -> diagnosis: PRB-3 標準病名 ``code^name^99XYZ^ICD-10^name^I10``, PRB-4 id, PRB-2
  recorded, PRB-16 onset, PRB-14 status, PV1-19 visit no.
* ``OMP-01`` prescription / ``OMP-02`` injection (RDE^O11, ORC/RXE/TQ1) -> medication: ORC-2 order no, ORC-9 date,
  ORC-5 status, RXE-2 ``YJ^name^99YJ^ATC^name^WHOATC``, RXE-3 dose, RXE-5 unit, TQ1-7/8 start/end, file dept.
* ``OML-11`` lab results (OUL^R22, OBR/OBX) -> lab: OBX-21 result id, OBX-3 ``JLAC10^name^JC10``, OBX-5 value,
  OBX-6 unit, OBX-14 sample time; ``local_code`` is the JLAC10 code (the JP mapping looks it up to LOINC).

ICD-10 comes from PRB-3's alternate coding; when a vendor sends only the 標準病名 code it is looked up in
``byomei_to_icd10.csv`` (``code,icd10``). ATC works the same way from ``yj_to_atc.csv`` (``yj_code,atc``). Codes that
resolve nowhere are counted in :attr:`Ssmix2Source.missed` and reach the mapping empty.

Tables SS-MIX2 does not standardize (practitioner, appointment, vital, procedure, report, note, claim, registry)
come from extended storage as CSV, ``<root>/extended/<table>.csv`` (or ``extended=``), read like the ``csv`` source.
"""

from __future__ import annotations

import csv
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

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
JP_CORE = Path(__file__).resolve().parents[2] / "mapping" / "jp_core"
_CLASS = {"O": "OPD", "I": "IPD", "E": "ER"}
_RX_STATUS = {"IP": "active", "SC": "active", "CM": "completed", "DC": "stopped", "CA": "stopped"}


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


def _alt(seg: hl7.Segment, n: int, systems: tuple[str, ...]) -> str:
    """The alternate code (components 4-6) of a CWE field when its coding system is one of ``systems``."""
    return seg.comp(n, 4) if seg.comp(n, 6) in systems else ""


class Ssmix2Source:
    name = "ssmix2"

    def __init__(
        self,
        directory: Path,
        *,
        extended: Path | None = None,
        byomei_to_icd10: Path | None = None,
        yj_to_atc: Path | None = None,
    ) -> None:
        if not directory.is_dir():
            raise FileNotFoundError(f"ssmix2 storage not found: {directory}")
        self.root = directory
        ext = extended or directory / "extended"
        self.extended = CsvSource(ext) if ext.is_dir() else None
        self.byomei = _lookup(byomei_to_icd10 or JP_CORE / "byomei_to_icd10.csv", "code", "icd10")
        self.yj = _lookup(yj_to_atc or JP_CORE / "yj_to_atc.csv", "yj_code", "atc")
        self.missed: Counter[str] = Counter()  # "diagnosis:<標準病名 code>", "medication:<YJ code>"
        self._index: dict[str, list[StoredFile]] | None = None

    def _files(self) -> dict[str, list[StoredFile]]:
        """The current version of every record by message type (latest timestamp wins, flag 0 = deleted)."""
        if self._index is None:
            latest: dict[tuple[str, str, str, str], StoredFile] = {}
            for top in sorted(p for p in self.root.iterdir() if p.is_dir() and p.name != "extended"):
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

    def rows(self, table: str, source_name: str, delta_column: str | None, since: str | None) -> Iterator[Row]:
        if table not in TYPES:
            if self.extended is not None:
                yield from self.extended.rows(table, source_name, delta_column, since)
            return
        build: Callable[[StoredFile, hl7.Message], Iterator[Row]] = getattr(self, f"_{table}")
        for typ in TYPES[table]:
            for sf in self._files().get(typ, []):
                for row in build(sf, hl7.parse(hl7.decode(sf.path.read_bytes()))):
                    if delta_column and not after(row.get(delta_column), since):
                        continue
                    yield row

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
        yield {
            "enc_no": pv1.comp(19, 1),
            "mrn": sf.patient,
            "visit_datetime": hl7.ts(pv1.field(44)) or "",
            "dept_code": pv1.comp(10, 1) or sf.dept,
            "staff_id": pv1.comp(7, 1),
            "enc_type": _CLASS.get(pv1.field(2), "OPD"),
        }

    def _diagnosis(self, sf: StoredFile, msg: hl7.Message) -> Iterator[Row]:
        pv1 = msg.first("PV1")
        enc = pv1.comp(19, 1) if pv1 else ""
        for prb in msg.all("PRB"):
            code = prb.comp(3, 1)
            icd = _alt(prb, 3, ("I10", "ICD10")) or self.byomei.get(code, "")
            if not icd:
                self.missed[f"diagnosis:{code}"] += 1
            yield {
                "diag_no": prb.comp(4, 1),
                "enc_no": enc,
                "mrn": sf.patient,
                "icd10": icd,
                "diag_date": hl7.ts(prb.field(16)) or "",
                "recorded_date": hl7.ts(prb.field(2)) or hl7.ts(prb.field(7)) or "",
                "status": "R" if prb.comp(14, 1) in ("R", "resolved") else "A",
            }

    def _medication(self, sf: StoredFile, msg: hl7.Message) -> Iterator[Row]:
        orc, rxe, tq1 = msg.first("ORC"), msg.first("RXE"), msg.first("TQ1")
        if orc is None or rxe is None:
            return
        yj = rxe.comp(2, 1)
        atc = _alt(rxe, 2, ("WHOATC", "ATC")) or self.yj.get(yj, "")
        if not atc:
            self.missed[f"medication:{yj}"] += 1
        yield {
            "rx_no": orc.comp(2, 1),
            "mrn": sf.patient,
            "nhi_drug_code": yj,
            "atc": atc,
            "drug_name": rxe.comp(2, 2),
            "order_date": hl7.ts(orc.field(9)) or "",
            "start_date": (hl7.ts(tq1.field(7)) or "") if tq1 else "",
            "end_date": (hl7.ts(tq1.field(8)) or "") if tq1 else "",
            "daily_dose": rxe.comp(3, 1),
            "dose_unit": rxe.comp(5, 1),
            "status": _RX_STATUS.get(orc.field(5), "active"),
            "dept_code": "" if sf.dept == "-" else sf.dept,
        }

    def _lab(self, sf: StoredFile, msg: hl7.Message) -> Iterator[Row]:
        for obx in msg.all("OBX"):
            yield {
                "lab_no": obx.comp(21, 1) or f"{sf.order}-{obx.field(1)}",
                "mrn": sf.patient,
                "local_code": obx.comp(3, 1),
                "item_name": obx.comp(3, 2),
                "result_value": hl7.unescape(obx.field(5)),
                "unit": obx.comp(6, 1),
                "sample_datetime": hl7.ts(obx.field(14)) or "",
            }
