"""Terminology mapping (SPEC §4.3.1): concept name -> explicit FHIR ValueSet.

Tables (``terminology/*.parquet``, built by ``tools/build_terminology.py`` from ``terminology/src/*.csv`` or a site's
official NHI / LOINC releases): ``icd10cm_tw``, ``nhi_drug`` (with ATC), ``atc``, ``loinc_tw`` (with
``component_of`` for panel members), ``nhi_order``, ``department``, ``synonyms``.

ICD-10-CM's blocks and Alphabetic Index (D-858; committed as US public domain, D-1029: ``icd10cm_blocks``,
``icd10cm_index``) resolve a condition's name to its families after every curated step; a newer release loaded on
the box at install (``terminology.installed``) is read in their place.

Full code lists (D-122): ``icd10cm_full`` holds every ICD-10-CM code (CMS/CDC 2026 release, public domain, built
from ``src/icd10cm_2026.csv.gz``). It answers code lookups and code-prefix groupers ("malignancy" = C0..C9 lists
every code in the families, so a valid code is never outside the list for want of a demo row); name matching and
the LLM candidates still read the curated ``icd10cm_tw`` only, so a grouper name is never shadowed by a header row.

Steps: exact display-name match -> synonym table (exact codes or code-prefix groups expanded against the tables) ->
the loaded synonym dictionary's curated entries (D-172; ``name_synonyms``) -> the model's synonyms -> the
dictionary's other entries (public translations, ambiguous abbreviations: method ``dictionary``, reviewed) ->
LLM ``concept_map`` over the top-20 lexical candidates, always flagged ``needs_review``. Output ValueSets carry only
``compose.include[].concept[]`` (no implicit expansions).
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

TERM_DIR = Path(__file__).resolve().parent
VS_BASE = "http://trialbox.local/fhir/ValueSet"
REVIEW_TAG_SYSTEM = "https://trialbox.local/fhir/CodeSystem/review-flag"
# D-113: a code-prefix grouper ("malignancy" = C0..C9) keeps its prefixes on the ValueSet, so a record coded inside
# the family but outside the enumerated concepts (a local or newer code the demo tables lack, e.g. C80.1) makes the
# criterion unknown instead of silently false. ``valueString`` is ``<system>|<prefix>``.
FAMILY_EXT = "https://trialbox.local/fhir/StructureDefinition/code-family"

SYSTEMS = {
    "icd10cm": "http://hl7.org/fhir/sid/icd-10-cm",
    "atc": "http://www.whocc.no/atc",
    "nhi_drug": "https://trialbox.local/fhir/CodeSystem/nhi-drug",
    "nhi_order": "https://trialbox.local/fhir/CodeSystem/nhi-order",
    "department": "https://trialbox.local/fhir/CodeSystem/department",
    "loinc": "http://loinc.org",
}
# T-610 (STD-042): a drug ValueSet may carry YJ ingredient stems beside its ATC codes, as concepts of this system
# (the first 7 characters of a YJ / 薬価基準 code: 薬効分類, ingredient, route). They are concepts, not an extension,
# so the ValueSet's content hash covers them. The engines match a medication whose YJ code starts with a listed stem
# exactly as one with a listed ATC code. A stem is added only for an ATC code (or an ATC family of a grouper) that
# the ingredient-to-ATC table gives it.
YJ_STEM = "urn:trialbox:jp:yj-stem7"  # as tb_common.refdata_jp.YJ_STEM
# which table answers which IR domain (exact-name step)
DOMAIN_TABLES = {
    "condition": ["icd10cm"],
    "medication": ["atc"],
    "observation": ["loinc"],
    "report": ["loinc"],
    "procedure": ["nhi_order"],
    "encounter": ["department"],
    "claim": ["nhi_drug"],
}
TABLE_FILES = {
    "icd10cm": "icd10cm_tw",
    "atc": "atc",
    "nhi_drug": "nhi_drug",
    "nhi_order": "nhi_order",
    "department": "department",
    "loinc": "loinc_tw",
}

FULL_FILES = {"icd10cm": "icd10cm_full"}

# TERM-1 (D-858): ICD-10-CM's blocks and Alphabetic Index (CMS, public domain), for a condition's name. Trial words
# and abbreviations the index does not spell, written as the index or a block names them, or as ``@`` and the
# ICD-10-CM categories they stand for (our own list)
ICD_WORDS: dict[str, str] = {
    "copd": "@J44",
    "chronic obstructive pulmonary disease": "@J44",
    "copd exacerbation": "@J44",
    "epilepsy": "@G40",
    "major depressive disorder": "@F32,F33",
    "chf": "heart failure",
    "congestive heart failure": "heart failure",
    "chronic heart failure": "heart failure",
    "mi": "myocardial infarction",
    "heart attack": "myocardial infarction",
    "ckd": "chronic kidney disease",
    "htn": "hypertensive diseases",
    "hypertension": "hypertensive diseases",
    "uncontrolled hypertension": "hypertensive diseases",
    "t2dm": "type 2 diabetes mellitus",
    "type ii diabetes": "type 2 diabetes mellitus",
    "type 2 diabetes": "type 2 diabetes mellitus",
    "t1dm": "type 1 diabetes mellitus",
    "type i diabetes": "type 1 diabetes mellitus",
    "type 1 diabetes": "type 1 diabetes mellitus",
    "cancer": "malignant neoplasms",
    "malignancy": "malignant neoplasms",
    "stroke": "cerebrovascular diseases",
    "cerebrovascular disease": "cerebrovascular diseases",
    "ischemic heart disease": "ischemic heart diseases",
    "ischaemic heart disease": "ischemic heart diseases",
    "coronary artery disease": "ischemic heart diseases",
    "cad": "ischemic heart diseases",
    "renal insufficiency": "chronic kidney disease",
    "renal disease": "chronic kidney disease",
    "chronic renal insufficiency": "chronic kidney disease",
    "hepatic disease": "diseases of liver",
    "liver disease": "diseases of liver",
    "seizure disorder": "@G40",
    "sle": "systemic lupus erythematosus",
    "lupus": "systemic lupus erythematosus",
    "substance abuse": "mental and behavioral disorders due to psychoactive substance use",
    "uterine fibroids": "leiomyoma of uterus",
    "fibroids": "leiomyoma of uterus",
}


def _icd_key(text: str) -> str:
    """A name as ICD-10-CM's lists are matched: lower case, no brackets or punctuation, a plain plural made singular."""
    s = re.sub(r"\([^)]*\)", " ", unicodedata.normalize("NFKC", text).lower())
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    words = [w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith(("ss", "us", "is")) else w for w in s.split()]
    return " ".join(words)


