"""catalogue_verify: check the clinical item catalogue against public sources and write its verification columns.

D-180. Two steps, so the catalogue can be rebuilt offline and the evidence is kept in the repository:

    python -m tools.catalogue_verify fetch           # network: NLM, MHLW, OHDSI -> catalogue/verification/evidence.json
    python -m tools.catalogue_verify build           # offline: evidence + curated files -> the catalogue CSVs
    python -m tools.catalogue_verify build --check   # exit 1 when a generated CSV is out of date

Inputs (curated by hand, in ``catalogue/verification/``):

* ``loinc_decisions.csv``        per item: adopt a LOINC code for a local item, keep it local, or say the code only
                                 partly fits; the search terms used and a note. A local item whose name search found
                                 any LOINC term must have a row here (somebody looked at the hits).
* ``jlac10_map.csv``             per item: the JLAC10 codes of the MHLW 特定健診 item table that name this item.
* ``phenotype_icd10cm_map.csv``  per OHDSI-linked phenotype: the cohort used and its ICD-10-CM include and exclude
                                 code families.

Evidence (written by ``fetch``, read by ``build``): ``evidence.json`` with the LOINC names of every code, the LOINC
search hits, the MHLW JLAC10 rows, the OHDSI cohorts' entry concepts, the ICD-10-CM codes under every code family and
ICD-10-CM title hits for every entry concept name.

Outputs: ``items.csv`` and ``phenotypes.csv`` (verification columns rewritten in place, other columns kept except
for adopted LOINC codes), ``phenotype_icd10cm.csv`` and ``codes_checked.csv``: every code the catalogue names
anywhere (a code column, a phenotype's ``codes``, a note, a score file), the source that holds it and whether it may
drive an exclusion. Never invents a code: a code is ``verified = yes`` only when the evidence holds it. A code that
is not verified has ``may_exclude = no``: unknown never excludes.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import io
import json
import re
import sys
import tempfile
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "catalogue"

NLM_LOINC = "https://clinicaltables.nlm.nih.gov/api/loinc_items/v3/search"
NLM_ICD10CM = "https://clinicaltables.nlm.nih.gov/api/icd10cm/v3/search"
MHLW_PAGE = "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/xml_30799.html"
MHLW_XLSX = "https://www.mhlw.go.jp/content/12400000/001082795.xlsx"
NCI_CDISC_SDTM = "https://evs.nci.nih.gov/ftp1/CDISC/SDTM/SDTM%20Terminology.txt"
WHOCC_ATC = "https://atcddd.fhi.no/atc_ddd_index/"
OHDSI_TAG = "v3.37.0"
OHDSI_RAW = f"https://raw.githubusercontent.com/OHDSI/PhenotypeLibrary/{OHDSI_TAG}/inst"

LOINC_NOTICE = (
    "LOINC: free for any purpose incl. commercial, LOINC notice+version required (baseline-open-data 2026-11-09)"
)
SRC_LOINC = "NLM Clinical Tables loinc_items"
SRC_MHLW = "MHLW 特定健診 XML 付属2 Ver.4 (001082795.xlsx)"
SRC_ICD = "NLM Clinical Tables icd10cm"
SRC_OHDSI = f"OHDSI PhenotypeLibrary {OHDSI_TAG}"
SRC_CDISC = "NCI EVS CDISC SDTM Terminology"
SRC_ATC = "WHOCC ATC/DDD Index"

ITEM_EXTRA = [
    "code_fit",
    "verified_source",
    "verified_date",
    "verified_note",
    "jlac10",
    "jlac10_source",
    "may_exclude",
]
PHENO_EXTRA = ["verified", "verified_source", "verified_date", "verified_note", "may_exclude"]
CODES_COLUMNS = [
    "file",
    "row",
    "field",
    "system",
    "code",
    "use",
    "verified",
    "name_in_source",
    "source",
    "verified_date",
    "may_exclude",
    "note",
]
PH_OUT_COLUMNS = [
    "phenotype_id",
    "ohdsi_cohort_id",
    "cohort_name",
    "library_status",
    "entry_concepts",
    "icd10cm_include",
    "icd10cm_exclude",
    "icd10cm_billable_codes",
    "name_check",
    "name_hits_outside",
    "derivation",
    "codes_verified",
    "mapping_verified",
    "verified_source",
    "verified_date",
    "may_exclude",
    "note",
]
# adopt / adopt_partial: give a local item this LOINC code (exact / partial fit); fit_exact / fit_partial: a person
# read an existing code against the item; keep_local: the search hits were read and none fits. A coded item with no
# decision has code_fit = unreviewed, which never excludes.
ACTIONS = {"adopt", "adopt_partial", "keep_local", "fit_exact", "fit_partial"}
ADOPT = {"adopt", "adopt_partial"}
FIT = {"adopt": "exact", "fit_exact": "exact", "adopt_partial": "partial", "fit_partial": "partial"}
JLAC10_FITS = {"exact", "partial"}
# The MHLW unit as printed in the 付属2 sheet -> its UCUM form. jlac10_map.csv `source_unit_ucum` must match this
# table, so a unit cannot be copied wrong; a unit not listed here stops the build until someone adds it.
MHLW_UNIT_UCUM = {
    "": "",
    "%": "%",
    "cm": "cm",
    "kg": "kg",
    "kg/m2": "kg/m2",
    "mmHg": "mm[Hg]",
    "拍／分": "/min",
    "mg/dl": "mg/dL",
    "g/dl": "g/dL",
    "mg/L": "mg/L",
    "ng/ml": "ng/mL",
    "U/l": "U/L",
    "ml/min/1.73m2": "mL/min/{1.73_m2}",
    "mg/g･CR": "mg/g",
    "ｆｌ": "fL",
    "/mm3": "/uL",
    "万/mm3": "10*4/uL",
}
# segments of a phenotype `codes` cell that name another vocabulary, not ICD-10-CM
NON_ICD_PREFIXES = ("LOINC", "ATC", "MEDIS", "ICD-O", "local", "procedure")
ICD_TOKEN = re.compile(r"\b([A-Z]\d[0-9A-Z](?:\.[0-9A-Z]{1,4})?)")
MAX_NAME_CHECKS = 40
MAX_STORED_CONCEPTS = 60  # per cohort in evidence.json; the count is kept
# Vocabularies whose concept names are licensed text (CPT4: AMA copyright; SNOMED CT: SNOMED International
# affiliate licence; HCPCS kept with them to be safe). evidence.json and the CSVs keep their concept ids only.
NAMELESS_VOCABULARIES = frozenset({"CPT4", "HCPCS", "SNOMED"})

Getter = Callable[[str], bytes]


class CatalogueError(ValueError):
    """A curated file or the evidence does not support what the catalogue would say."""


# ---------------------------------------------------------------- small helpers


def search_term(name_en: str) -> str:
    """The automatic LOINC search term for an item: its English name without brackets and commas."""
    term = re.sub(r"\([^)]*\)", " ", name_en).replace(",", " ")
    return " ".join(term.split())


ICD_RANGE = re.compile(r"\b([A-Z]\d[0-9A-Z](?:\.[0-9A-Z]{1,4})?)\*?\s*-\s*([A-Z]\d[0-9A-Z](?:\.[0-9A-Z]{1,4})?)\*?")
EXCL = re.compile(r"\(?\s*\bexcl(?:\.|uding)?\s*([^)]*)\)?")


def expand_icd_range(low: str, high: str) -> list[str]:
    """Every code a range names: ``A15-A19`` -> A15..A19, ``G40.0-G40.2`` -> G40.0..G40.2. A range that is not
    plain numbers on one stem gives its two ends only."""
    a, b = low.partition("."), high.partition(".")
    if not a[1] and not b[1] and low[0] == high[0] and low[1:].isdigit() and high[1:].isdigit():
        lo, hi = int(low[1:]), int(high[1:])
        if lo <= hi:
            return [f"{low[0]}{n:02d}" for n in range(lo, hi + 1)]
    if a[1] and b[1] and a[0] == b[0] and len(a[2]) == len(b[2]):
        head_lo, head_hi = a[2][:-1], b[2][:-1]
        if head_lo == head_hi and a[2][-1].isdigit() and b[2][-1].isdigit() and a[2][-1] <= b[2][-1]:
            return [f"{a[0]}.{head_lo}{d}" for d in range(int(a[2][-1]), int(b[2][-1]) + 1)]
    return [low, high]


def _icd_list(text: str) -> list[str]:
    out: list[str] = []
    pos = 0
    for m in ICD_RANGE.finditer(text):
        out += ICD_TOKEN.findall(text[pos : m.start()])
        out += expand_icd_range(m.group(1), m.group(2))
        pos = m.end()
    out += ICD_TOKEN.findall(text[pos:])
    return list(dict.fromkeys(out))


def icd_split(codes: str) -> tuple[list[str], list[str]]:
    """ICD-10-CM codes of a free-text `codes` cell, as (included, excluded). ``M05.*`` -> ``M05``; a range gives every
    code in it; ``(excl. M06.1, M06.4)`` gives excluded codes, never included ones."""
    inc: list[str] = []
    exc: list[str] = []
    for segment in codes.split(";"):
        seg = segment.strip()
        if seg.startswith("ICD-10-CM"):
            seg = seg[len("ICD-10-CM") :].strip()
        if not seg or seg.startswith(NON_ICD_PREFIXES) or seg.startswith("MEDIS"):
            continue
        for m in EXCL.finditer(seg):
            exc += [t for t in _icd_list(m.group(1)) if t not in exc]
        inc += [t for t in _icd_list(EXCL.sub(" ", seg)) if t not in inc and t not in exc]
    return inc, exc


def icd_tokens(codes: str) -> list[str]:
    """Every ICD-10-CM code a `codes` cell names, included then excluded (each must exist)."""
    inc, exc = icd_split(codes)
    return inc + [t for t in exc if t not in inc]


LOINC_TOKEN = re.compile(r"(?<![\w.-])(\d{3,7}-\d)(?![\w.-])")
ATC_AFTER = re.compile(r"\bATC\s+([A-Z0-9/ ,]+)")
ATC_TOKEN = re.compile(r"\b([A-V]\d{2}(?:[A-Z]{1,2}(?:\d{2})?)?)\b")
CDISC_CELL_TOKEN = re.compile(r"\b([A-Z][A-Z0-9]{3,})\b")
CDISC_TEXT_TOKEN = re.compile(r"\b([A-Z][A-Z0-9]*\d[A-Z0-9]*TC)\b")
CDISC_WORDS = {"CDISC", "RECIST", "RSCAT"}  # words in the `cdisc_qrs` cell that are not codelist names
# code shapes found without a keyword: a LOINC code with a valid check digit, an ATC code of level 3 or deeper
ATC_SHAPE = re.compile(r"(?<![\w.])([A-V]\d{2}[A-Z](?:[A-Z](?:\d{2})?)?)(?![\w.])")
ICDO_TOKEN = re.compile(r"\b(C\d{2}(?:\.\d)?)\b")


def loinc_check_digit_ok(code: str) -> bool:
    """LOINC's mod-10 check digit (the Luhn scheme over the digits before the hyphen)."""
    body, _, check = code.partition("-")
    if not body.isdigit() or not check.isdigit() or len(check) != 1:
        return False
    total = 0
    for pos, ch in enumerate(reversed(body)):
        d = int(ch) * (2 if pos % 2 == 0 else 1)
        total += d // 10 + d % 10
    return (10 - total % 10) % 10 == int(check)


