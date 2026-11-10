"""The hashed lock (D-185): ``uv.lock`` is the source, ``deploy/requirements.lock`` is its pip-readable export.

``deploy/requirements.lock`` is what the images install (``pip install -r``). Because every entry carries
``--hash=sha256:...``, pip runs in hash-checking mode: a file whose bytes differ from the lock is refused.
"""

from __future__ import annotations

import difflib
import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UV_LOCK = ROOT / "uv.lock"
REQUIREMENTS_LOCK = ROOT / "deploy" / "requirements.lock"
# pip-audit itself is installed from this hashed file (``make pip-audit``), never as a bare ``pip-audit==x``
PIP_AUDIT_LOCK = ROOT / "tools" / "supply_chain" / "pip-audit.lock"
PIP_AUDIT_VERSION = "2.10.1"

HEADER = (
    "# Generated from uv.lock by `make lock` (python -m tools.supply_chain lock-export, D-185). Do not edit.\n"
    "# Every entry is pinned with sha256 hashes, so pip installs it in hash-checking mode.\n"
    "# `make lock-check` (CI) fails when this file, uv.lock and pyproject.toml disagree.\n"
)
# the export the images install: the project's runtime dependencies only (no extras, no dev, not the project itself)
EXPORT_ARGS = [
    "export",
    "--frozen",
    "--no-emit-project",
    "--no-dev",
    "--no-header",
    "--format",
    "requirements.txt",
]

# the uv that wrote uv.lock and the export; CI pins the same (.github/workflows/trialbox-*.yml). Another uv may
# format the export differently, so a mismatch is named when the export differs. At least 0.13.4: uv 0.11.32 to
# 0.13.3 trust a compromised CA root in their bundled store (GHSA-hq85-5cpj-mr62, DEP-006).
UV_VERSION = "0.13.7"
# the oldest uv the lock check accepts at all (the fix of GHSA-hq85-5cpj-mr62); CI runs UV_VERSION
MIN_UV_VERSION = "0.13.4"

_HASH_RE = re.compile(r"--hash=([A-Za-z0-9]+):([0-9a-fA-F]+)")
_PIN_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?==([^\s;\\]+)")
_SHA256_LEN = 64


class LockError(RuntimeError):
    """uv is missing or failed."""


@dataclass(frozen=True)
class Requirement:
    """One logical entry of a requirements file (continuation lines joined)."""

    line: int
    text: str
    name: str | None
    version: str | None
    hashes: tuple[tuple[str, str], ...]
    marker: str | None = None  # the environment marker after ';', if any


