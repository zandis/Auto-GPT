"""Build the JP Core and TW Core rules the offline profile checks read (TB-PLAN-04 step 7, D-137; T-619a, D-417).

The box has no internet and the HL7 validator needs the R4 core package beside JP Core to snapshot the profiles, so
the ingest's JP Core check is a pure-Python one (``adapter.validate.jpcore``) that reads a small rules file derived
from the JP Core package's StructureDefinitions: for each profile its parent, and from its differential the
cardinalities, fixed and pattern values, slices and their discriminators, and bindings, with the codes of the
ValueSets bound ``required`` where the package enumerates them. The rules file is committed; the package is not.

The same generator builds ``twcore_rules.json`` from the pinned TW Core 1.0.0 package (``--ig tw``, STD-011): the
profiles the TW mapping claims, their slices (the ICD-10-CM editions, NHI drugs, NHI service codes, NHI departments)
and the bound ValueSets, so the TW Core slices are on file offline as JP Core's are; the HL7 validator job in CI
(``tools/twcore_check.py``) checks the resources themselves.

``--version`` builds another version of an IG without writing it, and ``--diff`` prints what changes against the
committed rules (STD-017: JP Core 1.2.0 against the pinned 1.1.0; the target is the Japan site's to choose).

Build time only (never at runtime, never in tests): ``--fetch`` downloads the pinned package into ``.cache/fhir/``
(``--cache`` another folder) and checks its sha256 and sha1 before anything reads it, with a retry for a network that
drops a name lookup; ``--package`` uses a copy already on disk.

    python -m tools.jpcore_rules --fetch            # writes services/adapter/validate/jp_core_rules.json
    python -m tools.jpcore_rules --package jp-core.r4-1.1.0.tgz --check
    python -m tools.jpcore_rules --ig tw --fetch --check
    python -m tools.jpcore_rules --fetch --version 1.2.0 --diff
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "services" / "adapter" / "validate" / "jp_core_rules.json"
OUT_TW = ROOT / "services" / "adapter" / "validate" / "twcore_rules.json"
CACHE = ROOT / ".cache" / "fhir"
PACKAGE = {
    "id": "jp-core.r4",
    "version": "1.1.0",
    "url": "https://packages.simplifier.net/jp-core.r4/1.1.0",
    "registry": "https://packages.fhir.org/jp-core.r4",
    "sha1": "b57586047ebff666f39875155b1ebedbace9ccef",  # the registry's dist.shasum
    "sha256": "60567c583943150c26275f156d63c181e5608efcdf0616289a7fe5c032457da1",
}
# STD-017: JP Core 1.2.0 is not on the FHIR package registries (they stop at 1.1.x); JAMI publishes the release
# package beside the IG. Both sums were taken on the download of 2026-11-11 (no registry sum to compare with).
PACKAGE_JP_120 = {
    "id": "jp-core.r4",
    "version": "1.2.0",
    "url": "https://jpfhir.jp/fhir/core/1.2.0/jp-core.r4-1.2.0.tgz",
    "registry": "https://jpfhir.jp/fhir/core/1.2.0/",
    "sha1": "4018978094d78aab90058a3d9a0ebebeed6fb140",
    "sha256": "39c4ade9c32ea815a6c5889f9ee89f80efe02d5bbc8236a6b02ec573a28a2c70",
}
# T-619a (STD-011): the TW Core package the HL7 validator and the cache use (tools/fhir-packages.sha256 pins the same
# sha256)
PACKAGE_TW = {
    "id": "tw.gov.mohw.twcore",
    "version": "1.0.0",
    "url": "https://packages.simplifier.net/tw.gov.mohw.twcore/1.0.0",
    "registry": "https://packages.fhir.org/tw.gov.mohw.twcore",
    "sha1": "847042697c4f67c6f78e00e01a018c5423f7237b",  # the registry's dist.shasum
    "sha256": "a9ea37f16ea163b2c584ce7d423a5095587a1c027d0d4e4a5cdb0e7445e4932d",
}
BASE = "http://jpfhir.jp/fhir/core/StructureDefinition/"
BASE_TW = "https://twcore.mohw.gov.tw/ig/twcore/StructureDefinition/"
# the TW Core profiles tw_core/demo_his.yaml and its lab lookup claim, with the TW parents they derive from
PROFILES_TW = (
    "Patient-twcore",
    "Practitioner-twcore",
    "Encounter-twcore",
    "Condition-twcore",
    "Observation-clinical-result-twcore",
    "Observation-laboratoryResult-twcore",
    "Observation-body-height-twcore",
    "Observation-body-weight-twcore",
    "Observation-bloodPressure-twcore",
    "MedicationRequest-twcore",
    "Procedure-twcore",
    "DiagnosticReport-twcore",
    "DocumentReference-twcore",
)
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
SNOMED = "http://snomed.info/sct"
# ig -> (packages by version, the pinned version, the profiles' base URL, the profiles, the committed rules file)
IGS: dict[str, tuple[dict[str, dict[str, str]], str, str, tuple[str, ...], Path]] = {
    "jp": ({"1.1.0": PACKAGE, "1.2.0": PACKAGE_JP_120}, "1.1.0", BASE, PROFILES, OUT),
    "tw": ({"1.0.0": PACKAGE_TW}, "1.0.0", BASE_TW, PROFILES_TW, OUT_TW),
}


def _download(url: str, tries: int = 4) -> bytes:
    """``url``'s bytes; a failed name lookup or a dropped connection is tried again (2, 4, 8 s apart)."""
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "trialbox-build/1.0"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data: bytes = resp.read()
                return data
        except (urllib.error.URLError, OSError) as exc:
            if attempt == tries - 1:
                raise SystemExit(f"cannot download {url}: {exc}") from exc
            time.sleep(2 ** (attempt + 1))
    raise AssertionError("unreachable")


