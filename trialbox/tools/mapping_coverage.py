"""How many of a site's codes reach the code systems the shipped criteria use, by domain (lane M; site data page).

    python -m tools.mapping_coverage <lists>... [--json OUT] [--lab-lookup CSV] [--jlac10 CSV] [--byomei CSV] [--yj CSV]
    python -m tools.mapping_coverage --synthetic tw|jp [--json OUT]
    python -m tools.mapping_coverage --write-synthetic tw|jp --out DIR
    python -m tools.mapping_coverage --criteria-table

A *list* is a CSV file (or a folder of them) of a site's code dictionary: one row per code, with the columns
``local_code``, ``local_name`` and ``system``, and an optional ``target_code`` (the code the site's own table already
gives it, an ATC column of a drug master, say). No patient row: the file is a dictionary. ``system`` names the code
system the site wrote the code in (see :data:`SYSTEMS`): a standard one the criteria use (``icd-10-cm``, ``loinc``,
``atc``, ``nhi-order``, ``department``), a national one with a cross-walk (``icd-10`` WHO, ``medis``, ``jlac10``,
``yj``, ``nhi-drug``, ``local-lab``), or one with no cross-walk yet (``jlac11``, ``hot``, ``jp-procedure``,
``icd-9-cm``, ``local-*``).

The check runs on every list, also on codes already in a standard system: a code "maps" when it reaches a
well-formed (for ICD-10-CM: existing) code of the domain's criteria system, by the route the adapter takes today
(the lookups shipped beside the mappings, or the ones given). It reports, per domain, the codes, how many map and by
which route, and every code that does not, with why. Then, per ruleset value set, how many of the site's codes fall
in it: a value set no site code reaches is a criterion that can only read unknown at that site. 100 % is a result,
printed like any other figure.

``--synthetic`` builds the lists of the shipped synthetic hospitals (``tools.synth`` catalogue: the TW-style CSV
site, and the same codes as the SS-MIX2 export writes them for the JP-style site) and checks them.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _p in ("libs", "services", ""):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

MAPPING = ROOT / "services" / "adapter" / "mapping"
TERMINOLOGY = ROOT / "services" / "criteria_compiler" / "terminology"
RULESETS = ROOT / "rulesets"
COLUMNS = ("local_code", "local_name", "system")

#: the criteria's code systems, by the short name this tool prints, and the value-set system URL
TARGETS = {
    "icd-10-cm": "http://hl7.org/fhir/sid/icd-10-cm",
    "loinc": "http://loinc.org",
    "clinical-score": "https://trialbox.local/fhir/CodeSystem/clinical-score",
    "atc": "http://www.whocc.no/atc",
    "nhi-order": "https://trialbox.local/fhir/CodeSystem/nhi-order",
    "jp-k-code": "https://trialbox.local/fhir/CodeSystem/jp-k-code",
    "department": "https://trialbox.local/fhir/CodeSystem/department",
}
TARGET_OF_URL = {v: k for k, v in TARGETS.items()}

#: domain -> the criteria systems a code of that domain must reach
DOMAINS = {
    "diagnosis": ("icd-10-cm",),
    "lab": ("loinc", "clinical-score"),
    "medication": ("atc",),
    "procedure": ("nhi-order", "jp-k-code"),
    "department": ("department",),
    "report": ("loinc",),
}

#: the criteria's IR domain -> this tool's domain (``observation`` of vital-sign codes only: ``vital``)
IR_DOMAIN = {
    "condition": "diagnosis",
    "observation": "lab",
    "medication": "medication",
    "procedure": "procedure",
    "encounter": "department",
    "report": "report",
}
#: LOINC codes the mappings write as constants from the export's vital-sign columns (height, weight, BMI, blood
#: pressure): no code list carries them, the export's columns do
VITAL_LOINC = {"8302-2", "29463-7", "39156-5", "8480-6", "8462-4"}

#: a site's system -> (domain, route). Route ``direct``: the code is already in the criteria system; a lookup name: the
#: cross-walk the adapter uses; ``none``: no cross-walk exists in the product today (a ``target_code`` can still map it)
SYSTEMS: dict[str, tuple[str, str]] = {
    "icd-10-cm": ("diagnosis", "direct"),
    "icd-10": ("diagnosis", "who-icd10"),
    "medis": ("diagnosis", "byomei"),
    "icd-9-cm": ("diagnosis", "none"),
    "local-diagnosis": ("diagnosis", "none"),
    "loinc": ("lab", "direct"),
    "local-lab": ("lab", "lab-lookup"),
    "jlac10": ("lab", "jlac10"),
    "jlac11": ("lab", "none"),
    "atc": ("medication", "direct"),
    "nhi-drug": ("medication", "nhi-drug"),
    "yj": ("medication", "yj"),
    "hot": ("medication", "none"),
    "local-drug": ("medication", "none"),
    "nhi-order": ("procedure", "direct"),
    "jp-procedure": ("procedure", "none"),
    "jp-k-code": ("procedure", "direct"),
    "local-order": ("procedure", "none"),
    "department": ("department", "direct"),
    "local-department": ("department", "department-table"),
    "local-report": ("report", "report-rule"),
}

#: the report exam codes a shipped mapping gives a LOINC code (tw_core/demo_his.yaml, the report's ``code.coding[0]``)
_REPORT_LOINC = {"RAD-CXR": ("loinc", "36643-5")}

_ICD10CM_SHAPE = re.compile(r"^[A-Z][0-9][0-9A-Z](\.[0-9A-Z]{1,4})?$")
_ATC5 = re.compile(r"^[A-V][0-9]{2}[A-Z]{2}[0-9]{2}$")
_NHI_ORDER = re.compile(r"^[0-9A-Z]{5}[A-Z]$")
_DEPT = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")
_LOINC = re.compile(r"^([0-9]{1,7})-([0-9])$")


def loinc_check_digit_ok(code: str) -> bool:
    """LOINC's mod-10 check digit (the Luhn form LOINC publishes) over the part before the hyphen."""
    m = _LOINC.match(code)
    if not m:
        return False
    digits = [int(c) for c in m.group(1)]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
            d *= 2
            d = d - 9 if d > 9 else d
        total += d
    return (10 - total % 10) % 10 == int(m.group(2))


