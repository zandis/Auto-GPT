"""H-143: the OS packages an image gets only from its security-upgrade step, at or above the lock's floor.

``python.Dockerfile`` and ``demo/Dockerfile`` take Debian's security fixes with ``apt-get upgrade`` (no pin, D-23).
A builder whose cache kept that layer from an older day ships the older library, and only a scan of that builder's
image sees it. ``deploy/images.lock`` ``security_floors`` names, per image repository, the lowest version each such
package may have (the version that fixes the finding); the release gates read the image's SBOM and refuse an image
whose package is older, or missing. Versions compare as dpkg compares them (epoch, upstream, revision).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
IMAGES_LOCK = ROOT / "deploy" / "images.lock"
_PURL_DEB = re.compile(r"^pkg:deb/[^/]+/([^@?#]+)@([^?#]+)(?:\?([^#]*))?")


def _order(c: str) -> int:
    if c == "~":
        return -1
    if c.isdigit():
        return 0
    if c.isalpha():
        return ord(c)
    return ord(c) + 256


def _cmp_part(a: str, b: str) -> int:
    """dpkg's verrevcmp: non-digit runs by the dpkg order (~ first, letters before other signs), digit runs by value."""
    i = j = 0
    while i < len(a) or j < len(b):
        first = 0
        while (i < len(a) and not a[i].isdigit()) or (j < len(b) and not b[j].isdigit()):
            ac = _order(a[i]) if i < len(a) else 0
            bc = _order(b[j]) if j < len(b) else 0
            if ac != bc:
                return ac - bc
            i += 1
            j += 1
        while i < len(a) and a[i] == "0":
            i += 1
        while j < len(b) and b[j] == "0":
            j += 1
        while i < len(a) and a[i].isdigit() and j < len(b) and b[j].isdigit():
            if not first:
                first = ord(a[i]) - ord(b[j])
            i += 1
            j += 1
        if i < len(a) and a[i].isdigit():
            return 1
        if j < len(b) and b[j].isdigit():
            return -1
        if first:
            return first
    return 0


def _split(v: str) -> tuple[int, str, str]:
    epoch, _, rest = v.partition(":") if ":" in v else ("0", "", v)
    if not epoch.isdigit():
        raise ValueError(f"not a Debian version: {v!r}")
    upstream, _, revision = rest.rpartition("-") if "-" in rest else (rest, "", "")
    if not upstream:
        raise ValueError(f"not a Debian version: {v!r}")
    return int(epoch), upstream, revision


def compare(a: str, b: str) -> int:
    """<0, 0 or >0 as Debian version ``a`` is older than, equal to or newer than ``b``."""
    ea, ua, ra = _split(a)
    eb, ub, rb = _split(b)
    if ea != eb:
        return ea - eb
    return _cmp_part(ua, ub) or _cmp_part(ra, rb)


def load(path: Path | None = None) -> dict[str, dict[str, str]]:
    """``security_floors`` of the lock: {image repository: {package: lowest version}}."""
    lock = json.loads((path or IMAGES_LOCK).read_text(encoding="utf-8"))
    floors = lock.get("security_floors")
    if not isinstance(floors, dict) or not isinstance(floors.get("images"), dict) or not floors["images"]:
        raise ValueError(f"{path or IMAGES_LOCK}: no security_floors.images")
    return {str(k): {str(p): str(v) for p, v in pk.items()} for k, pk in floors["images"].items()}


def deb_packages(doc: dict[str, Any]) -> dict[str, set[str]]:
    """{package: versions} of every Debian package in a CycloneDX SBOM, from its purl (epoch included)."""
    out: dict[str, set[str]] = {}
    stack = list(doc.get("components") or [])
    while stack:
        comp = stack.pop()
        if not isinstance(comp, dict):
            continue
        stack += list(comp.get("components") or [])
        m = _PURL_DEB.match(str(comp.get("purl", "")))
        if m:
            version = unquote(m.group(2))
            # the purl spec keeps a Debian epoch in a qualifier (zlib1g@1.3.dfsg...?epoch=1), not in the version
            quals = dict(q.split("=", 1) for q in (m.group(3) or "").split("&") if "=" in q)
            epoch = unquote(quals.get("epoch", ""))
            if epoch and ":" not in version:
                version = f"{epoch}:{version}"
            out.setdefault(unquote(m.group(1)), set()).add(version)
    return out


def repository(ref: str) -> str:
    """``trialbox-py`` of ``trialbox-py:1.0.0``, ``localhost:5000/trialbox-py:1.0.0`` or ``...@sha256:..``."""
    name = ref.split("@", 1)[0].rsplit("/", 1)[-1]
    return name.split(":", 1)[0]


def problems(ref: str, doc: dict[str, Any], floors: dict[str, dict[str, str]]) -> list[str]:
    """Why the image ``ref`` (its SBOM ``doc``) is below the lock's floor; [] when it is not, or has no floor."""
    want = floors.get(repository(ref))
    if not want:
        return []
    have = deb_packages(doc)
    out: list[str] = []
    for pkg, floor in sorted(want.items()):
        versions = have.get(pkg)
        if not versions:
            out.append(f"{ref}: {pkg} is not in the image's SBOM; deploy/images.lock security_floors needs {floor}")
            continue
        for v in sorted(versions):
            try:
                older = compare(v, floor) < 0
            except ValueError as exc:
                out.append(f"{ref}: {pkg} {exc}")
                continue
            if older:
                out.append(
                    f"{ref}: {pkg} {v} is older than {floor} (deploy/images.lock security_floors): the security-upgrade"
                    " layer came from a build cache; rebuild with make release-images (H-143)"
                )
    return out
