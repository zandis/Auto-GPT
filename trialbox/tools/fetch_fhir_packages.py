"""Populate an offline FHIR NPM package cache for the HL7 validator (the appliance needs no registry access).

The appliance has no egress, so the validator must run with a pre-filled cache. This tool downloads FHIR
packages from the FHIR package registry (default ``https://packages.fhir.org``, whose listings have the npm shape;
``TB_NPM_REGISTRY`` or ``--registry`` may name an npm-compatible mirror instead) and installs them as
``<cache>/<name>#<version>/package/...``. It is run at image build time (vendor side) and the cache is shipped
inside the signed offline bundle.

Usage::

    python tools/fetch_fhir_packages.py --cache /opt/fhir-cache/.fhir/packages \
        hl7.fhir.r4.core#4.0.1 hl7.terminology.r4#7.5.0 tw.gov.mohw.twcore#1.0.0
    python tools/fetch_fhir_packages.py --cache ... --twpas-settings deploy/settings.example.yaml

``--twpas-settings`` installs the TWPAS IG at the version the settings file names (``profiles.twpas_version``) with
the packages that version needs (``TWPAS_SETS``), so the cache always holds the version the box asks for (D-372).

Every tarball is pinned (ENG-013, T-110b): its sha256 must be the one ``tools/fhir-packages.sha256`` lists for that
``name#version``, or the fetch stops before the cache is touched. A package already in the cache is not fetched again
(its files are edited on install, so there is no tarball left to check): delete the cache to check it afresh.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

# The FHIR package registry (DEP-016, D-372): it carries every published version, where the npm mirror stops at old
# ones (TWPAS 1.2.0 only, a ballot of the extensions). The pins in fhir-packages.sha256 are of its tarballs.
DEFAULT_REGISTRY = "https://packages.fhir.org"
NPM_REGISTRY = "https://registry.npmjs.org"
PINS = Path(__file__).resolve().parent / "fhir-packages.sha256"
# FHIR package id -> npm package name, where they differ (only on the npm mirror)
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

# One version of the HL7 terminology and of the HL7 extensions for the whole cache (DEP-016, D-372): the released
# extensions 5.4.0 and the terminology 7.5.0 it declares. The older versions other packages declare (TW Core 1.0.0:
# 7.0.0 and 5.2.0; TWPAS 1.2.5: 7.3.0 and 5.3.0) are aliases of the same content.
TERMINOLOGY_VERSION = "7.5.0"
EXTENSIONS_VERSION = "5.4.0"
_TERMINOLOGY_ALIASES = "7.4.0,7.3.0,7.0.1,7.0.0,6.5.0,6.2.0,6.1.0"
_EXTENSIONS_ALIASES = "5.3.0,5.2.0,5.1.0"

# The packages the HL7 validator 6.x needs to validate R4 + TW Core offline.
DEFAULT_PACKAGES = [
    "hl7.fhir.r4.core#4.0.1",
    "hl7.fhir.xver-extensions#0.1.0",
    f"hl7.terminology.r4#{TERMINOLOGY_VERSION}={_TERMINOLOGY_ALIASES}",
    f"hl7.fhir.uv.extensions.r4#{EXTENSIONS_VERSION}={_EXTENSIONS_ALIASES}",
    "hl7.fhir.uv.tools.r4#1.1.0",
    f"hl7.terminology#{TERMINOLOGY_VERSION}",
    f"hl7.fhir.uv.extensions#{EXTENSIONS_VERSION}",
    "tw.gov.mohw.twcore#1.0.0",
]

# TWPAS IG version -> (packages, resource subsets) it needs on top of DEFAULT_PACKAGES. Only versions listed here can
# be named in settings; to move the version, add its set and its pins in one pull request (D-372).
# 1.2.5 declares TW Core 0.3.2 (the cache serves TW Core 1.0.0 under that version, as D-63 did) and Da Vinci PAS
# 2.2.1, of which its profiles use one extension definition (the full package drags in the US Core chain).
TWPAS_SETS: dict[str, tuple[list[str], list[str]]] = {
    "1.2.5": (
        ["tw.gov.mohw.nhi.pas#1.2.5", "tw.gov.mohw.twcore#1.0.0=0.3.2"],
        ["hl7.fhir.us.davinci-pas#2.2.1:StructureDefinition-extension-diagnosisRecordedDate.json"],
    ),
}
# The version the vendor build fetches and deploy/settings.example.yaml names (a test holds them equal).
TWPAS_VERSION = "1.2.5"
_TWPAS_SETTING = re.compile(r"""\btwpas_version\s*:\s*["']?([0-9A-Za-z.+-]+)""")


