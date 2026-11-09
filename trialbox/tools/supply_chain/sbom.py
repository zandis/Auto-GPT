"""SBOMs per release (D-186): Syft writes CycloneDX JSON for each image and for the Python lock.

    python -m tools.supply_chain sbom --out dist/sbom --lock deploy/requirements.lock --image trialbox-py:1.0.0 ...

Each file is checked after Syft writes it: CycloneDX, components present, and the lock's SBOM names every locked
``name==version``. ``index.json`` lists the files with their sha256, so the bundle manifest can carry them.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from tools.supply_chain.allowlist import norm
from tools.supply_chain.lock import parse_requirements

_PURL_PYPI = re.compile(r"^pkg:pypi/([^@?#]+)@([^?#]+)")


class SbomError(RuntimeError):
    pass


def syft_command(source: str, out: Path) -> list[str]:
    return ["syft", "scan", source, "-o", f"cyclonedx-json={out}"]


def file_name(source: str) -> str:
    """A file-system-safe name for one SBOM: ``trialbox-py:1.0.0`` -> ``trialbox-py_1.0.0.cdx.json``."""
    base = source.split(":", 1)[1] if source.startswith(("file:", "dir:", "docker:", "registry:")) else source
    base = Path(base).name if "/" in base and source.startswith(("file:", "dir:")) else base
    return re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("_") + ".cdx.json"


def validate(doc: Any) -> list[str]:
    """Structural checks on a CycloneDX JSON document."""
    if not isinstance(doc, dict) or doc.get("bomFormat") != "CycloneDX":
        return ["not a CycloneDX document (bomFormat)"]
    problems: list[str] = []
    if not str(doc.get("specVersion", "")).startswith("1."):
        problems.append(f"unexpected specVersion {doc.get('specVersion')!r}")
    comps = doc.get("components")
    if not isinstance(comps, list) or not comps:
        problems.append("no components")
    return problems


def pypi_components(doc: dict[str, Any]) -> set[tuple[str, str]]:
    """(name, version) of every Python package in the SBOM, from its purl (or name/version when no purl)."""
    out: set[tuple[str, str]] = set()
    for c in doc.get("components") or []:
        purl = str(c.get("purl", ""))
        m = _PURL_PYPI.match(purl)
        if m:
            out.add((norm(m.group(1)), m.group(2)))
    return out


def lock_coverage(doc: dict[str, Any], requirements_text: str) -> list[str]:
    """Locked packages the SBOM does not name at the locked version."""
    have = pypi_components(doc)
    missing = []
    for req in parse_requirements(requirements_text):
        if req.name and req.version and (norm(req.name), req.version) not in have:
            missing.append(f"{req.name}=={req.version}")
    return missing


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(out_dir: Path, *, lock: Path | None, images: list[str]) -> list[str]:
    """Run Syft for the lock and each image, check every file, write ``index.json``. Returns the problems."""
    if shutil.which("syft") is None:
        raise SbomError("syft is not on PATH (https://github.com/anchore/syft); nothing was written")
    out_dir.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []
    sources = ([f"file:{lock}"] if lock else []) + list(images)
    index: list[dict[str, str]] = []
    for source in sources:
        out = out_dir / file_name(source)
        proc = subprocess.run(syft_command(source, out), capture_output=True, text=True, check=False)
        if proc.returncode != 0 or not out.is_file():
            problems.append(f"{source}: syft failed: {proc.stderr.strip()[-400:]}")
            continue
        doc = json.loads(out.read_text(encoding="utf-8"))
        problems += [f"{source}: {p}" for p in validate(doc)]
        if lock is not None and source == f"file:{lock}":
            missing = lock_coverage(doc, lock.read_text(encoding="utf-8"))
            if missing:
                problems.append(f"{source}: SBOM misses locked packages: {', '.join(missing[:20])}")
        index.append({"source": source, "file": out.name, "sha256": sha256(out)})
    (out_dir / "index.json").write_text(json.dumps({"sboms": index}, indent=2) + "\n", encoding="utf-8")
    return problems
