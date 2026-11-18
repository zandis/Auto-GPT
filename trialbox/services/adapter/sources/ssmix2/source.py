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


def suspicion_in(text: str) -> bool:
    """A 疑 in a 病名 or flag text: "の疑い", "疑", "(疑)", "疑い" (review of PR #1095 item 3); not "疑いなし"."""
    t = unicodedata.normalize("NFKC", text or "")
    for word in _NOT_SUSPECTED:
        t = t.replace(word, "")
    return "疑" in t


def _suspected(prb: hl7.Segment) -> bool:
    """A suspected diagnosis: PRB-13 ``1^疑いあり^JHSD0005`` (any coding system name, as vendors vary), or a 病名
    whose text (PRB-3, or the written name in PRB-17) carries a 疑 (``の疑い``, ``疑``, ``(疑)``) when the vendor
    sends no flag. The flag is read from whichever triple names table JHSD0005 (a hospital's own code may stand
    first), and such a triple alone decides: a named ``0`` is not overruled by a ``1`` of another table or of none.
    With no triple naming the table, a triple whose code is ``1`` with a 疑 in its text is the flag whatever its
    coding system (``1^疑い^99ZZZ``), and the first triple is read as it always was."""
    named = [(flag, text) for flag, text, system in _triples(prb, 13) if system == "JHSD0005"]
    if not named:
        if any(flag.strip() == "1" and suspicion_in(text) for flag, text, _s in _triples(prb, 13)):
            return True
        first = prb.comp(13, 3).strip() == ""
        named = [(prb.comp(13, 1) if first else "", prb.comp(13, 2))]
    if any(flag.strip() == "1" or "疑いあり" in text for flag, text in named):
        return True
    if any(flag.strip() == "0" for flag, _t in named):  # a named "no suspicion" decides (its own earlier review)
        return False
    return suspicion_in(prb.comp(3, 2)) or suspicion_in(prb.comp(17, 1))


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


_OUTCOME: dict[str, dict[str, str]] = {}
for _r in _table_rows("prb14_outcome.csv"):
    _OUTCOME.setdefault(_r["system"].strip().upper(), {})[_r["code"].strip().upper()] = _r["status"].strip()
_LOINC_NOTE = {r["loinc"].strip(): r["note_type"].strip() for r in _table_rows("document_loinc.csv")}
_OUTCOME_ANY = {**_OUTCOME["HL70241"], **_OUTCOME["JHSD0006"]}
_OUTCOME_WORDS = (("治癒", "R"), ("resolved", "R"), ("死亡", "I"), ("寛解", "M"), ("中止", "U"), ("継続", "A"))
_DELETED = ("DE",)  # PRB-1 (HL7 table 0287): DE deletes the diagnosis (review 12 §4.4)
_RANK = {"1": "Y", "2": "N"}  # PRB-18 (JHSD0007): 1 主診断, 2 副診断


