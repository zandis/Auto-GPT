"""``ssmix2`` source: a reader for SS-MIX2 standardized storage (TB-PLAN-03 step 7, D-122; was a stub under D-28) and
its extended storage (TB-PLAN-04 step 7, D-137).

Layout (SS-MIX2 標準化ストレージ仕様書 v1.2): ``<root>/<id[0:3]>/<id[3:6]>/<patient id>/<YYYYMMDD | ->/<type>/<file>``
with file names ``<patient id>_<date>_<type>_<order no>_<timestamp>_<dept>_<flag>``. Every change writes a new file;
the newest timestamp per (patient, type, order no) wins and flag ``0`` means the record was deleted. A site whose
order numbers come back on another day sets ``TB_SSMIX2_ORDER_NUMBERS=per_day`` (D-594): the day is then part of
that key; either way an order number seen on several days is counted (``<type>:order number on several days``).

The message types read, and the canonical tables (``mapping/templates/CANONICAL.md``) they become:

* ``ADT-00`` (ADT^A08, PID) -> patient: PID-3 id (the repetition of identifier type ``PI``), PID-5 name (the
  ideographic repetition, ``^^^^^^L^I``), PID-7 birth, PID-8 sex, PID-13 phone, PID-29 death, PID-30 the death flag
  (``Y``: ``deceased``, with or without a date; STD-013, T-615a).
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
* ``OML-11`` lab results (OUL^R22, SPM/OBR/OBX) -> lab: OBX-21 result id, OBX-3 ``JLAC10^name^JC10``, OBX-5 value
  read by OBX-2 (``CWE`` / ``CE``: the text, else the code; ``SN``: comparator and numbers joined, ``<^0.03`` ->
  ``<0.03``; ``NM`` as is), OBX-6 unit, OBX-7 reference range, OBX-8 flag, OBX-11 status. The sample time is OBX-14,
  else the OBR-7 of its OBR, else the SPM-17 of the message, else the storage folder's date, and
  ``sample_time_from`` says which (STD-021, T-615a). A ``D`` (deleted) result is a tombstone: it is no row and
  removes what an earlier night stored. A ``C`` (corrected) result replaces the other results of the same OBR-3 /
  OBR-2, OBX-3 and OBX-4. ``local_code`` is the JLAC10 code (the JP mapping looks it up to LOINC); the specimen
  comes from the JLAC10 material code.

A message no codec reads (``hl7.decode_bytes``, STD-020), or one that is not HL7, is quarantined: the file is left
where it is (the storage is the hospital's), counted by type and reason in ``stats``, listed in
:attr:`Ssmix2Source.quarantined` for the steward, and the patient's other files still load. The table's night is held
(``quarantine_reason``) only when more than ``quarantine_max_pct`` % of its files could not be read.

ICD-10 comes from PRB-3's alternate coding; when a vendor sends only the 標準病名 code it is looked up in the site's
licensed MEDIS release (``adapter.licensed``) and then in ``byomei_to_icd10.csv`` (``code,icd10``). Japan codes in
WHO ICD-10 (2013), not ICD-10-CM (D-314): ``icd10`` is the WHO code as the site wrote it (written ``E14.9``: upper
case, the dot after the category, a dagger or asterisk mark dropped), kept even when ICD-10-CM has no such code
(``E14``, ``I64``, ``F00``); ``icd10cm`` is the same code only when it is also an ICD-10-CM code (D-137's rule), so the
JP mapping carries the WHO coding always and the ICD-10-CM one only where they are the same code. ATC works the same
way from ``yj_to_atc.csv`` (``yj_code,atc``) and a licensed YJ release that carries ATC, and then (T-610, STD-042)
from the line's ingredient: a YJ code's 7-character stem, or the stem of the YJ code the site's drug master
(``drug_master.csv`` beside the mapping, ``refdata_jp.parse_drug_master``) gives a HOT or local code, looked up in
the ingredient-to-ATC table (TrialBox's stems, then the site's ``ingredient_atc.csv``). The row keeps the stem
(``yj_stem``), so a drug ValueSet that lists stems reads the line even without ATC. A lab code with no row in the
lab look-up or the licensed JLAC10 release is counted too (STD-043). Codes that resolve nowhere are counted in
:attr:`Ssmix2Source.missed`, listed by volume in the ingest report (``reader.json``: ``unmapped`` and
``drug_resolution``), and reach the mapping without a standard code (D-130 keeps them unknown).

Extended storage (拡張ストレージ, D-137): documents (reports, discharge summaries, PDFs, text) under
``<root>/extended_storage/`` (or ``extended_storage=``), in the same patient folders:
``<id[0:3]>/<id[3:6]>/<id>/<YYYYMMDD>/<kind>/<file>``. File names in the standardized form (with any extension) are
versioned the same way; other names are one document each. Each becomes a ``note`` row (DocumentReference and note
text for the two models); a file whose text cannot be read is kept as a document without text and counted.

Tables SS-MIX2 does not standardize (practitioner, appointment, vital, procedure, report, note, claim, registry)
also come from ``<root>/extended/<table>.csv`` (or ``extended=``), read like the ``csv`` source.
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import logging
import os
import re
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tb_common import encoding, refdata_jp

from adapter.sources.base import Row, after
from adapter.sources.csv.source import CsvSource
from adapter.sources.ssmix2 import hl7

log = logging.getLogger("adapter.ssmix2")

TYPES = {
    "patient": ("ADT-00",),
    "encounter": ("ADT-12", "ADT-22"),
    "diagnosis": ("PPR-01",),
    "medication": ("OMP-01", "OMP-02"),
    "lab": ("OML-11",),
}
_RECORD_TYPES = frozenset(t for types in TYPES.values() for t in types)
ORDER_KEY_ENV = "TB_SSMIX2_ORDER_NUMBERS"
ORDER_KEYS = ("unique", "per_day")  # D-594
CHANGES = {"encounter": ("ADT-52",), "medication": ("OMP-11", "OMP-12")}  # read after the table's own types
INJECTION = ("OMP-02", "OMP-12")
JP_CORE = Path(__file__).resolve().parents[2] / "mapping" / "jp_core"
NOT_PATIENT_DIRS = ("extended", "extended_storage")
_CLASS = {"O": "OPD", "I": "IPD", "E": "ER"}
# ORC-5 (HL7 table 0038) as the canonical status (D-275): CA cancelled (never given) and ER (error, order not found)
# are not counted by the lake. A code not listed here is passed as it is: the site mapping reads a code it does not
# know as ``unknown`` (never ``active``); an empty ORC-5 stays empty ("not recorded")
_RX_STATUS = {"IP": "active", "SC": "active", "A": "active", "HD": "on-hold", "CM": "completed", "DC": "stopped",
              "CA": "cancelled", "ER": "entered-in-error"}  # fmt: skip
# OBX-11 (HL7 table 0085) as the canonical lab ``result_status`` (FHIR words, D-275): D (delete) and W (wrong) are
# entered in error, X (cannot be obtained) and N (not asked) cancelled, P / R / S not yet final; an unknown code is
# passed as it is (the mapping reads it as ``unknown``) and an empty OBX-11 stays empty ("not recorded")
_OBX_STATUS = {"F": "final", "U": "final", "C": "corrected", "P": "preliminary", "R": "preliminary",
               "S": "preliminary", "I": "registered", "O": "registered", "D": "entered-in-error",
               "W": "entered-in-error", "X": "cancelled", "N": "cancelled"}  # fmt: skip


def _status(table: dict[str, str], raw: str) -> str:
    code = (raw or "").strip().upper()
    return table.get(code, code)


# coding-system names vendors write in CWE-3 / CWE-6
_YJ_SYS = ("99YJ", "YJ", "99YJC")
_HOT_SYS = ("HOT", "HOT9", "99HOT", "HOT13", "99HOT9", "99HOT13")
_ATC_SYS = ("WHOATC", "ATC")
_JLAC_SYS = ("JC10", "JLAC10", "JC11")
_JLAC_SHAPE = re.compile(r"^[0-9A-Z]{15}([0-9A-Z]{2})?$")
# JLAC10 material code (characters 10-12) -> specimen name (the JP Core lab profile needs a specimen). Only codes read
# in JSLM's published JLAC10 pages (jslm.org/committees/code/jlac3.pdf: 001, 004, 018, 019, 022, 023; jlac.pdf's
# example: 041 髄液); STD-024 dropped 040 便 and 071 髄液, which no published page confirms. SPM-4 comes first and the
# site's licensed JLAC10 release (its 材料名) second; this table is the last resort.
_MATERIAL = {"001": "尿", "004": "蓄尿", "018": "全血", "019": "全血", "022": "血漿", "023": "血清", "041": "髄液"}
# extended-storage folder kinds -> canonical note types (prefix match, upper case; anything else: "document")
_DOC_KINDS = (("DSC", "discharge"), ("SUM", "discharge"), ("RPT", "report"), ("REP", "report"),
              ("PRG", "progress"), ("NOTE", "progress"), ("ADM", "admission"), ("CON", "consult"),
              ("NRS", "nursing"))  # fmt: skip
_TEXT_EXT = (".txt", ".text", ".csv", ".tsv")
_CODED = ("CWE", "CE", "CNE", "CF")
QUARANTINE_MAX_PCT = 1.0  # a table whose unreadable files pass this share of its files holds the night
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
    """Every ICD-10-CM code (D-122's full list): a WHO ICD-10 code is also given as ICD-10-CM only where it is one."""
    import pyarrow.parquet as pq

    path = Path(__file__).resolve().parents[3] / "criteria_compiler" / "terminology" / "icd10cm_full.parquet"
    if not path.exists():
        return set()
    return {str(c) for c in pq.read_table(path, columns=["code"]).column("code").to_pylist()}


_WHO_SHAPE = re.compile(r"^[A-Z][0-9]{2}(\.[0-9]{1,2})?$")


def who_icd10(code: str) -> str:
    """A WHO ICD-10 code written one way (D-314): upper case, no blanks, the dagger / asterisk / plus mark dropped, the
    dot after the three-character category (``e149`` -> ``E14.9``). Anything else is returned as written, stripped."""
    c = re.sub(r"\s+", "", code or "").upper().rstrip("*+\u2020")
    if re.fullmatch(r"[A-Z][0-9]{3,4}", c):
        c = f"{c[:3]}.{c[3:]}"
    return c


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
        if not text:  # D-215: the shared detector (UTF-8, Shift_JIS, EUC-JP); a file it cannot tell has no text
            with contextlib.suppress(encoding.EncodingRefused):
                text = encoding.decode(data, ("cp932", "euc_jp"))[0]
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
        drug_master: Path | None = None,
        ingredient_atc: Path | None = None,
        lab_lookup: Path | None = None,
        licensed: dict[str, dict[str, dict[str, str]]] | None = None,
        quarantine_max_pct: float = QUARANTINE_MAX_PCT,
        order_key: str | None = None,
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
        # T-610 (STD-042): order line -> ingredient (YJ stem) -> ATC, through the site's drug master and the
        # ingredient-to-ATC table (shipped stems, then the site's own); both site files are optional
        master = drug_master or JP_CORE / "drug_master.csv"
        self.drugs = refdata_jp.DrugResolver(
            refdata_jp.ingredient_atc(ingredient_atc or JP_CORE / "ingredient_atc.csv"),
            refdata_jp.parse_drug_master(master) if master.is_file() else (),
            licensed.get("yj") or {},
        )
        self.drug_lines: Counter[str] = Counter()  # every order line's drug code, for the resolution report
        # STD-043: a lab code with no LOINC row in the site's lookup or its licensed JLAC10 release is listed by volume
        self.lab_known = set(_lookup(lab_lookup or JP_CORE / "jlac10_to_loinc.csv", "local_code", "code"))
        self.lab_known |= {c for c, r in (licensed.get("jlac10") or {}).items() if r.get("target_code")}
        self.materials = _licensed_materials(licensed.get("jlac10") or {})
        self._cm: set[str] | None = None
        self.missed: Counter[str] = Counter()  # "diagnosis:<標準病名 code>", "medication:<YJ code>"
        self.stats: Counter[str] = Counter()  # messages and documents read, by type and outcome
        # NEW-DIN-4 (D-594): whether the day folder is part of an order's key: the site's declaration
        self.order_key = order_key or os.environ.get(ORDER_KEY_ENV) or "unique"
        if self.order_key not in ORDER_KEYS:
            raise ValueError(f"{ORDER_KEY_ENV}={self.order_key!r}: the key is one of {', '.join(ORDER_KEYS)}")
        self._index: dict[str, list[StoredFile]] | None = None
        self._gone: dict[str, list[StoredFile]] = {}  # newest version deleted (flag 0), by message type
        self._deleted_docs: list[Row] = []  # extended-storage documents whose newest version is deleted
        self.quarantine_max_pct = quarantine_max_pct
        self.quarantined: list[tuple[str, str, str]] = []  # (message type, path under the root, reason), STD-020
        self._lab_dead: list[Row] = []  # OBX-11 D results and results a C replaced: tombstones (T-615a)

    # ------------------------------------------------------------------ storage index
    def _files(self) -> dict[str, list[StoredFile]]:
        """The current version of every record by message type (latest timestamp wins, flag 0 = deleted)."""
        if self._index is None:
            latest: dict[tuple[str, str, str, str], StoredFile] = {}
            per_day: dict[tuple[str, str, str, str], StoredFile] = {}  # the newest version in each day folder
            for top in sorted(p for p in self.root.iterdir() if p.is_dir() and p.name not in NOT_PATIENT_DIRS):
                for f in top.glob("*/*/*/*/*"):
                    sf = parse_name(f)
                    if sf is None or not f.is_file():
                        continue
                    # D-594: the day is part of the key only where the site says its order numbers repeat
                    by_day = sf.order == "-" or self.order_key == "per_day"
                    key = (sf.patient, sf.type, sf.order, sf.day if by_day else "")
                    cur = latest.get(key)
                    if cur is None or sf.stamp > cur.stamp:
                        latest[key] = sf
                    if sf.order != "-" and sf.type in _RECORD_TYPES:
                        on = (sf.patient, sf.type, sf.order, sf.day)
                        if on not in per_day or sf.stamp > per_day[on].stamp:
                            per_day[on] = sf
            # counted either way, so the site check shows whether a storage's order numbers come back on another
            # day: live versions of the record types only (a change message names an earlier order by design)
            days: Counter[tuple[str, str, str]] = Counter()
            for (patient, typ, order, _day), sf in per_day.items():
                if not sf.deleted:
                    days[(patient, typ, order)] += 1
            for (_patient, typ, _order), n in days.items():
                if n > 1:
                    self.stats[f"{typ}:order number on several days"] += 1
            index: dict[str, list[StoredFile]] = {}
            gone: dict[str, list[StoredFile]] = {}
            for sf in sorted(latest.values(), key=lambda s: (s.type, s.patient, s.day, s.order)):
                (gone if sf.deleted else index).setdefault(sf.type, []).append(sf)
            self._index = index
            self._gone = gone
        return self._index

    def deleted_rows(self, table: str, source_name: str, delta_column: str | None, since: str | None) -> Iterator[Row]:
        """The rows of records whose newest version carries flag ``0`` (deleted at the hospital), so the adapter can
        tombstone what an earlier night stored (dataflow review P0-1). A delete message is read like any other; one
        that cannot be read is counted and skipped (the next full run removes it anyway)."""
        if table == "note":
            yield from self._deleted_docs
            return
        if table not in TYPES:
            return
        if table == "lab":
            yield from self._lab_dead
        self._files()
        build: Callable[[StoredFile, hl7.Message], Iterator[Row]] = getattr(self, f"_{table}")
        for typ in TYPES[table]:
            for sf in self._gone.get(typ, []):
                try:
                    rows = list(build(sf, hl7.parse(hl7.decode(sf.path.read_bytes()))))
                except Exception:  # a bare delete marker without a readable message
                    self.stats[f"{typ}:deleted unreadable"] += 1
                    continue
                self.stats[f"{typ}:deleted"] += 1
                for row in rows:
                    row.pop("_same", None)
                    yield row

    def _order_on_its_day(self, sf: StoredFile) -> str:
        """The order number for an id built from it (a result with no id of its own): with ``per_day`` it
        always carries its day, so an id never changes meaning when another day's file appears (D-594)."""
        return f"{sf.order}@{sf.day}" if self.order_key == "per_day" else sf.order

    def _messages(self, typ: str) -> Iterator[tuple[StoredFile, hl7.Message]]:
        """The current messages of one type. A file no codec reads, or that is not HL7, is quarantined (STD-020):
        counted, listed, skipped; the other files go on."""
        for sf in self._files().get(typ, []):
            try:
                text, codec = hl7.decode_bytes(sf.path.read_bytes())
                msg = hl7.parse(text)
            except (OSError, ValueError) as exc:  # hl7.Undecodable is a ValueError, as is "no MSH segment"
                why = "unreadable bytes" if isinstance(exc, hl7.Undecodable) else "not an HL7 message"
                self.stats[f"{typ}:quarantined ({why})"] += 1
                where = str(sf.path.relative_to(self.root)) if sf.path.is_relative_to(self.root) else sf.path.name
                self.quarantined.append((typ, where, f"{why}: {exc}"))
                log.warning("ssmix2: a %s file quarantined: %s", typ, why)  # the path names a patient: kept in memory
                continue
            self.stats[typ] += 1
            if codec not in ("iso2022_jp", "ascii", "utf-8"):
                self.stats[f"{typ}:read as {codec}"] += 1
            yield sf, msg

    def quarantine_reason(self, source_name: str) -> str | None:
        """Why the table ``source_name`` holds the night (T-615b's hook), or None: more than ``quarantine_max_pct`` %
        of its files could not be read. Fewer are counted and listed only (STD-020)."""
        types = TYPES.get(source_name, ()) + CHANGES.get(source_name, ())
        bad = [q for q in self.quarantined if q[0] in types]
        if not bad:
            return None
        total = sum(len(self._files().get(t, [])) for t in types)
        if len(bad) * 100 <= self.quarantine_max_pct * total:
            return None
        return (
            f"{len(bad)} of {total} SS-MIX2 files quarantined (more than {self.quarantine_max_pct:g} %): "
            + "; ".join(sorted({q[2].split(":", 1)[0] for q in bad}))
        )

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
        if table == "lab":
            self._lab_dead = []
        out: list[Row] = []
        for typ in TYPES[table]:
            for sf, msg in self._messages(typ):
                out.extend(build(sf, msg))
        if table == "encounter":
            out = self._encounter_changes(out)
        elif table == "medication":
            out = self._administrations(out)
        elif table == "lab":
            out = self._lab_corrections(out)
        for row in out:
            stamp = max(str(row.get(c) or "") for c in (delta_column, "class_changed_at", "end_datetime") if c)
            if delta_column and not after(stamp or None, since):
                continue
            yield row

    # ------------------------------------------------------------------ code lookups
    def _icd(self, byomei: str) -> str:
        """標準病名 -> WHO ICD-10 through the licensed MEDIS release, then the site's lookup file. The MEDIS target
        is kept even when ICD-10-CM has no such code (D-314: Japan's ICD-10 is WHO's)."""
        hit = self.licensed.get("medis", {}).get(byomei.upper()) if byomei else None
        if hit and hit.get("target_code"):
            code = who_icd10(hit["target_code"])
            self.stats["diagnosis:licensed"] += 1
            if not self._in_cm(code):
                self.stats["diagnosis:licensed WHO-only code"] += 1
            return code
        return who_icd10(self.byomei.get(byomei, ""))

    def _in_cm(self, code: str) -> bool:
        if self._cm is None:
            self._cm = _icd10cm()
        return bool(code) and code in self._cm

    def _icd_columns(self, code: str) -> dict[str, str]:
        """``icd10`` (WHO, always) and ``icd10cm`` (the same code when ICD-10-CM has it, else empty), D-314."""
        if code and not _WHO_SHAPE.match(code):
            self.stats["diagnosis:not a WHO ICD-10 shape"] += 1
        return {"icd10": code, "icd10cm": code if self._in_cm(code) else ""}

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
        name = pid.pick(5, 8, ("I",))  # the ideographic (漢字) name before the phonetic (カナ) one
        family, given = hl7.Segment.rep_comp(name, 1), hl7.Segment.rep_comp(name, 2)
        mrn = hl7.Segment.rep_comp(pid.pick(3, 5, ("PI",)), 1)
        yield {
            "mrn": mrn or sf.patient,
            "name": f"{family}　{given}" if given else family,
            "id_no": "",
            "birth_date": hl7.ts(pid.field(7)) or "",
            "sex": pid.field(8) if pid.field(8) in ("M", "F") else "",
            "death_date": hl7.ts(pid.field(29)) or "",
            # PID-30 (HL7 table 0136): ``Y`` marks the patient deceased even without a PID-29 date (STD-013)
            "deceased": "Y" if pid.comp(30, 1).strip().upper() == "Y" else "",
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
            icd = who_icd10(_alt(prb, 3, ("I10", "ICD10"))) or self._icd(code)
            if not icd:
                self.missed[f"diagnosis:{code}"] += 1
            yield {
                "diag_no": prb.comp(4, 1),
                "enc_no": enc,
                "mrn": sf.patient,
                **self._icd_columns(icd),
                "byomei_code": code if prb.comp(3, 3) not in ("I10", "ICD10") else "",
                "byomei_name": prb.comp(3, 2),
                "diag_date": hl7.ts(prb.field(16)) or "",
                "recorded_date": hl7.ts(prb.field(2)) or hl7.ts(prb.field(7)) or "",
                "status": "R" if prb.comp(14, 1) in ("R", "resolved") else "A",
                "suspected": "Y" if _suspected(prb) else "",
            }

    def _resolve_drug(self, codes: dict[str, str]) -> dict[str, str]:
        """The line's ingredient (STD-042): the YJ (or local) code first, then the HOT code."""
        first: dict[str, str] | None = None
        for code in (codes["yj"], codes["hot"]):
            if not code:
                continue
            res = self.drugs.resolve(code)
            if res["stem"]:
                return res
            first = first or res
        return first or {"code": "", "stem": "", "yj": "", "atc": "", "via": ""}

    def _drug_row(self, sf: StoredFile, orc: hl7.Segment, codes: dict[str, str]) -> Row:
        res = self._resolve_drug(codes)
        yj = codes["yj"]
        if res["via"] == "master" and res["yj"]:  # a HOT or local code the site's master turns into its YJ code
            yj = res["yj"]
            self.stats["medication:YJ from the drug master"] += 1
        self.drug_lines[codes["yj"] or codes["hot"]] += 1
        atc = codes["atc"] or self._atc(yj) or res["atc"]
        if res["stem"]:
            self.stats["medication:ingredient"] += 1
        if res["atc"] and not (codes["atc"] or self._atc(yj)):
            self.stats["medication:ATC from the ingredient table"] += 1
        if not atc:
            self.missed[f"medication:{codes['yj'] or codes['hot']}"] += 1
        return {
            "rx_no": orc.comp(2, 1),
            "mrn": sf.patient,
            "nhi_drug_code": yj,
            "source_drug_code": codes["yj"] or codes["hot"],
            "yj_stem": res["stem"],
            "hot_code": codes["hot"],
            "atc": atc,
            "drug_name": codes["name"],
            "order_date": hl7.ts(orc.field(9)) or "",
            "rp_no": orc.comp(4, 1),
            "rx_kind": "injection" if sf.type in INJECTION else "prescription",
            "status": _status(_RX_STATUS, orc.field(5)),
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
        """OML-11 (STD-021): OBX-2 read, OBX-11 read (``D`` a tombstone), the sample time with its fallbacks."""
        obr: hl7.Segment | None = None
        spm = msg.first("SPM")
        folder = hl7.ts(sf.day) or ""
        for seg in msg.segments:
            if seg.name == "OBR":
                obr = seg
                continue
            if seg.name != "OBX":
                continue
            obx = seg
            code, system = obx.comp(3, 1), obx.comp(3, 3)
            is_jlac = system in _JLAC_SYS or (not system and bool(_JLAC_SHAPE.match(code)))
            jlac = code if is_jlac else ""
            times = (
                ("OBX-14", hl7.ts(obx.field(14))),
                ("OBR-7", hl7.ts(obr.field(7)) if obr else None),
                ("SPM-17", hl7.ts(spm.comp(17, 1)) if spm else None),
                ("folder", folder),
            )
            src, when = next(((k, v) for k, v in times if v), ("", ""))
            if src != "OBX-14":
                self.stats[f"OML-11:sample time from {src or 'nowhere'}"] += 1
            status = _status(_OBX_STATUS, obx.field(11))
            order = (obr.comp(3, 1) or obr.comp(2, 1)) if obr else ""
            row: Row = {
                "lab_no": obx.comp(21, 1) or f"{self._order_on_its_day(sf)}-{obx.field(1)}",
                "mrn": sf.patient,
                "local_code": code,  # the lookup key (jlac10_to_loinc.csv), JLAC10 or the hospital's own code
                "jlac10_code": jlac,
                "hosp_lab_code": "" if is_jlac else code,
                "item_name": obx.comp(3, 2),
                "result_value": obx_value(obx),
                "unit": obx.comp(6, 1),
                "ref_range": hl7.unescape(obx.field(7)).strip(),
                "abnormal_flag": obx.comp(8, 1).strip(),
                "sample_datetime": when,
                "sample_time_from": src,
                "result_status": status,
                "specimen": self._specimen(spm, jlac),
                "_same": (sf.patient, order or sf.order, code, obx.field(4).strip()),
            }
            if code and code.upper() not in self.lab_known:
                self.missed[f"lab:{code}"] += 1
            if obx.field(11).strip().upper() == "D":  # deleted: a tombstone, never a record
                self.stats["OML-11:deleted result"] += 1
                row.pop("_same")
                self._lab_dead.append(row)
                continue
            yield row

    def _specimen(self, spm: hl7.Segment | None, jlac: str) -> str:
        """STD-024: SPM-4 (the specimen the lab sent: its text, else its code), else the JLAC10 material code read
        through the site's licensed release, else :data:`_MATERIAL`."""
        if spm is not None:
            said = spm.comp(4, 2).strip() or spm.comp(4, 1).strip()
            if said:
                self.stats["OML-11:specimen from SPM-4"] += 1
                return said
        mat = jlac[9:12] if len(jlac) >= 12 else ""
        return self.materials.get(mat) or _MATERIAL.get(mat, "")

    def _lab_corrections(self, rows: list[Row]) -> list[Row]:
        """A ``C`` (corrected) result replaces the other results of the same order, test and sub-id; a replaced
        result of another id becomes a tombstone (STD-021)."""
        corrected = {r["_same"]: r for r in rows if r["result_status"] == "corrected"}
        out: list[Row] = []
        for r in rows:
            fix = corrected.get(r.pop("_same"))
            if fix is not None and fix is not r:
                self.stats["OML-11:replaced by a correction"] += 1
                if r["lab_no"] != fix["lab_no"]:
                    self._lab_dead.append(r)
                continue
            out.append(r)
        return out

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
                self._deleted_docs.append({"note_no": "ext/" + "/".join(key), "mrn": patient})
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


def obx_value(obx: hl7.Segment) -> str:
    """OBX-5 read by its OBX-2 value type (STD-021). ``CWE`` / ``CE`` / ``CNE``: the text (component 2), else the
    code (``1^陰性^JHSD0001`` -> ``陰性``); ``SN``: comparator, numbers and separator joined (``<^0.03`` -> ``<0.03``,
    ``^1^:^40`` -> ``1:40``); ``NM``: the number as written; anything else (``ST``, ``TX``, ``FT``) the text."""
    vt = obx.field(2).strip().upper()
    raw = obx.field(5)
    if vt in _CODED:
        first = raw.split("~")[0]
        return hl7.Segment.rep_comp(first, 2).strip() or hl7.Segment.rep_comp(first, 1).strip()
    if vt == "SN":
        first = raw.split("~")[0]
        return "".join(hl7.Segment.rep_comp(first, i).strip() for i in (1, 2, 3, 4))
    if vt == "NM":
        return hl7.unescape(raw).strip()
    return hl7.unescape(raw)


def _licensed_materials(jlac10: dict[str, dict[str, Any]]) -> dict[str, str]:
    """JLAC10 material code -> its name, from the 材料名 of the site's licensed release (STD-024)."""
    out: dict[str, str] = {}
    for code, r in jlac10.items():
        extra = r.get("extra") or {}
        if isinstance(extra, str):
            extra = json.loads(extra or "{}")
        name = str(extra.get("material") or "").strip()
        if len(code) >= 12 and name:
            out.setdefault(code[9:12], name)
    return out


UNMAPPED_TOP = 50  # codes per table listed in the ingest report


def reader_summary(src: Any) -> dict[str, Any]:
    """What a reader saw, for the ingest record: messages and documents by type, codes that resolved nowhere (by
    table, and the codes themselves by volume: the steward's work list, STD-042 and STD-043), and how many order
    lines reached an ingredient and an ATC code."""
    missed: Counter[str] = Counter()
    unmapped: dict[str, Counter[str]] = {}
    for k, n in dict(getattr(src, "missed", {}) or {}).items():
        table, _, code = k.partition(":")
        missed[table] += int(n)
        unmapped.setdefault(table, Counter())[code] += int(n)
    out: dict[str, Any] = {
        "read": dict(sorted(dict(getattr(src, "stats", {}) or {}).items())),
        "missed": dict(missed),
        "unmapped": {
            t: [{"code": c, "count": n} for c, n in sorted(cs.items(), key=lambda kv: (-kv[1], kv[0]))[:UNMAPPED_TOP]]
            for t, cs in sorted(unmapped.items())
        },
    }
    drugs, lines = getattr(src, "drugs", None), getattr(src, "drug_lines", None)
    if drugs is not None and lines:
        out["drug_resolution"] = drugs.report(sorted(lines.items()), UNMAPPED_TOP)
    return out