def fetch(package: dict[str, str] = PACKAGE, cache: Path = CACHE) -> Path:
    """Download ``package`` into ``cache`` (build time) and check both hashes."""
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{package['id']}-{package['version']}.tgz"
    if not path.exists():
        data = _download(package["url"])
        check(data, package)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)
    check(path.read_bytes(), package)
    return path


def check(data: bytes, package: dict[str, str] = PACKAGE) -> None:
    got256, got1 = hashlib.sha256(data).hexdigest(), hashlib.sha1(data).hexdigest()
    if got256 != package["sha256"] or got1 != package["sha1"]:
        raise SystemExit(f"{package['id']}#{package['version']} package hash mismatch: sha256 {got256}, sha1 {got1}")


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
    """``{systems: [...], codes: {system: [...]} | None}``: codes only when every include is enumerable. SNOMED CT
    codes are never copied (TrialBox ships no SNOMED CT content: licence register row snomed-ct, D-342), so a value
    set that lists them is kept by its systems only."""
    systems: list[str] = []
    codes: dict[str, list[str]] = {}
    complete = True
    for inc in (vs.get("compose") or {}).get("include") or []:
        system = inc.get("system")
        if not system:
            complete = False
            continue
        systems.append(system)
        if system == SNOMED:
            complete = False
            continue
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


def build(
    data: bytes,
    package: dict[str, str] = PACKAGE,
    base: str = BASE,
    names: tuple[str, ...] = PROFILES,
    missing_ok: bool = False,
) -> dict[str, Any]:
    """The rules of ``names`` in the package. ``missing_ok`` (a diff against another version): a profile the package
    does not have is left out, so the diff lists it as gone."""
    check(data, package)
    docs = _files(data)
    profiles: dict[str, Any] = {}
    bound: set[str] = set()
    for name in names:
        sd = docs.get(base + name)
        if sd is None and missing_ok:
            continue
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
        "package": {k: package[k] for k in ("id", "version", "url", "sha256", "sha1")},
        "fhirVersion": "4.0.1",
        "generated_by": "tools/jpcore_rules.py",
        "profiles": profiles,
        "valuesets": valuesets,
    }