def settings_twpas_version(path: Path) -> str:
    """``profiles.twpas_version`` of a settings file (a regular expression, so the build needs no YAML library)."""
    found = _TWPAS_SETTING.findall(path.read_text(encoding="utf-8"))
    if len(found) != 1:
        raise SystemExit(f"{path}: expected one profiles.twpas_version, found {len(found)}")
    return str(found[0])


def twpas_set(version: str) -> tuple[list[str], list[str]]:
    """The packages and subsets TWPAS ``version`` needs; a version without a set stops the fetch."""
    if version not in TWPAS_SETS:
        raise SystemExit(
            f"TWPAS {version} has no package set in tools/fetch_fhir_packages.py (have: {', '.join(TWPAS_SETS)}); "
            "add its set and pins (D-372)"
        )
    return TWPAS_SETS[version]


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "trialbox-fetch/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data: bytes = resp.read()
        return data


def pins(path: Path = PINS) -> dict[str, str]:
    """``name#version`` -> pinned sha256 of its tarball."""
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            digest, spec = line.split()
            out[spec] = digest
    return out


def check_tarball(name: str, version: str, blob: bytes, pinned: dict[str, str] | None = None) -> bytes:
    """``blob`` when its sha256 is the pinned one for ``name#version``; else the fetch stops (SystemExit)."""
    want = (pins() if pinned is None else pinned).get(f"{name}#{version}")
    got = hashlib.sha256(blob).hexdigest()
    if want != got:
        raise SystemExit(
            f"{name}#{version}: tarball sha256 {got} is not the pinned {want or '(none: not in fhir-packages.sha256)'}"
            "; refusing it"
        )
    return blob


def npm_tarball(registry: str, name: str, version: str) -> bytes:
    npm_name = NPM_ALIASES.get(name, name) if registry.rstrip("/") == NPM_REGISTRY else name
    meta = json.loads(_get(f"{registry}/{npm_name.replace('/', '%2F')}"))
    versions = meta.get("versions", {})
    if version not in versions:
        raise SystemExit(f"{name}#{version} not in registry (have: {', '.join(sorted(versions)[-8:])})")
    return check_tarball(name, version, _get(versions[version]["dist"]["tarball"]))


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
    (packages declare older dependency versions than the one the cache holds, D-372)."""
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
    dependencies). TWPAS needs a single Da Vinci PAS extension definition, and the full package drags in the US Core
    chain (DECISIONS D-63, D-372)."""
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
    ap.add_argument(
        "--twpas-settings", type=Path, help="settings file: install the TWPAS IG set of its profiles.twpas_version"
    )
    args = ap.parse_args(argv)
    packages, subsets = list(args.packages), list(args.subset)
    if args.twpas_settings:
        version = settings_twpas_version(args.twpas_settings)
        extra, extra_subsets = twpas_set(version)
        print(f"TWPAS {version} (profiles.twpas_version of {args.twpas_settings})")
        packages += extra
        subsets += extra_subsets
    args.cache.mkdir(parents=True, exist_ok=True)
    for spec in subsets:
        install_subset(args.cache, spec, args.registry)
    if (subsets or args.twpas_settings) and not packages:
        return 0
    for spec in packages or DEFAULT_PACKAGES:
        try:
            install(args.cache, spec, args.registry, args.force)
        except OSError as exc:
            print(f"! {spec}: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
