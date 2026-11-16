"""PERF-010 R1 (D-968): restic, the incremental backup's tool, is built from its release's source archive (pinned
by sha256) with a patched Go (the image pinned by index digest) into its own image, ``trialbox-backup``, which only
the nightly's backup container runs: no service image carries Go code (the release gates of #887: Go's standard
library findings and Go modules without licence data). The licence register holds the same version and sum, and its
check fails when the image and the register disagree."""

from __future__ import annotations

import re
from pathlib import Path

from tools import licence_register as lr

ROOT = Path(__file__).resolve().parents[2]
BACKUP = ROOT / "deploy/docker/backup.Dockerfile"
SHA = re.compile(r"^[0-9a-f]{64}$")


def _args(text: str) -> dict[str, str]:
    return dict(re.findall(r"^ARG ([A-Z0-9_]+)=(\S+)$", text, re.M))


def test_restic_is_built_from_its_pinned_source_with_a_pinned_go() -> None:
    text = BACKUP.read_text(encoding="utf-8")
    args = _args(text)
    assert re.fullmatch(r"\d+\.\d+\.\d+", args["RESTIC_VERSION"])
    assert SHA.match(args["RESTIC_SHA256_SRC"])
    assert re.fullmatch(r"golang:1\.\d+\.\d+-bookworm@sha256:[0-9a-f]{64}", args["GO_IMAGE"])
    assert "restic-$RESTIC_VERSION.tar.gz" in text and "sha256sum -c -" in text
    assert "-mod=readonly" in text and "GOTOOLCHAIN=local" in text  # its go.sum, and no other Go fetched
    assert "go build" in text and "./cmd/restic" in text
    assert "COPY --from=restic /out/restic /usr/local/bin/restic" in text
    assert text.count("restic version") == 2  # checked in the builder and in the image


def test_each_module_bump_is_an_exact_version() -> None:
    """The release's modules with open advisories are raised to exact versions, never to a floating ``@latest``."""
    text = BACKUP.read_text(encoding="utf-8")
    bumps = re.search(r'^ARG RESTIC_MODULE_BUMPS="([^"]*)"$', text, re.M)
    assert bumps is not None
    mods = bumps.group(1).split()
    assert mods and all(re.fullmatch(r"[a-z0-9./-]+@v\d+\.\d+\.\d+", m) for m in mods), mods
    assert len({m.split("@")[0] for m in mods}) == len(mods)
    assert "go get $RESTIC_MODULE_BUMPS; go mod verify" in text


def test_no_service_image_carries_restic() -> None:
    for name in ("python.Dockerfile", "jvm.Dockerfile", "embed.Dockerfile", "db.Dockerfile"):
        assert "restic" not in (ROOT / "deploy/docker" / name).read_text(encoding="utf-8").lower(), name


def test_the_image_is_built_gated_and_bundled() -> None:
    mk = re.sub(r"\\\n\s*", "", (ROOT / "Makefile").read_text(encoding="utf-8"))  # one line per command
    images = mk[mk.index("\nimages:") : mk.index("\nembed-start:")]
    assert "-f deploy/docker/backup.Dockerfile -t trialbox-backup:1.0.0" in images
    multi = mk[mk.index("\nimages-multiarch:") :]
    assert "-f deploy/docker/backup.Dockerfile -t $(REGISTRY)/trialbox-backup:1.0.0" in multi[: multi.index("\n\n")]
    own = re.search(r"^SC_OWN_IMAGES \?= (.*)$", mk, re.M)
    assert own is not None and "trialbox-backup:1.0.0" in own.group(1).split()
    assert "trialbox-backup:1.0.0" in (ROOT / "tools/make_bundle.sh").read_text(encoding="utf-8")


def test_the_register_row_matches_the_image() -> None:
    rows = {r.id: r for r in lr.load()}
    row = rows["restic"]
    assert row.kind == "software" and row.spdx == "BSD-2-Clause" and row.status == "cleared"
    args = _args(BACKUP.read_text(encoding="utf-8"))
    assert row.raw["version"] == args["RESTIC_VERSION"]
    assert args["RESTIC_SHA256_SRC"] in row.raw["evidence"]
    assert not row.paths
    assert lr.software_problems(list(rows.values()), BACKUP.read_text(encoding="utf-8")) == []


def test_the_check_names_a_register_that_disagrees_with_the_image() -> None:
    row = next(r for r in lr.load() if r.id == "restic")
    text = BACKUP.read_text(encoding="utf-8")
    moved = re.sub(r"^ARG RESTIC_VERSION=\S+$", "ARG RESTIC_VERSION=9.9.9", text, flags=re.M)
    assert any("RESTIC_VERSION" in p for p in lr.software_problems([row], moved))
    src = _args(text)["RESTIC_SHA256_SRC"]
    assert any("RESTIC_SHA256_SRC" in p for p in lr.software_problems([row], text.replace(src, "0" * 64)))
    unpinned = re.sub(r"^ARG RESTIC_[A-Z0-9_]+=\S+\n", "", text, flags=re.M)
    assert any("no ARG RESTIC_VERSION" in p for p in lr.software_problems([row], unpinned))


def test_a_software_row_ships_no_path() -> None:
    row = next(r for r in lr.load() if r.id == "restic")
    bad = lr.Row(**{**row.__dict__, "paths": ("deploy/restic",)})
    assert any("ships no file" in p for p in lr.row_problems([bad]))


def test_the_whole_register_check_passes() -> None:
    assert lr.check() == []