def parse_requirements(text: str) -> list[Requirement]:
    """Split a requirements file into logical entries; comments and blank lines are dropped."""
    out: list[Requirement] = []
    buf: list[str] = []
    start = 0
    for no, raw in enumerate(text.splitlines(), start=1):
        line = raw.split(" #", 1)[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if not buf:
            if not line.strip():
                continue
            start = no
        cont = line.endswith("\\")
        buf.append(line[:-1] if cont else line)
        if cont:
            continue
        joined = " ".join(part.strip() for part in buf if part.strip())
        buf = []
        m = _PIN_RE.match(joined)
        out.append(
            Requirement(
                line=start,
                text=joined,
                name=m.group(1).lower() if m else None,
                version=m.group(3) if m else None,
                hashes=tuple((alg.lower(), digest.lower()) for alg, digest in _HASH_RE.findall(joined)),
                marker=_marker(joined),
            )
        )
    if buf:  # a trailing backslash with nothing after it
        joined = " ".join(part.strip() for part in buf if part.strip())
        out.append(Requirement(line=start, text=joined, name=None, version=None, hashes=()))
    return out


def _marker(joined: str) -> str | None:
    if ";" not in joined:
        return None
    marker = joined.split(";", 1)[1].split(" --hash=", 1)[0].strip()
    return marker or None


def check_requirements_hashes(text: str) -> list[str]:
    """Problems that make a requirements file unfit for a hash-checked install; empty when it is fit."""
    problems: list[str] = []
    entries = parse_requirements(text)
    if not entries:
        return ["no requirements in the file"]
    for req in entries:
        if req.text.startswith("-"):
            # options such as -e, -r, --index-url or --find-links widen what pip may fetch
            problems.append(f"line {req.line}: option not allowed in the lock: {req.text[:60]}")
            continue
        if req.name is None:
            problems.append(f"line {req.line}: not pinned with == : {req.text[:60]}")
            continue
        label = f"line {req.line}: {req.name}=={req.version}"
        if not req.hashes:
            problems.append(f"{label} has no --hash")
            continue
        for alg, digest in req.hashes:
            if alg != "sha256" or len(digest) != _SHA256_LEN:
                problems.append(f"{label} has a hash that is not sha256: {alg}:{digest[:12]}")
    names = [r.name for r in entries if r.name]
    for name in sorted({n for n in names if names.count(n) > 1}):
        # uv writes one entry per name with markers; two entries for one name is a hand edit
        problems.append(f"{name} is listed more than once")
    return problems


def check_uv_lock(text: str) -> list[str]:
    """Every registry package in uv.lock records a sha256 for each file (sdist and wheels) it may install."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return [f"uv.lock is not valid TOML: {exc}"]
    packages = data.get("package")
    if not isinstance(packages, list) or not packages:
        return ["uv.lock lists no packages"]
    problems: list[str] = []
    for pkg in packages:
        name = f"{pkg.get('name')}=={pkg.get('version')}"
        source = pkg.get("source") or {}
        if "registry" not in source:
            # the project itself (editable/virtual) has no files to hash; a git or URL source is not allowed
            if "git" in source or "url" in source:
                problems.append(f"{name}: source {sorted(source)} is not a registry; use a released version")
            continue
        files = [pkg["sdist"]] if isinstance(pkg.get("sdist"), dict) else []
        files += [w for w in pkg.get("wheels", []) if isinstance(w, dict)]
        if not files:
            problems.append(f"{name}: no files recorded")
        for f in files:
            digest = str(f.get("hash", ""))
            if not digest.startswith("sha256:") or len(digest) != len("sha256:") + _SHA256_LEN:
                problems.append(f"{name}: {Path(str(f.get('url', '?'))).name} has no sha256")
    return problems


def _uv() -> str:
    uv = shutil.which("uv")
    if uv is None:
        raise LockError("uv is not on PATH (https://docs.astral.sh/uv/)")
    return uv


def export_requirements(root: Path = ROOT) -> str:
    """The text deploy/requirements.lock must have, made from uv.lock without touching the network."""
    proc = subprocess.run([_uv(), *EXPORT_ARGS], cwd=root, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise LockError(f"uv export failed: {proc.stderr.strip()}")
    return HEADER + proc.stdout


def uv_version() -> str:
    proc = subprocess.run([_uv(), "--version"], capture_output=True, text=True, check=False)
    parts = proc.stdout.split()
    return parts[1] if len(parts) > 1 else "?"


def _version_tuple(version: str) -> tuple[int, ...]:
    """``0.13.7`` -> ``(0, 13, 7)``; anything unparsable sorts lowest."""
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return (-1,)


def uv_too_old(version: str) -> bool:
    """True when ``version`` is below MIN_UV_VERSION (a uv that trusts the compromised CA root, DEP-006)."""
    return _version_tuple(version) < _version_tuple(MIN_UV_VERSION)


def uv_lock_is_current(root: Path = ROOT, *, offline: bool = False) -> tuple[bool, str]:
    """``uv lock --check``: does uv.lock still satisfy pyproject.toml? (May query the index unless offline.)"""
    cmd = [_uv(), "lock", "--check"] + (["--offline"] if offline else [])
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, check=False)
    return proc.returncode == 0, (proc.stderr or proc.stdout).strip()


def diff(expected: str, actual: str, *, limit: int = 40) -> str:
    lines = list(
        difflib.unified_diff(
            actual.splitlines(), expected.splitlines(), "deploy/requirements.lock", "uv export", lineterm=""
        )
    )
    more = f"\n... {len(lines) - limit} more diff lines" if len(lines) > limit else ""
    return "\n".join(lines[:limit]) + more


def lock_check(root: Path = ROOT, *, offline: bool = False, skip_resolve: bool = False) -> list[str]:
    """All lock problems; empty means the hashed lock is current and complete."""
    problems: list[str] = []
    uv_lock = root / "uv.lock"
    req_lock = root / "deploy" / "requirements.lock"
    if not uv_lock.is_file():
        return [f"{uv_lock} is missing: run `make lock`"]
    if not req_lock.is_file():
        return [f"{req_lock} is missing: run `make lock`"]
    problems += [f"uv.lock: {p}" for p in check_uv_lock(uv_lock.read_text(encoding="utf-8"))]
    if not skip_resolve:
        if uv_too_old(found := uv_version()):
            problems.append(f"uv {found} is older than {MIN_UV_VERSION} (GHSA-hq85-5cpj-mr62): install uv {UV_VERSION}")
        ok, msg = uv_lock_is_current(root, offline=offline)
        if not ok:
            problems.append(f"uv.lock is stale against pyproject.toml (run `make lock`): {msg}")
    actual = req_lock.read_text(encoding="utf-8")
    problems += [f"deploy/requirements.lock: {p}" for p in check_requirements_hashes(actual)]
    tool_lock = root / "tools" / "supply_chain" / "pip-audit.lock"
    if not tool_lock.is_file():
        problems.append(f"{tool_lock} is missing: run `make lock`")
    else:
        tool_text = tool_lock.read_text(encoding="utf-8")
        problems += [f"tools/supply_chain/pip-audit.lock: {p}" for p in check_requirements_hashes(tool_text)]
        pinned = {r.name: r.version for r in parse_requirements(tool_text)}
        if pinned.get("pip-audit") != PIP_AUDIT_VERSION:
            problems.append(f"tools/supply_chain/pip-audit.lock must pin pip-audit=={PIP_AUDIT_VERSION}")
    expected = export_requirements(root)
    if expected != actual:
        if uv_version() != UV_VERSION:
            problems.append(f"uv {uv_version()} is not the pinned uv {UV_VERSION}; its export may differ in form")
        problems.append(
            "deploy/requirements.lock differs from `uv export` of uv.lock (run `make lock`):\n" + diff(expected, actual)
        )
    return problems