def who_to_cm(who: str, ref: Reference) -> tuple[str, str] | None:
    """``(ICD-10-CM code, "same" | "table")`` for a WHO ICD-10 code: the very same code when ICD-10-CM has it (D-314),
    else the WHO-to-CM table's row; ``None`` when neither (the code stays on the unmapped list, never dropped)."""
    if who in ref.icd10cm or (not ref.icd10cm and _ICD10CM_SHAPE.match(who)):
        return who, "same"
    row = ref.who_cm.get(who.upper())
    return (row[1], "table") if row else None


def who_icd10(code: str) -> str:
    """The WHO ICD-10 spelling the SS-MIX2 reader writes (upper case, mark dropped, ``E149`` -> ``E14.9``)."""
    from adapter.sources.ssmix2.source import who_icd10 as _who

    return _who(code)


# --- reference tables -------------------------------------------------------------------------------------------


def _csv_map(path: Path, key: str, value: str, system: str | None = None) -> dict[str, tuple[str, str]]:
    """``{key: (target system, target code)}`` of a shipped or given lookup CSV."""
    out: dict[str, tuple[str, str]] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            k, v = (row.get(key) or "").strip(), (row.get(value) or "").strip()
            if not k or not v:
                continue
            sysname = system or {"score": "clinical-score"}.get((row.get("system") or "").strip(), "loinc")
            out[k.upper()] = (sysname, v)
    return out


DEPT_TABLE = MAPPING / "tw_core" / "department_to_trialbox.csv"  # the mapping's department look-up (SDR2)
WHO_CM = MAPPING / "jp_core" / "who_icd10_to_icd10cm.csv"  # the SS-MIX2 reader's table (SDR2)