_ICD_WORDS = {_icd_key(k): v for k, v in ICD_WORDS.items()}


# D-314: WHO ICD-10 categories that ICD-10-CM does not have (Japan codes in WHO ICD-10 2013, through MEDIS 標準病名).
# A grouper whose ICD-10-CM family is one of the related categories (or a prefix of the WHO category: C9 holds C97)
# also stands for the WHO-only category, under the WHO URI: a record coded E14.9, I64 or F00.1 is then inside the
# family and outside the list, so the criterion is unknown (D-113), never a silent false. Category: the ICD-10-CM
# categories whose groupers it can belong to. A WHO code that ICD-10-CM also has (E11.9) is not here.
ICD10_WHO = "http://hl7.org/fhir/sid/icd-10"
WHO_ONLY_CATEGORIES: dict[str, tuple[str, ...]] = {
    "B24": ("B20",),  # unspecified HIV disease
    "C97": ("C80",),  # malignant neoplasms of independent (primary) multiple sites
    "E14": ("E08", "E09", "E10", "E11", "E13"),  # unspecified diabetes mellitus
    "F00": ("F01", "F02", "F03", "G30"),  # dementia in Alzheimer's disease
    "I64": ("I60", "I61", "I62", "I63"),  # stroke, not specified as haemorrhage or infarction
}


def who_only_families(families: set[tuple[str, str]] | list[tuple[str, str]]) -> set[tuple[str, str]]:
    """The WHO-only ICD-10 categories (``WHO_ONLY_CATEGORIES``) that a grouper's ICD-10-CM families stand for, as
    ``(WHO URI, category)`` families (D-314)."""
    out: set[tuple[str, str]] = set()
    for system, prefix in families:
        if system != SYSTEMS["icd10cm"]:
            continue
        for cat, related in WHO_ONLY_CATEGORIES.items():
            if prefix[:3] in related or cat.startswith(prefix):
                out.add((ICD10_WHO, cat))
    return out


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).strip().lower())


# TERM-2 (D-1113 to D-1116): the systems of the tables loaded at install (``terminology.installed``) that the shipped
# tables lack, beside ``SYSTEMS``; NHI's service and order codes are the shipped ``nhi_order`` system
LOADED_SYSTEMS = {**SYSTEMS, "icd10pcs": "http://www.cms.gov/Medicare/Coding/ICD10", "icd10_who": ICD10_WHO}
# the code system each table loaded at install serves (a site list names its own, row by row): the release stamp
# (TERM-2 follow-up) says which loaded table of which system a compile read
TABLE_SYSTEMS = {"icd10cm_blocks": "icd10cm", "icd10cm_index": "icd10cm", "atc_index": "atc",
                 "nhi_drug_list": "nhi_drug", "nhi_service_list": "nhi_order", "icd10pcs": "icd10pcs",
                 "loinc_table": "loinc", "icd10_who": "icd10_who"}  # fmt: skip


def table_system(table: str) -> str:
    """The code system a table loaded at install serves, as the release stamp and the refusals name it (one shape,
    TERM-2 follow-up and E-TERM-3, D-1048): its URI, or ``site`` for a site list (it names its own, row by row)."""
    return "site" if table.startswith("site_") else LOADED_SYSTEMS.get(TABLE_SYSTEMS.get(table, ""), "")


# which systems of a site list answer which IR domain (the site's lists win over every other table, D-1113)
SITE_DOMAIN_SYSTEMS: dict[str, tuple[str, ...]] = {
    "condition": ("icd10cm", "icd10_who"),
    "observation": ("loinc",),
    "report": ("loinc",),
    "medication": ("atc", "nhi_drug"),
    "procedure": ("icd10pcs", "nhi_order"),
    "encounter": ("department",),
    "claim": ("nhi_drug",),
}
# H-17 review (D-1127): an NHI service or order item is one billing item (inpatient or outpatient, with or without
# contrast), which may be narrower than the trial's word: an answer from it always goes to a person, as TERM-2's class B
# rule has it for an answer that may be narrower than the word asks for. The note of an answer from a table shipped in
# the image (not loaded at install) starts with this
_ALWAYS_REVIEWED = frozenset({"nhi_service_list"})
_SHIPPED_NOTE = "shipped NHI table"
# LOINC's specimens a lab named without one is read from (a component's codes in blood, serum or plasma)
_LOINC_BLOOD = frozenset({"bld", "blda", "bldc", "bldv", "plas", "ser", "ser/plas", "ser/plas/bld"})


def _name_keys(text: str) -> list[str]:
    """A name as the site's lists and the loaded tables are matched: as written (``norm``), and for a name in Latin
    letters only, also without punctuation and a plain plural (``Hepatitis-B (HBsAg)``: ``hepatitis b hbsag``). A name
    with any other letter (zh, ja) has only its written form: TERM-2 review, stripping it to its Latin letters made
    ``B型肝炎`` and ``B群鏈球菌感染`` one key. Brackets are kept as words, never dropped."""
    out = [norm(text)]
    t = unicodedata.normalize("NFKC", text).lower()
    if t.isascii():
        words = re.sub(r"[^a-z0-9]+", " ", t).split()
        k = " ".join(w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith(("ss", "us", "is")) else w
                     for w in words)  # fmt: skip
        if k and k not in out:
            out.append(k)
    return [x for x in out if x]


def _ingredient(text: str) -> str:
    """The ingredient of an NHI 成分 field, without strength or salt (``FLUPENTIXOL (2HCL) 3 MG``: flupentixol;
    ``VITAMIN B12 1 MG``: vitamin b12); empty for a combination."""
    t = norm(text)
    if re.search(r"[+&;]|\band\b", t):
        return ""
    t = re.split(r"\(|(?:^|\s)\d", t, maxsplit=1)[0]
    return " ".join(t.replace(",", " ").split())


# one entry of a loaded table's index: (domain, key, concepts, families, table, note)
_Entry = tuple[str, str, list["Concept"], frozenset[tuple[str, str]], str, str]


@dataclass
class _SiteHit:
    """A name in the site's lists: the first list that has it, its codes, whether that list gives it several codes,
    and the later lists that give it other codes (D-1113: then a person reviews it)."""

    table: str
    concepts: list[Concept]
    several: bool
    others: list[str]


@dataclass(frozen=True)
class Concept:
    system: str
    code: str
    display: str
    component_of: str | None = None


