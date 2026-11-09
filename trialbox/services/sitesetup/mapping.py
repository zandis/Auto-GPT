"""Once-per-site mapping of the site's own codes (D-131, D-135).

A diagnosis code of the hospital's own list (a 病名 code), a JLAC10 or hospital lab code, a YJ drug code, a lab column
of a PI's sheet or a diagnosis written as words is a *local code*. Until a person maps it, it stays in a code system
TrialBox cannot read (``urn:trialbox:local:<kind>``) and D-130's rule applies: an inclusion that could only be met
through it is ``unknown`` (``unknown_code_system``), never a silent "no". :func:`suggest` proposes a standard code
from what TrialBox already has (the JP-Core lookups shipped with the adapter, the hospital lab table, the curated
terminology by name); a coordinator or an administrator confirms each one once, and the mapping applies to every
input of the site.

A diagnosis found by its name (scenario run MAP-01: 胃癌 and 乳癌 were suggested C22.0 and 本態性高血圧症 E78.5 by a
shared character) is matched whole, never by a piece of it: first a known diagnosis name (``dx_names.csv`` and the
JP-Core 病名 table), then an ICD-10 title in Chinese or English, both after normalising width, case, punctuation and
the Japanese forms of characters (圧 = 壓). Each suggestion carries a ``confidence``; a name that matches nothing
whole, or two codes of different categories, gets no suggestion: the coordinator types the code.
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


# Japanese (shinjitai) forms of characters whose Traditional Chinese form the ICD-10 titles use
_JA_TO_ZH = str.maketrans(
    {"圧": "壓", "悪": "惡", "関": "關", "発": "發", "脳": "腦", "気": "氣", "臓": "臟", "単": "單", "帯": "帶",
     "続": "續", "広": "廣", "変": "變", "経": "經", "様": "樣", "険": "險", "粛": "肅"}
)  # fmt: skip
_PUNCT = re.compile(r"[\s、，,。.・·:：;；()（）\[\]［］「」『』\-ー－‐]+")
MIN_CONFIDENCE = 0.8  # below this no suggestion is shown


def norm_term(text: str) -> str:
    """A diagnosis name for matching: full width to half, lower case, no spaces or punctuation, Japanese character
    forms as the Traditional Chinese titles write them."""
    t = messy.half_width(text).lower()
    return _PUNCT.sub("", t).translate(_JA_TO_ZH)


@lru_cache(maxsize=1)
def _dx_index() -> dict[str, list[tuple[float, str, str, str]]]:
    """Normalised name -> [(confidence, ICD-10 code, display, method)]: known diagnosis names (``term``: 1.0 from
    ``dx_names.csv``, 0.95 from the JP-Core 病名 table), ICD-10 titles in Chinese and English (0.9, ``title``) and a
    title's head before its first comma (0.85)."""
    idx: dict[str, list[tuple[float, str, str, str]]] = {}

    def add(name: str, conf: float, code: str, display: str, method: str) -> None:
        key = norm_term(name)
        if key and not any(c == code and m == method for _, c, _, m in idx.get(key, [])):
            idx.setdefault(key, []).append((conf, code, display, method))

    with (Path(__file__).with_name("dx_names.csv")).open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            add(r["name"], 1.0, r["icd10"], r["name"], "term")
    path = MAPPING_DIR / "jp_core" / "byomei_to_icd10.csv"
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("name") and r.get("icd10"):  # the shipped 病名 sample: below the curated names
                    add(r["name"], 0.95, r["icd10"], r["name"], "term")
    try:
        rows = _terminology().rows.get("icd10cm", [])
    except Exception:  # no terminology tables: names and the 病名 table only
        rows = []
    for r in rows:
        for k in ("display_zh", "display"):
            title = str(r.get(k) or "")
            if title:
                add(title, 0.9, r["code"], title, "title")
                head = re.split(r"[，,]", title)[0]
                if head != title:
                    add(head, 0.85, r["code"], title, "title")
    return idx