def _verified_rows(path: Path) -> set[str]:
    """The ``who`` codes of the table's rows marked ``verified`` ``yes``; the others are applied and reported apart."""
    if not path.exists():
        return set()
    return {k for k, (_s, v) in _csv_map(path, "who", "verified").items() if v == "yes"}


def _parquet_column(name: str, *cols: str) -> list[tuple[str, ...]]:
    import pyarrow.parquet as pq

    path = TERMINOLOGY / name
    if not path.exists():
        return []
    t = pq.read_table(path, columns=list(cols), use_threads=False)
    return list(zip(*(t.column(c).to_pylist() for c in cols), strict=True))


@dataclass
class Reference:
    """The cross-walks and code lists a check reads; each defaults to the one shipped with the adapter."""

    lab: dict[str, tuple[str, str]]
    jlac10: dict[str, tuple[str, str]]
    byomei: dict[str, tuple[str, str]]
    yj: dict[str, tuple[str, str]]
    nhi_drug: dict[str, tuple[str, str]]
    stems: dict[str, tuple[str, str]]
    who_cm: dict[str, tuple[str, str]]
    who_cm_verified: set[str]
    departments_table: dict[str, tuple[str, str]]
    icd10cm: set[str]
    departments: set[str]
    sources: dict[str, str]

    @classmethod
    def load(
        cls,
        lab: Path | None = None,
        jlac10: Path | None = None,
        byomei: Path | None = None,
        yj: Path | None = None,
        ingredient_atc: Path | None = None,
        nhi_drug: Path | None = None,
        who_icd10cm: Path | None = None,
        department_table: Path | None = None,
    ) -> Reference:
        from tb_common import refdata_jp

        lab = lab or MAPPING / "tw_core" / "lab_local_to_loinc.csv"
        jlac10 = jlac10 or MAPPING / "jp_core" / "jlac10_to_loinc.csv"
        byomei = byomei or MAPPING / "jp_core" / "byomei_to_icd10.csv"
        yj = yj or MAPPING / "jp_core" / "yj_to_atc.csv"
        return cls(
            lab=_csv_map(lab, "local_code", "code"),
            jlac10=_csv_map(jlac10, "local_code", "code"),
            byomei=_csv_map(byomei, "code", "icd10", "icd-10"),
            yj=_csv_map(yj, "yj_code", "atc", "atc"),
            who_cm=_csv_map(who_icd10cm or WHO_CM, "who", "icd10cm", "icd-10-cm")
            if (who_icd10cm or WHO_CM).exists()
            else {},
            who_cm_verified=_verified_rows(who_icd10cm or WHO_CM),
            departments_table=_csv_map(department_table or DEPT_TABLE, "dept_code", "code", "department"),
            stems={
                k.upper(): ("atc", v["atc"])
                for k, v in refdata_jp.ingredient_atc(*([ingredient_atc] if ingredient_atc else [])).items()
            },
            nhi_drug=_csv_map(nhi_drug, "nhi_code", "atc", "atc")
            if nhi_drug
            else {str(c).upper(): ("atc", str(a)) for c, a in _parquet_column("nhi_drug.parquet", "nhi_code", "atc")},
            icd10cm={str(c) for (c,) in _parquet_column("icd10cm_full.parquet", "code")},
            departments={str(c) for (c,) in _parquet_column("department.parquet", "code")},
            sources={
                "lab-lookup": _rel(lab),
                "jlac10": _rel(jlac10),
                "byomei": _rel(byomei),
                "yj": _rel(yj),
                "yj-stem": "libs/tb_common/refdata_jp.py ingredient_atc"
                + (f" and {_rel(ingredient_atc)}" if ingredient_atc else ""),
                "nhi-drug": _rel(nhi_drug) if nhi_drug else "services/criteria_compiler/terminology/nhi_drug.parquet",
                "who-icd10": "services/criteria_compiler/terminology/icd10cm_full.parquet (the same code, D-314)",
                "department-table": _rel(department_table) if department_table else "none",
                "who-to-cm": _rel(who_icd10cm) if who_icd10cm else (_rel(WHO_CM) if WHO_CM.exists() else "none"),
                "report-rule": "services/adapter/mapping/tw_core/demo_his.yaml (the report code rule)",
            },
        )


