"""``ssmix2`` source: a reader for SS-MIX2 standardized storage (TB-PLAN-03 step 7, D-122; was a stub under D-28) and
its extended storage (TB-PLAN-04 step 7, D-137).

Layout (SS-MIX2 標準化ストレージ仕様書 v1.2): ``<root>/<id[0:3]>/<id[3:6]>/<patient id>/<YYYYMMDD | ->/<type>/<file>``
with file names ``<patient id>_<date>_<type>_<order no>_<timestamp>_<dept>_<flag>``. Every change writes a new file;
the newest timestamp per (patient, 診療日, type, order no) wins, the specification's record key (構築ガイドライン
3.1.4, review 12 F1), and flag ``0`` means the record was deleted. A site whose vendor files an order's amendments
under another day declares ``TB_SSMIX2_ORDER_NUMBERS=unique`` (D-594, D-1000): the day then leaves the key, except for
order number ``ALL9`` and the ADT types, which keep it always. Either way an order number seen on several days is
counted (``<type>:order number on several days``).

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
* ``PPR-01`` (PPR^ZD1, PRB, ZPR; one snapshot per patient) -> diagnosis (10B-3): PRB-1 ``DE`` a tombstone, PRB-3
  標準病名 (``code^name^MDCDX2``, or ``code^name^99XYZ^ICD-10^name^I10``), PRB-10 ICD-10 first, PRB-4 id, PRB-2
  recorded, PRB-7 diagnosed, PRB-9 end, PRB-16 onset, PRB-14 転帰 (HL7 0241 and JHSD0006) as the status, PRB-15 its
  day, PRB-18 主診断, PRB-17 the written name, ZPR 修飾語, PRB-13 the 疑い flag (``suspected``, D-142), PV1-19 visit
  no. The 標準病名 code is kept (``byomei_code``) beside the ICD-10, so a code nothing can read reaches the lake as
  itself, not as an empty code (D-130, D-137).
* ``OMP-01`` prescription / ``OMP-02`` injection orders (RDE^O11, ORC/RXE/TQ1) -> medication: ORC-2 order no, ORC-4
  Rp group, ORC-9 date, ORC-5 status, RXE-2 the drug (YJ or HOT, with an alternate ATC, YJ or HOT), RXE-31 the YJ
  code when RXE-2 names none, RXE-3 one dose (``dose_per_time``), TQ1-3 the 用法 and from it the doses a day (the
  site's ``usage.csv``, else "1日N回" in its text), ``daily_dose`` their product or empty (10B-4), RXE-5 unit,
  TQ1-7/8 start/end, file dept.
* ``OMP-11`` prescription / ``OMP-12`` injection 実施 (RAS^O17, ORC/RXA) (D-137) -> medication, YJ / HOT kept coded:
  folded into the order with the same ORC-2 when the storage has it (only empty fields are filled), else a
  medication of its own: RXA-5 the drug, RXA-3/4 start/end, RXA-6/7 the amount given and its unit
  (``dose_per_time``, never a day's dose), ORC-9 date, ORC-5 status.
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

ICD-10 comes from PRB-10, else PRB-3's alternate coding; when a vendor sends only the 標準病名 code it is looked up
in the site's
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
``<id[0:3]>/<id[3:6]>/<id>/<診療日>/<kind>/<file>``, or as the guideline lays it out (10B-5) with a content folder
between, ``<kind>/<content folder>/<files>``, the kind named like a CWE that carries the LOINC document code
(``doc_code``, which types the note). File and content-folder names in the standardized form (with any extension) are
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
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
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
_TABLE_OF = {t: table for table, types in TYPES.items() for t in types}
ORDER_KEY_ENV = "TB_SSMIX2_ORDER_NUMBERS"
ORDER_KEYS = ("unique", "per_day")  # D-594
DEFAULT_ORDER_KEY = "per_day"  # the specification's key (D-1000, amends D-594's default "unique")
# the order number of data no order manages (患者基本, 病名, アレルギー): 構築ガイドライン 3.1 (review 12 §4.2)
ALL9 = "ALL9"
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


# ORC-1 order control (HL7 table 0119), third review of PR #1095 item 5: what the message does to the order. A new or
# changed order, a status message and an administration's RE leave the status to ORC-5 as before; a cancel or a
# discontinue sets it; any other code, or none, is ``unknown``: never active
_ORC_KEEP = ("NW", "XO", "SC", "RE", "OK", "SN")
_ORC_SETS = {"CA": "cancelled", "OC": "cancelled", "CR": "cancelled", "DC": "stopped", "OD": "stopped",
             "DR": "stopped", "HD": "on-hold", "OH": "on-hold"}  # fmt: skip


def order_status(orc: hl7.Segment) -> str:
    """The canonical order ``status`` from ORC-1 and ORC-5 (:data:`_ORC_KEEP`, :data:`_ORC_SETS`)."""
    control = orc.field(1).strip().upper()
    if control in _ORC_SETS:
        return _ORC_SETS[control]
    if control in _ORC_KEEP:
        return _status(_RX_STATUS, orc.field(5))
    return "unknown"


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
# 10B-5: a guideline data-type folder is named like a CWE, ``[local code]^local name^[local system]^LOINC document
# code^standard name^LN`` (拡張ストレージ 構築ガイドライン 2.2, review 12 §4.5); its LOINC document code gives the note
# type through ``jp_core/document_loinc.csv`` (the codes review 12 §3 records from the 標準文書コード表, each row
# marked ``verify``); any other code is a ``document`` that keeps its LOINC code (``doc_code``)
CONTENTS_INDEX = "_contents.xml"  # the content folder's index file: its schema is not in review 12, not read


def document_code(kind: str) -> str:
    """The LOINC document code of a data-type folder named like a CWE: the triple whose system is ``LN`` (the
    alternate, components 4 to 6, or the first); empty for a local-only name or an old-style folder (``DSC-01``)."""
    parts = kind.split("^")
    for at in (3, 0):
        if len(parts) > at + 2 and parts[at + 2].strip().upper() == "LN" and parts[at].strip():
            return parts[at].strip()
    return ""


_TEXT_EXT = (".txt", ".text", ".csv", ".tsv")
_COPY_EXT = ("bak", "tmp", "temp", "old", "orig", "swp", "part", "crdownload")  # a copy, not a document
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
    flag: str = "1"


def parse_name(path: Path) -> StoredFile | None:
    parts = path.name.split("_")
    if len(parts) != 7:
        return None
    pid, day, typ, order, stamp, dept, flag = parts
    if flag not in FLAGS or not hl7.valid_stamp(stamp):
        return None
    return StoredFile(path, pid, day, typ, order, stamp, dept, flag == "0", flag)


FLAGS = (
    "0",
    "1",
    "2",
)  # 0 invalid or deleted, 1 valid, 2 past history (構築ガイドライン 3.1.2 to 3.1.4, review 12 §4.4)


def name_problem(name: str) -> str:
    """Why a standardised-storage file name is not read, as a pattern that names no patient (review of PR #1095
    item 7); empty when it is a message file's name."""
    if "." in name:
        return "an extension (not a message file)"
    parts = name.split("_")
    if len(parts) != 7:
        return f"{len(parts)} parts, not 7"
    if parts[6] not in FLAGS:
        return "a condition flag other than 0, 1 or 2"
    if not hl7.valid_stamp(parts[4]):
        return STAMP_PROBLEM
    return ""


STAMP_PROBLEM = "a 発生日時 that is not 17 digits of a real time"


def _newer(sf: StoredFile, cur: StoredFile) -> bool:
    """Whether ``sf`` replaces ``cur``: the later 発生日時; on the same time a deletion wins, so the answer never
    depends on the order a folder lists its files (review of PR #1095 item 7)."""
    return sf.stamp > cur.stamp or (sf.stamp == cur.stamp and sf.deleted and not cur.deleted)


SNAPSHOT = "*"  # the day part of a PPR-01 snapshot group's key: every day folder of the patient (D-1252)
#: the types whose records with no version in force are read as unknown (D-1252 P3, P4); the others keep #1095's
#: reading (a newest flag 2 set aside, an unreadable newest skipped), stated as a limit
VERSIONED_TYPES = ("PPR-01", "OMP-01", "OMP-02")
#: the order types whose number filed on several days makes the older day's record unknown (D-1252 P6)
CROSS_DAY_TYPES = ("OMP-01", "OMP-02")
_KEY_OF = {"diagnosis": "diag_no", "medication": "rx_no"}
DOUBT = {
    "tie": "two versions with one 発生日時",  # D-1252 P5
    "past": "no version in force (the newest carries flag 2)",  # D-1252 P3
}


def key_part(value: str) -> str:
    """A part of a record's key as the reader compares it (D-1252 P8): NFKC (full-width digits and letters become
    half-width) and blanks removed, so ``ＲＸ０１`` and ``RX01`` are one order number. Case is kept."""
    return "".join(unicodedata.normalize("NFKC", value or "").split())


def resolve(versions: list[StoredFile]) -> tuple[str, StoredFile, list[StoredFile], list[StoredFile]]:
    """One record's versions resolved by the guideline (SS-MIX2 標準化ストレージ 構成の説明と構築ガイドライン
    Ver.1.2j, JAMI 2026-08-14, 3.1.4(2)⑥ and (3)①; D-1252): ``(state, file, candidates, older)``.

    The order is the 発生日時 (表3.1-3 No.5), never the order files arrive in. ``deleted``: the newest file
    carries flag 0, on a tie too (a deletion renames every version to 0, ⑥2)); ``live``: the newest carries flag
    1 and is in force; ``tie``: two newest files share one 発生日時 and none is a deletion (P5); ``past``: the
    newest carries flag 2, "過去履歴", a version some newer one replaced, so none is in force (P3). ``candidates``:
    the other versions newer than the last deletion, newest first (what could be in force if the file cannot be
    read, P4); ``older``: every older version (what a newer version or a deletion supersedes)."""
    vs = sorted(versions, key=lambda s: (s.stamp, s.deleted, s.path.name))
    newest, older = vs[-1], vs[:-1]
    if newest.deleted:
        return "deleted", newest, [], older
    last_delete = max((s.stamp for s in vs if s.deleted), default="")
    live = [s for s in reversed(vs) if not s.deleted and s.stamp > last_delete]
    if sum(s.stamp == newest.stamp for s in vs) > 1:
        return "tie", newest, live[1:], older
    return ("past" if newest.flag == "2" else "live"), newest, live[1:], older


