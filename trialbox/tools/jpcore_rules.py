"""Build the JP Core rules the offline ``$validate`` checks against (TB-PLAN-04 step 7, D-137).

The box has no internet and the HL7 validator needs the R4 core package beside JP Core to snapshot the profiles, so
the ingest's JP Core check is a pure-Python one (``adapter.validate.jpcore``) that reads a small rules file derived
from the JP Core package's StructureDefinitions: for each profile its parent, and from its differential the
cardinalities, fixed and pattern values, slices and their discriminators, and bindings, with the codes of the
ValueSets bound ``required`` where the package enumerates them. The rules file is committed; the package is not.

Build time only (never at runtime, never in tests): ``--fetch`` downloads the pinned package into ``.cache/fhir/``
and checks its sha256 and the registry's sha1 before anything reads it; ``--package`` uses a copy already on disk.

    python -m tools.jpcore_rules --fetch            # writes services/adapter/validate/jp_core_rules.json
    python -m tools.jpcore_rules --package jp-core.r4-1.1.0.tgz --check
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tarfile
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "services" / "adapter" / "validate" / "jp_core_rules.json"
CACHE = ROOT / ".cache" / "fhir"
PACKAGE = {
    "id": "jp-core.r4",
    "version": "1.1.0",
    "url": "https://packages.simplifier.net/jp-core.r4/1.1.0",
    "registry": "https://packages.fhir.org/jp-core.r4",
    "sha1": "b57586047ebff666f39875155b1ebedbace9ccef",  # the registry's dist.shasum
    "sha256": "60567c583943150c26275f156d63c181e5608efcdf0616289a7fe5c032457da1",
}
BASE = "http://jpfhir.jp/fhir/core/StructureDefinition/"
PROFILES = (
    "JP_Patient",
    "JP_Practitioner",
    "JP_Organization",
    "JP_Encounter",
    "JP_Condition",
    "JP_AllergyIntolerance",
    "JP_Observation_Common",
    "JP_Observation_LabResult",
    "JP_Observation_VitalSigns",
    "JP_Observation_BodyMeasurement",
    "JP_MedicationRequestBase",
    "JP_MedicationRequest",
    "JP_MedicationRequest_Injection",
    "JP_Procedure",
    "JP_DiagnosticReport_Common",
    "JP_Coverage",
)
_VALUE_KEYS = ("fixed", "pattern")


def fetch() -> Path:
    """Download the pinned package into ``.cache/fhir`` (build time) and check both hashes."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{PACKAGE['id']}-{PACKAGE['version']}.tgz"
    if not path.exists():
        req = urllib.request.Request(PACKAGE["url"], headers={"User-Agent": "trialbox-build/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)
    check(path.read_bytes())
    return path


def check(data: bytes) -> None:
    got256, got1 = hashlib.sha256(data).hexdigest(), hashlib.sha1(data).hexdigest()
    if got256 != PACKAGE["sha256"] or got1 != PACKAGE["sha1"]:
        raise SystemExit(f"JP Core package hash mismatch: sha256 {got256}, sha1 {got1}")


def _files(data: bytes) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for m in tar.getmembers():
            name = m.name.removeprefix("package/")
            if not m.isfile() or "/" in name or not name.endswith(".json"):
                continue
            fh = tar.extractfile(m)
            if fh is None:
                continue
            doc = json.loads(fh.read().decode("utf-8-sig"))
            if isinstance(doc, dict) and doc.get("url"):
                out[doc["url"]] = doc
    return out


def _element(e: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"id": e["id"], "path": e["path"]}
    for k in ("min", "max", "sliceName"):
        if k in e:
            out[k] = e[k]
    for k, v in e.items():
        if k.startswith(_VALUE_KEYS) and k not in ("fixed", "pattern"):
            out["value"] = {"kind": "fixed" if k.startswith("fixed") else "pattern", "type": k, "value": v}
    if "slicing" in e:
        s = e["slicing"]
        out["slicing"] = {"discriminator": s.get("discriminator") or [], "rules": s.get("rules", "open")}
    if "binding" in e:
        b = e["binding"]
        out["binding"] = {"strength": b.get("strength"), "valueSet": (b.get("valueSet") or "").split("|")[0]}
    return out


def _valueset(vs: dict[str, Any], docs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """``{systems: [...], codes: {system: [...]} | None}``: codes only when every include is enumerable."""
    systems: list[str] = []
    codes: dict[str, list[str]] = {}
    complete = True
    for inc in (vs.get("compose") or {}).get("include") or []:
        system = inc.get("system")
        if not system:
            complete = False
            continue
        systems.append(system)
        if inc.get("concept"):
            codes.setdefault(system, []).extend(c["code"] for c in inc["concept"])
        elif inc.get("filter"):
            complete = False
        else:
            cs = docs.get(system)
            if cs and cs.get("content") == "complete" and cs.get("concept"):

                def walk(cs_concepts: list[dict[str, Any]]) -> list[str]:
                    found: list[str] = []
                    for c in cs_concepts:
                        found.append(c["code"])
                        found += walk(c.get("concept") or [])
                    return found

                codes.setdefault(system, []).extend(walk(cs["concept"]))
            else:
                complete = False
    return {"systems": sorted(set(systems)), "codes": codes if complete else None}


def build(data: bytes) -> dict[str, Any]:
    check(data)
    docs = _files(data)
    profiles: dict[str, Any] = {}
    bound: set[str] = set()
    for name in PROFILES:
        sd = docs.get(BASE + name)
        if sd is None:
            raise SystemExit(f"{name} is not in the package")
        elements = [_element(e) for e in (sd.get("differential") or {}).get("element") or []]
        for e in elements:
            b = e.get("binding")
            if b and b["valueSet"]:
                bound.add(b["valueSet"])
        profiles[sd["url"]] = {
            "name": sd["name"],
            "type": sd["type"],
            "base": sd.get("baseDefinition", ""),
            "elements": [e for e in elements if len(e) > 2 or "." not in e["path"]],
        }
    valuesets = {url: _valueset(docs[url], docs) for url in sorted(bound) if url in docs}
    return {
        "package": {k: PACKAGE[k] for k in ("id", "version", "url", "sha256", "sha1")},
        "fhirVersion": "4.0.1",
        "generated_by": "tools/jpcore_rules.py",
        "profiles": profiles,
        "valuesets": valuesets,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--fetch", action="store_true", help="download the pinned package into .cache/fhir (build time)")
    src.add_argument("--package", type=Path, help="a copy of the pinned package already on disk")
    ap.add_argument("--check", action="store_true", help="exit 1 if the committed rules differ from the package's")
    a = ap.parse_args(argv)
    path = fetch() if a.fetch else a.package
    rules = build(path.read_bytes())
    text = json.dumps(rules, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if a.check:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print("JP Core rules up to date" if same else "JP Core rules are stale: run tools/jpcore_rules.py")
        return 0 if same else 1
    OUT.write_text(text, encoding="utf-8")
    print(f"{len(rules['profiles'])} profiles, {len(rules['valuesets'])} value sets -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
