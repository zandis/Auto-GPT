"""H-93: the PostgreSQL image holds its krb5 libraries at the trixie-security fix.

The server (postgresql-16) and libpq5 depend on libgssapi-krb5-2, which depends on libkrb5-3, libk5crypto3 and
libkrb5support0, so the libraries cannot be removed. The base's 1.21.3-5+deb13u1 carries 14 CVEs the release gates
fail on; trixie-security's 1.21.3-5+deb13u2 fixes them (DSA-6650-1). The image installs and holds the four like
zlib1g (D-993, tests/unit/test_db_no_gosu.py). A real build and the gates' scan are CI's `rehearse` (step 3).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "deploy" / "docker" / "db.Dockerfile"
PACKAGES = ("libkrb5-3", "libkrb5support0", "libk5crypto3", "libgssapi-krb5-2")
FIXED = (1, 21, 3, 5, 13, 2)  # 1.21.3-5+deb13u2


def _key(version: str) -> tuple[int, ...]:
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)-(\d+)\+deb(\d+)u(\d+)", version)
    assert m, f"not a Debian security version: {version}"
    return tuple(int(x) for x in m.groups())


def test_the_four_krb5_packages_are_pinned_at_or_above_the_fix_and_held() -> None:
    df = DOCKERFILE.read_text(encoding="utf-8")
    m = re.search(r"^ARG KRB5_VERSION=(\S+)$", df, re.M)
    assert m and _key(m.group(1)) >= FIXED
    held = [ln for ln in df.splitlines() if "apt-mark hold zlib1g" in ln]
    assert len(held) == 1
    for p in PACKAGES:
        assert f'"{p}=${{KRB5_VERSION}}"' in df  # installed at the pin, as "zlib1g=${ZLIB1G_VERSION}" is
        assert f" {p}" in held[0]
    assert "for p in libkrb5-3 libkrb5support0 libk5crypto3 libgssapi-krb5-2; do" in df
    assert 'test "$(dpkg-query -W -f \'${Version}\' "$p")" = "${KRB5_VERSION}"' in df


def test_the_lock_records_the_four_at_the_dockerfile_pin() -> None:
    pin = re.search(r"^ARG KRB5_VERSION=(\S+)$", DOCKERFILE.read_text(encoding="utf-8"), re.M)
    lock = json.loads((ROOT / "deploy" / "images.lock").read_text(encoding="utf-8"))
    assert pin and all(lock["images"]["db"]["packages"][p] == pin.group(1) for p in PACKAGES)