def _folder_problem(sf: StoredFile) -> bool:
    """Whether a file sits in other folders than its name says (``<pid 1-3>/<pid 4-6>/<pid>/<day>/<type>``)."""
    parts = sf.path.parts
    return len(parts) < 6 or (parts[-6], parts[-5], parts[-4], parts[-3], parts[-2]) != (
        sf.patient[0:3],
        sf.patient[3:6],
        sf.patient,
        sf.day,
        sf.type,
    )


def storage_dir(root: Path, patient: str, day: str, typ: str) -> Path:
    return root / patient[0:3] / patient[3:6] / patient / day / typ


def _lookup(path: Path, key: str, field: str) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return {r[key]: r[field] for r in csv.DictReader(fh) if r.get(key) and r.get(field)}


def _triples(seg: hl7.Segment, n: int) -> list[tuple[str, str, str]]:
    """``(code, text, coding system)`` of every triple of a coded field: the primary and the alternate triple of
    each repetition, in order. The system's name is given without blanks and in upper case (vendors write ``i10``,
    ``Hot9``); a triple with neither code nor text is left out."""
    return [t for rep in _triples_by_rep(seg, n) for t in rep]


def _triples_by_rep(seg: hl7.Segment, n: int) -> list[list[tuple[str, str, str]]]:
    """:func:`_triples`, one list for each repetition of the field."""
    out: list[list[tuple[str, str, str]]] = []
    for rep in seg.reps(n):
        out.append([])
        for at in (1, 4):
            code, text = hl7.Segment.rep_comp(rep, at), hl7.Segment.rep_comp(rep, at + 1)
            if code or text:
                out[-1].append((code, text, hl7.Segment.rep_comp(rep, at + 2).strip().upper()))
    return out


_NOT_SUSPECTED = ("疑いなし", "疑い無し", "疑いナシ")
#: "R/O" (rule out) and "s/o" (suspicion of), as Japanese charts write them (second review of PR #1095 item 2), and the
#: English words (third review item 7): "rule out", "suspected", "suspicion" ("ruled out" is not one: it refutes)
_RULE_OUT = re.compile(r"(?<![a-z])(?:r/o|s/o|rule[- ]?out|suspect(?:ed)?|suspicion)(?![a-z])", re.IGNORECASE)
#: a diagnosis ruled out (third review of PR #1095 item 7): "…の疑いなし", "ruled out"
_RULED_OUT = re.compile(r"疑い(?:なし|無し|ナシ)|(?<![a-z])ruled[- ]?out(?![a-z])", re.IGNORECASE)


def refuted_in(text: str) -> bool:
    """A diagnosis written as ruled out: "肺癌の疑いなし", "ruled out"."""
    return bool(_RULED_OUT.search(unicodedata.normalize("NFKC", text or "")))


def suspicion_in(text: str) -> bool:
    """A suspicion in a 病名, flag or modifier text: a 疑 ("の疑い", "疑", "(疑)", "疑い", "疑診"), but not "疑いなし";
    "R/O" or "s/o"; or a question mark after the name ("肺癌?", "肺癌？") (review of PR #1095 item 3, second
    review item 2)."""
    t = unicodedata.normalize("NFKC", text or "")
    for word in _NOT_SUSPECTED:
        t = t.replace(word, "")
    return "疑" in t or bool(_RULE_OUT.search(t)) or t.rstrip().endswith("?")


def _jhsd0005(system: str) -> bool:
    """Whether a coding system names table JHSD0005: exactly ``JHSD0005`` or ``99JHSD0005`` after NFKC, blanks
    removed, upper case (fifth review of PR #1095 item 3: ``XYZJHSD0005`` is not it)."""
    return "".join(unicodedata.normalize("NFKC", system).split()).upper() in ("JHSD0005", "99JHSD0005")


def _suspected(prb: hl7.Segment) -> bool:
    """A suspected (provisional) diagnosis: any one of the three says so, and when they disagree it is provisional
    (second review of PR #1095 item 2: a "0" flag never overrules a 疑 in the text). (1) PRB-13 ``1^疑いあり^JHSD0005``
    in whichever triple names the table (also ``99JHSD0005``), or a ``1`` whose text carries a 疑 under any table, or
    a ``1`` in the first triple when no table is named; (2) a suspicion in the 病名 (PRB-3) or its written name
    (PRB-17), :func:`suspicion_in`. The ZPR modifiers are read by the caller. A bare ``1`` of an unknown table with no
    such text is not the flag."""
    triples = [(unicodedata.normalize("NFKC", f), t, sy) for f, t, sy in _triples(prb, 13)]  # "１" is "1"
    named = [(flag, text) for flag, text, system in triples if _jhsd0005(system)]
    if not named and prb.comp(13, 3).strip() == "":
        named = [(unicodedata.normalize("NFKC", prb.comp(13, 1)), prb.comp(13, 2))]
    if any(flag.strip() == "1" or "疑いあり" in text for flag, text in named):
        return True
    if any(flag.strip() == "1" and suspicion_in(text) for flag, text, _s in triples):
        return True
    return suspicion_in(prb.comp(3, 2)) or suspicion_in(prb.comp(17, 1))


def flag_confirmed(prb: hl7.Segment) -> bool:
    """Whether PRB-13 leaves the diagnosis confirmed: only when it is empty. The code table of JHSD0005 (SS-MIX2
    標準化ストレージ仕様書 Ver.1.2j 別紙：コード表, 表95 疑い病名フラグ; D-1252) holds one value, ``1`` 疑いあり, so a
    ``0`` (with any text, of JHSD0005 or of no named table) is not a recognised value: the certainty is unknown. This
    replaces the fourth review's allow-list of "0" texts, which rested on review 12's account of the table, not on
    the table itself. Anything written in the field, a table name alone included, is not empty."""
    return not prb.field(13).strip()


def same_text(a: str, b: str) -> bool:
    """Two names the same after NFKC and with their blanks removed."""

    def norm(t: str) -> str:
        return "".join(unicodedata.normalize("NFKC", t or "").split())

    return norm(a) == norm(b)


def certainty(prb: hl7.Segment, written: str, modifiers: list[str], unread_modifier: bool) -> str:
    """The canonical ``suspected`` column (third review of PR #1095 item 7, fourth review item a): ``Y`` suspected
    (provisional), ``X`` ruled out (refuted: the lake leaves it out), ``U`` certainty unknown (unconfirmed, never
    confirmed), empty confirmed. A suspicion in the flag (:func:`_suspected`), the name, PRB-17 or a modifier, or a
    modifier with only a code, is ``Y``; a "疑いなし" or "ruled out" there is ``X``; both at once ``U``. Confirmed
    only when everything is positively recognised: PRB-13 empty (:func:`flag_confirmed`; a "0" is not a value of
    JHSD0005), no ZPR modifier (its layout and table are not cited, so its meaning is not known), and PRB-17 empty
    or the same name as PRB-3. Anything else is ``U``."""
    if len(prb.reps(13)) > 1 or len(prb.reps(17)) > 1:
        return "U"  # a second certainty or written name is data, never dropped (fifth review item 2)
    texts = [written, *modifiers]
    suspected = _suspected(prb) or unread_modifier or any(map(suspicion_in, texts))
    refuted = any(map(refuted_in, [prb.comp(3, 2), *texts]))
    if suspected and refuted:
        return "U"
    if refuted:
        return "X"
    if suspected:
        return "Y"
    if not flag_confirmed(prb) or modifiers or (written and not same_text(written, prb.comp(3, 2))):
        return "U"
    if not any(c.strip() for c, _t, _s in _triples(prb, 3) + _triples(prb, 10)):
        return "U"  # a name with no code at all is never confirmed (fifth review item 6)
    return ""


def diag_key(value: str) -> str:
    """A diagnosis number as the duplicate check compares it (fifth review of PR #1095 item 5): NFKC, blanks removed,
    case folded, so ``DX01``, ``ＤＸ０１``, ``DX01 `` and ``dx01`` are one number."""
    return "".join(unicodedata.normalize("NFKC", value or "").split()).casefold()


def patient_id(value: str) -> str:
    """A patient id as every table carries it (fourth review of PR #1095 item c): Unicode NFKC, blanks removed."""
    return "".join(unicodedata.normalize("NFKC", value or "").split())


#: PRB-1 action codes (HL7 table 0287) a live diagnosis may carry: add, update, correct, unchanged. DE deletes; any
#: other (D, XX, UN, LI, none) is not recognised: the status is unknown (fourth review of PR #1095 item a)
_ACTIONS = ("AD", "UP", "CO", "UC")


def real_date(value: str) -> bool:
    """Whether a date field is empty, or one real calendar date (and time) :func:`hl7.ts` reads; a repeated date
    (``~``) is not one (fifth review of PR #1095 item 2)."""
    if not value.strip():
        return True
    if "~" in value:
        return False
    got = hl7.ts(value)
    if not got:
        return False
    try:
        date(int(got[:4]), int(got[5:7]), int(got[8:10]))
    except ValueError:
        return False
    return len(got) == 10 or (int(got[11:13]) < 24 and int(got[14:16]) < 60 and int(got[17:19]) < 60)


_ICD10_SYS = ("I10", "ICD10")  # the HL7 table 0396 name and the spelling vendors write


# PRB-14 転帰 (10B-3, review 12 F2) -> the canonical diagnosis ``status``: A active, R resolved,
# I inactive, M remission, U an outcome that says neither or that is not verified (D-587: no clinical
# status and unconfirmed, never active). The table is ``jp_core/prb14_outcome.csv``: only the codes a document
# in this repository records (review 12 §4.10 F2: HL7 table 0241 F 治癒 and D died; JHSD0006 I, M, C, O), each
# row marked ``verify``. Every other code of a named table (0241's N, P, R, S, U, W ...) is U until verified
# (review of PR #1095 item 4: R may mean "recovering", not resolved). The two tables share no code.
def _table_rows(name: str) -> list[dict[str, str]]:
    with (JP_CORE / name).open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


# Second review of PR #1095 item 9: a row is applied only once its meaning is verified against the published table
# (``verified`` = ``yes``); until then its ``status`` is a proposal for the owner's Japanese reader, and the code
# reads as unknown (U). No row is verified today.
#: the fields a verified PRB-14 row must name its public source in (fourth review of PR #1095 item e)
OUTCOME_SOURCE = ("title", "publisher", "version", "section", "document")
#: a document is a well-formed https URL or a DOI; a version a date or a version number (fifth review item 7)
_URL = re.compile(r"^https://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:[/?#][^\s]*)?$")
_DOI = re.compile(r"^(?:doi:|https://doi\.org/)?10\.\d{4,9}/\S+$", re.IGNORECASE)
_VERSION = re.compile(r"^(?:v(?:er\.?)?\s*)?\d+(?:\.\d+)*[a-z]?$|^\d{4}(?:-\d{2}(?:-\d{2})?)?$", re.IGNORECASE)


