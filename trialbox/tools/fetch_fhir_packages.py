"""Populate an offline FHIR NPM package cache for the HL7 validator (no access to packages.fhir.org needed).

The appliance has no egress, so the validator must run with a pre-filled cache. This tool downloads FHIR
packages from an npm-compatible registry (default ``https://registry.npmjs.org``, where HL7 packages are mirrored;
``hl7.fhir.r4.core`` is published there as ``@hl7/hl7.fhir.r4.core``) and installs them as
``<cache>/<name>#<version>/package/...``. It is run at image build time (vendor side) and the cache is shipped
inside the signed offline bundle.

Usage::

    python tools/fetch_fhir_packages.py --cache /opt/fhir-cache/.fhir/packages \
        hl7.fhir.r4.core#4.0.1 hl7.terminology.r4#7.0.1 tw.gov.mohw.twcore#1.0.0
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

DEFAULT_REGISTRY = "https://registry.npmjs.org"
# FHIR package id -> npm package name, where they differ
NPM_ALIASES = {"hl7.fhir.r4.core": "@hl7/hl7.fhir.r4.core"}
# Dependencies removed after install to break the terminology <-> extensions cycle that the validator's loader
# cannot resolve once versions are aliased (the terminology content does not need the extensions to load).
DROP_DEPENDENCIES = {
    "hl7.terminology.r4": ["hl7.fhir.uv.extensions.r4"],
    "hl7.terminology": ["hl7.fhir.uv.extensions.r5"],
    "hl7.fhir.uv.extensions": ["hl7.terminology", "hl7.terminology.r5"],
    # TW Core profiles used by TrialBox derive from base R4; IPS/SDC are only needed for document/questionnaire
    # profiles TrialBox never claims.
    "tw.gov.mohw.twcore": ["hl7.fhir.uv.ips", "hl7.fhir.uv.sdc"],
    "tw.gov.mohw.emr": ["hl7.fhir.uv.ips", "hl7.fhir.uv.sdc"],
}
# Code systems whose published resource states it is only an extract ("此處…僅擷取部分代碼") but is labelled
# content=complete: the cache relabels them content=fragment so unknown (real) codes are warnings, not errors
# (DECISIONS D-64). The full code systems live on the national terminology service.
FRAGMENT_MARKERS = ("僅擷取部分代碼",)

# The packages the HL7 validator 6.x needs to validate R4 + TW Core + TWPAS offline.
DEFAULT_PACKAGES = [
    "hl7.fhir.r4.core#4.0.1",
    "hl7.fhir.xver-extensions#0.1.0",
    "hl7.terminology.r4#7.0.1=6.2.0,6.5.0,7.0.0,6.1.0",
    "hl7.fhir.uv.extensions.r4#5.3.0-ballot-tc1=5.2.0,5.1.0",
    "hl7.fhir.uv.tools.r4#1.1.0",
    "hl7.terminology#7.0.1",
    "hl7.fhir.uv.extensions#5.3.0-ballot-tc1",
    "tw.gov.mohw.twcore#1.0.0",
]


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "trialbox-fetch/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data: bytes = resp.read()
        return data


def npm_tarball(registry: str, name: str, version: str) -> bytes:
    npm_name = NPM_ALIASES.get(name, name)
    meta = json.loads(_get(f"{registry}/{npm_name.replace('/', '%2F')}"))
    versions = meta.get("versions", {})
    if version not in versions:
        raise SystemExit(f"{name}#{version} not in registry (have: {', '.join(sorted(versions)[-8:])})")
    return _get(versions[version]["dist"]["tarball"])


def _alias_tree(src: Path, dst: Path) -> None:
    """Mirror ``src`` into ``dst`` with relative symlinks (aliases cost no space; Docker COPY keeps links)."""
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        target = dst / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(os.path.relpath(path, target.parent))


def install(cache: Path, spec: str, registry: str, force: bool = False) -> Path:
    """Install ``name#version``; ``name#version=alias`` installs that version under the alias version too
    (the validator pins some dependency versions that the npm mirror does not carry)."""
    spec, _, alias = spec.partition("=")
    name, _, version = spec.partition("#")
    if not version:
        raise SystemExit(f"package spec needs a version: {spec}")
    if alias:
        src = install(cache, spec, registry, force)
        for alias_version in alias.split(","):
            dst = cache / f"{name}#{alias_version}"
            if not dst.exists() or force:
                shutil.rmtree(dst, ignore_errors=True)
                _alias_tree(src, dst)
                pj = dst / "package" / "package.json"
                meta = json.loads((src / "package" / "package.json").read_text(encoding="utf-8"))
                meta["version"] = alias_version
                pj.unlink()
                pj.write_text(json.dumps(meta, indent=2), encoding="utf-8")
                print(f"~ {name}#{alias_version} -> content of {version}")
        return src
    target = cache / f"{name}#{version}"
    if target.exists() and not force:
        print(f"= {spec} (cached)")
        return target
    blob = npm_tarball(registry, name, version)
    tmp = cache / f".{name}#{version}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        tar.extractall(tmp, filter="data")
    pkg_json = tmp / "package" / "package.json"
    data = json.loads(pkg_json.read_text(encoding="utf-8"))
    data["name"] = name  # npm scope alias -> FHIR package id
    for dep in DROP_DEPENDENCIES.get(name, []):
        data.get("dependencies", {}).pop(dep, None)
    pkg_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
    for cs_path in sorted((tmp / "package").glob("CodeSystem-*.json")):
        text = cs_path.read_text(encoding="utf-8")
        if any(m in text for m in FRAGMENT_MARKERS):
            cs = json.loads(text)
            if cs.get("content") == "complete":
                cs["content"] = "fragment"
                cs_path.write_text(json.dumps(cs, ensure_ascii=False), encoding="utf-8")
                print(f"  {cs_path.name}: content=fragment (published extract)")
    shutil.rmtree(target, ignore_errors=True)
    os.replace(tmp, target)
    print(f"+ {spec} ({len(blob) // 1024} KiB)")
    return target


def install_subset(cache: Path, spec: str, registry: str) -> Path:
    """``name#version=alias:File1.json,File2.json`` -> a package ``name#alias`` holding only those resources (and no
    dependencies). TWPAS 1.2.0 needs a single Da Vinci PAS extension definition; davinci-pas 2.1.0 is not on the npm
    mirror and 2.2.0-ballot drags in the US Core chain (DECISIONS D-63)."""
    head, _, files = spec.partition(":")
    pkg, _, alias = head.partition("=")
    name, _, version = pkg.partition("#")
    target = cache / f"{name}#{alias or version}"
    blob = npm_tarball(registry, name, version)
    shutil.rmtree(target, ignore_errors=True)
    (target / "package").mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for f in files.split(","):
            member = tar.extractfile(f"package/{f}")
            if member is None:
                raise SystemExit(f"{f} not in {name}#{version}")
            (target / "package" / f).write_bytes(member.read())
    meta = {
        "name": name,
        "version": alias or version,
        "fhirVersions": ["4.0.1"],
        "dependencies": {"hl7.fhir.r4.core": "4.0.1"},
        "description": f"TrialBox subset of {name}#{version}: {files}",
    }
    (target / "package" / "package.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"+ {name}#{alias or version} (subset of {version}: {files})")
    return target


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", type=Path, default=Path.home() / ".fhir" / "packages")
    ap.add_argument("--registry", default=os.environ.get("TB_NPM_REGISTRY", DEFAULT_REGISTRY))
    ap.add_argument("--force", action="store_true")
    ap.add_argument("packages", nargs="*", help="name#version (default: validator R4 base set)")
    ap.add_argument("--subset", action="append", default=[], help="name#version=alias:File.json,... (resource subset)")
    args = ap.parse_args(argv)
    args.cache.mkdir(parents=True, exist_ok=True)
    for spec in args.subset:
        install_subset(args.cache, spec, args.registry)
    if args.subset and not args.packages:
        return 0
    for spec in args.packages or DEFAULT_PACKAGES:
        try:
            install(args.cache, spec, args.registry, args.force)
        except OSError as exc:
            print(f"! {spec}: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
