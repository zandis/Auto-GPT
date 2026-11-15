"""D-830: make_bundle says the disk space it needs before it saves the first image, and where (TMPDIR moves the
staging folder). Lane G's build ran out of space under /tmp while packing the vLLM image."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tools import bundle_space

pytestmark = pytest.mark.nodb

GB = 1 << 30


def test_enough_space_is_quiet(tmp_path: Path) -> None:
    assert bundle_space.problems(tmp_path, tmp_path, 1 * GB, free=lambda _p: 100 * GB) == []


def test_too_little_space_names_the_size_the_folder_and_tmpdir(tmp_path: Path) -> None:
    out = bundle_space.problems(tmp_path / "stage", tmp_path / "out", 40 * GB, free=lambda _p: 50 * GB, same=True)
    assert len(out) == 1
    assert "GB" in out[0] and "TMPDIR" in out[0] and str(tmp_path / "stage") in out[0]


def test_staging_and_the_bundle_on_different_disks_are_checked_apart(tmp_path: Path) -> None:
    stage, out = tmp_path / "stage", tmp_path / "out"
    free = {stage: 100 * GB, out: 1 * GB}
    problems = bundle_space.problems(stage, out, 10 * GB, free=lambda p: free[p], same=False)
    assert len(problems) == 1 and str(out) in problems[0] and "--out" in problems[0]


def test_payload_size_counts_images_and_models(tmp_path: Path) -> None:
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "w.bin").write_bytes(b"x" * 1000)
    inspect = {"a": [{"Size": 5000}], "b": [{}], "c": None}
    assert bundle_space.payload_bytes(["a", "b", "c"], tmp_path / "m", inspect=lambda r: inspect[r]) == 6000


def test_the_script_runs_the_check_before_the_first_save() -> None:
    script = (Path(bundle_space.__file__).resolve().parents[1] / "tools" / "make_bundle.sh").read_text(encoding="utf-8")
    assert script.index("tools.bundle_space") < script.index('echo "==> images"')
    assert os.path.basename(bundle_space.__file__) == "bundle_space.py"