def _rel(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(ROOT))
    except ValueError:
        return p.name  # a site's own file: its name only, never its folder


# --- the check --------------------------------------------------------------------------------------------------


@dataclass
class Result:
    domain: str
    system: str
    local_code: str
    local_name: str
    route: str  # direct, a lookup name, "site table", or "" when unmapped
    target_system: str
    target_code: str
    reason: str  # why it does not map; empty when it maps
    unverified: bool = False  # the map rests on a table row still marked ``verify`` (applied, reported apart)

    @property
    def mapped(self) -> bool:
        return not self.reason


def well_formed(target_system: str, code: str, ref: Reference) -> str:
    """Empty when ``code`` is a usable code of ``target_system``; else why not."""
    if target_system == "icd-10-cm":
        if not _ICD10CM_SHAPE.match(code):
            return "not an ICD-10-CM shape"
        if ref.icd10cm and code not in ref.icd10cm:
            return "not an ICD-10-CM code"
        return ""
    if target_system == "loinc":
        return "" if loinc_check_digit_ok(code) else "not a LOINC code (shape or check digit)"
    if target_system == "clinical-score":
        return "" if re.fullmatch(r"[A-Z0-9-]{2,20}", code) else "not a TrialBox score code"
    if target_system == "atc":
        return "" if _ATC5.match(code) else "not a level-5 ATC code (a substance)"
    if target_system == "nhi-order":
        return "" if _NHI_ORDER.match(code) else "not an NHI order-code shape"
    if target_system == "jp-k-code":
        return "" if re.fullmatch(r"K[0-9]{3}(-[0-9]+)?", code) else "not a 診療報酬点数表 K-code shape"
    if target_system == "department":
        if not _DEPT.match(code):
            return "not a department-code shape"
        return "" if not ref.departments or code in ref.departments else "not a TrialBox department code"
    return f"unknown target system {target_system}"


def check_code(row: dict[str, str], ref: Reference) -> Result:
    system = (row.get("system") or "").strip().lower()
    code = (row.get("local_code") or "").strip()
    name = (row.get("local_name") or "").strip()
    site_target = (row.get("target_code") or "").strip()
    if system not in SYSTEMS:
        return Result("unknown", system, code, name, "", "", "", f"system {system!r} not known to this check")
    domain, route = SYSTEMS[system]
    targets = DOMAINS[domain]

    def done(route_: str, tsys: str, tcode: str) -> Result:
        why = well_formed(tsys, tcode, ref) if tsys in targets else f"maps to {tsys}, not {'/'.join(targets)}"
        return Result(domain, system, code, name, route_ if not why else "", tsys, tcode, why)

    if not code:
        return Result(domain, system, code, name, "", "", "", "empty code")
    if route == "direct":
        c = code.upper() if system != "loinc" else code
        return done("direct", system if system in targets else targets[0], c)
    hit: tuple[str, str] | None = None
    if route in ("who-icd10", "byomei"):
        found = ref.byomei.get(code.upper()) if route == "byomei" else ("icd-10", code)
        if found:
            cm = who_to_cm(who_icd10(found[1]), ref)
            if cm:
                hit, route = ("icd-10-cm", cm[0]), (route if cm[1] == "same" else f"{route} + WHO-to-CM table")
                if cm[1] == "table" and who_icd10(found[1]).upper() not in ref.who_cm_verified:
                    r = done(route, *hit)
                    r.unverified = r.mapped
                    return r
            elif not site_target:
                why = "no same ICD-10-CM code and no row in the WHO-to-CM table"
                return Result(
                    domain, system, code, name, "", "icd-10-cm", who_icd10(found[1]), f"WHO ICD-10 code with {why}"
                )
    elif route == "lab-lookup":
        hit = ref.lab.get(code.upper())
    elif route == "jlac10":
        hit = ref.jlac10.get(code.upper())
    elif route == "yj":
        hit = ref.yj.get(code.upper())
        if not hit and len(code) >= 7 and ref.stems.get(code[:7].upper()):
            hit, route = ref.stems[code[:7].upper()], "yj-stem"  # the reader's ingredient route (T-610, STD-042)
    elif route == "nhi-drug":
        hit = ref.nhi_drug.get(code.upper())
    elif route == "department-table":
        hit = ref.departments_table.get(code.upper())
    elif route == "report-rule":
        hit = _REPORT_LOINC.get(code.upper())
    if hit:
        return done(route, hit[0], hit[1])
    if site_target:
        return done("site table", targets[0], site_target.upper() if targets[0] != "loinc" else site_target)
    if route == "none":
        return Result(domain, system, code, name, "", "", "", f"no cross-walk from {system} in the product today")
    return Result(domain, system, code, name, "", "", "", f"not in the {route} table")


