"""Taiwan reference data items (D-170, D-171, D-172): the NHI drug code -> ATC map, the NHIA ICD-10-CM/PCS 2014 <->
2023 map, the NHI lab code -> LOINC map and the zh-TW clinical synonyms for the name matcher.

Each item is one :class:`tb_common.refdata.Item` in the registry (``tools/refdata_fetch.py`` adds :data:`ITEMS`):
its source, licence (read at the source on 2026-11-09), terms, attribution, how its version is read, and its own
parser. The box never downloads them: the vendor runs ``tools/refdata_fetch.py fetch`` and ``build``, and the pack
reaches the box inside the signed update bundle (offline media).

Licences checked at the source (2026-11-09):

* data.gov.tw datasets 23715 (NHI drug list), 177508 (ICD-10-CM/PCS 2014 <-> 2023 map) and 15460 (NAER medical
  terms): dataset API field ``license`` = 1, the Open Government Data License version 1.0 (https://data.gov.tw/
  license): use, reproduction, distribution, adaptation and products of any kind, with no fee, on condition of the
  provider's attribution statement.
* The NHIA PAS IG package ``tw.gov.mohw.nhi.pas`` 1.3.0 (``ConceptMap-nhi-loinc``): ``package.json`` licence
  ``CC0-1.0``. The parser refuses a package with another licence.
* The curated zh-TW synonyms are TrialBox's own work (``tb_common/refdata_src/zh_tw_clinical_synonyms.csv``).

Nothing here is site-fetch: every licence allows redistribution.
"""

from __future__ import annotations

import io
import json
import re
import tarfile
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from tb_common.refdata import RELATIONS, Item, csv_rows, require_columns

OGDL = "Open Government Data License, version 1.0 (Taiwan)"
OGDL_URL = "https://data.gov.tw/license"
OGDL_TERMS = "Free use, reuse and redistribution, commercial included, with attribution of the provider."

ATC = "http://www.whocc.no/atc"
LOINC = "http://loinc.org"
NHI_DRUG = "urn:tw:nhi:drug"  # the pack's system for 藥品代號 (nhi_drugs, D-140)
NHI_SERVICE = "https://twcore.mohw.gov.tw/ig/twcore/CodeSystem/medical-service-payment-tw"  # 醫療服務給付項目
ICD_CM_2014 = "urn:tw:nhi:icd-10-cm-2014"
ICD_CM_2023 = "urn:tw:nhi:icd-10-cm-2023"  # the pack's system of tw_icd10_zh (D-140)
ICD_PCS_2014 = "urn:tw:nhi:icd-10-pcs-2014"
ICD_PCS_2023 = "urn:tw:nhi:icd-10-pcs-2023"

_ATC_SHAPE = re.compile(r"^[A-Z](\d{2}([A-Z]([A-Z](\d{2})?)?)?)?$")
_ATC_LEVEL = {1: 1, 3: 2, 4: 3, 5: 4, 7: 5}  # code length -> ATC level
REPO_SYNONYMS = Path(__file__).resolve().parent / "refdata_src" / "zh_tw_clinical_synonyms.csv"


DATAGOV_OGDL = "1"  # data.gov.tw dataset API: license 1 = Open Government Data License 1.0


def datagov_meta(meta_url: str) -> dict[str, Any]:
    """A data.gov.tw dataset's modified date (its version), its licence field and the download URLs it lists, from
    the dataset API (the vendor's fetch only; the box never calls it); empty when it does not answer. Kept in
    fetch.json as evidence of the licence read at fetch time. The download URLs bind the licence to the file: the
    NAER terms are fetched from opendata.naer.edu.tw, and the fetch checks that this is the URL the OGDL-licensed
    record 15460 distributes (D-172)."""
    import httpx

    try:
        r = httpx.get(meta_url, timeout=60)
        r.raise_for_status()
        res = r.json()["result"]
        downloads = sorted(unquote(str(d.get("resourceDownloadUrl") or "")) for d in res.get("distribution") or [])
        return {"version": f"data.gov.tw {res['datasetId']} modified {res['modifiedDate']}",
                "license": str(res.get("license", "")), "meta_url": meta_url,
                "downloads": [d for d in downloads if d]}  # fmt: skip
    except Exception:
        return {}