@dataclass
class MappingResult:
    name: str
    domain: str
    concepts: list[Concept]
    method: str  # exact | synonym | dictionary (D-172, always reviewed) | icd10cm | site | loaded | llm | none
    needs_review: bool
    notes: list[str] = field(default_factory=list)
    families: list[tuple[str, str]] = field(default_factory=list)  # (system, code prefix) of prefix groupers


ConceptMapLLM = Callable[[str, str, list[Concept]], tuple[list[tuple[str, str, float]], bool]]
# (name, domain) -> dictionary entries {canonical, curated, source_id}; tb_common.refdata.synonym_lookup (D-172)
NameSynonyms = Callable[[str, str], list[dict[str, Any]]]


FHIR_ID_MAX = 64  # FHIR R4 id: [A-Za-z0-9\-\.]{1,64}


def vs_resource_id(ruleset: str, vs_name: str) -> str:
    """FHIR id for a ValueSet: ``<RULESET>-<NAME>`` with underscores replaced (D-06).

    G1 of the P1b review (D-955): a public protocol's ruleset id (14) and a concept's name (up to 60) made ids of 75
    characters; the FHIR server refuses an id over 64 (HTTP 422), and all 12 such protocols failed. An id that would be
    longer, or hold a character an id may not, keeps its first 55 characters and ends in 8 hex characters of the whole
    name's hash: unique, stable, and every id that fitted before is unchanged."""
    rid = f"{ruleset}-{vs_name}".replace("_", "-")
    if len(rid) <= FHIR_ID_MAX and re.fullmatch(r"[A-Za-z0-9.\-]+", rid):
        return rid
    tag = hashlib.sha256(rid.encode("utf-8")).hexdigest()[:8]
    head = re.sub(r"[^A-Za-z0-9.\-]+", "-", rid)[: FHIR_ID_MAX - 9].rstrip("-.")
    return f"{head}-{tag}"


def vs_name_for(concept: str, unique: bool = False) -> str:
    """``VS_<SLUG>`` from the concept name. A name with non-ASCII letters (zh/ja, accents) would lose them in the slug
    and collide (every CJK name used to become ``VS_CONCEPT``), so it gets a stable hash suffix; ``unique`` forces the
    suffix (two different concepts with the same Latin slug)."""
    norm = unicodedata.normalize("NFKC", concept).strip()
    slug = re.sub(r"[^A-Za-z0-9]+", "_", norm).strip("_").upper()
    if unique or not slug or any(ch.isalpha() and not ch.isascii() for ch in norm):
        tag = hashlib.sha256(norm.lower().encode("utf-8")).hexdigest()[:8].upper()
        return f"VS_{slug[:47]}_{tag}" if slug else f"VS_C_{tag}"
    return f"VS_{slug}"[:60]