def loinc_tokens(text: str) -> list[str]:
    """LOINC codes in a cell: every LOINC shape when the cell says LOINC (``98979-8/62238-1`` gives both, a typo
    included), and otherwise every shape whose check digit is right (``eye 9267-6; verbal 9270-0``)."""
    found = LOINC_TOKEN.findall(text)
    if "LOINC" not in text:
        found = [t for t in found if loinc_check_digit_ok(t)]
    return list(dict.fromkeys(found))


def atc_tokens(text: str) -> list[str]:
    """ATC codes: any written after the word ATC (``ATC C02/C03`` gives both), and any of level 3 or deeper in a
    cell about drug exposure (``no M05B/G03XC exposure``)."""
    out: list[str] = []
    for group in ATC_AFTER.findall(text):
        for tok in ATC_TOKEN.findall(group):
            if tok not in out:
                out.append(tok)
    if "ATC" in text or "exposure" in text:  # a drug context; KRAS G12C is not an ATC code
        for tok in ATC_SHAPE.findall(text):
            if tok not in out:
                out.append(tok)
    return out


def cdisc_tokens(cell: str) -> list[str]:
    """CDISC CT codelist submission values named in an item's `cdisc_qrs` cell."""
    return [t for t in dict.fromkeys(CDISC_CELL_TOKEN.findall(cell)) if t not in CDISC_WORDS]


def split_list(cell: str) -> list[str]:
    return [p.strip() for p in cell.split(";") if p.strip()]


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def render_csv(columns: list[str], rows: Iterable[dict[str, str]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: row.get(c, "") for c in columns})
    return buf.getvalue()


# ---------------------------------------------------------------- evidence


