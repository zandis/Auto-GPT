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
for adopted LOINC codes) and ``phenotype_icd10cm.csv`` (new). Never invents a code: a code reaches a CSV only when
the evidence holds it.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
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
OHDSI_TAG = "v3.37.0"
OHDSI_RAW = f"https://raw.githubusercontent.com/OHDSI/PhenotypeLibrary/{OHDSI_TAG}/inst"

LOINC_NOTICE = (
    "LOINC: free for any purpose incl. commercial, LOINC notice+version required (baseline-open-data 2026-11-09)"
)
SRC_LOINC = "NLM Clinical Tables loinc_items"
SRC_MHLW = "MHLW 特定健診 XML 付属2 Ver.4 (001082795.xlsx)"
SRC_ICD = "NLM Clinical Tables icd10cm"
SRC_OHDSI = f"OHDSI PhenotypeLibrary {OHDSI_TAG}"

ITEM_EXTRA = ["code_fit", "verified_source", "verified_date", "verified_note", "jlac10", "jlac10_source"]
PHENO_EXTRA = ["verified", "verified_source", "verified_date", "verified_note"]
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
    "note",
]
ACTIONS = {"adopt", "keep_local", "fit_partial"}
# segments of a phenotype `codes` cell that name another vocabulary, not ICD-10-CM
NON_ICD_PREFIXES = ("LOINC", "ATC", "MEDIS", "ICD-O", "local", "procedure")
ICD_TOKEN = re.compile(r"\b([A-Z]\d[0-9A-Z](?:\.[0-9A-Z]{1,4})?)")
MAX_NAME_CHECKS = 40
MAX_STORED_CONCEPTS = 60  # per cohort in evidence.json; the count is kept

Getter = Callable[[str], bytes]


class CatalogueError(ValueError):
    """A curated file or the evidence does not support what the catalogue would say."""


# ---------------------------------------------------------------- small helpers


def search_term(name_en: str) -> str:
    """The automatic LOINC search term for an item: its English name without brackets and commas."""
    term = re.sub(r"\([^)]*\)", " ", name_en).replace(",", " ")
    return " ".join(term.split())


def icd_tokens(codes: str) -> list[str]:
    """ICD-10-CM code prefixes named in a free-text `codes` cell (``M05.*`` -> ``M05``; ranges give both ends)."""
    out: list[str] = []
    for segment in codes.split(";"):
        seg = segment.strip()
        if seg.startswith("ICD-10-CM"):
            seg = seg[len("ICD-10-CM") :].strip()
        if not seg or seg.startswith(NON_ICD_PREFIXES):
            continue
        for tok in ICD_TOKEN.findall(seg):
            if tok not in out:
                out.append(tok)
    return out


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
    icd10cm_names: dict[str, list[str]] = field(default_factory=dict)  # concept name -> ICD-10-CM codes by title
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
            sources=data.get("sources", {}),
        )

    def dump(self) -> str:
        data = {
            "date": self.date,
            "sources": self.sources,
            "loinc_codes": dict(sorted(self.loinc_codes.items())),
            "loinc_searches": dict(sorted(self.loinc_searches.items())),
            "jlac10": dict(sorted(self.jlac10.items())),
            "cohorts": dict(sorted(self.cohorts.items(), key=lambda kv: int(kv[0]))),
            "icd10cm_prefixes": dict(sorted(self.icd10cm_prefixes.items())),
            "icd10cm_names": dict(sorted(self.icd10cm_names.items())),
        }
        return json.dumps(data, ensure_ascii=False, indent=1) + "\n"

    def icd_exists(self, prefix: str) -> bool:
        return int(self.icd10cm_prefixes.get(prefix, {}).get("n", 0)) > 0


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


# ---------------------------------------------------------------- build: items


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
        if action == "adopt":
            code = dec["loinc"] if dec else ""
            if code not in ev.loinc_codes:
                raise CatalogueError(f"{row['id']}: adopted LOINC {code} is not in the evidence")
            if row["loinc"] != code:
                row["source"] = f"LOINC {code}; was local: {row['source']}" if row["source"] else f"LOINC {code}"
                row["loinc"] = code
                row["licence_notes"] = LOINC_NOTICE
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
                row["code_fit"] = "partial" if action == "fit_partial" else "exact"
                row["verified_note"] = note
                if action == "adopt":
                    row["verified_note"] = "; ".join(p for p in (_searches_note(terms, ev), note) if p)
        else:
            if action == "fit_partial":
                raise CatalogueError(f"{row['id']}: fit_partial on a local item")
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
        out.append(row)
    return out