def read_lists(paths: Iterable[Path]) -> list[dict[str, str]]:
    """The rows of every list CSV (a folder: each ``*.csv`` in it, sorted). A file without the columns is refused."""
    rows: list[dict[str, str]] = []
    for p in paths:
        files = sorted(p.glob("*.csv")) if p.is_dir() else [p]
        for f in files:
            rows += read_list_text(f.read_text(encoding="utf-8-sig"), f.name)
    return rows


def read_list_text(text: str, label: str = "list") -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text))
    header = [h.strip().lower() for h in reader.fieldnames or []]
    missing = [c for c in COLUMNS if c not in header]
    if missing:
        raise ValueError(f"{label}: missing column(s) {', '.join(missing)}")
    reader.fieldnames = header
    return [{k: (v or "") for k, v in r.items() if k} for r in reader]


# --- the criteria side -------------------------------------------------------------------------------------------


def criteria_valuesets(rulesets: Path = RULESETS) -> list[dict[str, Any]]:
    """Each shipped value set: ruleset, name, its (system, code) pairs and the criteria that read it."""
    used: dict[tuple[str, str], list[str]] = defaultdict(list)
    domains: dict[tuple[str, str], set[str]] = defaultdict(set)
    for f in sorted(rulesets.glob("*/ir/*.json")):
        ir = json.loads(f.read_text(encoding="utf-8"))
        key_rs = ir.get("ruleset", f.parent.parent.name)
        for vs, dom in sorted(set(_valueset_names(ir.get("logic")))):
            if ir.get("id", f.stem) not in used[(key_rs, vs)]:
                used[(key_rs, vs)].append(ir.get("id", f.stem))
            domains[(key_rs, vs)].add(dom)
    out = []
    for f in sorted(rulesets.glob("*/valuesets/*.json")):
        vs = json.loads(f.read_text(encoding="utf-8"))
        ruleset = f.parent.parent.name
        codes = {
            (TARGET_OF_URL.get(inc.get("system", ""), inc.get("system", "")), c["code"])
            for inc in (vs.get("compose") or {}).get("include") or []
            for c in inc.get("concept") or []
        }
        systems = sorted({s for s, _ in codes})
        name = vs.get("name", f.stem)
        doms = {IR_DOMAIN.get(d, d) for d in domains.get((ruleset, name), set())} or {"(no criterion)"}
        if doms == {"lab"} and {c for _s, c in codes} <= VITAL_LOINC:
            doms = {"vital"}
        out.append(
            {
                "ruleset": ruleset,
                "valueset": vs.get("name", f.stem),
                "systems": systems,
                "domain": "/".join(sorted(doms)),
                "codes": codes,
                "criteria": sorted(used.get((ruleset, vs.get("name", f.stem)), [])),
            }
        )
    return out