@dataclass
class Evidence:
    """What ``fetch`` read from the public sources, keyed for lookups."""

    date: str
    loinc_codes: dict[str, str] = field(default_factory=dict)  # code -> long common name
    loinc_searches: dict[str, dict[str, Any]] = field(default_factory=dict)  # term -> {total, hits}
    jlac10: dict[str, dict[str, str]] = field(default_factory=dict)  # 17-digit code -> {name, unit, method, group}
    cohorts: dict[str, dict[str, Any]] = field(default_factory=dict)  # id -> {name, status, entry_concepts}
    icd10cm_prefixes: dict[str, dict[str, Any]] = field(default_factory=dict)  # prefix -> {n, sample}
    icd10cm_names: dict[str, list[str]] = field(default_factory=dict)  # OMOP concept id -> ICD-10-CM codes by title
    atc: dict[str, str] = field(default_factory=dict)  # ATC code -> WHOCC name
    cdisc: dict[str, dict[str, str]] = field(default_factory=dict)  # submission value -> {nci_code, name}
    sources: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> Evidence:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            date=data["date"],
            loinc_codes=data["loinc_codes"],
            loinc_searches=data["loinc_searches"],
            jlac10=data["jlac10"],
            cohorts=data["cohorts"],
            icd10cm_prefixes=data["icd10cm_prefixes"],
            icd10cm_names=data["icd10cm_names"],
            atc=data.get("atc", {}),
            cdisc=data.get("cdisc", {}),
            sources=data.get("sources", {}),
        )

    def dump(self) -> str:
        data = {
            "date": self.date,
            "sources": self.sources,
            "loinc_codes": dict(sorted(self.loinc_codes.items())),
            "loinc_searches": dict(sorted(self.loinc_searches.items())),
            "jlac10": dict(sorted(self.jlac10.items())),
            "cohorts": {k: _nameless_cohort(v) for k, v in sorted(self.cohorts.items(), key=lambda kv: int(kv[0]))},
            "icd10cm_prefixes": dict(sorted(self.icd10cm_prefixes.items())),
            "icd10cm_names": dict(sorted(self.icd10cm_names.items())),
            "atc": dict(sorted(self.atc.items())),
            "cdisc": dict(sorted(self.cdisc.items())),
        }
        return json.dumps(data, ensure_ascii=False, indent=1) + "\n"

    def icd_exists(self, prefix: str) -> bool:
        return int(self.icd10cm_prefixes.get(prefix, {}).get("n", 0)) > 0