def _dx_by_name(name: str) -> dict[str, str]:
    """The best whole-name match for a diagnosis, or ``{}`` when there is none or it is not clear (MAP-01)."""
    hits = _dx_index().get(norm_term(name)) or []
    if not hits:
        return {}
    best = max(h[0] for h in hits)
    top = sorted({(c, d, m) for conf, c, d, m in hits if conf == best})
    codes = sorted({c for c, _d, _m in top})
    if len(codes) > 1:
        if len({c.split(".")[0] for c in codes}) > 1:
            return {}  # two diseases by this name: no guess
        best -= 0.05  # one category, several codes: the first, with less confidence
    if best < MIN_CONFIDENCE:
        return {}
    code, display, method = top[0]
    return {"system": ICD10CM, "code": code, "display": display, "method": method, "confidence": f"{best:.2f}"}


def _by_name(domain: str, name: str) -> dict[str, str]:
    if not name:
        return {}
    if domain == "observation":
        analyte = messy.analyte_of(name)
        if analyte:
            a = messy.ANALYTES[analyte]
            return {"system": LOINC, "code": a.loinc, "display": analyte, "method": "name", "confidence": "0.90"}
    if domain == "medication":
        for rx, atc, disp in _DRUG_WORDS:
            if re.search(rx, name, re.I):
                return {"system": ATC, "code": atc, "display": disp, "method": "name", "confidence": "0.90"}
    if domain == "condition":
        found = _dx_by_name(name)
        if found:
            return found
    try:  # an exact name or a curated synonym of the terminology; never a partial (lexical) candidate
        res = _terminology().map(domain, name)
    except Exception:
        return {}
    concepts = list(res.concepts)
    if not concepts or res.method not in ("exact", "synonym") or res.needs_review:
        return {}
    if len({c.code.split(".")[0] for c in concepts}) > 1:
        return {}  # a grouper (several diseases) is not one code
    c = concepts[0]
    conf = 0.9 if len(concepts) == 1 else 0.85
    return {"system": c.system, "code": c.code, "display": c.display, "method": "name", "confidence": f"{conf:.2f}"}


def _licensed(kind: str, code: str) -> dict[str, str] | None:
    """The site's licensed release's row for a code (D-137): MEDIS 病名, JLAC10 or YJ, when one is loaded."""
    from adapter import licensed

    lst = {"dx-code": "medis", "lab-code": "jlac10", "drug-code": "yj"}.get(kind)
    if lst is None:
        return None
    try:
        return licensed.tables(cached=True).get(lst, {}).get(code)
    except Exception:  # no trial database here: nothing is loaded
        return None


def suggest(domain: str, system: str, code: str, display: str = "") -> dict[str, str]:
    """A suggested standard code for one local code: ``{system, code, display, method}`` (``licensed``: the site's
    licensed MEDIS / JLAC10 / YJ release, its standard code or the name it gives; ``lookup``: the shipped table for
    this code; ``same``: the code already is a standard code; ``term``: a known diagnosis name; ``title``: an ICD-10
    title; ``name``: found by its name; ``refdata``: a map of the reference data pack, D-170 / D-171: NHI drug ->
    ATC, NHI lab -> LOINC, and at Taiwan sites a 2014 ICD-10-CM code -> its 2023 code) with its ``confidence``
    (0..1), or ``{}`` when TrialBox is not sure."""
    kind = system.rsplit(":", 1)[-1]
    up = code.strip().upper()
    lic = _licensed(kind, up)
    if lic is not None:
        target = lic.get("target_code") or ""
        if target and valid_target(domain, TARGET.get(domain, ""), target):
            return {
                "system": TARGET[domain],
                "code": target,
                "display": lic.get("display") or display,
                "method": "licensed",
                "confidence": "1.00",
            }
        by_name = _by_name(domain, lic.get("display") or "")
        if by_name:
            return {**by_name, "method": "licensed", "confidence": "1.00"}
    lk = _lookups()
    if kind == "dx-code":
        if up in lk["dx"]:
            icd, name = lk["dx"][up]
            return {"system": ICD10CM, "code": icd, "display": name, "method": "lookup", "confidence": "1.00"}
        moved = _tw_2014(up) if site_country() == "TW" else None
        if moved is not None:
            return moved
        if _ICD.match(up):
            return {"system": ICD10CM, "code": up, "display": display, "method": "same", "confidence": "1.00"}
    if kind == "lab-code":
        if up in lk["lab"]:
            loinc, name = lk["lab"][up]
            return {"system": LOINC, "code": loinc, "display": name, "method": "lookup", "confidence": "1.00"}
        if _LOINC.match(up):
            return {"system": LOINC, "code": up, "display": display, "method": "same", "confidence": "1.00"}
        nhi = _nhi_lab(up)
        if nhi:
            return nhi
    if kind == "drug-code":
        if up in lk["drug"]:
            atc, name = lk["drug"][up]
            return {"system": ATC, "code": atc, "display": name, "method": "lookup", "confidence": "1.00"}
        if _ATC.match(up):
            return {"system": ATC, "code": up, "display": display, "method": "same", "confidence": "1.00"}
        nhi = _nhi_drug(up)
        if nhi:
            return nhi
    return _by_name(domain, display or code)