def _datagov(meta_url: str) -> dict[str, Any]:
    return datagov_meta(meta_url)  # looked up at call time (tests replace datagov_meta)


def roc(s: str) -> str:
    """A 民國 date ``YYYMMDD`` (``1001201``, `` 960901``) or ``YYY.MM.DD`` -> ISO; anything else unchanged."""
    s = (s or "").strip()
    m = re.fullmatch(r"(\d{2,3})\.(\d{1,2})\.(\d{1,2})", s)
    if m:
        return f"{int(m.group(1)) + 1911}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    if re.fullmatch(r"\d{6,7}", s):
        s = s.zfill(7)
        return f"{int(s[:3]) + 1911}-{s[3:5]}-{s[5:7]}"
    return s


# ------------------------------------------------------------------------------------------------ D-170 NHI -> ATC
NHI_DRUG_COLS = ("藥品代號", "藥品中文名稱", "有效起日", "有效迄日", "ATC代碼")


def latest_nhi_rows(path: Path, having: str = "") -> dict[str, dict[str, str]]:
    """One row per 藥品代號: the row with the latest 有效起日 (the list has one row per validity period). With
    ``having``, only rows where that column has a value count (the newest row that states an ATC code, when the
    newest period left it empty)."""
    best: dict[str, dict[str, str]] = {}
    rows = require_columns(csv_rows(path.read_bytes()), NHI_DRUG_COLS, "the NHI drug list (data.gov.tw 23715)")
    for r in rows:
        code = r.get("藥品代號", "")
        if not code or (having and not r.get(having, "").strip()):
            continue
        r["有效起日"], r["有效迄日"] = roc(r.get("有效起日", "")), roc(r.get("有效迄日", ""))
        if code not in best or _iso(r["有效起日"]) >= _iso(best[code]["有效起日"]):
            best[code] = r
    return best


def _iso(d: str) -> str:
    """A date ``roc`` could read sorts by itself; anything else sorts first (it never wins over a real date)."""
    return d if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) else ""


def parse_nhi_drug_atc(path: Path) -> Iterator[dict[str, Any]]:
    """NHI 藥品代號 -> the ``ATC代碼`` the NHIA list gives (kept as given, D-140: no WHO ATC/DDD text). The product is
    narrower than its ATC class, so the target is ``wider``. The ATC code is the one of the newest validity period
    that states one. Codes without an ATC, or with a value that is not ATC-shaped, give no row (unknown, never a
    guess)."""
    for code, r in sorted(latest_nhi_rows(path, having="ATC代碼").items()):
        atc = r.get("ATC代碼", "").strip().upper()
        if not atc or not _ATC_SHAPE.match(atc) or len(atc) not in _ATC_LEVEL:
            continue
        yield {
            "source_system": NHI_DRUG, "source_code": code, "source_display": r.get("藥品中文名稱", ""),
            "target_system": ATC, "target_code": atc, "target_display": "", "relation": "wider",
            "extra": {"atc_level": _ATC_LEVEL[len(atc)], "name_en": r.get("藥品英文名稱", ""),
                      "ingredient": r.get("成分", ""), "valid_from": r.get("有效起日", ""),
                      "valid_to": r.get("有效迄日", "")},
        }  # fmt: skip


# ------------------------------------------------------------------------------------------------ D-171 ICD map
ICD_PCS_FILE = "tw_icd_2014_2023_pcs.csv"
ICD_COLS = ("2014年版ICD-10-CM/PCS", "2014年版ICD-10-CM/PCS_英文名稱", "2014年版ICD-10-CM/PCS_中文名稱",
            "2023年版ICD-10-CM/PCS", "2023年版ICD-10-CM/PCS_英文名稱", "2023年版ICD-10-CM/PCS_中文名稱",
            "2014代碼狀態", "2023代碼狀態", "修訂日期")  # fmt: skip