def nameless(concepts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The concepts without the names of NAMELESS_VOCABULARIES: only the id, vocabulary and flags stay."""
    return [
        {k: v for k, v in c.items() if k != "name"} if c.get("vocabulary") in NAMELESS_VOCABULARIES else c
        for c in concepts
    ]


def _nameless_cohort(rec: dict[str, Any]) -> dict[str, Any]:
    if "entry_concepts" not in rec:
        return rec
    return {**rec, "entry_concepts": nameless(rec["entry_concepts"])}


def concept_label(c: dict[str, Any]) -> str:
    named = f"{c['name']} " if c.get("name") else ""
    return f"{named}[{c['vocabulary']}, OMOP concept {c['concept_id']}]"


# ---------------------------------------------------------------- curated inputs


@dataclass
class Curated:
    loinc: dict[str, dict[str, str]]
    jlac10: dict[str, dict[str, str]]
    phenotypes: dict[str, dict[str, str]]

    @classmethod
    def load(cls, folder: Path) -> Curated:
        def keyed(name: str, key: str) -> dict[str, dict[str, str]]:
            out: dict[str, dict[str, str]] = {}
            for row in read_csv(folder / name)[1]:
                if row[key] in out:
                    raise CatalogueError(f"{name}: {row[key]} twice")
                out[row[key]] = row
            return out

        return cls(
            loinc=keyed("loinc_decisions.csv", "item_id"),
            jlac10=keyed("jlac10_map.csv", "item_id"),
            phenotypes=keyed("phenotype_icd10cm_map.csv", "phenotype_id"),
        )


# ---------------------------------------------------------------- every code the catalogue names


@dataclass(frozen=True)
class CodeRef:
    """One code named somewhere in the catalogue. `use` says what the code is for:

    ``code``       a code column or a phenotype's `codes` cell: a rule may use it
    ``exclude``    a code a phenotype's `codes` cell excludes (``excl. M06.1``): never a reason to include
    ``mapping``    a hand-made ICD-10-CM set in phenotype_icd10cm.csv (mapping_verified = no)
    ``reference``  a CDISC CT codelist: names a questionnaire's test codes, not a patient fact
    ``text``       named in a note, a source cell or a score file: never read by a rule
    """

    file: str
    row: str
    fld: str
    system: str
    code: str
    use: str


ITEM_CODE_FIELDS = {"id", "loinc", "omop_concept_id", "cdisc_qrs", "jlac10", "verified", *ITEM_EXTRA} - {
    "verified_note"
}


def phenotype_code_refs(row: dict[str, str]) -> list[CodeRef]:
    """The codes of a phenotype's `codes` cell, by vocabulary. MEDIS names, `local items` and `procedure codes HD/PD`
    are names, not codes, and are left out."""
    refs: list[CodeRef] = []

    def add(system: str, code: str, use: str = "code") -> None:
        refs.append(CodeRef("phenotypes.csv", row["id"], "codes", system, code, use))

    for segment in row.get("codes", "").split(";"):
        seg = segment.strip()
        if seg.startswith("LOINC"):
            for code in LOINC_TOKEN.findall(seg):
                add("LOINC", code)
        elif seg.startswith("ATC"):
            for code in atc_tokens(seg):
                add("ATC", code)
        elif seg.startswith("ICD-O"):
            for code in ICDO_TOKEN.findall(seg):
                add("ICD-O-3", code)
        elif seg and not seg.startswith(NON_ICD_PREFIXES) and not seg.startswith("MEDIS"):
            inc, exc = icd_split(seg)
            for code in inc:
                add("ICD-10-CM", code)
            for code in exc:
                add("ICD-10-CM", code, "exclude")
    for fld in ("definition", "notes"):
        for code in loinc_tokens(row.get(fld, "")):
            refs.append(CodeRef("phenotypes.csv", row["id"], fld, "LOINC", code, "text"))
        for code in atc_tokens(row.get(fld, "")):
            refs.append(CodeRef("phenotypes.csv", row["id"], fld, "ATC", code, "text"))
    return refs


def scan_refs(
    items: list[dict[str, str]],
    phenos: list[dict[str, str]],
    icd_rows: list[dict[str, str]],
    texts: dict[str, list[tuple[str, str]]],
) -> list[CodeRef]:
    """Every code the catalogue names. `texts` maps a file name to (row, line) pairs (score files, specialties)."""
    refs: list[CodeRef] = []
    for r in items:
        rid = r["id"]
        primary = r.get("loinc", "")
        if primary and primary != "local":
            refs.append(CodeRef("items.csv", rid, "loinc", "LOINC", primary, "code"))
        for code in split_list(r.get("jlac10", "")):
            refs.append(CodeRef("items.csv", rid, "jlac10", "JLAC10", code, "code"))
        for code in cdisc_tokens(r.get("cdisc_qrs", "")):
            refs.append(CodeRef("items.csv", rid, "cdisc_qrs", "CDISC CT", code, "reference"))
        for fld, cell in r.items():
            if fld in ITEM_CODE_FIELDS or not cell:
                continue
            for code in loinc_tokens(cell):
                if code != primary:
                    refs.append(CodeRef("items.csv", rid, fld, "LOINC", code, "text"))
            for code in atc_tokens(cell):
                refs.append(CodeRef("items.csv", rid, fld, "ATC", code, "text"))
    for r in phenos:
        refs.extend(phenotype_code_refs(r))
    for r in icd_rows:
        for fld in ("icd10cm_include", "icd10cm_exclude"):
            for code in split_list(r.get(fld, "")):
                refs.append(CodeRef("phenotype_icd10cm.csv", r["phenotype_id"], fld, "ICD-10-CM", code, "mapping"))
    for name, lines in texts.items():
        for row, line in lines:
            for code in loinc_tokens(line):
                refs.append(CodeRef(name, row, "text", "LOINC", code, "text"))
            for code in atc_tokens(line):
                refs.append(CodeRef(name, row, "text", "ATC", code, "text"))
            for code in dict.fromkeys(CDISC_TEXT_TOKEN.findall(line)):
                refs.append(CodeRef(name, row, "text", "CDISC CT", code, "text"))
    return list(dict.fromkeys(refs))


def text_sources(catalogue: Path) -> dict[str, list[tuple[str, str]]]:
    """The free-text files that may name codes: the score files (by line) and specialties.csv (by cell)."""
    out: dict[str, list[tuple[str, str]]] = {}
    for path in sorted((catalogue / "scores").glob("*.yaml")):
        lines = path.read_text(encoding="utf-8").splitlines()
        out[f"scores/{path.name}"] = [(f"line {n}", line) for n, line in enumerate(lines, 1)]
    spec = catalogue / "specialties.csv"
    if spec.exists():
        cells = [(r["specialty_id"], v) for r in read_csv(spec)[1] for v in r.values() if v]
        out["specialties.csv"] = cells
    return out


def check_ref(ref: CodeRef, ev: Evidence) -> tuple[bool, str, str, str]:
    """(verified, the name the source gives, the source, a note) for one code."""
    if ref.system == "LOINC":
        if not loinc_check_digit_ok(ref.code):
            return False, "", "", "the LOINC check digit is wrong"
        name = ev.loinc_codes.get(ref.code)
        if name is None:
            return False, "", SRC_LOINC, "not found in the source"
        return True, name, SRC_LOINC, ""
    if ref.system == "ICD-10-CM":
        hit = ev.icd10cm_prefixes.get(ref.code)
        if hit is None:
            return False, "", SRC_ICD, "not looked up; run fetch"
        if not ev.icd_exists(ref.code):
            return False, "", SRC_ICD, "no ICD-10-CM code under it (a WHO ICD-10 code, or none)"
        sample = hit.get("sample") or []
        first = f"{sample[0][0]} {sample[0][1]}" if sample else ""
        return True, f"{hit['n']} codes{'; first ' + first if first else ''}", SRC_ICD, ""
    if ref.system == "JLAC10":
        row = ev.jlac10.get(ref.code)
        return (True, row["name"], SRC_MHLW, "") if row else (False, "", SRC_MHLW, "not in the MHLW table")
    if ref.system == "ATC":
        name = ev.atc.get(ref.code)
        return (True, name, SRC_ATC, "") if name else (False, "", SRC_ATC, "not found in the source")
    if ref.system == "CDISC CT":
        hit = ev.cdisc.get(ref.code)
        if not hit:
            return False, "", SRC_CDISC, "not found in the source"
        return True, f"{hit['nci_code']} {hit['name']}", SRC_CDISC, ""
    return False, "", "", f"no public {ref.system} source was read"


def build_codes(refs: list[CodeRef], ev: Evidence, items: list[dict[str, str]], cur: Curated) -> list[dict[str, str]]:
    """codes_checked.csv: one row per code and place. `may_exclude` is yes only for a verified code in an item's
    `loinc` or `jlac10` column that a person read against the item and found to fit exactly. Everything else is no:
    unreviewed and partial fits, phenotype codes (no per-code fit review yet), excluded codes, mappings, CDISC
    codelists and text mentions. When unsure, no: unknown never excludes."""
    by_item = {r["id"]: r for r in items}
    out = []
    for ref in refs:
        ok, name, source, note = check_ref(ref, ev)
        may = False
        if ok and ref.file == "items.csv" and ref.fld == "loinc":
            fit = by_item[ref.row].get("code_fit", "")
            may = fit == "exact"
            note = "" if may else f"code_fit {fit}: not read against the item, or only part of it"
        elif ok and ref.file == "items.csv" and ref.fld == "jlac10":
            may = cur.jlac10[ref.row]["fit"] == "exact"
            note = "" if may else "the MHLW item covers only part of the catalogue item"
        elif ok and ref.use == "code":
            note = "found; its fit to this phenotype is not reviewed"
        elif ok:
            note = {
                "exclude": "excluded by the phenotype",
                "mapping": "the code exists; the mapping to the cohort is not verified",
                "reference": "a CDISC codelist: names the test codes, not a patient fact",
                "text": "named in text only",
            }[ref.use]
        out.append(
            {
                "file": ref.file,
                "row": ref.row,
                "field": ref.fld,
                "system": ref.system,
                "code": ref.code,
                "use": ref.use,
                "verified": "yes" if ok else "no",
                "name_in_source": name,
                "source": source,
                "verified_date": ev.date if source else "",
                "may_exclude": "yes" if may else "no",
                "note": note,
            }
        )
    return out


# ---------------------------------------------------------------- build: items


# a licence note that only says the item had no code; it goes when a LOINC code is adopted
LOCAL_ONLY_NOTE = re.compile(r"local( concept)?( until mapped)?")


def with_loinc_notice(notes: str) -> str:
    """The item's licence notes with the LOINC notice appended once. Other notes (an instrument's copyright, a
    staging licence) are kept: adopting a LOINC code adds a licence, it never removes one."""
    parts = [p.strip() for p in notes.split("; ") if p.strip()]
    parts = [p for p in parts if not LOCAL_ONLY_NOTE.fullmatch(p)]
    if LOINC_NOTICE not in parts:
        parts.append(LOINC_NOTICE)
    return "; ".join(parts)


def _searches_note(terms: list[str], ev: Evidence) -> str:
    parts = []
    for t in terms:
        hit = ev.loinc_searches.get(t)
        parts.append(f"'{t}' ({hit['total']} hits)" if hit else f"'{t}' (not run)")
    return "NLM LOINC search " + ", ".join(parts)


def build_items(rows: list[dict[str, str]], cur: Curated, ev: Evidence) -> list[dict[str, str]]:
    """The items with adopted LOINC codes and the verification columns filled. Raises on unsupported codes."""
    ids = {r["id"] for r in rows}
    for item_id in list(cur.loinc) + list(cur.jlac10):
        if item_id not in ids:
            raise CatalogueError(f"curated row for unknown item {item_id}")
    retired = {d["retired_local_id"] for d in cur.loinc.values() if d.get("retired_local_id")}
    out: list[dict[str, str]] = []
    for src in rows:
        row = dict(src)
        dec = cur.loinc.get(row["id"])
        action = dec["action"] if dec else ""
        if dec and action not in ACTIONS:
            raise CatalogueError(f"{row['id']}: unknown action {action!r}")
        own_retired = dec.get("retired_local_id", "") if dec else ""
        if row.get("omop_concept_id") in retired and row["omop_concept_id"] != own_retired:
            raise CatalogueError(f"{row['id']}: reuses retired local id {row['omop_concept_id']}")
        if action in ADOPT:
            code = dec["loinc"] if dec else ""
            if code not in ev.loinc_codes:
                raise CatalogueError(f"{row['id']}: adopted LOINC {code} is not in the evidence")
            if row["loinc"] != code:
                row["source"] = f"LOINC {code}; was local: {row['source']}" if row["source"] else f"LOINC {code}"
                row["loinc"] = code
            row["licence_notes"] = with_loinc_notice(row.get("licence_notes", ""))
            if row["omop_concept_id"] and row["omop_concept_id"] != (dec or {}).get("retired_local_id"):
                raise CatalogueError(f"{row['id']}: record local id {row['omop_concept_id']} as retired_local_id")
            row["omop_concept_id"] = ""
        terms = split_list(dec.get("search_terms", "")) if dec else []
        note = dec.get("note", "") if dec else ""
        code = row["loinc"]
        if code and code != "local":
            name = ev.loinc_codes.get(code)
            if name is None:
                row.update(verified="no", code_fit="", verified_source="", verified_date="")
                row["verified_note"] = f"LOINC {code} not found in {SRC_LOINC}; check by hand"
            else:
                row.update(verified="yes", verified_source=f"{SRC_LOINC}: {code} '{name}'", verified_date=ev.date)
                row["code_fit"] = FIT.get(action, "unreviewed")
                row["verified_note"] = note
                if action in ADOPT:
                    row["verified_note"] = "; ".join(p for p in (_searches_note(terms, ev), note) if p)
        else:
            if action in ("fit_partial", "fit_exact"):
                raise CatalogueError(f"{row['id']}: {action} on a local item")
            auto = search_term(row["name_en"])
            hit = ev.loinc_searches.get(auto)
            if hit is None:
                raise CatalogueError(f"{row['id']}: no evidence for the name search {auto!r}; run fetch")
            if int(hit["total"]) > 0 and not dec:
                raise CatalogueError(f"{row['id']}: the name search found LOINC terms; review them in loinc_decisions")
            all_terms = [auto, *[t for t in terms if t != auto]]
            verdict = "no LOINC term adopted"
            row.update(verified="no", code_fit="none", verified_source=SRC_LOINC, verified_date=ev.date)
            row["verified_note"] = "; ".join(p for p in (f"{_searches_note(all_terms, ev)}: {verdict}", note) if p)
        _fill_jlac10(row, cur, ev)
        row["may_exclude"] = "yes" if row["verified"] == "yes" and row["code_fit"] == "exact" else "no"
        out.append(row)
    return out


def _fill_jlac10(row: dict[str, str], cur: Curated, ev: Evidence) -> None:
    jl = cur.jlac10.get(row["id"])
    row["jlac10"], row["jlac10_source"] = "", ""
    if not jl:
        return
    codes = split_list(jl["jlac10"])
    fit = jl.get("fit", "")
    if codes and fit not in JLAC10_FITS:
        raise CatalogueError(f"{row['id']}: jlac10_map fit must be exact or partial, not {fit!r}")
    if not codes and fit:
        raise CatalogueError(f"{row['id']}: jlac10_map fit without a code")
    for code in codes:
        if code not in ev.jlac10:
            raise CatalogueError(f"{row['id']}: JLAC10 {code} is not in the MHLW evidence")
        if not re.fullmatch(r"[0-9][0-9A-Z]{16}", code):
            raise CatalogueError(f"{row['id']}: {code} is not a 17-character JLAC10 code")
    unit_note = _jlac10_unit(row, jl, codes, ev) if codes else ""
    if codes:
        names = sorted({ev.jlac10[c]["name"] for c in codes})
        row["jlac10"] = ";".join(codes)
        row["jlac10_source"] = f"{SRC_MHLW} '{' / '.join(names)}', checked {ev.date}"
        if unit_note:
            row["jlac10_source"] += f"; {unit_note}"
    if jl.get("note"):
        row["jlac10_source"] = "; ".join(p for p in (row["jlac10_source"], jl["note"]) if p)


def _jlac10_unit(row: dict[str, str], jl: dict[str, str], codes: list[str], ev: Evidence) -> str:
    """Check the MHLW unit against the item's unit. When they differ, jlac10_map must give `unit_factor`
    (value in the item's unit = value in the MHLW unit x factor), or the build fails: a JLAC10 value read in the
    wrong unit could exclude a patient. Returns the note for `jlac10_source`."""
    item_id = row["id"]
    raw = {ev.jlac10[c]["unit"] for c in codes}
    if len(raw) > 1:
        raise CatalogueError(f"{item_id}: the JLAC10 codes have different MHLW units {sorted(raw)}; map them apart")
    mhlw = raw.pop()
    if mhlw not in MHLW_UNIT_UCUM:
        raise CatalogueError(f"{item_id}: MHLW unit {mhlw!r} has no UCUM form in MHLW_UNIT_UCUM")
    given = jl.get("source_unit_ucum", "")
    if given != MHLW_UNIT_UCUM[mhlw]:
        raise CatalogueError(
            f"{item_id}: jlac10_map source_unit_ucum {given!r} is not the MHLW unit {mhlw!r} ({MHLW_UNIT_UCUM[mhlw]!r})"
        )
    target = row.get("unit_ucum", "")
    factor = jl.get("unit_factor", "")
    if not given and target:
        if jl.get("fit") == "exact" or factor:
            raise CatalogueError(
                f"{item_id}: the MHLW table gives no unit, so the code cannot fit {target!r} exactly; "
                "use fit partial and no unit_factor"
            )
        return f"the MHLW table gives no unit; not checked against {target}"
    if given == target:
        if factor not in ("", "1"):
            raise CatalogueError(f"{item_id}: unit_factor {factor} although the units are the same ({given!r})")
        return ""
    if not factor:
        raise CatalogueError(
            f"{item_id}: MHLW unit {given!r} differs from the item's unit {target!r} and jlac10_map gives no "
            "unit_factor"
        )
    try:
        value = float(factor)
    except ValueError:
        raise CatalogueError(f"{item_id}: unit_factor {factor!r} is not a number") from None
    if not value > 0:
        raise CatalogueError(f"{item_id}: unit_factor {factor!r} must be positive")
    return f"MHLW unit {mhlw} ({given}); x{factor} to {target}"


# ---------------------------------------------------------------- build: phenotypes


def _cohort_ids(cell: str) -> list[str]:
    return [] if cell.strip() == "local" else split_list(cell)


def build_phenotypes(rows: list[dict[str, str]], cur: Curated, ev: Evidence) -> list[dict[str, str]]:
    """phenotypes.csv with verification columns: cohort ids exist in the library and ICD-10-CM codes exist."""
    out = []
    for src in rows:
        row = dict(src)
        problems: list[str] = []
        status: list[str] = []
        ids = _cohort_ids(row["ohdsi_pl_cohort_ids"])
        for cid in ids:
            co = ev.cohorts.get(cid)
            if co is None:
                problems.append(f"cohort {cid} not in {SRC_OHDSI}")
            else:
                status.append(f"{cid} {co['status']}")
        tokens = icd_tokens(row["codes"])
        missing = [t for t in tokens if not ev.icd_exists(t)]
        if missing:
            problems.append(
                "not in ICD-10-CM (WHO ICD-10 only, or a range category ICD-10-CM lacks): " + ", ".join(missing)
            )
        others = [ref for ref in phenotype_code_refs(row) if ref.use == "code" and ref.system != "ICD-10-CM"]
        unchecked = []
        for ref in others:
            ok, _name, _src, why = check_ref(ref, ev)
            if not ok:
                unchecked.append(f"{ref.system} {ref.code} ({why})")
        if unchecked:
            problems.append("not verified: " + ", ".join(unchecked))
        if not tokens and not others:
            problems.append("no code in `codes`")
        parts = [f"{len(tokens) - len(missing)} of {len(tokens)} ICD-10-CM codes exist"]
        if others:
            parts.append(f"{len(others) - len(unchecked)} of {len(others)} other codes found in their sources")
        if status:
            parts.append("library status " + ", ".join(status))
        parts += problems
        tr = cur.phenotypes.get(row["id"])
        if tr:
            parts.append("ICD-10-CM translation in phenotype_icd10cm.csv" + (f" ({tr['note']})" if tr["note"] else ""))
        row["verified"] = "no" if problems else "yes"
        row["may_exclude"] = "no"  # no per-code fit review of phenotype codes yet: unknown never excludes
        systems = {ref.system for ref in others}
        extra_src = [src for system, src in (("LOINC", SRC_LOINC), ("ATC", SRC_ATC)) if system in systems]
        row["verified_source"] = "; ".join([SRC_ICD] + extra_src + ([SRC_OHDSI] if ids else []))
        row["verified_date"] = ev.date
        row["verified_note"] = "; ".join(parts)
        out.append(row)
    for pid in cur.phenotypes:
        if pid not in {r["id"] for r in rows}:
            raise CatalogueError(f"phenotype_icd10cm_map.csv: unknown phenotype {pid}")
    return out


def build_icd10cm(rows: list[dict[str, str]], cur: Curated, ev: Evidence) -> list[dict[str, str]]:
    """One row per OHDSI-linked phenotype: the ICD-10-CM concept set that stands in for the SNOMED one."""
    by_id = {r["id"]: r for r in rows}
    linked = [r["id"] for r in rows if _cohort_ids(r["ohdsi_pl_cohort_ids"])]
    missing = [p for p in linked if p not in cur.phenotypes]
    if missing:
        raise CatalogueError("no ICD-10-CM translation for: " + ", ".join(missing))
    out = []
    for pid in linked:
        m = cur.phenotypes[pid]
        cid = m["ohdsi_cohort_id"]
        if cid not in _cohort_ids(by_id[pid]["ohdsi_pl_cohort_ids"]):
            raise CatalogueError(f"{pid}: cohort {cid} is not one of the phenotype's cohorts")
        co = ev.cohorts.get(cid)
        if co is None:
            raise CatalogueError(f"{pid}: cohort {cid} not in the evidence; run fetch")
        include, exclude = split_list(m["icd10cm_include"]), split_list(m["icd10cm_exclude"])
        if not include:
            raise CatalogueError(f"{pid}: empty ICD-10-CM include list")
        bad = [t for t in include + exclude if not ev.icd_exists(t)]
        n_codes = sum(int(ev.icd10cm_prefixes.get(t, {}).get("n", 0)) for t in include)
        concepts = co["entry_concepts"]
        names = _name_checked(concepts)
        found = inside = 0
        outside: list[str] = []
        for cid in names:
            hits = ev.icd10cm_names.get(cid, [])
            if not hits:
                continue
            found += 1
            if any(_in_set(h, include, exclude) for h in hits):
                inside += 1
            else:
                outside.extend(f"{h} (OMOP concept {cid})" for h in hits[:2])
        total = int(co.get("entry_concept_count", len(concepts)))
        shown = "; ".join(concept_label(c) for c in concepts[:6])
        if total > 6:
            shown += f"; +{total - 6} more"
        out.append(
            {
                "phenotype_id": pid,
                "ohdsi_cohort_id": cid,
                "cohort_name": co["name"],
                "library_status": co["status"],
                "entry_concepts": shown,
                "icd10cm_include": ";".join(include),
                "icd10cm_exclude": ";".join(exclude),
                "icd10cm_billable_codes": str(n_codes),
                "name_check": f"{found} of {len(names)} SNOMED entry concept names matched ICD-10-CM titles; "
                f"{inside} of those inside the include set",
                "name_hits_outside": "; ".join(outside[:6]),
                "derivation": "by hand from the cohort's entry concept names and the ICD-10-CM tabular list "
                "(code families checked in NLM icd10cm); not from the OMOP Maps-to table (Athena refused, HTTP 403)",
                "codes_verified": "no" if bad else "yes",
                "mapping_verified": "no",
                "verified_source": f"{SRC_OHDSI} cohort {cid}; {SRC_ICD}",
                "verified_date": ev.date,
                "may_exclude": "no",
                "note": "; ".join(p for p in (("unknown codes: " + ", ".join(bad)) if bad else "", m["note"]) if p),
            }
        )
    return out


def _name_checked(concepts: list[dict[str, Any]]) -> list[str]:
    """The OMOP ids of the SNOMED entry concepts whose names were searched in the ICD-10-CM titles."""
    ids = [str(c["concept_id"]) for c in concepts if c.get("vocabulary") == "SNOMED" and not c.get("excluded")]
    return list(dict.fromkeys(ids))[:MAX_NAME_CHECKS]


def _in_set(code: str, include: list[str], exclude: list[str]) -> bool:
    return any(code.startswith(i) for i in include) and not any(code.startswith(x) for x in exclude)


# ---------------------------------------------------------------- build driver


@dataclass
class Paths:
    catalogue: Path

    @property
    def verification(self) -> Path:
        return self.catalogue / "verification"

    @property
    def evidence(self) -> Path:
        return self.verification / "evidence.json"


def build(paths: Paths) -> dict[Path, str]:
    """Every generated file and its new text (nothing is written here)."""
    ev = Evidence.load(paths.evidence)
    cur = Curated.load(paths.verification)
    item_cols, items = read_csv(paths.catalogue / "items.csv")
    ph_cols, phenos = read_csv(paths.catalogue / "phenotypes.csv")
    item_cols = item_cols + [c for c in ITEM_EXTRA if c not in item_cols]
    ph_cols = ph_cols + [c for c in PHENO_EXTRA if c not in ph_cols]
    built_items = build_items(items, cur, ev)
    built_phenos = build_phenotypes(phenos, cur, ev)
    icd_rows = build_icd10cm(phenos, cur, ev)
    refs = scan_refs(built_items, built_phenos, icd_rows, text_sources(paths.catalogue))
    return {
        paths.catalogue / "items.csv": render_csv(item_cols, built_items),
        paths.catalogue / "phenotypes.csv": render_csv(ph_cols, built_phenos),
        paths.catalogue / "phenotype_icd10cm.csv": render_csv(PH_OUT_COLUMNS, icd_rows),
        paths.catalogue / "codes_checked.csv": render_csv(CODES_COLUMNS, build_codes(refs, ev, built_items, cur)),
    }


def stale(outputs: dict[Path, str]) -> list[Path]:
    return [p for p, text in outputs.items() if not p.exists() or p.read_text(encoding="utf-8") != text]


# ---------------------------------------------------------------- fetch (network)


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "trialbox-catalogue-verify"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data: bytes = resp.read()
        return data


def _nlm(get: Getter, base: str, **params: str | int) -> list[Any]:
    url = base + "?" + urllib.parse.urlencode(params)
    data: list[Any] = json.loads(get(url))
    return data


def fetch_loinc_code(get: Getter, code: str) -> str | None:
    d = _nlm(get, NLM_LOINC, terms=code, sf="LOINC_NUM", df="LOINC_NUM,LONG_COMMON_NAME", maxList=5)
    return next((str(h[1]) for h in d[3] if h[0] == code), None)


def fetch_loinc_search(get: Getter, term: str) -> dict[str, Any]:
    d = _nlm(get, NLM_LOINC, terms=term, df="LOINC_NUM,LONG_COMMON_NAME", maxList=10)
    return {"total": int(d[0]), "hits": [[str(h[0]), str(h[1])] for h in d[3]]}


def fetch_icd_prefix(get: Getter, prefix: str) -> dict[str, Any]:
    d = _nlm(get, NLM_ICD10CM, terms=prefix, sf="code", df="code,name", maxList=500)
    codes = [h for h in d[3] if str(h[0]).startswith(prefix)]
    return {"n": len(codes), "sample": [[str(h[0]), str(h[1])] for h in codes[:2]]}


def fetch_icd_name(get: Getter, name: str) -> list[str]:
    words = " ".join(re.sub(r"[^\w\s-]", " ", name).split())
    d = _nlm(get, NLM_ICD10CM, terms=words, sf="code,name", df="code,name", maxList=5)
    return [str(h[0]) for h in d[3]]


def parse_mhlw_rows(rows: Iterable[tuple[Any, ...]]) -> dict[str, dict[str, str]]:
    """JLAC10 rows of the MHLW 付属2 sheet: group (col D), code (F), name (G), unit (L), method (T)."""
    out: dict[str, dict[str, str]] = {}
    for r in rows:
        if len(r) < 20 or not r[5]:
            continue
        code = str(r[5]).strip()
        if not re.fullmatch(r"[0-9][0-9A-Z]{16}", code):
            continue
        out[code] = {
            "group": str(r[3] or ""),
            "name": str(r[6] or ""),
            "unit": str(r[11] or ""),
            "method": str(r[19] or ""),
        }
    return out


def fetch_mhlw(get: Getter) -> dict[str, dict[str, str]]:
    import warnings

    import openpyxl

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mhlw.xlsx"
        path.write_bytes(get(MHLW_XLSX))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)  # the sheet's print area names itself
            wb = openpyxl.load_workbook(path, read_only=True)
        rows = list(wb.worksheets[0].iter_rows(values_only=True))
        wb.close()
    return parse_mhlw_rows(rows)


def fetch_atc(get: Getter, code: str) -> str | None:
    """The WHOCC name of an ATC code, from its index page; None when the page does not list the code."""
    page = get(f"{WHOCC_ATC}?code={urllib.parse.quote(code)}&showdescription=no").decode("utf-8", "replace")
    c = re.escape(code)
    pattern = rf'(?<![A-Z0-9]){c} <b><a href="\./\?code={c}&showdescription=\w+">([^<]+)</a>'
    m = re.search(pattern, page)
    return html.unescape(m.group(1)).strip() if m else None


def parse_cdisc(text: str, wanted: set[str]) -> dict[str, dict[str, str]]:
    """Codelist rows of the NCI EVS SDTM Terminology file (tab separated): code, codelist code (blank on a codelist
    row), extensible, codelist name, submission value."""
    out: dict[str, dict[str, str]] = {}
    for line in text.splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) < 5 or cols[1] or cols[4] not in wanted:
            continue
        out[cols[4]] = {"nci_code": cols[0], "name": cols[3]}
    return out


def entry_concepts(cohort: dict[str, Any]) -> list[dict[str, Any]]:
    """The concepts of the concept sets that a Circe cohort's primary criteria name (its entry events)."""
    ids: list[int] = []
    for crit in cohort.get("PrimaryCriteria", {}).get("CriteriaList", []):
        for body in crit.values():
            if isinstance(body, dict) and "CodesetId" in body and body["CodesetId"] not in ids:
                ids.append(int(body["CodesetId"]))
    out = []
    for cs in cohort.get("ConceptSets", []):
        if int(cs["id"]) not in ids:
            continue
        for it in cs.get("expression", {}).get("items", []):
            c = it["concept"]
            out.append(
                {
                    "set": cs["name"],
                    "concept_id": int(c["CONCEPT_ID"]),
                    "vocabulary": c.get("VOCABULARY_ID", ""),
                    "name": c.get("CONCEPT_NAME", ""),
                    "domain": c.get("DOMAIN_ID", ""),
                    "descendants": bool(it.get("includeDescendants")),
                    "excluded": bool(it.get("isExcluded")),
                }
            )
    return out


def fetch(paths: Paths, date: str, get: Getter = http_get, log: Callable[[str], None] = print) -> Evidence:
    """Read every public source the catalogue needs. Network only here."""
    cur = Curated.load(paths.verification)
    _, items = read_csv(paths.catalogue / "items.csv")
    _, phenos = read_csv(paths.catalogue / "phenotypes.csv")
    ev = Evidence(
        date=date,
        sources={
            "loinc": NLM_LOINC,
            "icd10cm": NLM_ICD10CM,
            "jlac10": f"{MHLW_XLSX} (linked from {MHLW_PAGE})",
            "ohdsi": f"{OHDSI_RAW}/Cohorts.csv and {OHDSI_RAW}/cohorts/<id>.json",
            "atc": f"{WHOCC_ATC}?code=<code>",
            "cdisc": NCI_CDISC_SDTM,
        },
    )
    maps = [dict(m, phenotype_id=pid) for pid, m in cur.phenotypes.items()]
    refs = scan_refs(items, phenos, maps, text_sources(paths.catalogue))
    codes = {r["loinc"] for r in items if r["loinc"] not in ("", "local")}
    codes |= {d["loinc"] for d in cur.loinc.values() if d["loinc"]}
    codes |= {r.code for r in refs if r.system == "LOINC" and loinc_check_digit_ok(r.code)}
    for d in cur.loinc.values():  # the notes reach items.csv `verified_note` at build
        codes |= {c for c in LOINC_TOKEN.findall(d.get("note", "")) if loinc_check_digit_ok(c)}
    for code in sorted(codes):
        name = fetch_loinc_code(get, code)
        if name is not None:
            ev.loinc_codes[code] = name
    terms = {search_term(r["name_en"]) for r in items if r["loinc"] == "local"}
    terms |= {search_term(r["name_en"]) for r in items if cur.loinc.get(r["id"], {}).get("action") == "adopt"}
    for d in cur.loinc.values():
        terms |= set(split_list(d["search_terms"]))
    for term in sorted(terms):
        ev.loinc_searches[term] = fetch_loinc_search(get, term)
    log(f"loinc: {len(ev.loinc_codes)} codes, {len(ev.loinc_searches)} searches")
    ev.jlac10 = fetch_mhlw(get)
    log(f"jlac10: {len(ev.jlac10)} MHLW rows")
    lib = {r["cohortId"]: r for r in csv.DictReader(io.StringIO(get(f"{OHDSI_RAW}/Cohorts.csv").decode("utf-8-sig")))}
    wanted = {cid for r in phenos for cid in _cohort_ids(r["ohdsi_pl_cohort_ids"])}
    primary = {m["ohdsi_cohort_id"] for m in cur.phenotypes.values()}
    full_concepts: dict[str, list[dict[str, Any]]] = {}
    for cid in sorted(wanted, key=int):
        if cid not in lib:
            continue
        rec: dict[str, Any] = {"name": lib[cid]["cohortName"], "status": lib[cid]["status"], "entry_concepts": []}
        if cid in primary:
            concepts = entry_concepts(json.loads(get(f"{OHDSI_RAW}/cohorts/{cid}.json")))
            full_concepts[cid] = concepts[:MAX_STORED_CONCEPTS]
            rec["entry_concepts"] = nameless(concepts[:MAX_STORED_CONCEPTS])
            rec["entry_concept_count"] = len(concepts)
        ev.cohorts[cid] = rec
    log(f"ohdsi: {len(ev.cohorts)} cohorts, {len(primary)} with entry concepts")
    prefixes = {t for r in phenos for t in icd_tokens(r["codes"])}
    for m in cur.phenotypes.values():
        prefixes |= set(split_list(m["icd10cm_include"])) | set(split_list(m["icd10cm_exclude"]))
    prefixes |= {r.code for r in refs if r.system == "ICD-10-CM"}
    for p in sorted(prefixes):
        ev.icd10cm_prefixes[p] = fetch_icd_prefix(get, p)
    by_name: dict[str, list[str]] = {}  # the name is searched, then dropped: only the concept id is kept
    for cid in primary:
        concepts = full_concepts.get(cid, [])
        checked = set(_name_checked(concepts))
        for c in concepts:
            if str(c["concept_id"]) in checked:
                ev.icd10cm_names[str(c["concept_id"])] = by_name.setdefault(c["name"], [])
    for name in sorted(by_name):
        by_name[name].extend(fetch_icd_name(get, name))
    log(f"icd10cm: {len(ev.icd10cm_prefixes)} code families, {len(ev.icd10cm_names)} concepts searched by name")
    for code in sorted({r.code for r in refs if r.system == "ATC"}):
        atc_name = fetch_atc(get, code)
        if atc_name is not None:
            ev.atc[code] = atc_name
    wanted_cdisc = {r.code for r in refs if r.system == "CDISC CT"}
    if wanted_cdisc:
        ev.cdisc = parse_cdisc(get(NCI_CDISC_SDTM).decode("utf-8-sig"), wanted_cdisc)
    log(f"atc: {len(ev.atc)} codes; cdisc: {len(ev.cdisc)} of {len(wanted_cdisc)} codelists")
    return ev


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="read the public sources (network) into evidence.json")
    f.add_argument("--date", default=dt.date.today().isoformat(), help="the day the sources are read (default today)")
    b = sub.add_parser("build", help="write the catalogue CSVs from evidence.json (offline)")
    b.add_argument("--check", action="store_true", help="only report CSVs that are out of date")
    for sp in (f, b):
        sp.add_argument("--catalogue", type=Path, default=CATALOGUE)
    args = ap.parse_args(argv)
    paths = Paths(args.catalogue)
    if args.cmd == "fetch":
        ev = fetch(paths, args.date)
        paths.evidence.write_text(ev.dump(), encoding="utf-8")
        return 0
    try:
        outputs = build(paths)
    except CatalogueError as exc:
        print(f"catalogue_verify: {exc}", file=sys.stderr)
        return 2
    if args.check:
        old = stale(outputs)
        for p in old:
            print(f"out of date: {p.relative_to(paths.catalogue.parent)}", file=sys.stderr)
        return 1 if old else 0
    for p, text in outputs.items():
        p.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
