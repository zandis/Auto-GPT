"""SBOMs per release (D-186): Syft writes CycloneDX JSON for each image and for the Python lock.

The lock's SBOM is Syft's scan of an environment installed from ``deploy/requirements.lock`` with hashes
(``make lock-env``), so it carries each package's licence from its installed metadata (PEP 639
``License-Expression``, the ``License`` field, classifiers), not just names. It must name every locked package that
installs on the box at its locked version.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from tools.supply_chain.allowlist import norm
from tools.supply_chain.vulns import lock_targets

_PURL_PYPI = re.compile(r"^pkg:pypi/([^@?#]+)@([^?#]+)")


class SbomError(RuntimeError):
    pass


def syft_command(source: str, out: Path, *, platform: str | None = None) -> list[str]:
    cmd = ["syft", "scan", source, "-q", "-o", f"cyclonedx-json={out}"]
    return [*cmd, "--platform", platform] if platform else cmd


def syft_env(base: dict[str, str]) -> dict[str, str]:
    """No update check, no config file from the working tree."""
    env = {k: v for k, v in base.items() if not k.upper().startswith("SYFT_")}
    env["SYFT_CHECK_FOR_APP_UPDATE"] = "false"
    return env


def file_name(source: str, platform: str | None = None) -> str:
    """A file-system-safe name for one SBOM: ``trialbox-py:1.0.0`` + ``linux/arm64`` ->
    ``trialbox-py_1.0.0_linux_arm64.cdx.json``."""
    base = source.split(":", 1)[1] if source.startswith(("file:", "dir:", "docker:", "registry:")) else source
    base = Path(base).name if "/" in base and source.startswith(("file:", "dir:")) else base
    base = base.split("@sha256:", 1)[0] + ("_" + base.split("@sha256:", 1)[1][:12] if "@sha256:" in base else "")
    if platform:
        base += "_" + platform
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


def subject_version(doc: dict[str, Any]) -> str:
    """What Syft says it scanned (for an image: the digest or image id it resolved)."""
    meta = doc.get("metadata") or {}
    return str((meta.get("component") or {}).get("version", ""))


def layer_ids(doc: dict[str, Any]) -> set[str]:
    """The image layers (diff ids) Syft found packages in (``syft:location:N:layerID`` properties)."""
    out: set[str] = set()
    stack = list(doc.get("components") or [])
    while stack:
        comp = stack.pop()
        if not isinstance(comp, dict):
            continue
        stack += list(comp.get("components") or [])
        for prop in comp.get("properties") or []:
            if isinstance(prop, dict) and str(prop.get("name", "")).endswith(":layerID") and prop.get("value"):
                out.add(str(prop["value"]))
    return out


def pypi_components(doc: dict[str, Any]) -> set[tuple[str, str]]:
    """(name, version) of every Python package in the SBOM, from its purl."""
    out: set[tuple[str, str]] = set()
    for c in doc.get("components") or []:
        m = _PURL_PYPI.match(str(c.get("purl", "")))
        if m:
            out.add((norm(m.group(1)), m.group(2)))
    return out


def lock_coverage(doc: dict[str, Any], requirements_text: str) -> list[str]:
    """Locked packages (those that install on the box) the SBOM does not name at the locked version."""
    have = pypi_components(doc)
    return [f"{n}=={v}" for n, v in sorted(lock_targets(requirements_text).items()) if (norm(n), v) not in have]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_syft(source: str, out: Path, env: dict[str, str], *, platform: str | None = None) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            syft_command(source, out, platform=platform), capture_output=True, text=True, env=env, check=False
        )
    except FileNotFoundError as exc:
        raise SbomError("syft is not on PATH (make scanners)") from exc
    if proc.returncode != 0 or not out.is_file():
        raise SbomError(f"{source}: syft failed: {proc.stderr.strip()[-400:]}")
    doc = json.loads(out.read_text(encoding="utf-8"))
    problems = validate(doc)
    if problems:
        raise SbomError(f"{source}: {'; '.join(problems)}")
    return dict(doc)


def lock_sbom(lock_env: Path, lock: Path, out: Path, env: dict[str, str]) -> list[str]:
    """Syft SBOM of the environment installed from the lock; problems if it misses a locked package."""
    if not (lock_env / "pyvenv.cfg").is_file():
        return [f"{lock_env} is not an environment installed from the lock (make lock-env)"]
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        doc = run_syft(f"dir:{lock_env}", out, env)
    except SbomError as exc:
        return [str(exc)]
    missing = lock_coverage(doc, lock.read_text(encoding="utf-8"))
    return [f"lock SBOM misses locked packages: {', '.join(missing)}"] if missing else []
