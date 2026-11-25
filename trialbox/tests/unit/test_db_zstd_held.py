"""The PostgreSQL image holds zstd and libzstd1 at the trixie-security fix.

The base's 1.5.7+dfsg-1 carries CVE-2026-124851, which the release gates fail on; trixie-security's
1.5.7+dfsg-1+deb13u1 fixes it (DSA-6657-1). The image installs and holds both like zlib1g and the krb5 libraries
(tests/unit/test_db_krb5_held_h93.py). A real build and the gates' scan are CI's `rehearse` (step 3).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "deploy" / "docker" / "db.Dockerfile"
PACKAGES = ("libzstd1", "zstd")
FIXED = (1, 5, 7, 1, 13, 1)  # 1.5.7+dfsg-1+deb13u1


def _key(version: str) -> tuple[int, ...]:
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)\+dfsg-(\d+)\+deb(\d+)u(\d+)", version)
    assert m, f"not a Debian security version: {version}"
    return tuple(int(x) for x in m.groups())


def test_zstd_and_libzstd1_are_pinned_at_or_above_the_fix_and_held() -> None:
    df = DOCKERFILE.read_text(encoding="utf-8")
    m = re.search(r"^ARG ZSTD_VERSION=(\S+)$", df, re.M)
    assert m and _key(m.group(1)) >= FIXED
    held = [ln for ln in df.splitlines() if "apt-mark hold zlib1g" in ln]
    assert len(held) == 1
    for p in PACKAGES:
        assert f'"{p}=${{ZSTD_VERSION}}"' in df
        assert f" {p}" in held[0]
    assert 'for p in libzstd1 zstd; do test "$(dpkg-query -W -f \'${Version}\' "$p")" = "${ZSTD_VERSION}"; done' in df


def test_the_lock_records_both_at_the_dockerfile_pin() -> None:
    pin = re.search(r"^ARG ZSTD_VERSION=(\S+)$", DOCKERFILE.read_text(encoding="utf-8"), re.M)
    lock = json.loads((ROOT / "deploy" / "images.lock").read_text(encoding="utf-8"))
    assert pin and all(lock["images"]["db"]["packages"][p] == pin.group(1) for p in PACKAGES)