def diff(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """What changes from rules ``old`` to rules ``new``: profiles added or gone, and per profile the elements added,
    gone or changed (cardinality, fixed or pattern value, slicing, binding), then the ValueSets whose codes changed."""
    out: list[str] = []
    op, np = old.get("profiles") or {}, new.get("profiles") or {}
    out += [f"+ profile {u}" for u in sorted(set(np) - set(op))]
    out += [f"- profile {u}" for u in sorted(set(op) - set(np))]
    for url in sorted(set(op) & set(np)):
        a = {e["id"]: e for e in op[url]["elements"]}
        b = {e["id"]: e for e in np[url]["elements"]}
        name = np[url]["name"]
        if op[url].get("base") != np[url].get("base"):
            out.append(f"~ {name}: parent {op[url].get('base')} -> {np[url].get('base')}")
        out += [f"+ {name} {eid}" for eid in sorted(set(b) - set(a))]
        out += [f"- {name} {eid}" for eid in sorted(set(a) - set(b))]
        for eid in sorted(set(a) & set(b)):
            if a[eid] != b[eid]:
                keys = sorted(k for k in set(a[eid]) | set(b[eid]) if a[eid].get(k) != b[eid].get(k))
                out.append(f"~ {name} {eid}: {', '.join(keys)}")
    ov, nv = old.get("valuesets") or {}, new.get("valuesets") or {}
    out += [f"+ valueset {u}" for u in sorted(set(nv) - set(ov))]
    out += [f"- valueset {u}" for u in sorted(set(ov) - set(nv))]
    out += [f"~ valueset {u}" for u in sorted(set(ov) & set(nv)) if ov[u] != nv[u]]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--fetch", action="store_true", help="download the pinned package into .cache/fhir (build time)")
    src.add_argument("--package", type=Path, help="a copy of the pinned package already on disk")
    ap.add_argument("--ig", choices=sorted(IGS), default="jp", help="jp (JP Core, default) or tw (TW Core)")
    ap.add_argument("--version", help="another version of the IG: built and compared (--diff), never written")
    ap.add_argument("--cache", type=Path, default=CACHE, help="the download folder (default .cache/fhir)")
    ap.add_argument("--check", action="store_true", help="exit 1 if the committed rules differ from the package's")
    ap.add_argument("--diff", action="store_true", help="print what changes against the committed rules")
    a = ap.parse_args(argv)
    packages, pinned, base, names, out = IGS[a.ig]
    version = a.version or pinned
    if version not in packages:
        raise SystemExit(f"{a.ig}: no pinned package for version {version} (have {', '.join(sorted(packages))})")
    package = packages[version]
    path = fetch(package, a.cache) if a.fetch else a.package
    rules = build(path.read_bytes(), package, base, names, missing_ok=a.diff)
    text = json.dumps(rules, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    label = f"{package['id']}#{version}"
    if a.diff:
        old = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
        changes = diff(old, rules)
        print(f"{label} against the committed {out.name} ({(old.get('package') or {}).get('version')}): "
              f"{len(changes)} change(s)")  # fmt: skip
        for line in changes:
            print(f"  {line}")
        return 0
    if version != pinned:
        raise SystemExit(f"{label} is not the pinned version {pinned}: use --diff")
    if a.check:
        same = out.exists() and out.read_text(encoding="utf-8") == text
        print(
            f"{label} rules up to date" if same else f"{label} rules are stale: run tools/jpcore_rules.py --ig {a.ig}"
        )
        return 0 if same else 1
    out.write_text(text, encoding="utf-8")
    print(f"{len(rules['profiles'])} profiles, {len(rules['valuesets'])} value sets -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
