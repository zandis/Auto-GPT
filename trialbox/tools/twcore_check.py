"""TW Core conformance of the adapter's output in CI (T-619a, STD-011, T-STD-05): the HL7 validator on 200 resources.

Synthetic site A (``tools/make_fixtures.py``) is mapped with ``tw_core/demo_his.yaml`` (no database, no pid map: the
mapping engine alone), 200 resources are chosen (first the ones that carry each TW Core slice's code system, then
every resource type in turn, in a fixed hash order), and the HL7 validator CLI checks them against TW Core 1.0.0
offline (``TB_HL7_VALIDATOR_JAR``, ``TB_FHIR_PACKAGE_HOME``: ``make jvm-deps`` fills both). It passes when

* no resource has an error or a fatal issue, and
* each TW Core slice the mapping fills is matched by the validator at least once (the coding is not reported as
  "does not match any known slice"). ICD-10-CM 2023 TW is the exception, and is reported: its ValueSet keeps only the
  codes with ``USE = 1``, a property the package's extract of the code system holds for 11 codes, so offline no real
  code can be shown to belong (the national terminology service has the full list).

    python -m tools.twcore_check                      # exit 1 on an error or an unmatched slice
    python -m tools.twcore_check --n 200 --json twcore.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from collections import deque
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

MAPPING = ROOT / "services" / "adapter" / "mapping" / "tw_core" / "demo_his.yaml"
CS = "https://twcore.mohw.gov.tw/ig/twcore/CodeSystem/"
IG = "tw.gov.mohw.twcore#1.0.0"


class Slice:
    def __init__(self, name: str, rtype: str, path: str, expr: str, system: str, offline: str = "") -> None:
        self.name, self.rtype, self.path, self.expr, self.system = name, rtype, path, expr, system
        self.offline = offline  # why the slice cannot be shown matched offline ("" = it must be)


SLICES = (
    Slice("Condition.code.coding:icd10-cm-2014", "Condition", "code.coding", "code.coding", CS + "icd-10-cm-2014-tw"),
    Slice(
        "Condition.code.coding:icd10-cm-2023",
        "Condition",
        "code.coding",
        "code.coding",
        CS + "icd-10-cm-2023-tw",
        offline="ValueSet filter USE = 1 on an 11-code extract of the code system",
    ),
    Slice(
        "MedicationRequest.medicationCodeableConcept.coding:nhi-medication-tw",
        "MedicationRequest",
        "medicationCodeableConcept.coding",
        "medication.ofType(CodeableConcept).coding",
        CS + "medication-nhi-tw",
    ),
    Slice(
        "Procedure.code.coding:medical-service-payment",
        "Procedure",
        "code.coding",
        "code.coding",
        CS + "medical-service-payment-tw",
    ),
    Slice(
        "Encounter.serviceType.coding:TWMedicalConsultationDepartment",
        "Encounter",
        "serviceType.coding",
        "serviceType.coding",
        CS + "medical-consultation-department-nhi-tw",
    ),
)


def _codings(r: dict[str, Any], path: str) -> list[dict[str, Any]]:
    cur: Any = r
    for part in path.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur if isinstance(cur, list) else []


def _slot(r: dict[str, Any], sl: Slice) -> int | None:
    """The index of the coding of ``sl``'s code system in ``r``, if it has one."""
    if r.get("resourceType") != sl.rtype:
        return None
    return next((i for i, c in enumerate(_codings(r, sl.path)) if c.get("system") == sl.system), None)


def mapped(synth: Path) -> list[dict[str, Any]]:
    """Site A's resources as the TW mapping writes them (mapping engine only: no pid map, no database)."""
    from adapter.mapping.engine import Mapper, Mapping
    from adapter.pipeline import make_source

    m = Mapping.load(MAPPING)
    src = make_source("csv", str(synth))
    mapper = Mapper(m, b"twcore-check-site-key-0123456789abcdef", "CI")
    out: list[dict[str, Any]] = []
    for table, t in m.tables.items():
        out += list(mapper.map_table(table, iter(src.rows(table, t["source"], None, None))))
    return out


