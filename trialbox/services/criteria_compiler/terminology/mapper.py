"""Terminology mapping (SPEC §4.3.1): concept name -> explicit FHIR ValueSet.

Tables (``terminology/*.parquet``, built by ``tools/build_terminology.py`` from ``terminology/src/*.csv`` or a site's
official NHI / LOINC releases): ``icd10cm_tw``, ``nhi_drug`` (with ATC), ``atc``, ``loinc_tw`` (with
``component_of`` for panel members), ``nhi_order``, ``department``, ``synonyms``.

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
    method: str  # exact | synonym | dictionary (D-172, always reviewed) | llm | none
    needs_review: bool
    notes: list[str] = field(default_factory=list)
    families: list[tuple[str, str]] = field(default_factory=list)  # (system, code prefix) of prefix groupers


ConceptMapLLM = Callable[[str, str, list[Concept]], tuple[list[tuple[str, str, float]], bool]]
# (name, domain) -> dictionary entries {canonical, curated, source_id}; tb_common.refdata.synonym_lookup (D-172)
NameSynonyms = Callable[[str, str], list[dict[str, Any]]]


def vs_resource_id(ruleset: str, vs_name: str) -> str:
    """FHIR id for a ValueSet: ``<RULESET>-<NAME>`` with underscores replaced (D-06)."""
    return f"{ruleset}-{vs_name}".replace("_", "-")


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
    def __init__(self, directory: Path = TERM_DIR, name_synonyms: NameSynonyms | None = None) -> None:
        self.dir = directory
        self.name_synonyms = name_synonyms
        # T-610: a Japanese site's ingredient-to-ATC table (stem -> {atc, ingredient}); drug ValueSets then carry
        # the YJ stems of their ATC codes. None (every other site, and the shipped rulesets): no stems
        self.ingredients: dict[str, dict[str, str]] | None = None
        self.rows: dict[str, list[dict[str, Any]]] = {}
        for key, fname in TABLE_FILES.items():
            path = directory / f"{fname}.parquet"
            self.rows[key] = pq.read_table(path).to_pylist() if path.exists() else []
        # full code lists (D-122): code lookups and prefix groupers only, never name matching
        self.full: dict[str, list[dict[str, Any]]] = {}
        for key, fname in FULL_FILES.items():
            path = directory / f"{fname}.parquet"
            if path.exists():
                self.full[key] = pq.read_table(path).to_pylist()
        syn = directory / "synonyms.parquet"
        self.synonyms = pq.read_table(syn).to_pylist() if syn.exists() else []
        self._by_code: dict[tuple[str, str], Concept] = {}
        for key, rows in self.full.items():
            for r in rows:
                c = self._concept(key, r)
                self._by_code[(c.system, c.code)] = c
        for key, rows in self.rows.items():  # curated rows win (zh displays, demo spellings)
            for r in rows:
                c = self._concept(key, r)
                self._by_code[(c.system, c.code)] = c

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
        primary = norm(name)
        names = [primary] + [norm(s) for s in synonyms or []]

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
                    # listed: a record with one makes the answer unknown, not a silent "not present" (D-113). For
                    # codes that mean the concept only sometimes or in the past (Z85, a history of malignancy)
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
        # 3. LLM-proposed candidates (always needs_review)
        cands = self.candidates(domain, names, 20)
        if llm is not None and cands:
            choices, review = llm(name, domain, cands)
            chosen = [c for code, system, _conf in choices for c in cands if c.code == code and c.system == system]
            if chosen:
                return MappingResult(name, domain, _dedupe(chosen), "llm", True, [f"LLM-proposed (review={review})"])
        return MappingResult(name, domain, [], "none", True, ["no mapping found"])

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

    def url(self, name: str) -> str:
        return str(self.by_name[name]["url"])

    def version(self, name: str) -> str:
        return str(self.by_name[name].get("version") or "")

    def codes(self, name: str) -> list[tuple[str, str]]:
        vs = self.by_name.get(name)
        if vs is None:
            raise KeyError(f"ValueSet {name} not defined for ruleset {self.ruleset}")
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