def _this_project(name: str) -> bool:
    return "trialbox" in "".join(ch for ch in unicodedata.normalize("NFKC", name).casefold() if ch.isalnum())


def outcome_table(rows: list[dict[str, str]]) -> tuple[dict[str, dict[str, str]], set[str]]:
    """``(applied rows by table and code, every table named)`` of ``prb14_outcome.csv``. A row is applied only when
    ``verified`` is ``yes`` and it names its public source (fourth review item e, fifth review item 7): ``document``
    a well-formed https URL or a DOI, ``version`` a date or a version number, ``title``, ``publisher`` and
    ``section`` not empty, and the publisher not this project. A person reviews each row in the pull request that
    adds it; this is the mechanical part. A verified row that fails stops the reader at start."""
    applied: dict[str, dict[str, str]] = {}
    tables: set[str] = set()
    for r in rows:
        tables.add(r["system"].strip().upper())
        if r.get("verified", "").strip().lower() != "yes":
            continue
        f = {k: unicodedata.normalize("NFKC", r.get(k) or "").strip() for k in OUTCOME_SOURCE}
        bad = [k for k in ("title", "publisher", "section") if not f[k]]
        if not (_URL.match(f["document"]) or _DOI.match(f["document"])):
            bad.append("document")
        if not _VERSION.match(f["version"]) or not re.search(r"[1-9]", f["version"]):  # "0" is no version
            bad.append("version")
        if _this_project(f["publisher"]) or _this_project(f["title"]):
            bad.append("publisher")
        if bad:
            raise ValueError(
                f"prb14_outcome.csv: {r['system']} {r['code']} is verified but cites no public source "
                f"({', '.join(bad)})"
            )
        applied.setdefault(r["system"].strip().upper(), {})[r["code"].strip()] = r["status"].strip()
    return applied, tables


_OUTCOME, _OUTCOME_TABLES = outcome_table(_table_rows("prb14_outcome.csv"))
_LOINC_NOTE = {r["loinc"].strip(): r["note_type"].strip() for r in _table_rows("document_loinc.csv")}
_DELETED = ("DE",)  # PRB-1 (HL7 table 0287): DE deletes the diagnosis (review 12 §4.4)
_RANK = {"1": "Y", "2": "N"}  # PRB-18 (JHSD0007): 1 主診断, 2 副診断


#: the reader's own legacy outcome words, PRB-14 ``A`` or ``R`` alone (no text, no table): what TrialBox's exporter
#: and older tests write, read as they always were
_LEGACY_OUTCOME = {"A": "A", "R": "R"}


def outcome_status(prb: hl7.Segment) -> tuple[str, str]:
    """``(status, outcome code)`` of PRB-14 by an exact allow-list (fifth review of PR #1095 item 1): active when
    PRB-14 is empty; otherwise one repetition whose code and table are exactly a recognised pair, a verified row of
    :data:`_OUTCOME` (none is today) or the reader's legacy ``A`` / ``R`` alone. Anything else (another table, a
    local or unknown one, text with no code, a lower-case code, a second repetition) is ``U``: never active."""
    raw = prb.field(14)
    if not raw.strip():
        return "A", ""
    code = unicodedata.normalize("NFKC", prb.comp(14, 1)).strip()
    text = unicodedata.normalize("NFKC", prb.comp(14, 2)).strip()
    system = unicodedata.normalize("NFKC", prb.comp(14, 3)).strip().upper()
    if len(prb.reps(14)) != 1:
        return "U", code
    if system and code in _OUTCOME.get(system, {}):
        return _OUTCOME[system][code], code
    if not system and not text and raw.strip() == code and code in _LEGACY_OUTCOME:
        return _LEGACY_OUTCOME[code], code
    return "U", code


def _alt(seg: hl7.Segment, n: int, systems: tuple[str, ...]) -> str:
    """The alternate code (components 4-6) of a CWE field when its coding system is one of ``systems``."""
    return seg.comp(n, 4) if seg.comp(n, 6).strip().upper() in systems else ""


def drug_codes(seg: hl7.Segment, n: int) -> dict[str, str]:
    """``{yj, hot, atc, name}`` from a drug CWE (RXE-2, RXA-5): each code by the coding system its triple names,
    whatever the case of the name. A first code whose system is none of them (none at all, or a hospital's own
    ``99xxx``) is the YJ / local drug code, as OMP-01 always was, unless another triple names a YJ code. "First" is
    the field's first component: an alternate code after an empty first triple is not it."""
    out = {"yj": "", "hot": "", "atc": "", "name": seg.comp(n, 2)}
    for code, _text, system in _triples(seg, n):
        if not code:
            continue
        if system in _ATC_SYS:
            out["atc"] = out["atc"] or code
        elif system in _HOT_SYS:
            out["hot"] = out["hot"] or code
        elif system in _YJ_SYS:
            out["yj"] = out["yj"] or code
    if seg.comp(n, 3).strip().upper() not in (*_ATC_SYS, *_HOT_SYS, *_YJ_SYS):
        out["yj"] = out["yj"] or seg.comp(n, 1)
    return out


# RXE-31 (10B-4, review 12 F3): the YJ code the specification puts there (revision 1.2g, as review 12 records it); a
# triple with no coding system counts only with the YJ shape (the codes of ``jp_core/yj_to_atc.csv``: seven digits,
# the dosage-form letter, four more)
_YJ_SHAPE = re.compile(r"^[0-9]{7}[A-Z][0-9A-Z]{4}$")


def supplementary_yj(rxe: hl7.Segment) -> str:
    """The YJ code of RXE-31: the first triple that names a YJ system, else one of the YJ shape with no system."""
    for code, _text, system in _triples(rxe, 31):
        code = code.strip()
        if code and (system in _YJ_SYS or (not system and _YJ_SHAPE.match(code.upper()))):
            return code
    return ""


def usage(tq1: hl7.Segment | None) -> tuple[str, str]:
    """``(code, text)`` of the 用法 in TQ1-3 (10B-4). TQ1-3 is an HL7 RPT whose first component is a CWE, so its
    parts are subcomponents (``code&text&system``); a vendor that writes them as components (``code^text^system``)
    is read too. JAMI 標準用法 (``JAMISDP01``) or a local code (review 12 §4.6)."""
    if tq1 is None:
        return "", ""
    rep = tq1.field(3).split("~")[0]
    first = rep.split("^")[0]
    if "&" in first:
        parts = [hl7.unescape(x) for x in first.split("&")]
        return parts[0].strip(), (parts[1] if len(parts) > 1 else "").strip()
    return hl7.Segment.rep_comp(rep, 1).strip(), hl7.Segment.rep_comp(rep, 2).strip()


_KANJI_DIGIT = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_TIMES_A_DAY = re.compile(r"(?<![0-9一-十])(?:1|一)日\s*([0-9]{1,2}|[一二三四五六七八九十])\s*回")


# what a 用法 text may hold beside "1日N回" for the reader to trust it: the times of the day around meals and
# bed, the route; anything else (週, 隔日, 頓用, 疼痛時 and every "...時", まで, 限度, 月N回, 分N, a weekday) is a
# wording the reader does not fully understand, so no daily dose is given (review of PR #1095 item 1)
_USAGE_TIMING = re.compile(r"(毎食後|毎食前|毎食間|朝|昼|夕|食後|食前|食間|就寝前|寝る前|内服|経口|[・、，,()（）\s])")


def doses_from_text(text: str) -> int | None:
    """The number of doses a day a 用法 text states as "1日N回" (full-width or kanji digits too), only when that is
    the whole of what it says besides meal and bed times and the route; None for anything else (週1回, 隔日, 頓用,
    疼痛時, "1日3回まで", "1日2回を限度", 分3, two "1日N回"): the reader does not guess, and a wrong dose is worse
    than none."""
    t = unicodedata.normalize("NFKC", text or "")
    found = list(_TIMES_A_DAY.finditer(t))
    if len(found) != 1:
        return None
    m = found[0]
    rest = _USAGE_TIMING.sub("", t[: m.start()] + t[m.end() :])
    if rest:
        return None
    n = int(m.group(1)) if m.group(1).isdigit() else _KANJI_DIGIT[m.group(1)]
    return n or None


def rx_lines(msg: hl7.Message) -> list[tuple[hl7.Segment, hl7.Segment, hl7.Segment | None, bool]]:
    """Every drug line of an order message as ``(ORC, RXE, TQ1, ambiguous)`` (review of PR #1095 item 6): each RXE
    with the ORC before it. A TQ1 is the line's timing only when the message's structure leaves no doubt (second
    review item 5): its ORC group holds one RXE and one TQ1 (before the RXE, as RDE^O11 orders it, or after). An ORC
    group with several RXE, or several TQ1, gives its lines no TQ1 and ``ambiguous`` true: no daily dose."""
    groups: list[tuple[hl7.Segment, list[hl7.Segment], list[hl7.Segment]]] = []
    for seg in msg.segments:
        if seg.name == "ORC":
            groups.append((seg, [], []))
        elif groups and seg.name == "RXE":
            groups[-1][1].append(seg)
        elif groups and seg.name == "TQ1":
            groups[-1][2].append(seg)
    out: list[tuple[hl7.Segment, hl7.Segment, hl7.Segment | None, bool]] = []
    for orc, rxes, tq1s in groups:
        clear = len(rxes) == 1 and len(tq1s) <= 1
        for rxe in rxes:
            out.append((orc, rxe, tq1s[0] if clear and tq1s else None, not clear and bool(tq1s)))
    return out


def order_no(sf: StoredFile, orc: hl7.Segment) -> str:
    """An order's key (third review of PR #1095 item 6): the file's オーダNo, which with the patient, the day and the
    type is the specification's unique key, and ORC-2 (the placer order number) when it says something else, as
    ``<file order>:<ORC-2>``; ORC-2 alone for a file whose order number is "ALL9" or "-". Empty when neither says:
    the caller quarantines the message."""
    placer = orc.comp(2, 1).strip()
    # compared and written as the key compares them (D-1252 P8): "ＲＸ０１" in a file name is the order RX01
    filed = "" if sf.order in ("-", ALL9) else key_part(sf.order)
    if filed and placer and key_part(placer) != filed:
        return f"{filed}:{placer}"
    return filed or placer