# ------------------------------------------------------------- the Taiwan maps of the reference data (D-170, D-171)
def _refdata(system: str, code: str) -> list[dict[str, Any]]:
    from tb_common.refdata import map_targets_or_empty

    return map_targets_or_empty(system, code)


def _nhi_drug(code: str) -> dict[str, str]:
    """An NHI 藥品代號 -> the ATC code the NHIA list gives (``refdata``), when it is a full (level 5) code."""
    from tb_common import refdata_tw as tw

    atc = {t["target_code"] for t in _refdata(tw.NHI_DRUG, code) if _ATC.match(t["target_code"])}
    if len(atc) != 1:
        return {}
    # 0.90, not 1.00: the ATC class is wider than the product (relation ``wider``)
    return {"system": ATC, "code": atc.pop(), "display": "", "method": "refdata", "confidence": "0.90"}


def _nhi_lab(code: str) -> dict[str, str]:
    """An NHI lab order code -> LOINC from the NHIA ConceptMap. Its targets are candidates (relatedto): one target is
    a suggestion at 0.90; when there are several, the one that is also in TrialBox's curated lab table is offered at
    0.80 only (that says what TrialBox knows, not which specimen or method the hospital uses: a person confirms);
    otherwise none (the coordinator picks)."""
    from tb_common import refdata_tw as tw

    rows = _refdata(tw.NHI_SERVICE, code)
    loinc = sorted({t["target_code"] for t in rows if _LOINC.match(t["target_code"])})
    conf = "0.90"
    if len(loinc) > 1:
        loinc, conf = [c for c in loinc if c in _known_loinc()], "0.80"
    if len(loinc) != 1:
        return {}
    disp = next((t["source_display"] for t in rows), "")
    return {"system": LOINC, "code": loinc[0], "display": disp, "method": "refdata", "confidence": conf}


@lru_cache(maxsize=1)
def _known_loinc() -> frozenset[str]:
    try:
        return frozenset(c.code for c in _terminology().expand("loinc", "", "prefix"))
    except Exception:
        return frozenset()


def site_country() -> str | None:
    """``TW``, ``JP`` or None from the site's settings (time zone, else page locale)."""
    try:
        from tb_common.config import get_config
        from tb_common.derived import country_of

        cfg = get_config()
        return country_of(cfg.env.tz, cfg.settings.site.locale)
    except Exception:
        return None


def _tw_2014(code: str) -> dict[str, str] | None:
    """Taiwan sites only. A TW 2014-edition ICD-10-CM code that the 2023 edition no longer has (NHIA map): one 2023
    code -> that code;
    several (a split) -> no suggestion, the coordinator picks. None when the code is still a 2023 code (I10 stays
    I10 although I16 was split out of it) or the map does not know it."""
    from tb_common import refdata_tw as tw

    rows = _refdata(tw.ICD_CM_2014, code)
    targets = sorted({t["target_code"] for t in rows})
    if not rows or code in targets:
        return None
    if len(targets) == 1 and _ICD.match(targets[0]):
        return {"system": ICD10CM, "code": targets[0], "display": rows[0]["target_display"], "method": "refdata",
                "confidence": "0.90"}  # fmt: skip
    return {}


def valid_target(domain: str, system: str, code: str) -> bool:
    """A mapping a person may confirm: a code of the domain's standard system, in its shape."""
    if TARGET.get(domain) != system:
        return False
    rx = {"condition": _ICD, "observation": _LOINC, "medication": _ATC}[domain]
    return bool(rx.match(code.strip().upper()))
