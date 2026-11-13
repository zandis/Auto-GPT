"""DEMO-CA (D-575): a build secret is mounted readable by root only, and apt fetches as ``_apt``. A step that points
apt at the mounted ``extra_ca`` secret must mount it with ``mode=0444``, or ``apt-get update`` fails behind a
TLS-inspecting proxy. The demo image did not; the database image did."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
# apt is pointed at the mounted secret itself, in a config file or on its command line
APT_READS_IT = re.compile(r'Acquire::https::CAInfo[= ]"?/run/secrets/extra_ca')

pytestmark = pytest.mark.nodb


def _steps(text: str) -> list[str]:
    """Each RUN instruction with its continuation lines."""
    return [m.group(0) for m in re.finditer(r"^RUN (?:.*\\\n)*.*$", text, re.M)]


def _dockerfiles() -> list[Path]:
    found = [
        p for p in ROOT.rglob("*Dockerfile*") if ".venv" not in p.parts and ".cache" not in p.parts and p.is_file()
    ]
    assert len(found) >= 5
    return sorted(found)


def test_a_step_that_gives_the_mounted_secret_to_apt_mounts_it_world_readable() -> None:
    seen = 0
    for path in _dockerfiles():
        for step in _steps(path.read_text(encoding="utf-8")):
            if not APT_READS_IT.search(step):
                continue
            seen += 1
            mount = re.search(r"--mount=type=secret,id=extra_ca\S*", step)
            assert mount and "mode=0444" in mount.group(0), f"{path.relative_to(ROOT)}: apt cannot read the secret"
    assert seen >= 2  # the demo image and the database image; the others copy the secret to a file first


def test_the_demo_image_is_one_of_them() -> None:
    steps = [s for s in _steps((ROOT / "demo" / "Dockerfile").read_text(encoding="utf-8")) if APT_READS_IT.search(s)]
    assert len(steps) == 1 and "--mount=type=secret,id=extra_ca,required=false,mode=0444" in steps[0]
