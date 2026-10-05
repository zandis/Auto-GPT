"""Terminology mapping (SPEC §4.3.1): concept name -> explicit FHIR ValueSet.

Tables (``terminology/*.parquet``, built by ``tools/build_terminology.py`` from ``terminology/src/*.csv`` or a site's
official NHI / LOINC releases): ``icd10cm_tw``, ``nhi_drug`` (with ATC), ``atc``, ``loinc_tw`` (with
``component_of`` for panel members), ``nhi_order``, ``department``, ``synonyms``.

Steps: exact display-name match -> synonym table (exact codes or code-prefix groups expanded against the tables) ->
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

SYSTEMS = {
    "icd10cm": "http://hl7.org/fhir/sid/icd-10-cm",
    "atc": "http://www.whocc.no/atc",
    "nhi_drug": "https://trialbox.local/fhir/CodeSystem/nhi-drug",
    "nhi_order": "https://trialbox.local/fhir/CodeSystem/nhi-order",
    "department": "https://trialbox.local/fhir/CodeSystem/department",
    "loinc": "http://loinc.org",
}
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
    method: str  # exact | synonym | llm | none
    needs_review: bool
    notes: list[str] = field(default_factory=list)


ConceptMapLLM = Callable[[str, str, list[Concept]], tuple[list[tuple[str, str, float]], bool]]


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
    def __init__(self, directory: Path = TERM_DIR) -> None:
        self.dir = directory
        self.rows: dict[str, list[dict[str, Any]]] = {}
        for key, fname in TABLE_FILES.items():
            path = directory / f"{fname}.parquet"
            self.rows[key] = pq.read_table(path).to_pylist() if path.exists() else []
        syn = directory / "synonyms.parquet"
        self.synonyms = pq.read_table(syn).to_pylist() if syn.exists() else []
        self._by_code: dict[tuple[str, str], Concept] = {}
        for key, rows in self.rows.items():
            for r in rows:
                c = self._concept(key, r)
                self._by_code[(c.system, c.code)] = c

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

        # 1. exact display-name match on the concept name itself
        hits = exact([primary])
        if hits:
            return MappingResult(name, domain, _dedupe(hits), "exact", False)
        # 2. curated synonym/grouper table (name first, then the model's synonyms) — a grouper such as
        #    "urate-lowering therapy" must win over exact matches of individual example drugs
        for candidates in ([primary], names):
            hits = []
            for s in self.synonyms:
                if s["domain"] == domain and norm(s["name"]) in candidates:
                    hits.extend(self.expand(s["table"], s["code"], s["match"]))
            if hits:
                return MappingResult(name, domain, _dedupe(hits), "synonym", False)
        # 2b. exact match on the synonyms (flagged for review: the grouping came from the model)
        hits = exact(names[1:])
        if hits:
            return MappingResult(name, domain, _dedupe(hits), "exact", True, ["matched via model synonyms"])
        # 3. LLM-proposed candidates (always needs_review)
        cands = self.candidates(domain, names, 20)
        if llm is not None and cands:
            choices, review = llm(name, domain, cands)
            chosen = [c for code, system, _conf in choices for c in cands if c.code == code and c.system == system]
            if chosen:
                return MappingResult(name, domain, _dedupe(chosen), "llm", True, [f"LLM-proposed (review={review})"])
        return MappingResult(name, domain, [], "none", True, ["no mapping found"])

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
) -> dict[str, Any]:
    by_system: dict[str, list[Concept]] = {}
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
    if needs_review:
        vs["meta"] = {"tag": [{"system": REVIEW_TAG_SYSTEM, "code": "needs_review"}]}
    return vs


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
