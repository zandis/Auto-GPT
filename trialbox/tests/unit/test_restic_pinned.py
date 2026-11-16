"""PERF-010 R1 (D-968): restic, the incremental backup's tool, rides in the ``trialbox-py`` image (the backup
container), pinned by version and by the sha256 of each architecture's release file; the licence register holds the
same version and sums, and its check fails when the image and the register disagree."""

from __future__ import annotations

import re
from pathlib import Path

from tools import licence_register as lr

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "deploy/docker/python.Dockerfile"
SHA = re.compile(r"^[0-9a-f]{64}$")


def _args(text: str) -> dict[str, str]:
    return dict(re.findall(r"^ARG (RESTIC_[A-Z0-9_]+)=(\S+)$", text, re.M))


def test_the_image_pins_restic_for_both_architectures() -> None:
    args = _args(DOCKERFILE.read_text(encoding="utf-8"))
    assert re.fullmatch(r"\d+\.\d+\.\d+", args["RESTIC_VERSION"])
    assert SHA.match(args["RESTIC_SHA256_AMD64"]) and SHA.match(args["RESTIC_SHA256_ARM64"])
    assert args["RESTIC_SHA256_AMD64"] != args["RESTIC_SHA256_ARM64"]


def test_the_download_is_the_pinned_fetch_and_no_os_package() -> None:
    """The release file comes through tools/fetch_pinned.py (https, written only at the pinned sha256, D-632); it is
    unpacked by python (the slim base has no bzip2, and D-23 adds no OS package); an architecture without a pin stops
    the build."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    step = text[text.index("ARG RESTIC_VERSION") :]
    step = step[: step.index("restic version") + len("restic version")]
    assert "fetch_pinned.py" in step
    assert "https://github.com/restic/restic/releases/download/v$RESTIC_VERSION/" in step
    assert "restic_${RESTIC_VERSION}_linux_${TARGETARCH}.bz2" in step
    assert 'amd64) sha="$RESTIC_SHA256_AMD64"' in step and 'arm64) sha="$RESTIC_SHA256_ARM64"' in step
    assert "exit 1" in step  # any other architecture
    assert "bz2.decompress" in step
    assert "apt-get install" not in text


def test_the_register_row_matches_the_image() -> None:
    rows = {r.id: r for r in lr.load()}
    row = rows["restic"]
    assert row.kind == "software" and row.spdx == "BSD-2-Clause" and row.status == "cleared"
    args = _args(DOCKERFILE.read_text(encoding="utf-8"))
    assert row.raw["version"] == args["RESTIC_VERSION"]
    assert args["RESTIC_SHA256_AMD64"] in row.raw["evidence"] and args["RESTIC_SHA256_ARM64"] in row.raw["evidence"]
    assert not row.paths
    assert lr.software_problems(list(rows.values()), DOCKERFILE.read_text(encoding="utf-8")) == []


def test_the_check_names_a_register_that_disagrees_with_the_image() -> None:
    row = next(r for r in lr.load() if r.id == "restic")
    text = DOCKERFILE.read_text(encoding="utf-8")
    moved = re.sub(r"^ARG RESTIC_VERSION=\S+$", "ARG RESTIC_VERSION=9.9.9", text, flags=re.M)
    assert any("RESTIC_VERSION" in p for p in lr.software_problems([row], moved))
    amd = _args(text)["RESTIC_SHA256_AMD64"]
    other = text.replace(amd, "0" * 64)
    assert any("RESTIC_SHA256_AMD64" in p for p in lr.software_problems([row], other))
    unpinned = re.sub(r"^ARG RESTIC_[A-Z0-9_]+=\S+\n", "", text, flags=re.M)
    assert any("no ARG RESTIC_VERSION" in p for p in lr.software_problems([row], unpinned))


def test_a_software_row_ships_no_path() -> None:
    row = next(r for r in lr.load() if r.id == "restic")
    bad = lr.Row(**{**row.__dict__, "paths": ("deploy/restic",)})
    assert any("ships no file" in p for p in lr.row_problems([bad]))


def test_the_whole_register_check_passes() -> None:
    assert lr.check() == []
