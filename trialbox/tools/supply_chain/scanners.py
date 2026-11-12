"""Syft and Trivy, fetched as release archives whose sha256 is pinned here (D-186), never by an install script.

    python -m tools.supply_chain scanners --dest .cache/scanners      # then put .cache/scanners/bin on PATH

The sums are the ones the projects publish in their ``*_checksums.txt`` for these releases (fetched 2026-11-10 and
checked against the downloaded archives). To move a version, change the version and both sums together, in one pull
request the security owner approves. An archive whose sha256 differs is refused and nothing is installed.
"""

from __future__ import annotations

import hashlib
import io
import platform as _platform
import shutil
import tarfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Asset:
    tool: str
    version: str
    arch: str  # amd64 | arm64
    url: str
    sha256: str


SYFT_VERSION = "1.57.1"
TRIVY_VERSION = "0.76.2"
_SYFT = f"https://github.com/anchore/syft/releases/download/v{SYFT_VERSION}/syft_{SYFT_VERSION}_linux_{{arch}}.tar.gz"
_TRIVY = f"https://github.com/aquasecurity/trivy/releases/download/v{TRIVY_VERSION}/trivy_{TRIVY_VERSION}_Linux-{{arch}}.tar.gz"
ASSETS = (
    Asset("syft", SYFT_VERSION, "amd64", _SYFT.format(arch="amd64"),
          "bf52519eb57f675d47c07d43213cb6dff6449f3d6d1147ff6701ed91f44eef0c"),
    Asset("syft", SYFT_VERSION, "arm64", _SYFT.format(arch="arm64"),
          "aa3d3e07344f590bcce8d31043b752daa76c8a56c2aa34ceeee63c6168152582"),
    Asset("trivy", TRIVY_VERSION, "amd64", _TRIVY.format(arch="64bit"),
          "bc0fc726e017b8927a62b2d3531d7a84ee01769daf5c99ed866dced54089fdbf"),
    Asset("trivy", TRIVY_VERSION, "arm64", _TRIVY.format(arch="ARM64"),
          "ab9d51f86e6a5fb936f605faff6b593ac51bc378fff4d3e8b9d58358b9c367c3"),
)  # fmt: skip


class ScannerError(RuntimeError):
    pass


def host_arch() -> str:
    machine = _platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    raise ScannerError(f"no pinned scanner build for {machine}")


def asset(tool: str, arch: str) -> Asset:
    for a in ASSETS:
        if a.tool == tool and a.arch == arch:
            return a
    raise ScannerError(f"no pinned {tool} for {arch}")


def verify(data: bytes, expected: str, what: str) -> None:
    got = hashlib.sha256(data).hexdigest()
    if got != expected:
        raise ScannerError(f"{what}: sha256 {got} is not the pinned {expected}; refusing it")


def extract(data: bytes, tool: str, dest: Path) -> Path:
    """Write the one binary named ``tool`` from the archive to ``dest/bin``; nothing else is unpacked."""
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        member = next((m for m in tar.getmembers() if m.isfile() and Path(m.name).name == tool), None)
        if member is None:
            raise ScannerError(f"{tool} binary not in the archive")
        src = tar.extractfile(member)
        if src is None:
            raise ScannerError(f"{tool}: cannot read the binary from the archive")
        (dest / "bin").mkdir(parents=True, exist_ok=True)
        target = dest / "bin" / tool
        tmp = target.with_suffix(".part")
        with tmp.open("wb") as fh:
            shutil.copyfileobj(src, fh)
        tmp.chmod(0o755)
        tmp.replace(target)
    return target


def fetch(tool: str, dest: Path, *, arch: str | None = None) -> Path:
    a = asset(tool, arch or host_arch())
    marker = dest / "bin" / f".{tool}.sha256"
    target = dest / "bin" / tool
    if target.is_file() and marker.is_file() and marker.read_text(encoding="utf-8").strip() == a.sha256:
        return target
    with urllib.request.urlopen(a.url, timeout=300) as resp:
        data = resp.read()
    verify(data, a.sha256, f"{tool} {a.version} {a.arch}")
    target = extract(data, tool, dest)
    marker.write_text(a.sha256 + "\n", encoding="utf-8")
    return target