def times(dose: str, per_day: int | None) -> str:
    """One dose times the doses a day, written without a trailing zero; empty when either is unknown or the dose is
    not a number."""
    if per_day is None:
        return ""
    try:
        q = Decimal(unicodedata.normalize("NFKC", dose).strip()) * per_day
    except (InvalidOperation, ValueError):
        return ""
    out = format(q, "f")
    return out.rstrip("0").rstrip(".") if "." in out else out


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
        usage_table: Path | None = None,
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
        # 10B-4: the site's 用法 table (review 12 §7 ``codes/usage.csv``: ``code,doses_per_day``), optional; a code it
        # does not list is read from its text ("1日3回"), else the daily dose stays unknown
        self.usage = _lookup(usage_table or JP_CORE / "usage.csv", "code", "doses_per_day")
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
        self.order_key = order_key or os.environ.get(ORDER_KEY_ENV) or DEFAULT_ORDER_KEY
        if self.order_key not in ORDER_KEYS:
            raise ValueError(f"{ORDER_KEY_ENV}={self.order_key!r}: the key is one of {', '.join(ORDER_KEYS)}")
        hl7.site_encoding()  # an unknown TB_SSMIX2_ENCODING stops the reader here (third review of PR #1095 item 2)
        self._index: dict[str, list[StoredFile]] | None = None
        self._repeated: set[tuple[str, str, str]] = set()  # (patient, type, order no) filed on several days
        self._plain: dict[tuple[str, str, str], list[StoredFile]] = {}  # their files: the plain key is tombstoned
        self._plain_keys = False  # while True, an order line is keyed without its day (to tombstone the plain key)
        self._gone: dict[str, list[StoredFile]] = {}  # newest version deleted (flag 0), by message type
        self._older: dict[Path, list[StoredFile]] = {}  # a record's newest file -> every version it supersedes
        self._fallback: dict[Path, list[StoredFile]] = {}  # -> the versions that could be in force (D-1252 P4)
        self._doubt: dict[Path, str] = {}  # a record with no version in force -> why (read as unknown, D-1252)
        self._rx_dead: list[Row] = []  # drug lines a newer version of their order no longer holds: tombstones
        self._deleted_docs: list[Row] = []  # extended-storage documents whose newest version is deleted
        self.quarantine_max_pct = quarantine_max_pct
        self.quarantined: list[tuple[str, str, str]] = []  # (message type, path under the root, reason), STD-020
        self._lab_dead: list[Row] = []  # OBX-11 D results and results a C replaced: tombstones (T-615a)
        self._dx_dead: list[Row] = []  # PRB-1 DE diagnoses of the current snapshots: tombstones (10B-3)

    # ------------------------------------------------------------------ storage index
    def _walk(self) -> Iterator[Path]:
        """Every message file of the standardised storage: at ``<pid 1-3>/<pid 4-6>/<pid>/<day>/<type>/<file>``, in
        name order. What is not read is counted by pattern, never by name (review of PR #1095 item 7): a file at
        another depth, a name that is not a message file's, a symbolic link (never followed out of the root)."""
        for top in sorted(p for p in self.root.iterdir() if p.is_dir() and p.name not in NOT_PATIENT_DIRS):
            if top.is_symlink():
                self.stats["storage:symbolic link not followed"] += 1
                continue
            for dirpath, dirnames, filenames in os.walk(top):  # never follows a linked folder
                here = Path(dirpath)
                for d in dirnames:
                    if (here / d).is_symlink():
                        self.stats["storage:symbolic link not followed"] += 1
                dirnames.sort()
                depth = len(here.relative_to(top).parts)
                for name in sorted(filenames):
                    f = here / name
                    if f.is_symlink():
                        self.stats["storage:symbolic link not followed"] += 1
                        continue
                    if depth != 4:
                        self.stats["storage:file at another folder depth"] += 1
                        continue
                    why = name_problem(name)
                    if why:
                        self.stats[f"storage:file name not read ({why})"] += 1
                        if why == STAMP_PROBLEM:  # a message file all the same: listed for the site (item 10)
                            self.quarantined.append((name.split("_")[2], str(f.relative_to(self.root)), why))
                        continue
                    yield f

    def _files(self) -> dict[str, list[StoredFile]]:
        """The version in force of every record, by message type (D-1252). Every file of the storage is grouped by
        the specification's key (patient, 診療日, データ種別, オーダNo; 構築ガイドライン Ver.1.2j 3.1.2(3)③ and
        3.1.4(3)②2)), the order number compared after :func:`key_part`, and each group is resolved by
        :func:`resolve`: the newest by 発生日時 (表3.1-3 No.5) decides; a group whose newest file carries flag 0
        is deleted, exactly that group's records (3.1.4(2)⑥2)); a newer version replaces the whole record, an
        order with all its lines (3.1.2(2)). What the guideline does not settle (two versions with one 発生日時; a
        newest file of flag 2; a newest file that cannot be read) is no version in force: for the diagnosis and
        medication types every version that could be in force is read, and its rows go out as unknown with the
        reason (``version_note``), never as confirmed and active. PPR-01 under "ALL9" (or "-") is one group per
        patient: the patient's whole problem list (3.1.2(2)), whatever its day folder."""
        if self._index is None:
            groups: dict[tuple[str, str, str, str], list[StoredFile]] = {}
            for f in self._walk():
                sf = parse_name(f)
                if sf is None:
                    continue
                order = key_part(sf.order)
                if order != sf.order:
                    self.stats["storage:order number written in another width or with a blank (one key)"] += 1
                # D-1000 (amends D-594): the specification's key is the default; ``unique`` is a site's declared
                # exception, and even then "ALL9" (data not managed by an order) and the ADT types (a per-day
                # sequence, not an order number) keep their day
                by_day = sf.order in ("-", ALL9) or self.order_key == "per_day" or sf.type.startswith("ADT-")
                if sf.type == "PPR-01" and sf.order in ("-", ALL9):
                    key = (sf.patient, sf.type, ALL9, SNAPSHOT)
                else:
                    key = (sf.patient, sf.type, order, sf.day if by_day else "")
                groups.setdefault(key, []).append(sf)
            index: dict[str, list[StoredFile]] = {}
            gone: dict[str, list[StoredFile]] = {}
            self._doubt, self._fallback, self._older = {}, {}, {}
            chosen: dict[tuple[str, str, str, str], StoredFile] = {}
            for key, versions in sorted(groups.items()):
                state, sf, candidates, older = resolve(versions)
                typ = sf.type
                chosen[key] = sf
                valid = [v for v in versions if v.flag == "1"]
                if len(valid) > 1:  # the writer did not rename the older version to 2 (D-1252 P1)
                    self.stats[f"{typ}:several valid versions of one record (the newest decides)"] += 1
                if state == "deleted":
                    if any(v.flag == "1" for v in older):  # D-1252 P2: deleted all the same
                        self.stats[f"{typ}:deleted while an older valid file remains"] += 1
                    gone.setdefault(typ, []).append(sf)
                    self._older[sf.path] = older
                    continue
                if typ in VERSIONED_TYPES:
                    if state != "live":
                        self._doubt[sf.path] = DOUBT[state]
                        self.stats[f"{typ}:{DOUBT[state]} (read as unknown)"] += 1
                    else:
                        self._older[sf.path] = older
                    self._fallback[sf.path] = candidates
                elif state == "past":
                    # #1095's reading kept for the other types: a record whose newest version carries flag 2 is set
                    # aside, neither read nor deleted (D-1252 states it as a limit)
                    self.stats[f"{typ}:set aside (no version in force: the newest carries flag 2)"] += 1
                    continue
                elif state == "tie":
                    self.stats[f"{typ}:two versions with one 発生日時 (one read)"] += 1
                index.setdefault(typ, []).append(sf)
            self._count_days(groups)
            self._snapshots(groups, chosen, index, gone)
            self._across_days(groups, chosen)
            self._index = index
            self._gone = gone
        return self._index

    def _count_days(self, groups: dict[tuple[str, str, str, str], list[StoredFile]]) -> None:
        """Counted whatever the key, so the site check shows whether a storage's order numbers come back on another
        day: numbers whose newest file of a day is live on several days, of the record types only (a change message
        names an earlier order by design). A delete with no record on its own day while the number is live on
        another day is counted too (review of PR #1095 item 8)."""
        per_day: dict[tuple[str, str, str, str], StoredFile] = {}
        for versions in groups.values():
            for sf in versions:
                if sf.order in ("-", ALL9) or sf.type not in _RECORD_TYPES:
                    continue
                on = (sf.patient, sf.type, key_part(sf.order), sf.day)
                if on not in per_day or _newer(sf, per_day[on]):
                    per_day[on] = sf
        live: Counter[tuple[str, str, str]] = Counter(k[:3] for k, sf in per_day.items() if not sf.deleted)
        for (_patient, typ, _order), n in live.items():
            if n > 1:
                self.stats[f"{typ}:order number on several days"] += 1
        for (patient, typ, order, _day), sf in per_day.items():
            if sf.deleted and live[(patient, typ, order)] > 0:
                self.stats[f"{typ}:delete filed under another day"] += 1

    def _snapshots(
        self,
        groups: dict[tuple[str, str, str, str], list[StoredFile]],
        chosen: dict[tuple[str, str, str, str], StoredFile],
        index: dict[str, list[StoredFile]],
        gone: dict[str, list[StoredFile]],
    ) -> None:
        """D-1252 P9: the guideline defines one PPR-01 file per patient holding all the diagnoses (構築ガイドライン
        3.1.2(2)); TrialBox's exporter writes one file per diagnosis under its own number, which is read as a record
        of its own. Beside a snapshot, a per-diagnosis record whose newest file is older than the snapshot in force
        is superseded by it (what it holds and the snapshot does not becomes a tombstone); one that is newer is read
        as unknown (which list is current cannot be told)."""
        for (patient, typ, _order, day), snap in chosen.items():
            if typ != "PPR-01" or day != SNAPSHOT:
                continue
            for key, versions in groups.items():
                if key[0] != patient or key[1] != "PPR-01" or key[3] == SNAPSHOT:
                    continue
                sf = chosen[key]
                if max(v.stamp for v in versions) < snap.stamp:
                    for files in (index.get(typ, []), gone.get(typ, [])):
                        if sf in files:
                            files.remove(sf)
                    self._doubt.pop(sf.path, None)
                    self._older.setdefault(snap.path, []).extend(versions)
                    self._fallback.setdefault(snap.path, []).extend(
                        sorted((v for v in versions if not v.deleted), key=lambda v: v.stamp, reverse=True)
                    )
                    self.stats["PPR-01:per-diagnosis file superseded by a newer snapshot"] += 1
                elif sf in index.get(typ, []) and sf.path not in self._doubt:
                    self._doubt[sf.path] = "a per-diagnosis file newer than the patient's snapshot"
                    self.stats["PPR-01:a per-diagnosis file newer than the patient's snapshot (read as unknown)"] += 1

    def _across_days(
        self,
        groups: dict[tuple[str, str, str, str], list[StoredFile]],
        chosen: dict[tuple[str, str, str, str], StoredFile],
    ) -> None:
        """An order number filed on several days (D-1252 P6). Under the specification's key the day is part of the
        record, so a delete filed under another day deletes nothing there (a deletion of exactly the keyed record).
        The reader's own caution, not the guideline's rule: for the order types (OMP-01, OMP-02; not "ALL9", not the
        ADT types), a record of one day whose number another day holds with a newer file (a newer version, a delete,
        a file of flag 2 or one that cannot be read) is read as unknown. Each day's lines are keyed
        ``<number>@<day>`` once the number is filed on several days (any flag), so an id never changes when another
        day's file appears; the plain key an earlier night may have stored is tombstoned. Under ``unique`` the days
        are one record already. Counted either way."""
        days: dict[tuple[str, str, str], list[tuple[str, str, str, str]]] = {}
        for key in groups:
            patient, typ, order, day = key
            if typ in _RECORD_TYPES and order not in ("-", ALL9) and day not in ("", SNAPSHOT):
                days.setdefault((patient, typ, order), []).append(key)
        self._repeated, self._plain = set(), {}
        for number, keys in days.items():
            if len(keys) < 2:
                continue
            typ = number[1]
            if number[1] not in CROSS_DAY_TYPES:
                continue
            self.stats[f"{typ}:order number filed on several days (keyed by its day)"] += 1
            self._repeated.add(number)
            self._plain[number] = [v for k in keys for v in groups[k]]
            for key in keys:
                sf = chosen[key]
                if sf.deleted or sf.path in self._doubt:
                    continue
                if any(max(v.stamp for v in groups[k]) > sf.stamp for k in keys if k != key):
                    self._doubt[sf.path] = "the order number is filed on another day with a newer file"
                    self.stats[f"{typ}:order number on another day with a newer file (read as unknown)"] += 1

    def _quiet(self, fn: Callable[[], list[Row]]) -> list[Row]:
        """``fn()`` with what it counts and the tombstones it adds put back: an older version read only to name or
        mark its rows (D-1252)."""
        counts = (self.stats.copy(), self.missed.copy(), self.drug_lines.copy(), list(self.quarantined))
        marks = (len(self._dx_dead), len(self._rx_dead), len(self._lab_dead))
        try:
            return fn()
        except Exception:  # an older version that cannot be read names nothing
            log.debug("ssmix2: an older version could not be read")
            return []
        finally:
            self.stats, self.missed, self.drug_lines, self.quarantined = counts
            del self._dx_dead[marks[0] :]
            del self._rx_dead[marks[1] :]
            del self._lab_dead[marks[2] :]

    def _version_rows(self, typ: str, sf: StoredFile) -> list[Row]:
        """The rows one version names, read quietly (nothing counted, quarantined or tombstoned)."""
        build: Callable[[StoredFile, hl7.Message], Iterator[Row]] = getattr(self, f"_{_TABLE_OF[typ]}_rows")

        def read() -> list[Row]:
            text, _codec = hl7.decode_bytes(sf.path.read_bytes())
            msg = hl7.parse(text)
            if self._identity_problem(sf, msg) or hl7.offset_problem(text):
                return []
            return list(build(sf, msg))

        return self._quiet(read)

    def _union(self, typ: str, files: list[StoredFile]) -> list[Row]:
        """Every row the versions name, the newest version's row first for each key (D-1252 P3, P4)."""
        col = _KEY_OF[_TABLE_OF[typ]]
        seen: set[str] = set()
        out: list[Row] = []
        for sf in files:
            for row in self._version_rows(typ, sf):
                if str(row[col]) not in seen:
                    seen.add(str(row[col]))
                    out.append(row)
        return out

    def _as_unknown(self, typ: str, rows: list[Row], why: str) -> list[Row]:
        """Rows of a record with no version in force, read as unknown with the reason (D-1252 P3, P4): a diagnosis
        status ``U`` and certainty ``U``; an order line status ``unknown``. Their text is kept as read."""
        for row in rows:
            if _TABLE_OF[typ] == "diagnosis":
                row["status"], row["suspected"] = "U", "U"
            else:
                row["status"] = "unknown"
            row["version_note"] = why
            self.stats[f"{typ}:row read as unknown ({why})"] += 1
        return rows

    def _record_rows(
        self, typ: str, sf: StoredFile, build: Callable[[StoredFile, hl7.Message], Iterator[Row]]
    ) -> list[Row]:
        """The rows of one record's version in force; for a record with no version in force (D-1252 P3, P5, P6, P9)
        or whose newest version cannot be read (P4), the rows of every version that could be in force, as unknown.
        An older version is never read as in force while a newer one exists."""
        doubt = self._doubt.get(sf.path, "")
        if doubt:
            self._message(typ, sf)  # counted, and quarantined as usual when it cannot be read
            return self._as_unknown(typ, self._union(typ, [sf, *self._fallback.get(sf.path, [])]), doubt)
        msg = self._message(typ, sf)
        if msg is not None:
            mark = len(self.quarantined)
            rows = list(build(sf, msg))
            if len(self.quarantined) == mark:
                return rows
        older = self._fallback.get(sf.path, [])
        if typ not in VERSIONED_TYPES or not older:
            return []
        why = "the newest version could not be read"
        return self._as_unknown(typ, self._union(typ, older), why)

    def deleted_rows(self, table: str, source_name: str, delta_column: str | None, since: str | None) -> Iterator[Row]:
        """The rows of records whose newest version carries flag ``0`` (deleted at the hospital), so the adapter can
        tombstone what an earlier night stored (dataflow review P0-1): the deleted file's own rows and every row an
        older version of the same record named (D-1252: a deletion of exactly the keyed record, all of it). A delete
        message is read like any other; one that cannot be read is counted and skipped (the next full run removes it
        anyway). For the order types, the plain key of an order number filed on several days is tombstoned too: its
        records are keyed by their day (D-1252 P6)."""
        if table == "note":
            yield from self._deleted_docs
            return
        if table not in TYPES:
            return
        if table == "lab":
            yield from list(self._lab_dead)
        if table == "diagnosis":
            yield from list(self._dx_dead)
        if table == "medication":
            yield from list(self._rx_dead)
        self._files()
        build: Callable[[StoredFile, hl7.Message], Iterator[Row]] = getattr(self, f"_{table}")
        # a deleted file is read only to name its records: what that read appends to the tombstone lists is taken
        # here and removed again, so the lists never grow or repeat on another call (review of PR #1095)
        marks = (len(self._dx_dead), len(self._lab_dead), len(self._rx_dead))
        col = _KEY_OF.get(table, "")
        for typ in TYPES[table]:
            for sf in self._gone.get(typ, []):
                dead = len(self._dx_dead)
                try:
                    msg = hl7.parse(hl7.decode(sf.path.read_bytes()))
                    if self._identity_problem(sf, msg):  # a delete names only its own patient's records
                        self.stats[f"{typ}:deleted, patient not certain (not applied)"] += 1
                        continue
                    rows = list(build(sf, msg))
                    rows += self._dx_dead[dead:]  # a deleted file's DE diagnoses are gone too
                except Exception:  # a bare delete marker without a readable message
                    self.stats[f"{typ}:deleted unreadable"] += 1
                    # the flag is in the name: the older versions are deleted with it when the file is filed in its
                    # own patient's folders (D-1252); else nothing is applied
                    if not self._older.get(sf.path) or _folder_problem(sf):
                        continue
                    rows = []
                self.stats[f"{typ}:deleted"] += 1
                if typ in VERSIONED_TYPES and col:
                    named = {str(r[col]) for r in rows}
                    for old in self._older.get(sf.path, []):
                        for row in self._version_rows(typ, old):
                            if str(row[col]) not in named:
                                named.add(str(row[col]))
                                rows.append(row)
                                self.stats[f"{typ}:deleted with the record (an older version named it)"] += 1
                for row in rows:
                    row.pop("_same", None)
                    row.pop("_order", None)
                    row.pop("_changed", None)
                    yield row
            if typ in CROSS_DAY_TYPES:
                for number, files in sorted(self._plain.items()):
                    if number[1] != typ:
                        continue
                    seen: set[str] = set()
                    self._plain_keys = True
                    try:
                        for old in files:
                            for row in self._version_rows(typ, old):
                                if str(row[col]) not in seen:
                                    seen.add(str(row[col]))
                                    row.pop("_order", None)
                                    row.pop("_changed", None)
                                    self.stats[f"{typ}:plain key of an order number on several days tombstoned"] += 1
                                    yield row
                    finally:
                        self._plain_keys = False
        del self._dx_dead[marks[0] :]
        del self._lab_dead[marks[1] :]
        del self._rx_dead[marks[2] :]

    def _order_on_its_day(self, sf: StoredFile) -> str:
        """The order number for an id built from it (a result with no id of its own): with ``per_day`` it
        always carries its day, so an id never changes meaning when another day's file appears (D-594); "ALL9"
        always does, as the key does (D-1000)."""
        return f"{sf.order}@{sf.day}" if self.order_key == "per_day" or sf.order == ALL9 else sf.order

    def _quarantine(self, typ: str, sf: StoredFile, why: str, said: str) -> None:
        self.stats[f"{typ}:quarantined ({why})"] += 1
        where = str(sf.path.relative_to(self.root)) if sf.path.is_relative_to(self.root) else sf.path.name
        self.quarantined.append((typ, where, f"{why}: {said}"))
        log.warning("ssmix2: a %s file quarantined: %s", typ, why)  # the path names a patient: kept in memory

    def _message(self, typ: str, sf: StoredFile) -> hl7.Message | None:
        """One file's message, or None when it is quarantined (STD-020): a file no codec reads, or that is not HL7,
        or whose patient or times are not certain, is counted, listed and skipped."""
        try:
            text, codec = hl7.decode_bytes(sf.path.read_bytes())
            msg = hl7.parse(text)
        except hl7.Undecodable as exc:  # the reader's own sentence (D-682): which reading failed, MSH-18's name
            self._quarantine(typ, sf, "unreadable bytes", str(exc))
            return None
        except (OSError, ValueError) as exc:  # "no MSH segment" is a ValueError
            # D-682: the error's type; an OS error's text holds the whole path
            self._quarantine(typ, sf, "not an HL7 message", type(exc).__name__)
            return None
        why = self._identity_problem(sf, msg)
        if why:
            self._quarantine(typ, sf, "patient", why)
            return None
        why = hl7.offset_problem(text)
        if why:
            self._quarantine(typ, sf, "time", why)
            return None
        self.stats[typ] += 1
        if codec not in ("iso2022_jp", "ascii", "utf-8"):
            self.stats[f"{typ}:read as {codec}"] += 1
        return msg

    def _messages(self, typ: str) -> Iterator[tuple[StoredFile, hl7.Message]]:
        """The current messages of one type (:meth:`_message` for each)."""
        for sf in self._files().get(typ, []):
            msg = self._message(typ, sf)
            if msg is not None:
                yield sf, msg

    def _identity_problem(self, sf: StoredFile, msg: hl7.Message) -> str:
        """Why a message's patient is not certain, empty when it is (third review of PR #1095 item 3, fourth review
        item b). The file name's patient, its folders (``<pid 1-3>/<pid 4-6>/<pid>``, and the day and type folders)
        and the message must name one patient: exactly one PID segment; in its PID-3 a patient id (a repetition of
        identifier type ``PI``, or with no type) and no repetition of that kind naming another; PID-2 and PID-4,
        where they carry such an id, the same; no MRG segment outside an ADT message. Ids are compared as
        :func:`patient_id` writes them (NFKC, blanks removed; leading zeros kept)."""
        parts = sf.path.parts
        if len(parts) < 6 or (parts[-6], parts[-5], parts[-4]) != (sf.patient[0:3], sf.patient[3:6], sf.patient):
            return "the folders name another patient than the file name"
        if (parts[-3], parts[-2]) != (sf.day, sf.type):
            return "the folders name another day or data type than the file name"
        pids = msg.all("PID")
        if len(pids) != 1:
            return "no PID segment" if not pids else "more than one PID segment"
        if msg.first("MRG") is not None and not sf.type.startswith("ADT-"):
            return "an MRG segment outside an ADT message"
        pid = pids[0]

        def ids(n: int) -> set[str]:
            return {
                patient_id(hl7.Segment.rep_comp(r, 1))
                for r in pid.reps(n)
                if hl7.Segment.rep_comp(r, 5).strip().upper() in ("PI", "") and patient_id(hl7.Segment.rep_comp(r, 1))
            }

        said = ids(3)
        if not said:
            return "no patient id in PID-3"
        if len(said) > 1:
            return "PID-3 names two patients"
        if said != {sf.patient}:
            return "PID-3 names another patient than the file name"
        for n in (2, 4):
            if ids(n) - {sf.patient}:
                return f"PID-{n} names another patient than the file name"
        return ""

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
        """The table's rows; the dates :func:`hl7.ts` refused while reading them are counted (review of PR #1095)."""
        before = Counter(hl7.REFUSED)
        try:
            yield from self._rows(table, source_name, delta_column, since)
        finally:
            for why, n in (Counter(hl7.REFUSED) - before).items():
                self.stats[f"{table}:date {why}"] += n

    def _rows(self, table: str, source_name: str, delta_column: str | None, since: str | None) -> Iterator[Row]:
        if table not in TYPES:
            if self.extended is not None:
                yield from self.extended.rows(table, source_name, delta_column, since)
            if table == "note":
                for row in self._documents():
                    # a new version of a document keeps its day: its content folder's 発生日時 counts too
                    changed = row.pop("_changed", "")
                    stamp = max(str(row.get(delta_column) or ""), changed) if delta_column else ""
                    if delta_column and not after(stamp or None, since):
                        continue
                    yield row
            return
        build: Callable[[StoredFile, hl7.Message], Iterator[Row]] = getattr(self, f"_{table}")
        if table == "lab":
            self._lab_dead = []
        if table == "diagnosis":
            self._dx_dead = []
        if table == "medication":
            self._rx_dead = []
        out: list[Row] = []
        for typ in TYPES[table]:
            for sf in self._files().get(typ, []):
                out.extend(self._record_rows(typ, sf, build))
            if typ in VERSIONED_TYPES:
                out.extend(self._uncertain_deletes(typ))
        if table == "diagnosis":
            self._one_number_one_record(out)
        if table == "encounter":
            out = self._encounter_changes(out)
        elif table == "medication":
            out = self._administrations(out)
        elif table == "lab":
            out = self._lab_corrections(out)
        for row in out:
            # the change time: the delta column, a class change or end, and for a diagnosis the time its snapshot
            # file was written (a diagnosis recorded long ago and ended last night is a change, review of PR
            # #1095 item 2)
            changed = str(row.pop("_changed", "") or "")
            row.pop("_order", None)
            cols = (delta_column, "class_changed_at", "end_datetime", "end_date")
            stamp = max([str(row.get(c) or "") for c in cols if c] + [changed])
            # a row read as unknown (D-1252) is sent on every night: what an earlier night stored as in force must
            # change, whatever the dates the row itself carries
            if delta_column and not row.get("version_note") and not after(stamp or None, since):
                continue
            yield row

    def _uncertain_deletes(self, typ: str) -> list[Row]:
        """A delete (flag 0) whose message names another patient, or none, is not applied (third review of PR
        #1095 item 3); the version before it is then not in force either (D-1252 P4): its rows as unknown."""
        out: list[Row] = []
        for sf in self._gone.get(typ, []):

            def uncertain(sf: StoredFile = sf) -> list[Row]:
                text, _codec = hl7.decode_bytes(sf.path.read_bytes())
                problem = self._identity_problem(sf, hl7.parse(text))
                return [{"problem": problem}] if problem else []

            if not self._quiet(uncertain):
                continue
            older = self._older.get(sf.path, [])
            last = max((v.stamp for v in older if v.deleted), default="")
            candidates = sorted((v for v in older if not v.deleted and v.stamp > last), key=lambda v: v.stamp)
            out += self._as_unknown(typ, self._union(typ, candidates[::-1]), "a delete whose patient is not certain")
        return out

    def _one_number_one_record(self, rows: list[Row]) -> None:
        """One diagnosis number given by two records of one patient (two per-diagnosis files under two numbers or
        days, TrialBox's exporter's layout; D-1252 P9): which is current cannot be told, so every such row is read
        as unknown. The lake would keep whichever came last."""
        seen: Counter[tuple[str, str]] = Counter((str(r["mrn"]), diag_key(str(r["diag_no"]))) for r in rows)
        for row in rows:
            if seen[(str(row["mrn"]), diag_key(str(row["diag_no"])))] > 1 and not row.get("version_note"):
                self._as_unknown("PPR-01", [row], "one diagnosis number in two records")

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
        yield {
            "mrn": sf.patient,  # PID-3 agrees with it (the identity check): one form of the id for every table
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
        """:meth:`_diagnosis_rows`, and the supersession of older versions (third review of PR #1095 item 8, D-1252):
        a diagnosis an older version of the record holds and this one does not is a tombstone: an older snapshot of
        the patient, a per-diagnosis file this snapshot supersedes, or an older version of the same file (all of
        them when the newest is itself deleted, :meth:`deleted_rows`). The lake removes a tombstoned diagnosis, as it
        does one deleted by ``DE``."""
        mark = len(self._dx_dead)
        rows = list(self._diagnosis_rows(sf, msg))
        numbers = [diag_key(str(r["diag_no"])) for r in [*rows, *self._dx_dead[mark:]]]
        if len(numbers) != len(set(numbers)):  # two diagnoses under one key: which is which (fourth review item f)
            del self._dx_dead[mark:]
            self._quarantine(sf.type, sf, "duplicate key", "two diagnoses carry one diagnosis number (PRB-4)")
            return
        present = {r["diag_no"] for r in rows} | {r["diag_no"] for r in self._dx_dead}
        older = [] if sf.deleted else self._older.get(sf.path, [])
        for old in (row for version in older for row in self._version_rows(sf.type, version)):
            if old["diag_no"] not in present:  # a deleted snapshot's own rows are tombstones already
                old.pop("_changed", None)
                self._dx_dead.append(old)
                present.add(old["diag_no"])
                self.stats["PPR-01:diagnosis gone from a newer snapshot"] += 1
        yield from rows

    def _diagnosis_rows(self, sf: StoredFile, msg: hl7.Message) -> Iterator[Row]:
        """PPR-01: one snapshot of a patient's diagnoses, one PRB each with the ZPR segments that follow it (10B-3,
        review 12 F2; SS-MIX2 標準化ストレージ仕様書 表 3-46 and 3-47 as the review records them):

        * PRB-1 ``DE`` deletes the diagnosis: it is no row, and a tombstone for what an earlier night stored;
        * ICD-10 from PRB-10 (``K297^^I10^O^外来時^JHSD0004``) first, then from PRB-3 as before;
        * PRB-7 診断日 (``diagnosed_date``), PRB-9 終了日 (``end_date``), PRB-16 発生日 (``diag_date``, the onset);
        * PRB-14 転帰 through :func:`outcome_status` into ``status`` (A, R, I, M, U), the code kept as ``outcome``,
          PRB-15 転帰日 as ``outcome_date``;
        * PRB-18 主診断 / 副診断 as ``main_diagnosis`` (``Y`` / ``N``);
        * PRB-17 the written name (``written_name``) and the ZPR 修飾語 (``modifiers``, their texts): a "疑い" in
          either makes the diagnosis suspected, as PRB-13 does (``suspected``, D-142). ZPR's field layout is not in
          review 12, so every coded value of a ZPR is read as a 修飾語 (not re-verified).
        """
        pv1 = msg.first("PV1")
        enc = pv1.comp(19, 1) if pv1 else ""
        groups: list[tuple[hl7.Segment, list[hl7.Segment]]] = []
        for seg in msg.segments:
            if seg.name == "PRB":
                groups.append((seg, []))
            elif seg.name == "ZPR" and groups:
                groups[-1][1].append(seg)
        for prb, zprs in groups:
            code = prb.comp(3, 1)
            # NEW-DIN-5 (DIN-005): the ICD-10 code is in whichever triple names ICD-10: the standard puts the 病名
            # code first and ICD-10 second, vendors differ, and some send it as a second repetition. A triple that
            # is called ICD-10 and is not a code of that shape is never passed on and hides no later one. The first
            # repetition is read whole first (its 病名 code through the site's licence too): a later repetition is
            # asked only when the first gives no ICD-10 code, so it never replaces one
            first, *later = _triples_by_rep(prb, 3) or [[]]
            named = bool(first) and prb.comp(3, 3).strip().upper() in _ICD10_SYS  # the first triple says ICD-10

            def shaped(triples: list[tuple[str, str, str]]) -> str:
                codes = (who_icd10(t[0]) for t in triples if t[2] in _ICD10_SYS)
                return next((c for c in codes if _WHO_SHAPE.match(c)), "")

            icd = shaped(_triples(prb, 10))  # 10B-3: the specification's place for ICD-10
            if icd:
                self.stats["PPR-01:ICD-10 from PRB-10"] += 1
            if not icd:
                icd = shaped(first)
            if not icd:  # as before: an alternate that is called ICD-10 is passed on as written
                icd = who_icd10(_alt(prb, 3, _ICD10_SYS)) or ("" if named else self._icd(code))
            if not icd:
                icd = shaped([t for r in later for t in r])
            if len(prb.reps(3)) > 1:
                self.stats["PPR-01:PRB-3 repeated"] += 1  # one diagnosis is made of it; the site check shows it
            status, outcome = outcome_status(prb)
            if outcome and outcome.upper() != "A":
                self.stats[f"PPR-01:outcome {outcome} as {status}"] += 1
            action = unicodedata.normalize("NFKC", prb.field(1)).strip().upper()
            dates = [prb.field(n) for n in (2, 7, 9, 15, 16)]
            if action not in _ACTIONS + _DELETED:
                # fourth review of PR #1095 item a: active only when everything is recognised
                status = "U"
                self.stats["PPR-01:action code not recognised (unknown)"] += 1
            elif not all(real_date(d) for d in dates):
                status = "U"  # a date that cannot be read: unknown, its text kept (``*_text``)
                self.stats["PPR-01:a date not read (unknown)"] += 1
            elif any(len(prb.reps(n)) > 1 for n in (3, 14)):
                status = "U"  # a second 病名 or 転帰 is data, never dropped (fifth review of PR #1095 item 2)
                self.stats["PPR-01:a repeated name or outcome (unknown)"] += 1
            elif any(
                (hl7.ts(prb.field(n)) or "")[:10] > (hl7.ts(sf.stamp[:8]) or "")
                for n in (2, 7, 16)
                if prb.field(n).strip()
            ):
                status = "U"  # onset, diagnosis or record after the file was written (fifth review item 4)
                self.stats["PPR-01:a date after its file was written (unknown)"] += 1
            elif status in ("A", "U") and (prb.field(9).strip() or prb.field(15).strip()):
                # an end day or an outcome day says the diagnosis is over, whatever 転帰 says or does not: E, ended
                # with its outcome unknown, never active; the days kept (third review item 4, fourth review item a)
                status = "E"
                self.stats["PPR-01:end or outcome date without a read outcome (ended)"] += 1
            # a modifier keeps its text, else its code; one with only a code cannot be read: a doubt, so the
            # diagnosis is suspected (never confirmed when in doubt, review of PR #1095 item 3)
            # (a first field of digits alone is taken for a set id, as HL7 segments begin)
            triples = [
                t
                for z in zprs
                for n in range(1, len(z.fields))
                if not (n == 1 and z.field(1).strip().isdigit())
                for t in _triples(z, n)
            ]
            modifiers = [t or c for c, t, _s in triples if t or c]
            unread = [c for c, t, _s in triples if c and not t]
            if unread:
                self.stats["PPR-01:modifier code without text (read as suspected)"] += 1
            written = prb.comp(17, 1).strip()
            row: Row = {
                "diag_no": prb.comp(4, 1),
                "enc_no": enc,
                "mrn": sf.patient,
                **self._icd_columns(icd),
                "byomei_code": "" if named else code,
                "byomei_name": prb.comp(3, 2),
                "written_name": written,
                "modifiers": "、".join(modifiers),
                "diag_date": hl7.ts(prb.field(16)) if real_date(prb.field(16)) else "",
                "diagnosed_date": hl7.ts(prb.field(7)) if real_date(prb.field(7)) else "",
                "recorded_date": (hl7.ts(prb.field(2)) if real_date(prb.field(2)) else "")
                or (hl7.ts(prb.field(7)) if real_date(prb.field(7)) else ""),
                # a date that cannot be read (or is repeated) keeps its text, never dropped (fifth review item 2, 4)
                "date_text": "; ".join(
                    f"PRB-{n} {prb.field(n).strip()}" for n in (2, 7, 16) if not real_date(prb.field(n))
                ),
                "end_date": hl7.ts(prb.field(9)) if real_date(prb.field(9)) else "",
                "end_date_text": "" if real_date(prb.field(9)) else prb.field(9).strip(),  # never dropped
                "status": status,
                "outcome": outcome,
                "outcome_date": hl7.ts(prb.field(15)) if real_date(prb.field(15)) else "",
                "outcome_date_text": "" if real_date(prb.field(15)) else prb.field(15).strip(),
                "main_diagnosis": _RANK.get(prb.comp(18, 1).strip(), ""),
                "_changed": hl7.ts(sf.stamp[:14]) or "",  # the snapshot file's 発生日時 (not a column)
                "suspected": certainty(prb, written, modifiers, bool(unread)),
            }
            if (
                unicodedata.normalize("NFKC", prb.field(1)).strip().upper() in _DELETED
            ):  # ＤＥ too (minor)  # deleted at the hospital: a tombstone, never a record
                self.stats["PPR-01:deleted diagnosis"] += 1
                row.pop("_changed", None)
                self._dx_dead.append(row)
                continue
            if not icd:
                self.missed[f"diagnosis:{code}"] += 1
            yield row

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

    def _drug_row(self, sf: StoredFile, orc: hl7.Segment, codes: dict[str, str], source: str = "") -> Row:
        """``source``: the code the order line itself carried, when another field (RXE-31) gave the YJ code."""
        res = self._resolve_drug(codes)
        yj = codes["yj"]
        if res["via"] == "master" and res["yj"]:  # a HOT or local code the site's master turns into its YJ code
            yj = res["yj"]
            self.stats["medication:YJ from the drug master"] += 1
        source = source or codes["yj"] or codes["hot"]
        self.drug_lines[source] += 1
        atc = codes["atc"] or self._atc(yj) or res["atc"]
        if res["stem"]:
            self.stats["medication:ingredient"] += 1
        if res["atc"] and not (codes["atc"] or self._atc(yj)):
            self.stats["medication:ATC from the ingredient table"] += 1
        if not atc:
            self.missed[f"medication:{source}"] += 1
        rx_no = order_no(sf, orc)
        if rx_no and not self._plain_keys and (sf.patient, sf.type, key_part(sf.order)) in self._repeated:
            # one number on two days is two records: two keys, from the first night it is filed on a second day
            # (review of PR #1095 item 8, D-1252 P6; under ``unique`` the days are one record and nothing is added)
            rx_no = f"{rx_no}@{sf.day}"
        return {
            "rx_no": rx_no,
            "mrn": sf.patient,
            "nhi_drug_code": yj,
            "source_drug_code": source,
            "yj_stem": res["stem"],
            "hot_code": codes["hot"],
            "atc": atc,
            "drug_name": codes["name"],
            "order_date": hl7.ts(orc.field(9)) or "",
            "rp_no": orc.comp(4, 1),
            "rx_kind": "injection" if sf.type in INJECTION else "prescription",
            "status": order_status(orc),
            "dept_code": "" if sf.dept == "-" else sf.dept,
        }

    def _medication(self, sf: StoredFile, msg: hl7.Message) -> Iterator[Row]:
        """OMP-01 / OMP-02 (10B-4, review 12 F3): RXE-3 is one dose (``dose_per_time``); the doses a day come from
        the 用法 of TQ1-3, through the site's usage table, else its text ("1日3回"); ``daily_dose`` is their product,
        and stays empty when the frequency is unknown (頓用, no TQ1-3, a wording the reader does not read): never a
        guess. RXE-31's YJ code is read when RXE-2 names no YJ code (a HOT9 or local first code)."""
        rows = self._medication_rows(sf, msg)
        if any(not r["rx_no"] for r in rows):
            self._quarantine(sf.type, sf, "no order key", "neither the file name nor ORC-2 gives an order number")
            return
        if not sf.deleted:
            # a line no newer version holds is a tombstone (second review of PR #1095 item 4): the order is the unit
            # of change and a newer version replaces all its lines (構築ガイドライン 3.1.2(2), D-1252)
            keys = {r["rx_no"] for r in rows}
            for version in self._older.get(sf.path, []):
                for row in self._version_rows(sf.type, version):
                    if row["rx_no"] not in keys:
                        keys.add(row["rx_no"])
                        row.pop("_order", None)
                        self._rx_dead.append(row)
                        self.stats[f"{sf.type}:drug line gone from a newer version"] += 1
        yield from rows

    def _medication_rows(self, sf: StoredFile, msg: hl7.Message, count: bool = True) -> list[Row]:
        """The drug lines of one order message. One line keeps the order number as its key (``rx_no``); in a message
        of several lines each is keyed by the order number, its Rp number (ORC-4) and its drug code (RXE-2), never by
        its position, so a line removed in a newer version does not hand its key to the next (second review of PR
        #1095 item 4); the same Rp and drug twice is told apart by its occurrence and counted."""
        lines = rx_lines(msg)
        rows: list[Row] = []
        seen: Counter[str] = Counter()
        for orc, rxe, tq1, ambiguous in lines:
            row = self._medication_line(sf, orc, rxe, tq1, count)
            row["_order"] = row["rx_no"]  # the order's own key, for its administrations (not a column)
            if ambiguous and count:
                self.stats[f"{sf.type}:timing not tied to one drug (no daily dose)"] += 1
            if len(lines) > 1:
                key = f"{row['rx_no']}#{orc.comp(4, 1) or '-'}:{rxe.comp(2, 1) or '-'}"
                seen[key] += 1
                if seen[key] > 1:
                    if count:
                        self.stats[f"{sf.type}:same Rp and drug twice in one order"] += 1
                    key = f"{key}~{seen[key]}"
                row["rx_no"] = key
            rows.append(row)
        return rows

    def _medication_line(
        self, sf: StoredFile, orc: hl7.Segment, rxe: hl7.Segment, tq1: hl7.Segment | None, count: bool = True
    ) -> Row:
        codes = drug_codes(rxe, 2)
        source = ""
        yj31 = supplementary_yj(rxe)
        if yj31 and not any(system in _YJ_SYS for _c, _t, system in _triples(rxe, 2)):
            source = codes["yj"] or codes["hot"]
            codes = {**codes, "yj": yj31}
            self.stats["medication:YJ from RXE-31"] += count
        row = self._drug_row(sf, orc, codes, source)
        dose = rxe.comp(3, 1)
        code, text = usage(tq1)
        per_day: int | None = None
        how = ""
        if code and self.usage.get(code, "").strip().isdigit() and int(self.usage[code]) > 0:
            per_day, how = int(self.usage[code]), "usage table"
        elif doses_from_text(text) is not None:
            per_day, how = doses_from_text(text), "usage text"
        daily = times(dose, per_day)
        if dose and not daily:
            why = "no frequency" if per_day is None else "dose not a number"
            self.stats[f"{sf.type}:daily dose unknown ({why})"] += count
            if code and per_day is None:
                self.missed[f"usage:{code}"] += count
        row.update(
            start_date=(hl7.ts(tq1.field(7)) or "") if tq1 else "",
            end_date=(hl7.ts(tq1.field(8)) or "") if tq1 else "",
            dose_per_time=dose,
            doses_per_day=str(per_day) if per_day is not None else "",
            doses_per_day_from=how,
            usage_code=code,
            usage_text=text,
            daily_dose=daily,
            dose_unit=rxe.comp(5, 1),
        )
        return row

    def _administrations(self, rows: list[Row]) -> list[Row]:
        """OMP-11/12 (実施): fill the empty fields of the order line it was given for, or become a medication of its
        own. The line is the one of its order (the order's key, :func:`order_no`) whose drug code it shares (YJ,
        HOT or the line's own code): an administration of a drug its order does not hold, of no drug code, or that
        fits several lines, never fills a line (third review of PR #1095 item 9): it is a row of its own, keyed
        ``<order>~<its drug code>``, and counted."""
        lines: dict[tuple[str, str], list[Row]] = {}
        for r in rows:
            lines.setdefault((r["mrn"], str(r.get("_order") or r["rx_no"]).split("@", 1)[0]), []).append(r)
        for typ in CHANGES["medication"]:
            for sf, msg in self._messages(typ):
                orc, rxa = msg.first("ORC"), msg.first("RXA")
                if orc is None or rxa is None:
                    self.stats[f"{typ}:no ORC/RXA"] += 1
                    continue
                codes = drug_codes(rxa, 5)
                done = {  # RXA-6 is the amount given at this administration, never a day's dose (10B-4)
                    "start_date": hl7.ts(rxa.field(3)) or "",
                    "end_date": hl7.ts(rxa.field(4)) or "",
                    "dose_per_time": rxa.comp(6, 1),
                    "dose_unit": rxa.comp(7, 1),
                }
                key = order_no(sf, orc)
                given = {c for c in (codes["yj"], codes["hot"]) if c}
                candidates = lines.get((sf.patient, key), [])
                same = [
                    r for r in candidates
                    if given & {str(r.get(c) or "") for c in ("nhi_drug_code", "hot_code", "source_drug_code")} - {""}
                ]  # fmt: skip
                if len(same) == 1:
                    order = same[0]
                    for k, v in {**done, "hot_code": codes["hot"], "nhi_drug_code": codes["yj"]}.items():
                        if v and not order.get(k):
                            order[k] = v
                    self.stats[f"{typ}:with its order"] += 1
                    continue
                row = self._drug_row(sf, orc, codes)
                if candidates:  # its order is here, but not one line of it is certainly this drug
                    why = "no drug code" if not given else ("several lines" if same else "another drug")
                    self.stats[f"{typ}:administration not tied to an order line ({why})"] += 1
                    row["rx_no"] = f"{key}~{codes['yj'] or codes['hot'] or '-'}"
                else:
                    self.stats[f"{typ}:without an order"] += 1
                # an administration alone says nothing of the doses a day: the daily dose is unknown, never RXA-6
                row.update(doses_per_day="", doses_per_day_from="", usage_code="", usage_text="", daily_dose="")
                row.update(done)
                rows.append(row)
                lines.setdefault((sf.patient, key), []).append(row)
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
            code, system = obx.comp(3, 1), obx.comp(3, 3).strip().upper()
            # the JLAC10 code is in whichever triple names it (a hospital's own code may stand first); with no
            # system at all, a first code of the JLAC10 shape is one, as before. The first triple is asked first; a
            # later triple's code is taken without its blanks and only when it has the shape
            if system in _JLAC_SYS or (not system and _JLAC_SHAPE.match(code)):
                jlac = code
            else:
                later = (c.strip() for c, _t, sysname in _triples(obx, 3) if sysname in _JLAC_SYS)
                jlac = next((c for c in later if _JLAC_SHAPE.match(c)), "")
            # the look-up key: the first code when the table knows it, else the JLAC10 code when the table knows that
            known = code.upper() in self.lab_known
            key = jlac if not known and jlac.upper() in self.lab_known else code
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
                "local_code": key,  # the lookup key (jlac10_to_loinc.csv), JLAC10 or the hospital's own code
                "jlac10_code": jlac,
                "hosp_lab_code": "" if jlac == code else code,  # the first code, when it is the hospital's own
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
            if code and key.upper() not in self.lab_known:
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
    def _ext_kind_dirs(self, root: Path) -> list[Path]:
        """The data-type folders of the extended storage, ``<pid 1-3>/<pid 4-6>/<pid>/<診療日>/<データ種別>``, in name
        order; a symbolic link at any level is counted and never followed out of the root (second review of PR #1095
        item 6), as in the standardised storage."""
        level = [root]
        for _depth in range(5):
            nxt: list[Path] = []
            for d in level:
                for c in sorted(d.iterdir()):
                    if c.is_symlink():
                        self.stats["document:not read (a symbolic link, not followed)"] += 1
                    elif c.is_dir():
                        nxt.append(c)
            level = nxt
        return level

    def _ext_problem(self, f: Path) -> str:
        """Why a document file or content folder is not read, as a pattern that names no patient: a symbolic link, a
        hidden name, a backup or temporary copy (``b.txt.bak``, ``b.txt~``)."""
        if f.is_symlink():
            return "a symbolic link, not followed"
        if f.name.startswith("."):
            return "a hidden name"
        if f.name.endswith("~") or ("." in f.name and f.name.rsplit(".", 1)[-1].lower() in _COPY_EXT):
            return "a backup or temporary copy"
        return ""

    def _documents(self) -> Iterator[Row]:
        """Documents of the extended storage as ``note`` rows. Under each data-type folder (``<pid 1-3>/<pid 4-6>/
        <pid>/<診療日>/<データ種別>``) a file is one document (the layout read before), and a folder is the guideline's
        content folder (10B-5, review 12 F4): one document whose files are read together (``_contents.xml`` left
        out), versioned and flagged by the folder's own name. The newest version of a standardized name wins, flag 0
        deletes. The 診療日 may be ``YYYYMMDD``, ``YYYYMM``, ``YYYY`` or ``-``: the document's time is the day when it
        is a whole date, else the content folder's 発生日時, else unknown."""
        root = self.ext_storage
        self._deleted_docs = []  # one walk's tombstones, never added to on another call
        if not root.is_dir():
            return
        latest: dict[tuple[str, ...], tuple[str, Path, str, str, str, bool]] = {}
        for kind_dir in self._ext_kind_dirs(root):
            patient, day, kind = kind_dir.parts[-3], kind_dir.parts[-2], kind_dir.name
            for f in sorted(kind_dir.iterdir()):
                why = self._ext_problem(f)
                if why:
                    self.stats[f"document:not read ({why})"] += 1
                    continue
                stem = f.name.rsplit(".", 1)[0] if f.is_file() and "." in f.name else f.name
                sf = parse_name(Path(stem))
                if sf is not None and sf.patient == patient:
                    if sf.flag == "2":  # its meaning not verified (second review of PR #1095 item 9)
                        self.stats["document:set aside (condition flag 2, meaning not verified)"] += 1
                        continue
                    key: tuple[str, ...] = (patient, day, kind, sf.order)
                    stamp, deleted = sf.stamp, sf.deleted
                elif len(stem.split("_")) == 7 and stem.split("_")[0] == patient:
                    self.stats["document:not read (a standardized name that is not valid)"] += 1
                    continue
                else:
                    key, stamp, deleted = (patient, day, kind, f.name), "", False
                    if f.is_dir():
                        self.stats["document:content folder without a standardized name"] += 1
                cur = latest.get(key)
                # the later 発生日時; on the same time a deletion wins, as in the standardised storage (_newer)
                if cur is None or stamp > cur[0] or (stamp == cur[0] and deleted and not cur[5]):
                    latest[key] = (stamp, f, patient, day, kind, deleted)
        for key, (stamp, f, patient, day, kind, deleted) in sorted(latest.items()):
            if deleted:
                self.stats["document:deleted"] += 1
                self._deleted_docs.append({"note_no": "ext/" + "/".join(key), "mrn": patient})
                continue
            if f.is_dir():
                self.stats["document:content folder"] += 1
                texts: list[str] = []
                hows: list[str] = []
                for part in sorted(x for x in f.iterdir()):
                    why = self._ext_problem(part)
                    if why or not part.is_file():
                        self.stats[f"document:not read ({why or 'a folder inside a content folder'})"] += 1
                        continue
                    if part.name == CONTENTS_INDEX:
                        self.stats["document:_contents.xml not read"] += 1
                        continue
                    t, h = document_text(part.name, part.read_bytes())
                    (texts if t else hows).append(t or h)
                text, how = "\n\n".join(texts), "; ".join(hows) or "no file"
            else:
                text, how = document_text(f.name, f.read_bytes())
            self.stats["document" if text else f"document without text ({how})"] += 1
            when = hl7.ts(day) or ""
            if not when and stamp:
                when = hl7.ts(stamp[:14]) or ""
            code = document_code(kind)
            if code:
                note_type = _LOINC_NOTE.get(code, "document")
            else:
                note_type = next((t for p, t in _DOC_KINDS if kind.upper().startswith(p)), "document")
            yield {
                "note_no": "ext/" + "/".join(key),  # becomes a keyed hash: the path never leaves the adapter
                "mrn": patient,
                "enc_no": "",
                "note_datetime": when if len(when) > 10 else (f"{when} 00:00:00" if when else ""),
                "note_type": note_type,
                "doc_code": code,
                "text": text,
                "_changed": hl7.ts(stamp[:14]) or "",  # the version's 発生日時, for the delta (not a column)
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
