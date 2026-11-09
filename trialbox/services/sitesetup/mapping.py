"""Once-per-site mapping of the site's own codes (D-131, D-135).

A diagnosis code of the hospital's own list (a 病名 code), a JLAC10 or hospital lab code, a YJ drug code, a lab column
of a PI's sheet or a diagnosis written as words is a *local code*. Until a person maps it, it stays in a code system
TrialBox cannot read (``urn:trialbox:local:<kind>``) and D-130's rule applies: an inclusion that could only be met
through it is ``unknown`` (``unknown_code_system``), never a silent "no". :func:`suggest` proposes a standard code
from what TrialBox already has (the JP-Core lookups shipped with the adapter, the hospital lab table, the curated
terminology by name); a coordinator or an administrator confirms each one once, and the mapping applies to every
input of the site.
"""

from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from sitesetup import messy

LOCAL = "urn:trialbox:local"
KINDS = ("dx-code", "dx-text", "lab-code", "lab-column", "drug-code", "drug-name")
ICD10CM = "http://hl7.org/fhir/sid/icd-10-cm"
LOINC = "http://loinc.org"
ATC = "http://www.whocc.no/atc"
TARGET = {"condition": ICD10CM, "observation": LOINC, "medication": ATC}
MAPPING_DIR = Path(__file__).resolve().parents[1] / "adapter" / "mapping"
_ICD = re.compile(r"^[A-TV-Z]\d[0-9A-Z](\.[0-9A-Z]{1,4})?$")
_ATC = re.compile(r"^[A-Z]\d{2}[A-Z]{2}\d{2}$")
_LOINC = re.compile(r"^\d{1,6}-\d$")
_DRUG_WORDS = (
    (r"アロプリノール|allopurinol|別嘌呤醇", "M04AA01", "allopurinol"),
    (r"フェブキソスタット|febuxostat", "M04AA03", "febuxostat"),
    (r"ベンズブロマロン|benzbromarone", "M04AB03", "benzbromarone"),
    (r"コルヒチン|colchicine|秋水仙素", "M04AC01", "colchicine"),
    (r"メトホルミン|metformin", "A10BA02", "metformin"),
)


def local_system(kind: str) -> str:
    return f"{LOCAL}:{kind}"


def is_local(system: str) -> bool:
    return system.startswith(LOCAL)


def norm_code(text: str) -> str:
    return re.sub(r"\s+", " ", messy.half_width(text)).strip()[:80]


@lru_cache(maxsize=1)
def _lookups() -> dict[str, dict[str, tuple[str, str]]]:
    out: dict[str, dict[str, tuple[str, str]]] = {"dx": {}, "lab": {}, "drug": {}}
    files = (
        ("dx", MAPPING_DIR / "jp_core" / "byomei_to_icd10.csv", "code", "icd10", "name"),
        ("lab", MAPPING_DIR / "jp_core" / "jlac10_to_loinc.csv", "local_code", "code", "display"),
        ("lab", MAPPING_DIR / "tw_core" / "lab_local_to_loinc.csv", "local_code", "code", "display"),
        ("drug", MAPPING_DIR / "jp_core" / "yj_to_atc.csv", "yj_code", "atc", "name"),
    )
    for kind, path, key, val, disp in files:
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get(key) and r.get(val):
                    out[kind][r[key].strip().upper()] = (r[val].strip(), (r.get(disp) or "").strip())
    return out


@lru_cache(maxsize=1)
def _terminology() -> Any:
    from criteria_compiler.terminology.mapper import Terminology

    return Terminology()


def _by_name(domain: str, name: str) -> dict[str, str]:
    if not name:
        return {}
    if domain == "observation":
        analyte = messy.analyte_of(name)
        if analyte:
            a = messy.ANALYTES[analyte]
            return {"system": LOINC, "code": a.loinc, "display": analyte, "method": "name"}
    if domain == "medication":
        for rx, atc, disp in _DRUG_WORDS:
            if re.search(rx, name, re.I):
                return {"system": ATC, "code": atc, "display": disp, "method": "name"}
    try:
        res = _terminology().map(domain, name)
        concepts = list(res.concepts)
        if not concepts:
            concepts = _terminology().candidates(domain, [name.lower()], 1)
    except Exception:
        return {}
    if not concepts:
        return {}
    c = concepts[0]
    return {"system": c.system, "code": c.code, "display": c.display, "method": "name"}


def suggest(domain: str, system: str, code: str, display: str = "") -> dict[str, str]:
    """A suggested standard code for one local code: ``{system, code, display, method}`` (``lookup``: the shipped
    table for this code; ``same``: the code already is a standard code; ``name``: found by its name), or ``{}``."""
    kind = system.rsplit(":", 1)[-1]
    up = code.strip().upper()
    lk = _lookups()
    if kind == "dx-code":
        if up in lk["dx"]:
            icd, name = lk["dx"][up]
            return {"system": ICD10CM, "code": icd, "display": name, "method": "lookup"}
        if _ICD.match(up):
            return {"system": ICD10CM, "code": up, "display": display, "method": "same"}
    if kind == "lab-code":
        if up in lk["lab"]:
            loinc, name = lk["lab"][up]
            return {"system": LOINC, "code": loinc, "display": name, "method": "lookup"}
        if _LOINC.match(up):
            return {"system": LOINC, "code": up, "display": display, "method": "same"}
    if kind == "drug-code":
        if up in lk["drug"]:
            atc, name = lk["drug"][up]
            return {"system": ATC, "code": atc, "display": name, "method": "lookup"}
        if _ATC.match(up):
            return {"system": ATC, "code": up, "display": display, "method": "same"}
    return _by_name(domain, display or code)


def valid_target(domain: str, system: str, code: str) -> bool:
    """A mapping a person may confirm: a code of the domain's standard system, in its shape."""
    if TARGET.get(domain) != system:
        return False
    rx = {"condition": _ICD, "observation": _LOINC, "medication": _ATC}[domain]
    return bool(rx.match(code.strip().upper()))