def _fill_jlac10(row: dict[str, str], cur: Curated, ev: Evidence) -> None:
    jl = cur.jlac10.get(row["id"])
    row["jlac10"], row["jlac10_source"] = "", ""
    if not jl:
        return
    codes = split_list(jl["jlac10"])
    for code in codes:
        if code not in ev.jlac10:
            raise CatalogueError(f"{row['id']}: JLAC10 {code} is not in the MHLW evidence")
        if not re.fullmatch(r"[0-9][0-9A-Z]{16}", code):
            raise CatalogueError(f"{row['id']}: {code} is not a 17-character JLAC10 code")
    if codes:
        names = sorted({ev.jlac10[c]["name"] for c in codes})
        row["jlac10"] = ";".join(codes)
        row["jlac10_source"] = f"{SRC_MHLW} '{' / '.join(names)}', checked {ev.date}"
    if jl.get("note"):
        row["jlac10_source"] = "; ".join(p for p in (row["jlac10_source"], jl["note"]) if p)


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
            problems.append("not ICD-10-CM codes: " + ", ".join(missing))
        if not tokens:
            problems.append("no ICD-10-CM code in `codes`")
        parts = [f"{len(tokens) - len(missing)} of {len(tokens)} ICD-10-CM codes exist"]
        if status:
            parts.append("library status " + ", ".join(status))
        parts += problems
        tr = cur.phenotypes.get(row["id"])
        if tr:
            parts.append("ICD-10-CM translation in phenotype_icd10cm.csv" + (f" ({tr['note']})" if tr["note"] else ""))
        row["verified"] = "no" if problems else "yes"
        row["verified_source"] = "; ".join([SRC_ICD] + ([SRC_OHDSI] if ids else []))
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
        names = [c["name"] for c in concepts if c.get("vocabulary") == "SNOMED" and not c.get("excluded")]
        names = names[:MAX_NAME_CHECKS]
        found = inside = 0
        outside: list[str] = []
        for name in names:
            hits = ev.icd10cm_names.get(name, [])
            if not hits:
                continue
            found += 1
            if any(_in_set(h, include, exclude) for h in hits):
                inside += 1
            else:
                outside.extend(f"{h} ({name})" for h in hits[:2])
        total = int(co.get("entry_concept_count", len(concepts)))
        shown = "; ".join(f"{c['name']} [{c['vocabulary']} {c['concept_id']}]" for c in concepts[:6])
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
                "note": "; ".join(p for p in (("unknown codes: " + ", ".join(bad)) if bad else "", m["note"]) if p),
            }
        )
    return out


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
    return {
        paths.catalogue / "items.csv": render_csv(item_cols, build_items(items, cur, ev)),
        paths.catalogue / "phenotypes.csv": render_csv(ph_cols, build_phenotypes(phenos, cur, ev)),
        paths.catalogue / "phenotype_icd10cm.csv": render_csv(PH_OUT_COLUMNS, build_icd10cm(phenos, cur, ev)),
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
                    "code": str(c.get("CONCEPT_CODE", "")),
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
        },
    )
    codes = {r["loinc"] for r in items if r["loinc"] not in ("", "local")}
    codes |= {d["loinc"] for d in cur.loinc.values() if d["loinc"]}
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
    for cid in sorted(wanted, key=int):
        if cid not in lib:
            continue
        rec: dict[str, Any] = {"name": lib[cid]["cohortName"], "status": lib[cid]["status"], "entry_concepts": []}
        if cid in primary:
            concepts = entry_concepts(json.loads(get(f"{OHDSI_RAW}/cohorts/{cid}.json")))
            rec["entry_concepts"] = concepts[:MAX_STORED_CONCEPTS]
            rec["entry_concept_count"] = len(concepts)
        ev.cohorts[cid] = rec
    log(f"ohdsi: {len(ev.cohorts)} cohorts, {len(primary)} with entry concepts")
    prefixes = {t for r in phenos for t in icd_tokens(r["codes"])}
    for m in cur.phenotypes.values():
        prefixes |= set(split_list(m["icd10cm_include"])) | set(split_list(m["icd10cm_exclude"]))
    for p in sorted(prefixes):
        ev.icd10cm_prefixes[p] = fetch_icd_prefix(get, p)
    names = set()
    for cid in primary:
        concepts = ev.cohorts.get(cid, {}).get("entry_concepts", [])
        snomed = [c["name"] for c in concepts if c["vocabulary"] == "SNOMED" and not c["excluded"]]
        names |= set(snomed[:MAX_NAME_CHECKS])
    for name in sorted(names):
        ev.icd10cm_names[name] = fetch_icd_name(get, name)
    log(f"icd10cm: {len(ev.icd10cm_prefixes)} code families, {len(ev.icd10cm_names)} concept names")
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