def choose(resources: list[dict[str, Any]], n: int, per_slice: int = 3) -> list[dict[str, Any]]:
    """``n`` resources: ``per_slice`` carriers of each slice's code system first, then each type in turn."""

    def h(r: dict[str, Any]) -> str:
        return hashlib.sha256(f"twcore|{r['resourceType']}|{r['id']}".encode()).hexdigest()

    ordered = sorted(resources, key=h)
    chosen: dict[tuple[str, str], dict[str, Any]] = {}
    for sl in SLICES:
        for r in [x for x in ordered if _slot(x, sl) is not None][:per_slice]:
            chosen[(r["resourceType"], r["id"])] = r
    queues: dict[str, deque[dict[str, Any]]] = {}
    for r in ordered:
        queues.setdefault(r["resourceType"], deque()).append(r)
    while len(chosen) < n and any(queues.values()):
        for rtype in sorted(queues):
            if queues[rtype] and len(chosen) < n:
                r = queues[rtype].popleft()
                chosen.setdefault((r["resourceType"], r["id"]), r)
    return list(chosen.values())[:n]


def _merge(v: Any, picked: list[dict[str, Any]], groups: list[list[int]]) -> Any:
    """One validator result for ``picked``, validated in ``groups`` (indexes into ``picked``) by separate runs."""
    from adapter.validate.validator import ValidationResult

    out = ValidationResult("hl7-validator", 0, 0)
    for group in groups:
        if not group:
            continue
        part = v.validate([picked[i] for i in group], ["-level", "hints"])
        out.sampled += part.sampled
        out.errors += part.errors
        out.messages += part.messages
        for j, i in enumerate(group):
            out.per_file[i] = part.per_file.get(j, [])
            out.unsliced[i] = part.unsliced.get(j, [])
    return out


def run(synth: Path, n: int) -> dict[str, Any]:
    from adapter.validate.validator import Hl7Validator

    v = Hl7Validator.from_env()
    if v is None:
        raise SystemExit("the HL7 validator is not set up: make jvm-deps (TB_HL7_VALIDATOR_JAR, TB_FHIR_PACKAGE_HOME)")
    if IG not in v.igs:
        v.igs = [*v.igs, IG]
    picked = choose(mapped(synth), n)
    # the validator 6.10.4 keeps state between the files of one run: after a body-height Observation (whose base
    # profile binds UCUM) it can no longer place any MimeType code, and every later DocumentReference fails
    # Attachment.contentType. Each part alone validates clean, so notes and the rest are checked in two runs
    notes = [i for i, r in enumerate(picked) if r["resourceType"] == "DocumentReference"]
    rest = [i for i in range(len(picked)) if i not in set(notes)]
    res = _merge(v, picked, [notes, rest])
    slices: dict[str, Any] = {}
    for sl in SLICES:
        carriers = [(i, k) for i, r in enumerate(picked) if (k := _slot(r, sl)) is not None]
        hit = sum(1 for i, k in carriers if f"{sl.rtype}.{sl.expr}[{k}]" not in res.unsliced.get(i, []))
        slices[sl.name] = {"carriers": len(carriers), "matched": hit, "offline_limit": sl.offline or None}
    types: dict[str, int] = {}
    for r in picked:
        types[r["resourceType"]] = types.get(r["resourceType"], 0) + 1
    problems = []
    if res.sampled < n:
        problems.append(f"only {res.sampled} resources validated (want {n})")
    if res.errors:
        problems.append(f"{res.errors} resource(s) with errors: {res.messages[:10]}")
    for name, s in slices.items():
        if not s["matched"] and not s["offline_limit"]:
            problems.append(f"slice {name} never matched ({s['carriers']} carrier(s))")
    return {
        "ig": IG,
        "validator": res.validator,
        "sampled": res.sampled,
        "errors": res.errors,
        "types": dict(sorted(types.items())),
        "slices": slices,
        "problems": problems,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--synth", type=Path, help="a synthetic site folder (default: site A made afresh)")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="tb-twcore-") as td:
        synth = a.synth
        if synth is None:
            from tools.make_fixtures import main as make_fixtures

            make_fixtures(["--out", td, "--sites", "a"])
            synth = Path(td) / "site-a"
        report = run(synth, a.n)
    print(f"{report['ig']}: {report['sampled']} resources, {report['errors']} with errors ({report['validator']})")
    print(f"types: {report['types']}")
    for name, s in report["slices"].items():
        note = f" (offline limit: {s['offline_limit']})" if s["offline_limit"] else ""
        print(f"slice {name}: matched {s['matched']} of {s['carriers']}{note}")
    for p in report["problems"]:
        print(f"problem: {p}")
    if a.json:
        a.json.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("TW Core: FAIL" if report["problems"] else "TW Core: PASS")
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