def outcome_status(prb: hl7.Segment) -> tuple[str, str]:
    """``(status, outcome code)`` of PRB-14: the 転帰 read through :data:`_OUTCOME`. No 転帰 is active, as before; a
    code no table lists, or one not verified, is ``U`` (never active, D-587); ``resolved``, and ``A`` or ``R`` with
    no table named, read as they always did (the shape TrialBox's exporter and older tests write)."""
    code, text, system = prb.comp(14, 1).strip(), prb.comp(14, 2), prb.comp(14, 3).strip().upper()
    if not code and not text:
        return "A", ""
    table = _OUTCOME.get(system, _OUTCOME_ANY)
    if code.upper() in table:
        return table[code.upper()], code
    if code.lower() == "resolved":
        return "R", code
    # the reader's own legacy words, A and R with no table named (TrialBox's exporter and older tests write them):
    # read as they always were; a code R that names table 0241 is not verified and is U
    if code.upper() in ("A", "R") and system not in _OUTCOME:
        return code.upper(), code
    if system in _OUTCOME:  # a code of a named table that is not mapped: not verified, never active
        return "U", code
    word = next((st for w, st in _OUTCOME_WORDS if w in text or w == code), "")
    return word or "U", code


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
        self._index: dict[str, list[StoredFile]] | None = None
        self._gone: dict[str, list[StoredFile]] = {}  # newest version deleted (flag 0), by message type
        self._deleted_docs: list[Row] = []  # extended-storage documents whose newest version is deleted
        self.quarantine_max_pct = quarantine_max_pct
        self.quarantined: list[tuple[str, str, str]] = []  # (message type, path under the root, reason), STD-020
        self._lab_dead: list[Row] = []  # OBX-11 D results and results a C replaced: tombstones (T-615a)
        self._dx_dead: list[Row] = []  # PRB-1 DE diagnoses of the current snapshots: tombstones (10B-3)

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
                    # D-1000 (amends D-594): the specification's key (patient, 診療日, データ種別,
                    # オーダNo; 構築ガイドライン 3.1.4, review 12 F1) is the default; ``unique`` is a site's
                    # declared exception, and even then "ALL9" (data not managed by an order) and the ADT
                    # types (a per-day sequence, not an order number) keep their day
                    by_day = sf.order in ("-", ALL9) or self.order_key == "per_day" or sf.type.startswith("ADT-")
                    key = (sf.patient, sf.type, sf.order, sf.day if by_day else "")
                    cur = latest.get(key)
                    if cur is None or sf.stamp > cur.stamp:
                        latest[key] = sf
                    if sf.order not in ("-", ALL9) and sf.type in _RECORD_TYPES:
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
        if table == "diagnosis":
            yield from list(self._dx_dead)
        self._files()
        build: Callable[[StoredFile, hl7.Message], Iterator[Row]] = getattr(self, f"_{table}")
        for typ in TYPES[table]:
            for sf in self._gone.get(typ, []):
                dead = len(self._dx_dead)
                try:
                    rows = list(build(sf, hl7.parse(hl7.decode(sf.path.read_bytes()))))
                    rows += self._dx_dead[dead:]  # a deleted file's DE diagnoses are gone too
                except Exception:  # a bare delete marker without a readable message
                    self.stats[f"{typ}:deleted unreadable"] += 1
                    continue
                self.stats[f"{typ}:deleted"] += 1
                for row in rows:
                    row.pop("_same", None)
                    yield row

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

    def _messages(self, typ: str) -> Iterator[tuple[StoredFile, hl7.Message]]:
        """The current messages of one type. A file no codec reads, or that is not HL7, is quarantined (STD-020):
        counted, listed, skipped; the other files go on."""
        for sf in self._files().get(typ, []):
            try:
                text, codec = hl7.decode_bytes(sf.path.read_bytes())
                msg = hl7.parse(text)
            except hl7.Undecodable as exc:  # the reader's own sentence (D-682): which reading failed, MSH-18's name
                self._quarantine(typ, sf, "unreadable bytes", str(exc))
                continue
            except (OSError, ValueError) as exc:  # "no MSH segment" is a ValueError
                # D-682: the error's type; an OS error's text holds the whole path
                self._quarantine(typ, sf, "not an HL7 message", type(exc).__name__)
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
        if table == "diagnosis":
            self._dx_dead = []
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
                "diag_date": hl7.ts(prb.field(16)) or "",
                "diagnosed_date": hl7.ts(prb.field(7)) or "",
                "recorded_date": hl7.ts(prb.field(2)) or hl7.ts(prb.field(7)) or "",
                "end_date": hl7.ts(prb.field(9)) or "",
                "status": status,
                "outcome": outcome,
                "outcome_date": hl7.ts(prb.field(15)) or "",
                "main_diagnosis": _RANK.get(prb.comp(18, 1).strip(), ""),
                "suspected": "Y" if _suspected(prb) or unread or any(map(suspicion_in, (written, *modifiers))) else "",
            }
            if prb.field(1).strip().upper() in _DELETED:  # deleted at the hospital: a tombstone, never a record
                self.stats["PPR-01:deleted diagnosis"] += 1
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
        return {
            "rx_no": orc.comp(2, 1),
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
            "status": _status(_RX_STATUS, orc.field(5)),
            "dept_code": "" if sf.dept == "-" else sf.dept,
        }

    def _medication(self, sf: StoredFile, msg: hl7.Message) -> Iterator[Row]:
        """OMP-01 / OMP-02 (10B-4, review 12 F3): RXE-3 is one dose (``dose_per_time``); the doses a day come from
        the 用法 of TQ1-3, through the site's usage table, else its text ("1日3回"); ``daily_dose`` is their product,
        and stays empty when the frequency is unknown (頓用, no TQ1-3, a wording the reader does not read): never a
        guess. RXE-31's YJ code is read when RXE-2 names no YJ code (a HOT9 or local first code)."""
        orc, rxe, tq1 = msg.first("ORC"), msg.first("RXE"), msg.first("TQ1")
        if orc is None or rxe is None:
            return
        codes = drug_codes(rxe, 2)
        source = ""
        yj31 = supplementary_yj(rxe)
        if yj31 and not any(system in _YJ_SYS for _c, _t, system in _triples(rxe, 2)):
            source = codes["yj"] or codes["hot"]
            codes = {**codes, "yj": yj31}
            self.stats["medication:YJ from RXE-31"] += 1
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
            self.stats[f"{sf.type}:daily dose unknown ({why})"] += 1
            if code and per_day is None:
                self.missed[f"usage:{code}"] += 1
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
                done = {  # RXA-6 is the amount given at this administration, never a day's dose (10B-4)
                    "start_date": hl7.ts(rxa.field(3)) or "",
                    "end_date": hl7.ts(rxa.field(4)) or "",
                    "dose_per_time": rxa.comp(6, 1),
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
                # an administration alone says nothing of the doses a day: the daily dose is unknown, never RXA-6
                row.update(doses_per_day="", doses_per_day_from="", usage_code="", usage_text="", daily_dose="")
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
    def _documents(self) -> Iterator[Row]:
        """Documents of the extended storage as ``note`` rows. Under each data-type folder (``<pid 1-3>/<pid 4-6>/
        <pid>/<診療日>/<データ種別>``) a file is one document (the layout read before), and a folder is the guideline's
        content folder (10B-5, review 12 F4): one document whose files are read together (``_contents.xml`` left
        out), versioned and flagged by the folder's own name. The newest version of a standardized name wins, flag 0
        deletes. The 診療日 may be ``YYYYMMDD``, ``YYYYMM``, ``YYYY`` or ``-``: the document's time is the day when it
        is a whole date, else the content folder's 発生日時, else unknown."""
        root = self.ext_storage
        if not root.is_dir():
            return
        latest: dict[tuple[str, ...], tuple[str, Path, str, str, str, bool]] = {}
        for kind_dir in sorted(root.glob("*/*/*/*/*")):
            if not kind_dir.is_dir():
                continue
            patient, day, kind = kind_dir.parts[-3], kind_dir.parts[-2], kind_dir.name
            for f in sorted(kind_dir.iterdir()):
                stem = f.name.rsplit(".", 1)[0] if f.is_file() and "." in f.name else f.name
                sf = parse_name(Path(stem))
                if sf is not None and sf.patient == patient:
                    key: tuple[str, ...] = (patient, day, kind, sf.order)
                    stamp, deleted = sf.stamp, sf.deleted
                else:
                    key, stamp, deleted = (patient, day, kind, f.name), "", False
                    if f.is_dir():
                        self.stats["document:content folder without a standardized name"] += 1
                cur = latest.get(key)
                if cur is None or stamp > cur[0]:
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
                for part in sorted(x for x in f.iterdir() if x.is_file()):
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
                when = hl7.ts(stamp) or ""
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
