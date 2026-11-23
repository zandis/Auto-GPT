"""H-95 (c), the integrator's 7097604232: ``tools/make_bundle.sh`` refuses to make a bundle whose stack has an image
pinned by digest (``deploy/images.lock`` third_party) given by its tag alone. Such a bundle carried no image-pins.json
(the walk's step 2 of 2026-11-23), and the box could not find the image offline. Refused before anything is exported:
these runs need no Docker. Also the two packs' options that are refused before anything is built."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LOCK = json.loads((ROOT / "deploy/images.lock").read_text(encoding="utf-8"))
PINNED = {e["image"]: e["digest"] for e in LOCK["third_party"].values() if str(e.get("digest", "")).startswith("sha256:")}


def _run(tmp: Path, *args: str) -> subprocess.CompletedProcess[str]:
    (tmp / "gates.json").write_text("{}", encoding="utf-8")
    (tmp / "sbom").mkdir(exist_ok=True)
    (tmp / "vendor.key").write_text("not a key: never read before the refusals under test\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.endswith("_IMAGE")}
    env["PY"] = sys.executable
    # a stand-in docker that answers nothing and says so: every refusal here comes before an image is exported
    (tmp / "bin").mkdir(exist_ok=True)
    (tmp / "bin/docker").write_text('#!/bin/sh\necho "stand-in docker: $*" >&2\nexit 1\n', encoding="utf-8")
    (tmp / "bin/docker").chmod(0o755)
    env["PATH"] = f"{tmp}/bin:{os.environ.get('PATH', '/usr/bin:/bin')}"
    return subprocess.run(
        ["bash", str(ROOT / "tools/make_bundle.sh"), "--key", str(tmp / "vendor.key"), "--id", "2026.11-9",
         "--release-seq", "9", "--out", str(tmp / "dist/trialbox-2026.11-9.tar"), "--gates", str(tmp / "gates.json"),
         "--sbom-dir", str(tmp / "sbom"), "--allow-dirty", "a test", *args],
        capture_output=True, text=True, env=env, cwd=ROOT, check=False, timeout=120,
    )  # fmt: skip


@pytest.mark.parametrize("ref", sorted(PINNED))
def test_a_pinned_image_given_by_its_tag_alone_is_refused(tmp_path: Path, ref: str) -> None:
    r = _run(tmp_path, "--image", "trialbox-py:1.0.0", "--image", ref)
    assert r.returncode == 2, r.stderr
    assert "an image the stack pins by digest is given without its digest" in r.stderr
    assert f"{ref} (the stack pins {ref}@{PINNED[ref]})" in r.stderr
    assert not (tmp_path / "dist").exists()  # nothing made


def test_the_same_images_by_digest_pass_this_check(tmp_path: Path) -> None:
    refs = [f"{ref}@{d}" for ref, d in sorted(PINNED.items())]
    r = _run(tmp_path, "--image", "trialbox-py:1.0.0", *[x for ref in refs for x in ("--image", ref)])
    assert "given without its digest" not in r.stderr
    assert r.returncode != 0 and "stand-in docker: pull -q trialbox-py:1.0.0" in r.stderr  # it went on to the images


def test_another_tag_of_a_pinned_repository_is_refused_too(tmp_path: Path) -> None:
    ref = sorted(PINNED)[0]
    other = ref.rsplit(":", 1)[0] + ":some-other-tag"
    r = _run(tmp_path, "--image", other)
    assert r.returncode == 2 and f"{other} (the stack pins" in r.stderr


@pytest.mark.parametrize(
    ("args", "said"),
    [
        (["--model-pack-out", "dist/models.tar", "--models", "m"], "must be named trialbox-models-<id>.pack"),
        (["--model-pack-out", "dist/trialbox-models-x.pack"], "--model-pack-out needs --models"),
        (["--model-pack-out", "dist/trialbox-models-x.pack", "--model-pack", "x.pack", "--models", "m"], "one of the two"),
        (["--model-id", "x"], "--model-id and --model-release-seq go with --model-pack-out"),
    ],
)
def test_the_two_packs_options_refused_before_anything_is_built(tmp_path: Path, args: list[str], said: str) -> None:
    r = _run(tmp_path, *args)
    assert r.returncode == 2 and said in r.stderr, r.stderr
    assert not (tmp_path / "dist").exists()