def _valueset_names(o: Any) -> Iterable[tuple[str, str]]:
    """``(value set, IR domain)`` of every leaf of a criterion's logic."""
    if isinstance(o, dict):
        vs = o.get("valueset")
        if isinstance(vs, str) and vs != "NONE":
            yield vs, str(o.get("domain", ""))
        for k, v in o.items():
            if k != "valueset":
                yield from _valueset_names(v)
    elif isinstance(o, list):
        for x in o:
            yield from _valueset_names(x)


def criteria_table(rulesets: Path = RULESETS) -> str:
    """A markdown table: each value set, its code systems, codes and the criteria that read it."""
    lines = [
        "| Ruleset | Value set | Domain | Code system | Codes | Criteria |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for v in criteria_valuesets(rulesets):
        crit = ", ".join(v["criteria"]) or "(none)"
        row = [v["ruleset"], v["valueset"], v["domain"], ", ".join(v["systems"]), str(len(v["codes"])), crit]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


# --- the report --------------------------------------------------------------------------------------------------


def coverage(rows: list[dict[str, str]], ref: Reference, rulesets: Path = RULESETS) -> dict[str, Any]:
    results = [check_code(r, ref) for r in rows]
    by_domain: dict[str, dict[str, Any]] = {}
    for d in [*DOMAINS, "unknown"]:
        rs = [r for r in results if r.domain == d]
        if not rs and d == "unknown":
            continue
        mapped = sum(r.mapped for r in rs)
        by_domain[d] = {
            "codes": len(rs),
            "mapped": mapped,
            "unmapped": len(rs) - mapped,
            "percent": round(100.0 * mapped / len(rs), 1) if rs else None,
            "routes": dict(sorted(Counter(r.route for r in rs if r.mapped).items())),
            "applied_not_verified": sum(r.unverified for r in rs),
            "systems": dict(sorted(Counter(r.system for r in rs).items())),
        }
    reached = {(r.target_system, r.target_code) for r in results if r.mapped}
    present = {d for d, v in by_domain.items() if v["codes"]}
    valuesets = []
    for v in criteria_valuesets(rulesets):
        hits = len(v["codes"] & reached)
        listed = bool(set(v["domain"].split("/")) & present)
        valuesets.append(
            {
                "ruleset": v["ruleset"],
                "valueset": v["valueset"],
                "systems": v["systems"],
                "domain": v["domain"],
                "site_codes": hits,
                "list_given": listed,
                "criteria": v["criteria"],
            }
        )
    return {
        "codes": len(results),
        "mapped": sum(r.mapped for r in results),
        "by_domain": by_domain,
        "applied_not_verified": [
            {"domain": r.domain, "system": r.system, "local_code": r.local_code, "target_code": r.target_code}
            for r in results
            if r.unverified
        ],
        "unmapped": [
            {
                "domain": r.domain,
                "system": r.system,
                "local_code": r.local_code,
                "local_name": r.local_name,
                "why": r.reason,
            }
            for r in results
            if not r.mapped
        ],
        "valuesets": valuesets,
        "valuesets_reached": sum(1 for v in valuesets if v["site_codes"]),
        "valuesets_not_reached": [
            f"{v['ruleset']}/{v['valueset']}" for v in valuesets if v["list_given"] and not v["site_codes"]
        ],
        "valuesets_without_list": sorted({v["domain"] for v in valuesets if not v["list_given"]}),
        "references": ref.sources,
    }


def render(report: dict[str, Any], title: str = "Mapping coverage") -> str:
    out = [f"{title}: {report['mapped']} of {report['codes']} codes map to the criteria's code systems"]
    for d, v in report["by_domain"].items():
        pct = "n/a (no list)" if v["percent"] is None else f"{v['percent']:.1f}%"
        routes = ", ".join(f"{k} {n}" for k, n in v["routes"].items()) or "-"
        out.append(f"  {d:<11} {v['mapped']:>5} / {v['codes']:<5} {pct:>14}   routes: {routes}")
        if d == "department" and v["codes"]:
            table = report.get("references", {}).get("department-table", "none")
            shown = table if table != "none" else "none (TrialBox's own codes only)"
            out.append(f"  {'':<11} department table: {shown}; {v['unmapped']} reach no TrialBox department code")
        if v.get("applied_not_verified"):
            out.append(
                f"  {'':<11} applied, not verified: {v['applied_not_verified']} (a table row still marked verify)"
            )
    if report["unmapped"]:
        out.append(f"Not mapped ({len(report['unmapped'])}):")
        for u in report["unmapped"]:
            out.append(f"  {u['domain']:<11} {u['system']:<12} {u['local_code']:<20} {u['local_name']}  ({u['why']})")
    else:
        out.append("Not mapped: none")
    vs = report["valuesets"]
    out.append(f"Value sets with at least one site code: {report['valuesets_reached']} of {len(vs)}")
    if report["valuesets_without_list"]:
        n = sum(1 for v in vs if not v["list_given"])
        doms = ", ".join(report["valuesets_without_list"])
        out.append(f"Value sets of a domain with no list given (not checked here): {n} ({doms})")
    if report["valuesets_not_reached"]:
        out.append("Value sets of a listed domain no site code reaches (their criteria read unknown at this site):")
        for v in vs:
            if v["list_given"] and not v["site_codes"]:
                out.append(
                    f"  {v['ruleset']}/{v['valueset']} ({', '.join(v['systems'])}): {', '.join(v['criteria']) or '-'}"
                )
    return "\n".join(out)


# --- the synthetic hospitals ------------------------------------------------------------------------------------


def synthetic_lists(style: str) -> dict[str, list[dict[str, str]]]:
    """The code dictionaries of the shipped synthetic hospital, by domain file name. ``tw``: the CSV site's codes as
    its HIS writes them; ``jp``: the same patients' codes as ``tools.ssmix2_export`` writes them (JLAC10, YJ,
    標準病名 sample codes; the score items stay hospital codes)."""
    from tools.synth import catalog as cat

    dx = {**cat.DX, **cat.AD_DX, **cat.RAJAK_DX}
    drugs = {**cat.DRUGS, **cat.AD_DRUGS, **cat.RAJAK_DRUGS}
    depts = sorted(set(cat.DEPTS) | set(cat.AD_DEPTS))
    procs = dict(cat.PROCS)
    reports = {**dict(cat.REPORT_EXAMS.values()), **{k: n for k, (n, _ja) in cat.AD_REPORT_EXAMS.items()}}
    if style == "tw":
        return {
            "diagnosis": [_row(c, n, "icd-10-cm") for c, n in sorted(set(dx.values()))],
            "lab": [_row(k, n, "local-lab") for k, (n, _u) in sorted(cat.LABS.items())],
            "medication": [
                _row(d.nhi_code, d.name, "nhi-drug", d.atc) for d in sorted(drugs.values(), key=lambda d: d.key)
            ],
            "procedure": [_row(c, n, "nhi-order") for c, n in sorted(set(procs.values()))],
            "department": [_row(d, d, "department") for d in depts],
            "report": [_row(c, n, "local-report") for c, n in sorted(reports.items())],
        }
    if style == "jp":
        from tools.ssmix2_export import _LOCAL_TO_JLAC10

        byomei = _rev_csv(MAPPING / "jp_core" / "byomei_to_icd10.csv", "icd10", "code", "name")
        yj = _rev_csv(MAPPING / "jp_core" / "yj_to_atc.csv", "atc", "yj_code", "name")
        diag = []
        for c, n in sorted(set(dx.values())):
            hit = byomei.get(c)
            diag.append(_row(hit[0], hit[1], "medis") if hit else _row(c, n, "icd-10"))
        lab = [
            _row(_LOCAL_TO_JLAC10[k], n, "jlac10") if k in _LOCAL_TO_JLAC10 else _row(k, n, "local-lab")
            for k, (n, _u) in sorted(cat.LABS.items())
        ]
        med = []
        for d in sorted(drugs.values(), key=lambda d: d.key):
            hit = yj.get(d.atc)
            # no YJ sample code: the export sends the hospital code with the ATC as its alternate (WHOATC), the
            # drug master's ATC column here
            med.append(_row(hit[0], hit[1], "yj") if hit else _row(d.nhi_code, d.name, "local-drug", d.atc))
        return {
            "diagnosis": diag,
            "lab": lab,
            "medication": med,
            "procedure": [_row(c, n, "nhi-order") for c, n in sorted(set(procs.values()))],
            "department": [_row(d, d, "department") for d in depts],
            "report": [_row(c, n, "local-report") for c, n in sorted(reports.items())],
        }
    raise ValueError(f"unknown synthetic style {style!r}: tw or jp")


def _row(code: str, name: str, system: str, target: str = "") -> dict[str, str]:
    return {"local_code": code, "local_name": name, "system": system, "target_code": target}


def _rev_csv(path: Path, key: str, code: str, name: str) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            out.setdefault(r[key].strip(), (r[code].strip(), r[name].strip()))
    return out


def write_lists(lists: dict[str, list[dict[str, str]]], out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, rows in lists.items():
        p = out / f"{name}.csv"
        with p.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=[*COLUMNS, "target_code"], lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
        written.append(p)
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.mapping_coverage", description=__doc__.split("\n\n")[0])
    ap.add_argument("lists", nargs="*", type=Path, help="code-list CSV files or folders of them")
    ap.add_argument("--synthetic", choices=("tw", "jp"), help="check the shipped synthetic hospital's lists")
    ap.add_argument("--write-synthetic", choices=("tw", "jp"), help="write the synthetic hospital's lists to --out")
    ap.add_argument("--out", type=Path, help="folder for --write-synthetic")
    ap.add_argument("--criteria-table", action="store_true", help="print the value sets and their criteria")
    ap.add_argument("--json", type=Path, help="also write the report as JSON")
    ap.add_argument("--lab-lookup", type=Path, help="local lab code -> LOINC CSV (default: tw_core sample)")
    ap.add_argument("--jlac10", type=Path, help="JLAC10 -> LOINC CSV (default: jp_core sample)")
    ap.add_argument("--byomei", type=Path, help="標準病名 -> ICD-10 CSV (default: jp_core sample)")
    ap.add_argument("--yj", type=Path, help="YJ -> ATC CSV (default: jp_core sample)")
    ap.add_argument("--nhi-drug", type=Path, help="NHI drug code -> ATC CSV (nhi_code,atc; the NHI open data list)")
    ap.add_argument(
        "--department-table", type=Path, help="hospital department -> TrialBox department CSV (dept_code,code)"
    )
    ap.add_argument("--who-icd10cm", type=Path, help="WHO ICD-10 -> ICD-10-CM CSV (who,icd10cm)")
    ap.add_argument("--ingredient-atc", type=Path, help="the site's YJ stem -> ATC table (beside the shipped one)")
    a = ap.parse_args(argv)
    if a.criteria_table:
        print(criteria_table())
        return 0
    if a.write_synthetic:
        if not a.out:
            ap.error("--write-synthetic needs --out")
        for p in write_lists(synthetic_lists(a.write_synthetic), a.out):
            print(p)
        return 0
    if a.synthetic:
        rows = [r for rs in synthetic_lists(a.synthetic).values() for r in rs]
        title = f"Mapping coverage, synthetic {a.synthetic.upper()} hospital"
    elif a.lists:
        try:
            rows = read_lists(a.lists)
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
        title = "Mapping coverage"
    else:
        ap.error("give code lists, --synthetic, --write-synthetic or --criteria-table")
    ref = Reference.load(
        a.lab_lookup, a.jlac10, a.byomei, a.yj, a.ingredient_atc, a.nhi_drug, a.who_icd10cm, a.department_table
    )
    report = coverage(rows, ref)
    print(render(report, title))
    if a.json:
        report_out = {**report, "valuesets": [{**v} for v in report["valuesets"]]}
        a.json.write_text(json.dumps(report_out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