class Terminology:
    def __init__(self, directory: Path = TERM_DIR, name_synonyms: NameSynonyms | None = None,
                 installed: Path | None = None) -> None:  # fmt: skip
        self.dir = directory
        self.name_synonyms = name_synonyms
        # T-610: a Japanese site's ingredient-to-ATC table (stem -> {atc, ingredient}); drug ValueSets then carry
        # the YJ stems of their ATC codes. None (every other site, and the shipped rulesets): no stems
        self.ingredients: dict[str, dict[str, str]] | None = None
        self.rows: dict[str, list[dict[str, Any]]] = {}
        for key, fname in TABLE_FILES.items():
            path = directory / f"{fname}.parquet"
            self.rows[key] = pq.read_table(path, use_threads=False).to_pylist() if path.exists() else []
        # full code lists (D-122): code lookups and prefix groupers only, never name matching
        self.full: dict[str, list[dict[str, Any]]] = {}
        for key, fname in FULL_FILES.items():
            path = directory / f"{fname}.parquet"
            if path.exists():
                self.full[key] = pq.read_table(path, use_threads=False).to_pylist()
        # TERM-1 (D-858, D-1029): block name -> categories, index term -> code or the term it sees, display -> codes.
        # The blocks and the index ship beside the tables (US public domain, D-1029); a newer release loaded on the box
        # at install (``terminology.installed``) is read instead when its manifest line vouches for it. A refused
        # table is reported (``installed_problems``), never read, and the shipped one answers
        from criteria_compiler.terminology import installed as inst

        self.icd_blocks: dict[str, list[str]] = {}
        self.icd_index: dict[str, tuple[str, str]] = {}
        self.icd_display: dict[str, list[str]] = {}
        self.icd_sources: dict[str, str] = {}
        # E-TERM-3 (D-1048): each refused table by name: a refused site list blocks approval, every mapping says so
        self._icd_refused: list[dict[str, str]] = []
        self._term2_refused: list[dict[str, str]] = []
        # TERM-2 follow-up: each table loaded at install that these tables read, as the release stamp names it
        self.installed_read: dict[str, dict[str, str]] = {}
        where = installed if installed is not None else inst.installed_dir()
        self._where = where
        cats = sorted({str(r["code"]) for r in self.full.get("icd10cm", []) if len(str(r["code"])) == 3})
        for name in (inst.ICD_BLOCKS, inst.ICD_INDEX):
            try:
                rows = inst.read_table(where, name)
            except inst.TerminologyRefused as exc:
                self._icd_refused.append({"table": name, "system": table_system(name), "reason": str(exc)})
                rows = None
            if rows is not None:
                self.icd_sources[name] = str(inst.manifest(where)["tables"][name].get("version") or "installed")
                self._read_installed(inst, where, name, rows)
            else:
                # beside the tables, else the shipped ones (a box's vocabulary-built tables hold codes, not these)
                path = directory / f"{name}.parquet"
                path = path if path.exists() else TERM_DIR / f"{name}.parquet"
                rows = pq.read_table(path, use_threads=False).to_pylist() if path.exists() else []
                self.icd_sources[name] = "shipped" if rows else ""
            for r in rows:
                if name == inst.ICD_BLOCKS:
                    inside = [c for c in cats if str(r["first"]) <= c <= str(r["last"])]
                    self.icd_blocks.setdefault(_icd_key(str(r["name"])), inside)
                else:
                    self.icd_index.setdefault(_icd_key(str(r["term"])), (str(r["code"] or ""), str(r["see"] or "")))
        for r in self.full.get("icd10cm", []):
            self.icd_display.setdefault(_icd_key(str(r["display"])), []).append(str(r["code"]))
        syn = directory / "synonyms.parquet"
        self.synonyms = pq.read_table(syn, use_threads=False).to_pylist() if syn.exists() else []
        self._by_code: dict[tuple[str, str], Concept] = {}
        for key, rows in self.full.items():
            for r in rows:
                c = self._concept(key, r)
                self._by_code[(c.system, c.code)] = c
        for key, rows in self.rows.items():  # curated rows win (zh displays, demo spellings)
            for r in rows:
                c = self._concept(key, r)
                self._by_code[(c.system, c.code)] = c
        # TERM-2 (D-1113 to D-1116): the site's lists and the code systems loaded at install
        self.site_names: dict[str, dict[str, _SiteHit]] = {}  # system -> name -> the first list's answer
        self.site_codes: dict[tuple[str, str], Concept] = {}  # (system, local code) -> its standard concept
        self.loaded_names: dict[str, dict[str, tuple[list[Concept], frozenset[tuple[str, str]], bool, str]]] = {}
        self.loaded_sources: dict[str, str] = {}
        self._load_term2(where)

    @property
    def terminology_refused(self) -> list[dict[str, str]]:
        """E-TERM-3 (D-1048): each installed table refused at read, ``{"table", "reason"}`` (the reason names the
        table and why, never a row of it). A compile records them in its manifest (``terminology_refused``)."""
        return [*self._icd_refused, *self._term2_refused]

    @property
    def installed_problems(self) -> list[str]:
        """The refusals' sentences (``trialbox doctor``, ``tools.terminology_coverage``)."""
        return [r["reason"] for r in self.terminology_refused]

    def refused_site_lists(self) -> list[dict[str, str]]:
        """E-TERM-3 (D-1048): the refused tables that are site lists (D-1113: the primary source). While one is
        refused, approval is refused; a refused shipped or licensed table is recorded and stays a warning."""
        from criteria_compiler.terminology import installed as inst

        return [r for r in self.terminology_refused if r["table"].startswith(inst.SITE_PREFIX)]

    def refresh_installed(self) -> None:
        """E-TERM-3 (D-1048): read the site's lists and the TERM-2 tables again, as they are now on the box (a list
        loaded again or removed is seen without a restart). A compile and an approval call this first."""
        self._load_term2(self._where)

    _release: str | None = None

    @property
    def release(self) -> str:
        """The terminology release these tables are (D-301): the Parquet's own, or the vocabulary's when pinned by
        ``criteria_compiler.terminology.resolver``. A compiled ruleset records it in its manifest."""
        if self._release is None:
            from criteria_compiler.terminology import resolver

            self._release = resolver.parquet_release(self.dir)
        return self._release

    def pin(self, release: str) -> None:
        self._release = release

    def _concept(self, table: str, r: dict[str, Any]) -> Concept:
        if table == "nhi_drug":
            return Concept(SYSTEMS[table], r["nhi_code"], r["name"])
        if table == "loinc":
            return Concept(r.get("system") or SYSTEMS["loinc"], r["code"], r["display"], r.get("component_of") or None)
        return Concept(SYSTEMS[table], r["code"], r["display"])

    def concept(self, system: str, code: str) -> Concept | None:
        return self._by_code.get((system, code))

    def _names(self, table: str, r: dict[str, Any]) -> list[str]:
        keys = ("name", "name_zh") if table == "nhi_drug" else ("display", "display_zh")
        return [norm(str(r[k])) for k in keys if r.get(k)]

    def expand(self, table: str, code: str, match: str) -> list[Concept]:
        out = []
        for r in self.rows.get(table, []):
            c = self._concept(table, r)
            if (match == "exact" and c.code == code) or (match == "prefix" and c.code.startswith(code)):
                out.append(c)
        if match == "prefix" and table in self.full:  # every code of the family, curated display first (D-122)
            seen = {c.code for c in out}
            for r in self.full[table]:
                if r["code"].startswith(code) and r["code"] not in seen:
                    out.append(self._concept(table, r))
        return out

    def map(
        self, domain: str, name: str, synonyms: list[str] | None = None, llm: ConceptMapLLM | None = None
    ) -> MappingResult:
        """The concept's codes. E-TERM-3 (D-1048): while a site list is refused, every answer says it was not read."""
        res = self._map(domain, name, synonyms, llm)
        for r in self.refused_site_lists():
            res.notes.append(f"site list {r['table']} was not read; the shipped tables answered")
        return res

    def _map(
        self, domain: str, name: str, synonyms: list[str] | None = None, llm: ConceptMapLLM | None = None
    ) -> MappingResult:
        primary = norm(name)
        names = [primary] + [norm(s) for s in synonyms or []]
        # 0. TERM-2 (D-1113): the site's own lists win over every shipped and loaded table
        found = self._site_list(name, domain)
        if found is not None:
            return found

        def exact(candidates: list[str]) -> list[Concept]:
            return [
                self._concept(table, r)
                for table in DOMAIN_TABLES.get(domain, [])
                for r in self.rows.get(table, [])
                if set(self._names(table, r)) & set(candidates)
            ]

        def grouped(candidates: list[str]) -> tuple[list[Concept], set[tuple[str, str]]]:
            hits: list[Concept] = []
            fams: set[tuple[str, str]] = set()
            for s in self.synonyms:
                if s["domain"] == domain and norm(s["name"]) in candidates:
                    hits.extend(self.expand(s["table"], s["code"], s["match"]))
                    # "family" (SCR-01): the codes under the prefix belong to the concept's family without being
                    # listed: a record with one makes the answer unknown, not a silent "not present" (D-113). It is
                    # for codes that mean the concept only sometimes or in the past (Z85, a history of malignancy)
                    if s["match"] in ("prefix", "family"):
                        fams.add((SYSTEMS[s["table"]], s["code"]))
            return hits, fams | who_only_families(fams)

        # 1. exact display-name match on the concept name itself
        hits = exact([primary])
        trusted: list[dict[str, Any]] | None = None
        if hits:
            # a trusted dictionary entry whose canonical name holds the exact hit and more wins: 心衰竭 is the
            # display of I50.9 but means heart failure, the whole I50 family (D-172)
            trusted, other = self._dictionary(name, domain, primary)
            wide = self._via(name, domain, trusted, grouped, exact, "synonym", False)
            if wide is not None and {c.code for c in hits} < {c.code for c in wide.concepts}:
                return wide
            return MappingResult(name, domain, _dedupe(hits), "exact", False)
        # 2. curated synonym/grouper table on the name — a grouper such as "urate-lowering therapy" must win over
        #    exact matches of individual example drugs
        hits, fams = grouped([primary])
        if hits:
            return MappingResult(name, domain, _dedupe(hits), "synonym", False, families=sorted(fams))
        # 2a. the loaded synonym dictionary (D-172), trusted entries only: TrialBox's curated rows that are not
        #     ambiguous (類風濕關節炎 -> rheumatoid arthritis, GPT -> alt), then the curated table and the exact names
        #     on their canonical names. Such a match is a curated synonym: no review.
        if trusted is None:
            trusted, other = self._dictionary(name, domain, primary)
        found = self._via(name, domain, trusted, grouped, exact, "synonym", False)
        if found is not None:
            return found
        # 2 (cont.). the curated table on the model's synonyms
        hits, fams = grouped(names)
        if hits:
            return MappingResult(name, domain, _dedupe(hits), "synonym", False, families=sorted(fams))
        # 2b. exact match on the synonyms (flagged for review: the grouping came from the model)
        hits = exact(names[1:])
        if hits:
            return MappingResult(name, domain, _dedupe(hits), "exact", True, ["matched via model synonyms"])
        # 2c. the rest of the dictionary (a public dictionary's translations, ambiguous abbreviations): only after
        #     everything above, with its own method, always for review (one English term has several senses)
        found = self._via(name, domain, other, grouped, exact, "dictionary", True)
        if found is not None:
            return found
        # 2d. TERM-1 (D-858): a condition's name in ICD-10-CM itself: a block's name (every category in it), a code's
        #     description (that code; a category: its family), or an Alphabetic Index term (its code's category).
        #     Deterministic and from the code system's own words; an index term or a trial word is for review
        found = self._icd10cm(name, domain)
        if found is not None:
            return found
        # 2e. TERM-2: a name in a code system loaded at install (ICD-10-PCS, the NHI lists, LOINC, WHO ICD-10, ATC)
        found = self._loaded(name, domain)
        if found is not None:
            return found
        # 3. LLM-proposed candidates (always needs_review)
        cands = self.candidates(domain, names, 20)
        if llm is not None and cands:
            choices, review = llm(name, domain, cands)
            chosen = [c for code, system, _conf in choices for c in cands if c.code == code and c.system == system]
            if chosen:
                return MappingResult(name, domain, _dedupe(chosen), "llm", True, [f"LLM-proposed (review={review})"])
        return MappingResult(name, domain, [], "none", True, ["no mapping found"])

    def _icd10cm(self, name: str, domain: str) -> MappingResult | None:
        if domain != "condition" or "icd10cm" not in self.full:
            return None
        raw = _icd_key(name)
        word = _ICD_WORDS.get(raw)
        key = _icd_key(word) if word else raw
        cats: list[str] = []
        how = ""
        if word and word.startswith("@"):
            cats, how = word[1:].split(","), "category"
        elif key in self.icd_blocks:
            cats, how = self.icd_blocks[key], "block"
        elif key in self.icd_display:
            code = min(self.icd_display[key], key=len)
            cats, how = ([code] if len(code) == 3 else []), "description"
            if not cats:
                hits = self.expand("icd10cm", code, "exact") or [
                    c for c in [self.concept(SYSTEMS["icd10cm"], code)] if c
                ]
                return MappingResult(name, domain, _dedupe(hits), "icd10cm", word is not None,
                                     [f"ICD-10-CM description: {code}"]) if hits else None  # fmt: skip
        else:
            words = key.split()
            turned = " ".join(
                words[-1:] + words[:-1]
            )  # "cerebrovascular accident": the index's "Accident, cerebrovascular"
            code = (
                self._index_code(key) or self._index_code(raw) or (self._index_code(turned) if len(words) > 1 else "")
            )
            if code:
                cats, how = [code[:3]], "index"
        if not cats:
            return None
        hits = [c for cat in cats for c in self.expand("icd10cm", cat, "prefix")]
        if not hits:
            return None
        fams = {(SYSTEMS["icd10cm"], cat) for cat in cats}
        review = how == "index" or word is not None
        note = f"ICD-10-CM {how}: {cats[0]}" + (f"-{cats[-1]}" if len(cats) > 1 else "")
        return MappingResult(name, domain, _dedupe(hits), "icd10cm", review, [note],
                             families=sorted(fams | who_only_families(fams)))  # fmt: skip

    def _load_term2(self, where: Path) -> None:
        """The site's lists and the TERM-2 tables loaded in ``where`` (each read only when its manifest line vouches
        for it; a refused one is reported in ``installed_problems`` and never read)."""
        from criteria_compiler.terminology import installed as inst

        self.site_names = {}
        self.site_codes = {}
        self.loaded_names = {}
        self.loaded_sources = {}
        self._term2_refused = []
        # the stamp's TERM-2 part is read again with them (the ICD blocks and index stay as __init__ read them)
        self.installed_read = {k: v for k, v in self.installed_read.items() if k in (inst.ICD_BLOCKS, inst.ICD_INDEX)}
        self.loaded_codes: set[tuple[str, str]] = set()  # every code of a loaded table (a site code is checked here)
        self.who_categories: dict[str, list[Concept]] = {}  # a WHO ICD-10 category -> its codes, when loaded
        have = sorted(p.stem for p in where.glob("*.parquet")) if where.is_dir() else []
        # H-17 (D-1127): the NHI open data shipped in the image answers when the box loaded none of its own
        shipped = {n for n in inst.SHIPPABLE if n not in have and (inst.SHIPPED_DIR / f"{n}.parquet").is_file()}
        try:  # E-TERM-3 (D-1048): a site list whose line stays while its file is gone was not removed on purpose
            lines = inst.manifest(where)["tables"] if where.is_dir() else {}
        except inst.TerminologyRefused:
            lines = {}  # a damaged manifest: each table below is refused by read_loaded, by name
        for gone in sorted(n for n in lines if n.startswith(inst.SITE_PREFIX) and n not in have):
            self._term2_refused.append({"table": gone, "system": "site", "reason": (
                f"{where / (gone + '.parquet')}: in {inst.MANIFEST} but its file is missing; load it again, or remove "
                "it with python -m tools.terminology_install remove-site-list")})  # fmt: skip
        order = [n for n in have if n.startswith(inst.SITE_PREFIX)] + [
            n for n in (inst.ATC_INDEX, inst.NHI_DRUGS, inst.NHI_SERVICES, inst.ICD_PCS, inst.LOINC_TABLE,
                        inst.ICD10_WHO) if n in have or n in shipped]  # fmt: skip
        exact: list[_Entry] = []
        loose: list[_Entry] = []
        for table in order:
            src = inst.SHIPPED_DIR if table in shipped else where
            try:
                rows = inst.read_loaded(src, table)
            except inst.TerminologyRefused as exc:
                self._term2_refused.append({"table": table, "system": table_system(table), "reason": str(exc)})
                continue
            if rows is None:
                continue
            self.loaded_sources[table] = str(inst.manifest(src)["tables"][table].get("version") or "installed")
            self._read_installed(inst, src, table, rows)
            if table.startswith(inst.SITE_PREFIX):
                self._index_site(table, rows)
            else:
                e, lo = self._index_loaded(inst, table, rows)
                if table in shipped:  # H-17 review (D-1127): the answer says it came from the image's table
                    said = f"{_SHIPPED_NOTE} {self.loaded_sources[table]}: "
                    e, lo = [(*x[:5], said + x[5]) for x in e], [(*x[:5], said + x[5]) for x in lo]
                exact += e
                loose += lo
        self._merge(exact, False)
        self._merge(loose, True)  # a component or an ingredient: after every exact name, always for review

    def _read_installed(self, inst: Any, where: Path, table: str, rows: list[dict[str, Any]]) -> None:
        """Record one loaded table as read: its system's URI (``site`` for a site list), the version and the sha256 of
        its manifest line (the bytes :func:`installed.read_table` checked)."""
        line = inst.manifest(where)["tables"][table]
        # the shape lane E's refusals use too (E-TERM-3, D-1048): a system URI, or "site" for a site list
        system = table_system(table)
        self.installed_read[table] = {"table": table, "system": system, "version": str(line.get("version") or ""),
                                      "sha256": str(line.get("sha256") or "")}  # fmt: skip

    def installed_stamp(self) -> list[dict[str, str]]:
        """TERM-2 follow-up: each table loaded at install these tables read, by name (system, version, the manifest's
        sha256). Empty: the shipped Parquet alone, which ``release`` names. Two boxes whose loaded tables differ
        compile under different stamps, never under one."""
        return [self.installed_read[n] for n in sorted(self.installed_read)]

    def _merge(self, entries: list[_Entry], loose: bool) -> None:
        """TERM-2 review (D-1114, D-1115): every code a name has, never the first one alone. One table's rows that give
        one name different codes answer with all of them, for review; a name in two tables answers from the first
        (in ``_load_term2``'s order), for review, with a note naming the others."""
        grouped: dict[tuple[str, str], dict[str, tuple[list[Concept], set[tuple[str, str]], set[frozenset[str]], str]]]
        grouped = {}
        for domain, key, concepts, fams, table, note in entries:
            g = grouped.setdefault((domain, key), {}).setdefault(table, ([], set(), set(), note))
            g[0].extend(concepts)
            g[1].update(fams)
            g[2].add(frozenset(c.code for c in concepts))
        for (domain, key), tables in grouped.items():
            if key in self.loaded_names.get(domain, {}):
                continue  # an exact name already answers
            first, *others = list(tables)
            found, families, rowsets, first_note = tables[first]
            several = len(rowsets) > 1
            text = first_note + ("; several codes share this name" if several else "")
            text += f"; also in {', '.join(others)}" if others else ""
            review = loose or several or bool(others) or first in _ALWAYS_REVIEWED
            self.loaded_names.setdefault(domain, {})[key] = (_dedupe(found), frozenset(families), review,
                                                             text)  # fmt: skip

    def _index_site(self, table: str, rows: list[dict[str, Any]]) -> None:
        mine: dict[tuple[str, str], list[Concept]] = {}
        for r in rows:
            sy, code = str(r["system"]), str(r["code"])
            uri = LOADED_SYSTEMS[sy]
            known = self.concept(uri, code)
            c = Concept(uri, code, str(r.get("display") or "") or (known.display if known else "")
                        or str(r.get("local_name") or "") or code)  # fmt: skip
            if r.get("local_code"):
                self.site_codes.setdefault((sy, str(r["local_code"])), c)
            for key in _name_keys(str(r.get("local_name") or "")):
                mine.setdefault((sy, key), []).append(c)
        for (sy, key), concepts in mine.items():
            codes = {c.code for c in concepts}
            had = self.site_names.setdefault(sy, {}).get(key)
            if had is None:  # several codes under one key of one list (names that differ only in punctuation): review
                self.site_names[sy][key] = _SiteHit(table, _dedupe(concepts), len(codes) > 1, [])
            elif {c.code for c in had.concepts} != codes:  # TERM-2 review (D-1113): two lists disagree, a person sees
                had.others.append(table)

    def _index_loaded(self, inst: Any, table: str, rows: list[dict[str, Any]]) -> tuple[list[_Entry], list[_Entry]]:
        """A loaded code system's exact names and its looser keys (a LOINC component, an NHI ingredient), one entry per
        row and key, merged by ``_merge``. An NHI code whose validity ended is left out."""
        today = date.today().isoformat()
        exact: list[_Entry] = []
        loose: list[_Entry] = []

        def ended(r: dict[str, Any]) -> bool:
            end = str(r.get("valid_to") or "")
            return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", end)) and end < today

        if table == inst.ATC_INDEX:
            uri = LOADED_SYSTEMS["atc"]
            under: dict[str, list[Concept]] = {}  # an ATC group -> its substances (level 5)
            for x in rows:
                self.loaded_codes.add((uri, str(x["code"])))
                if len(str(x["code"])) == 7:
                    for depth in (1, 3, 4, 5):
                        under.setdefault(str(x["code"])[:depth], []).append(
                            Concept(uri, str(x["code"]), str(x["display"]))
                        )
            for r in rows:
                code = str(r["code"])
                concepts = [Concept(uri, code, str(r["display"]))] if len(code) == 7 else under.get(code, [])
                fams = frozenset({(uri, code)}) if len(code) < 7 else frozenset()
                if concepts:
                    exact += [("medication", k, concepts, fams, table, table) for k in _name_keys(str(r["display"]))]
        elif table == inst.NHI_DRUGS:
            uri = LOADED_SYSTEMS["atc"]
            for r in rows:
                self.loaded_codes.add((LOADED_SYSTEMS["nhi_drug"], str(r["nhi_code"])))
                ing = _ingredient(str(r.get("ingredient") or ""))
                atc = str(r.get("atc") or "")
                # H-17 review (D-1127): NHIA names one ingredient in 成分 for some 複方 (combination) products; such
                # a row never answers for that ingredient (a table without the column, TERM-2's, is read as before)
                if ing and len(atc) == 7 and not ended(r) and str(r.get("kind") or "") != "複方":
                    c = self.concept(uri, atc) or Concept(uri, atc, ing)
                    note = f"NHI drug list ingredient ({table})"
                    loose += [("medication", k, [c], frozenset(), table, note) for k in _name_keys(ing)]
        elif table == inst.NHI_SERVICES:
            uri = LOADED_SYSTEMS["nhi_order"]
            for r in rows:
                self.loaded_codes.add((uri, str(r["code"])))
                if ended(r):
                    continue
                c = Concept(uri, str(r["code"]), str(r.get("display_en") or r["display"]))
                for n in (r.get("display"), r.get("display_en")):
                    exact += [("procedure", k, [c], frozenset(), table, table) for k in _name_keys(str(n or ""))]
        elif table == inst.ICD_PCS:
            uri = LOADED_SYSTEMS["icd10pcs"]
            for r in rows:
                if str(r.get("valid")) == "1":
                    self.loaded_codes.add((uri, str(r["code"])))
                    c = Concept(uri, str(r["code"]), str(r["display"]))
                    for n in (r.get("display"), r.get("short")):
                        exact += [("procedure", k, [c], frozenset(), table, table) for k in _name_keys(str(n or ""))]
        elif table == inst.LOINC_TABLE:
            uri = LOADED_SYSTEMS["loinc"]
            for r in rows:
                if str(r.get("status") or "").upper() == "DEPRECATED":
                    continue
                self.loaded_codes.add((uri, str(r["code"])))
                c = Concept(uri, str(r["code"]), str(r["display"]))
                for n in (r.get("display"), r.get("shortname")):
                    exact += [(d, k, [c], frozenset(), table, table) for d in ("observation", "report")
                              for k in _name_keys(str(n or ""))]  # fmt: skip
                if str(r.get("specimen") or "").lower() in _LOINC_BLOOD:
                    note = f"LOINC component ({table})"
                    loose += [(d, k, [c], frozenset(), table, note) for d in ("observation", "report")
                              for k in _name_keys(str(r.get("component") or ""))]  # fmt: skip
        elif table == inst.ICD10_WHO:
            for x in rows:
                if "-" not in str(x["code"]):
                    self.loaded_codes.add((ICD10_WHO, str(x["code"])))
                    self.who_categories.setdefault(str(x["code"])[:3], []).append(
                        Concept(ICD10_WHO, str(x["code"]), str(x["display"]))
                    )
            for r in rows:
                code = str(r["code"])
                if "-" in code:
                    continue
                concepts = (self.who_categories.get(code) if len(code) == 3 else None) or [
                    Concept(ICD10_WHO, code, str(r["display"]))
                ]
                fams = frozenset({(ICD10_WHO, code)}) if len(code) == 3 else frozenset()
                exact += [("condition", k, concepts, fams, table, table) for k in _name_keys(str(r["display"]))]
        return exact, loose

    def _known(self, system: str, code: str) -> bool:
        """A site list's code is one the full ICD-10-CM list, a shipped table or a loaded table holds."""
        if self._icd_codes is None:
            self._icd_codes = {str(r["code"]) for r in self.full.get("icd10cm", [])}
        if system == SYSTEMS["icd10cm"] and code in self._icd_codes:
            return True
        return (system, code) in self._by_code or (system, code) in self.loaded_codes

    _icd_codes: set[str] | None = None

    def _site_list(self, name: str, domain: str) -> MappingResult | None:
        """Step 0 (D-1113): the concept's name in one of the site's own lists, for a system of its domain. Reviewed
        when a code is in no table (a code nothing can match), when one list gives the name several codes, or when two
        lists disagree."""
        for sy in SITE_DOMAIN_SYSTEMS.get(domain, ()):
            for key in _name_keys(name):
                hit = self.site_names.get(sy, {}).get(key)
                if hit is None:
                    continue
                fams: set[tuple[str, str]] = set()
                out: list[Concept] = []
                unknown = []
                for c in hit.concepts:
                    if not self._known(c.system, c.code):
                        unknown.append(c.code)
                    if sy == "icd10cm" and len(c.code) == 3:  # a category: its family
                        out += self.expand("icd10cm", c.code, "prefix") or [c]
                        fams.add((c.system, c.code))
                    elif sy == "icd10_who" and len(c.code) == 3:
                        out += self.who_categories.get(c.code) or [c]
                        fams.add((c.system, c.code))
                    else:
                        out.append(c)
                notes = [f"site list {hit.table}"]
                if hit.several:
                    notes.append("several codes share this name in the list")
                if hit.others:
                    notes.append(f"lists {', '.join([hit.table, *hit.others])} give this name different codes")
                if unknown:
                    notes.append(f"in no loaded or shipped table: {', '.join(sorted(unknown))}")
                review = hit.several or bool(hit.others) or bool(unknown)
                return MappingResult(name, domain, _dedupe(out), "site", review, notes,
                                     families=sorted(fams | who_only_families(fams)))  # fmt: skip
        return None

    def _loaded(self, name: str, domain: str) -> MappingResult | None:
        """Step 2e: the concept's name in a code system loaded at install; a LOINC component or an NHI ingredient
        (looser than a name), a name with several codes, or one in two tables is for review."""
        for key in _name_keys(name):
            got = self.loaded_names.get(domain, {}).get(key)
            if got is not None:
                concepts, fams, review, note = got
                said = note if note.startswith(_SHIPPED_NOTE) else f"loaded at install: {note}"
                return MappingResult(name, domain, _dedupe(concepts), "loaded", review, [said],
                                     families=sorted(fams))  # fmt: skip
        return None

    def _index_code(self, key: str, hops: int = 0) -> str:
        """The code an Alphabetic Index term leads to, following at most two "see" references; "" for none."""
        code, see = self.icd_index.get(key, ("", ""))
        if code:
            return code
        if see and hops < 2:
            return self._index_code(_icd_key(see.split(",")[0]) if "," not in see else _icd_key(see), hops + 1)
        return ""

    def _dictionary(self, name: str, domain: str, primary: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """The dictionary's entries for the name: (trusted, other). Trusted = curated by the TrialBox team and not
        marked ambiguous (``curated``); other = public dictionaries and ambiguous rows. Never raises."""
        if self.name_synonyms is None:
            return [], []
        try:
            got = [e for e in self.name_synonyms(name, domain) if norm(str(e.get("canonical") or "")) != primary]
        except Exception:
            return [], []
        return [e for e in got if e.get("curated")], [e for e in got if not e.get("curated")]

    @staticmethod
    def _via(
        name: str,
        domain: str,
        entries: list[dict[str, Any]],
        grouped: Callable[[list[str]], tuple[list[Concept], set[tuple[str, str]]]],
        exact: Callable[[list[str]], list[Concept]],
        method: str,
        review: bool,
    ) -> MappingResult | None:
        """The curated table, then the exact names, on the entries' canonical names; None when nothing resolves."""
        if not entries:
            return None
        canon = sorted({norm(str(e["canonical"])) for e in entries})
        hits, fams = grouped(canon)
        if not hits:
            hits, fams = exact(canon), set()
        if not hits:
            return None
        srcs = ", ".join(sorted({str(e.get("source_id") or "") for e in entries}))
        note = f"via synonym dictionary ({srcs}): {', '.join(canon)}"
        return MappingResult(name, domain, _dedupe(hits), method, review, [note], families=sorted(fams))

    def candidates(self, domain: str, names: list[str], k: int) -> list[Concept]:
        def toks(s: str) -> set[str]:
            return set(re.findall(r"[a-z0-9]+|[一-鿿]", s))

        want: set[str] = set().union(*(toks(n) for n in names)) if names else set()
        scored = []
        for table in DOMAIN_TABLES.get(domain, []):
            for r in self.rows.get(table, []):
                got = set().union(*(toks(n) for n in self._names(table, r))) if self._names(table, r) else set()
                score = len(want & got) / (len(want | got) or 1)
                if score > 0:
                    c = self._concept(table, r)
                    scored.append((-score, c.code, c))
        return [c for _, _, c in sorted(scored)[:k]]


def _dedupe(concepts: list[Concept]) -> list[Concept]:
    seen: dict[tuple[str, str], Concept] = {}
    for c in concepts:
        seen.setdefault((c.system, c.code), c)
    return sorted(seen.values(), key=lambda c: (c.system, c.code))


def valueset(
    ruleset: str,
    vs_name: str,
    title: str,
    concepts: list[Concept],
    version: str,
    needs_review: bool = False,
    status: str = "draft",
    families: list[tuple[str, str]] | None = None,
    ingredients: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """A FHIR ValueSet of the concepts. ``ingredients`` (``stem -> {atc, ingredient}``, a Japanese site's
    ingredient-to-ATC table, :func:`tb_common.refdata_jp.ingredient_atc`) adds the YJ stems of its ATC codes and
    families (:func:`yj_ingredients`)."""
    by_system: dict[str, list[Concept]] = {}
    if ingredients:
        concepts = [*concepts, *yj_ingredients(concepts, families or [], ingredients)]
    for c in concepts:
        by_system.setdefault(c.system, []).append(c)
    rid = vs_resource_id(ruleset, vs_name)
    compose = {
        "include": [
            {
                "system": system,
                "concept": [{"code": c.code, "display": c.display} for c in sorted(cs, key=lambda c: c.code)],
            }
            for system, cs in sorted(by_system.items())
        ]
    }
    # content-addressed version: fhir-store caches expansions by url|version, so new content needs a new version
    digest = hashlib.sha256(json.dumps(compose, sort_keys=True).encode("utf-8")).hexdigest()[:8]
    vs: dict[str, Any] = {
        "resourceType": "ValueSet",
        "id": rid,
        "url": f"{VS_BASE}/{rid}",
        "version": f"{version}-v{digest}",
        "name": vs_name,
        "title": title,
        "status": status,
        "compose": compose,
    }
    if families:
        vs["extension"] = [{"url": FAMILY_EXT, "valueString": f"{sy}|{pre}"} for sy, pre in sorted(set(families))]
    if needs_review:
        vs["meta"] = {"tag": [{"system": REVIEW_TAG_SYSTEM, "code": "needs_review"}]}
    return vs


def yj_ingredients(
    concepts: list[Concept], families: list[tuple[str, str]], ingredients: dict[str, dict[str, str]]
) -> list[Concept]:
    """The YJ stems (``YJ_STEM`` concepts) whose ATC code is one of the listed ATC concepts or lies in one of the
    grouper's ATC families; none for a list without ATC codes (a diagnosis or lab list)."""
    atc = SYSTEMS["atc"]
    listed = {c.code for c in concepts if c.system == atc}
    prefixes = [pre for sy, pre in families if sy == atc and pre]
    out = [
        Concept(YJ_STEM, stem, row.get("ingredient") or "")
        for stem, row in sorted(ingredients.items())
        if row.get("atc") and (row["atc"] in listed or any(row["atc"].startswith(p) for p in prefixes))
    ]
    return out


@dataclass
class ValueSets:
    """Lookup over a ruleset's ValueSet resources (by IR valueset id)."""

    ruleset: str
    by_name: dict[str, dict[str, Any]]
    terminology: Terminology | None = None

    def _defined(self, name: str) -> dict[str, Any]:
        """The value set ``name``; B14 (D-502): one the IR names and no concept candidate defined is a compile error
        (the criterion goes to a person), never a ``KeyError`` that fails the whole protocol."""
        vs = self.by_name.get(name)
        if vs is None:
            from criteria_compiler.semantics import UnknownValueSet

            raise UnknownValueSet(
                f"ValueSet {name} not defined for ruleset {self.ruleset}: the criterion names a concept that is not "
                f"among its concept candidates"
            )
        return vs

    def url(self, name: str) -> str:
        return str(self._defined(name)["url"])

    def version(self, name: str) -> str:
        return str(self._defined(name).get("version") or "")

    def codes(self, name: str) -> list[tuple[str, str]]:
        vs = self._defined(name)
        return [(inc["system"], c["code"]) for inc in vs["compose"]["include"] for c in inc.get("concept", [])]

    def yj_stems(self, name: str) -> list[str]:
        """The YJ ingredient stems a drug ValueSet carries (T-610); empty for every other list. Only 7-digit codes
        are stems (the generators inline them in SQL and CQL)."""
        if name not in self.by_name:
            return []
        return sorted(c for s, c in self.codes(name) if s == YJ_STEM and re.fullmatch(r"[0-9]{7}", c))

    def families(self, name: str) -> list[tuple[str, str]]:
        """(system, prefix) of the code families a grouper ValueSet stands for (D-113); empty for plain lists."""
        vs = self.by_name.get(name) or {}
        out = []
        for ext in vs.get("extension") or []:
            if ext.get("url") == FAMILY_EXT and "|" in str(ext.get("valueString", "")):
                sy, pre = str(ext["valueString"]).rsplit("|", 1)
                out.append((sy, pre))
        return out

    def is_component_set(self, name: str) -> bool:
        """True when every code is a panel component (e.g. systolic BP inside 85354-9)."""
        term = self.terminology
        if term is None:
            return False
        flags = [bool((term.concept(s, c) or Concept(s, c, "")).component_of) for s, c in self.codes(name)]
        if any(flags) and not all(flags):
            from criteria_compiler.semantics import CompileError

            raise CompileError(f"ValueSet {name} mixes panel components and standalone codes")
        return bool(flags) and all(flags)