def icd_map_rows(data: bytes, pcs: bool) -> Iterator[dict[str, Any]]:
    """One NHIA 2014 <-> 2023 file (CM or PCS; same columns). The relation says how the 2023 code's meaning relates
    to the 2014 code's:

    * the same code with one target and one source: ``equivalent``;
    * a 2014 code split into several 2023 codes: ``narrower`` targets;
    * several 2014 codes merged into one 2023 code: a ``wider`` target;
    * both at once, or a one-to-one change of code: ``inexact``;
    * a mapping NHIA added later for a deleted code (修訂日期 "增列對應", e.g. 2014 Z22.51 carrier -> 2023 B18.1
      chronic hepatitis B) is ``relatedto``: a candidate, not the same meaning; it does not count as a merge for the
      other rows;
    * a 2014 code with no 2023 code at all (deleted): one ``unmatched`` row without a target, so site set-up never
      offers the obsolete code as a standard code.

    Cardinality is counted over the file's distinct pairs."""
    rows = require_columns(csv_rows(data), ICD_COLS[:8], "an NHIA 2014/2023 ICD-10 map")
    c14, c23 = ICD_COLS[0], ICD_COLS[3]
    pairs = [(r[c14], r[c23], r) for r in rows if r.get(c14) and r.get(c23)]
    added = {(a, b) for a, b, r in pairs if "增列對應" in (r.get(ICD_COLS[8]) or "")}
    uniq = {(a, b) for a, b, _ in pairs} - added
    n_targets, n_sources = Counter(a for a, _ in uniq), Counter(b for _, b in uniq)
    seen: set[tuple[str, str]] = set()
    src, tgt = (ICD_PCS_2014, ICD_PCS_2023) if pcs else (ICD_CM_2014, ICD_CM_2023)

    def extra(r: dict[str, str]) -> dict[str, str]:
        return {"source_zh": r.get(ICD_COLS[2], ""), "target_zh": r.get(ICD_COLS[5], ""),
                "status_2014": r.get(ICD_COLS[6], ""), "status_2023": r.get(ICD_COLS[7], ""),
                "revised": r.get(ICD_COLS[8], "")}  # fmt: skip

    for a, b, r in pairs:
        if (a, b) in seen:
            continue
        seen.add((a, b))
        split, merged = n_targets[a] > 1, n_sources[b] > 1
        if (a, b) in added:
            rel = "relatedto"
        elif split and merged:
            rel = "inexact"
        elif split:
            rel = "narrower"
        elif merged:
            rel = "wider"
        else:
            rel = "equivalent" if a == b else "inexact"
        yield {
            "source_system": src, "source_code": a, "source_display": r.get(ICD_COLS[1], ""),
            "target_system": tgt, "target_code": b, "target_display": r.get(ICD_COLS[4], ""), "relation": rel,
            "extra": extra(r),
        }  # fmt: skip
    mapped = {a for a, _, _ in pairs}
    for r in rows:
        a = r.get(c14, "")
        if a and not r.get(c23) and a not in mapped:
            mapped.add(a)
            yield {
                "source_system": src, "source_code": a, "source_display": r.get(ICD_COLS[1], ""),
                "target_system": tgt, "target_code": "", "target_display": "", "relation": "unmatched",
                "extra": extra(r),
            }  # fmt: skip


def parse_tw_icd_2014_2023(path: Path) -> Iterator[dict[str, Any]]:
    """The fetched CM file (``path``) and the PCS file beside it: both are required (the item is the two files)."""
    pcs = path.parent / ICD_PCS_FILE
    if not pcs.is_file():
        raise ValueError(f"{pcs.name} is missing beside {path.name}: fetch tw_icd_2014_2023 again")
    yield from icd_map_rows(path.read_bytes(), pcs=False)
    yield from icd_map_rows(pcs.read_bytes(), pcs=True)


# ------------------------------------------------------------------------------------------------ D-171 NHI -> LOINC
def _pas_package(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """``package.json`` and ``ConceptMap-nhi-loinc.json`` from the package tgz (or a directory holding them)."""
    if path.is_dir():
        return (json.loads((path / "package.json").read_text(encoding="utf-8")),
                json.loads((path / "ConceptMap-nhi-loinc.json").read_text(encoding="utf-8")))  # fmt: skip
    with tarfile.open(path, "r:*") as tf:

        def read(name: str) -> dict[str, Any]:
            try:
                f = tf.extractfile(f"package/{name}")
            except KeyError:
                f = None
            if f is None:
                raise ValueError(f"{path.name}: no package/{name}")
            return dict(json.load(io.TextIOWrapper(f, encoding="utf-8")))

        return read("package.json"), read("ConceptMap-nhi-loinc.json")


def parse_nhi_lab_loinc(path: Path) -> Iterator[dict[str, Any]]:
    """The NHIA ConceptMap ``nhi-loinc``: NHI 醫療服務給付項目 (lab order) code -> LOINC, every target as a row with
    its equivalence (``relatedto`` throughout 1.3.0: candidates, not equivalents). LOINC codes only: a LOINC display
    in a later release is never copied (LOINC text stays under the LOINC licence). An R5 ``relationship`` is turned
    into the R4 equivalence; an unknown one, or an element without a code, refuses the package. A target that says
    no match (``unmatched``, ``disjoint``, R5 ``not-related-to``) is skipped: it maps nothing. Only groups whose source
    is the NHI service code system are read; a package with none is refused (site set-up asks that system)."""
    pkg, cm = _pas_package(path)
    if str(pkg.get("license", "")).upper() != "CC0-1.0":
        raise ValueError(f"the NHI PAS package's licence is {pkg.get('license')!r}, not CC0-1.0: do not ship")
    seen: set[tuple[str, str, str]] = set()
    groups = [
        g for g in cm.get("group") or [] if g.get("target") == LOINC and (g.get("source") or NHI_SERVICE) == NHI_SERVICE
    ]
    if not groups:
        raise ValueError(f"{path.name}: the ConceptMap has no group from {NHI_SERVICE} to {LOINC}")
    system = NHI_SERVICE
    for g in groups:
        for e in g.get("element") or []:
            if not e.get("code"):
                raise ValueError(f"{path.name}: an element without a code: {e!r}")
            for t in e.get("target") or []:
                rel = t.get("equivalence") or R5_TO_R4.get(str(t.get("relationship") or ""), "")
                if rel in ("unmatched", "disjoint"):
                    continue  # no match: nothing to map
                if not t.get("code"):
                    raise ValueError(f"{path.name}: {e['code']}: a target without a code: {t!r}")
                if rel not in RELATIONS:
                    raise ValueError(f"{path.name}: {e['code']} -> {t['code']}: unknown relation {t!r}")
                key = (str(system), str(e["code"]), str(t["code"]))
                if key in seen:
                    continue
                seen.add(key)
                yield {
                    "source_system": system, "source_code": key[1], "source_display": e.get("display", ""),
                    "target_system": LOINC, "target_code": key[2], "target_display": "", "relation": rel,
                    "extra": {"conceptmap": cm.get("url", ""), "conceptmap_version": cm.get("version", ""),
                              "loinc_version": g.get("targetVersion", "")},
                }  # fmt: skip


# FHIR R5 ConceptMap relationship -> R4 equivalence (the relation is the target's meaning against the source's)
R5_TO_R4 = {"related-to": "relatedto", "equivalent": "equivalent", "source-is-narrower-than-target": "wider",
            "source-is-broader-than-target": "narrower", "not-related-to": "unmatched"}  # fmt: skip


def pas_version(path: Path) -> str:
    """The package, the ConceptMap and the LOINC version the map states (``targetVersion``; the LOINC terms ask for
    the version)."""
    pkg, cm = _pas_package(path)
    loinc = sorted({str(g.get("targetVersion")) for g in cm.get("group") or [] if g.get("targetVersion")})
    return (f"{pkg.get('name', '')} {pkg.get('version', '')}, ConceptMap nhi-loinc {cm.get('version', '')}"
            + (f", LOINC {'/'.join(loinc)}" if loinc else "")).strip()  # fmt: skip


# ------------------------------------------------------------------------------------------------ D-172 synonyms
def parse_naer_terms(path: Path) -> Iterator[dict[str, Any]]:
    """NAER 醫學學術名詞: one row per zh-TW name (``中文名稱`` lists several, split at ``；``) -> the English term.
    These are academic translations, one English term with several senses: not curated (the matcher flags them)."""
    seen: set[tuple[str, str]] = set()
    for r in require_columns(csv_rows(path.read_bytes()), ("英文名稱", "中文名稱"), "the NAER medical terms"):
        en = r.get("英文名稱", "")
        for zh in re.split(r"[；;]", r.get("中文名稱", "")):
            zh = zh.strip()
            if not en or not zh or (zh, en.lower()) in seen:
                continue
            seen.add((zh, en.lower()))
            yield {"term": zh, "lang": "zh-TW", "canonical": en, "canonical_lang": "en", "domain": "", "system": "",
                   "code": "", "curated": False, "extra": {"naer_no": r.get("序號", "")}}  # fmt: skip


def parse_zh_tw_synonyms(path: Path) -> Iterator[dict[str, Any]]:
    """TrialBox's own curated list: zh-TW clinical words and the abbreviations of Taiwanese notes -> the name the
    matcher knows, per domain. A row is trusted (``curated``: no review) unless its ``review`` column says yes (an
    abbreviation with another meaning in some specialty: MI, RA, CVA)."""
    cols = ("term", "lang", "canonical", "domain", "review")
    for r in require_columns(csv_rows(path.read_bytes()), cols, "the curated zh-TW synonyms"):
        if r.get("term") and r.get("canonical"):
            review = r.get("review", "").lower() in ("yes", "y", "true", "1")
            yield {"term": r["term"], "lang": r.get("lang") or "zh-TW", "canonical": r["canonical"],
                   "canonical_lang": r.get("canonical_lang") or "en", "domain": r.get("domain", ""), "system": "",
                   "code": "", "curated": not review,
                   "extra": {"note": r.get("note", ""), "review": review}}  # fmt: skip


def synonyms_version(path: Path) -> str:
    import hashlib

    return f"TrialBox zh-TW synonyms, {sum(1 for _ in parse_zh_tw_synonyms(path))} entries, " \
           f"sha256 {hashlib.sha256(path.read_bytes()).hexdigest()[:12]}"  # fmt: skip


# ------------------------------------------------------------------------------------------------ the items
NHIA = "National Health Insurance Administration (衛生福利部中央健康保險署)"
ITEMS: tuple[Item, ...] = (
    Item(
        "nhi_drug_atc", "NHI drug code -> ATC (from 健保用藥品項查詢項目檔, data.gov.tw 23715)", "map", "ship",
        "https://info.nhi.gov.tw/api/iode0000s01/Dataset?rId=A21030000I-E41001-001", OGDL, OGDL_URL,
        OGDL_TERMS + " The ATC codes are given as the NHIA list carries them; no WHO ATC/DDD index text is shipped.",
        f"健保用藥品項查詢項目檔, {NHIA}, via data.gov.tw (dataset 23715), Open Government Data License 1.0. "
        "ATC codes as listed by NHIA.",
        "monthly", "one map row per drug code with an ATC code (the list had 45,224 codes in the D-140 fetch)",
        "Read from the nhi_drugs download (no second download); non-ATC-shaped values are left out.",
        country="TW", decision="D-170", derived_from="nhi_drugs", parse=parse_nhi_drug_atc,
        read_meta=_datagov, licence_id=DATAGOV_OGDL,
        meta_url="https://data.gov.tw/api/v2/rest/dataset/23715",
    ),
    Item(
        "tw_icd_2014_2023", "Taiwan ICD-10-CM/PCS 2014 <-> 2023 map (NHIA, data.gov.tw 177508)", "map", "ship",
        "https://info.nhi.gov.tw/api/iode0000s01/Dataset?rId=A21030000I-D20026-007", OGDL, OGDL_URL, OGDL_TERMS,
        f"2014年版與2023年版ICD-10-CM/PCS對應檔, {NHIA}, via data.gov.tw (dataset 177508), Open Government Data "
        "License 1.0. ICD-10-CM/PCS is based on the WHO ICD-10 (copyright World Health Organization); ICD-10-CM and "
        "ICD-10-PCS are by NCHS and CMS (U.S.).",
        "with each NHIA revision (months)", "CM 74,872 rows (21 MB CSV), PCS 79,062 rows (21 MB CSV), 2026-09",
        "NHI claims moved from the 2014 to the 2023 edition on 2025-01-01: records before then carry 2014 codes.",
        "tw_icd_2014_2023_cm.csv", country="TW", decision="D-171", parse=parse_tw_icd_2014_2023,
        extra_files=(("tw_icd_2014_2023_pcs.csv",
                      "https://info.nhi.gov.tw/api/iode0000s01/Dataset?rId=A21030000I-D20026-008"),),
        read_meta=_datagov, licence_id=DATAGOV_OGDL,
        meta_url="https://data.gov.tw/api/v2/rest/dataset/177508",
    ),
    Item(
        "nhi_lab_loinc", "NHI lab order code -> LOINC (NHIA PAS IG ConceptMap nhi-loinc)", "map", "ship",
        "https://packages.fhir.org/tw.gov.mohw.nhi.pas/1.3.0", "CC0 1.0 (public domain dedication)",
        "https://creativecommons.org/publicdomain/zero/1.0/",
        "The package is CC0-1.0 (package.json, checked by the parser). The targets are LOINC codes only, no LOINC "
        "names; LOINC codes stay under the LOINC licence (notice below), and the LOINC version is in the version.",
        f"臺灣健保署醫療服務給付項目對應LOINC (ConceptMap nhi-loinc), {NHIA}, 臺灣健保事前審查實作指引 (PAS IG). "
        "This material contains content from LOINC (http://loinc.org); LOINC is copyright Regenstrief Institute, "
        "Inc. and the LOINC Committee and is available at no cost under the license at http://loinc.org/license.",
        "with each IG release", "806 rows, 53 NHI codes (1.3.0); about 1.6 MB package",
        "Candidates (relatedto), not equivalents: site set-up suggests one only when the choice is clear.",
        "nhi_pas.tgz", country="TW", decision="D-171", parse=parse_nhi_lab_loinc, version_of=pas_version,
        sha256="1bdc33f3ca30733d0fa911a0de9fd4a2896312bb347c9122ffec3c2c210dcfe3",  # 1.3.0, read 2026-11-09
    ),
    Item(
        "naer_medical_terms", "NAER medical terms en <-> zh-TW (國家教育研究院 醫學學術名詞, data.gov.tw 15460)",
        "synonym", "ship",
        "https://opendata.naer.edu.tw/%E5%AD%B8%E8%A1%93%E5%90%8D%E8%A9%9E/%E5%9C%8B%E5%AE%B6%E6%95%99%E8%82%B2"
        "%E7%A0%94%E7%A9%B6%E9%99%A2-%E9%86%AB%E5%AD%B8%E5%AD%B8%E8%A1%93%E5%90%8D%E8%A9%9E.csv",
        OGDL, OGDL_URL, OGDL_TERMS,
        "國家教育研究院 醫學學術名詞 (National Academy for Educational Research), via data.gov.tw (dataset 15460), "
        "Open Government Data License 1.0.",
        "rarely (dataset modified 2026-08-12)", "30,797 terms, 2.1 MB CSV",
        "Academic translations: an English term lists several zh-TW names and senses, so matches are reviewed.",
        "naer_medical_terms.csv", country="TW", decision="D-172", parse=parse_naer_terms,
        read_meta=_datagov, licence_id=DATAGOV_OGDL,
        meta_url="https://data.gov.tw/api/v2/rest/dataset/15460",
    ),
    Item(
        "tw_zh_synonyms", "TrialBox zh-TW clinical synonyms and note abbreviations (curated)", "synonym", "ship",
        "repo:libs/tb_common/refdata_src/zh_tw_clinical_synonyms.csv", "TrialBox (own work)", "",
        "Written by the TrialBox team; shipped with the product.",
        "TrialBox zh-TW clinical synonyms, Aimedics.",
        "with releases", "42 entries",
        "Colloquial zh-TW words and Taiwanese note abbreviations -> the matcher's names; curated, no review.",
        "zh_tw_clinical_synonyms.csv", country="TW", decision="D-172", parse=parse_zh_tw_synonyms,
        version_of=synonyms_version,
    ),
)  # fmt: skip
