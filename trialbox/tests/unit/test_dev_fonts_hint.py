"""D-829: a fresh checkout's `make venv` says plainly that the PDF reports need the fonts (`make fonts`) when they
are not fetched yet: on a host run, 3 of 8 SCREEN jobs failed at the report (ReportError) before anyone ran
tools/fetch_fonts.py. No download is added to `make venv` (CI runs it in every job). An installed box has them in
the trialbox-py image (deploy/docker/python.Dockerfile)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="needs make")


def _venv(fonts: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["make", "--no-print-directory", "-s", "venv", "UV_SYNC=true", f"FONTS={fonts}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_make_venv_names_make_fonts_when_the_fonts_are_missing(tmp_path: Path) -> None:
    res = _venv(tmp_path / "NotoSansTC-Regular.ttf")
    assert res.returncode == 0
    assert "make fonts" in res.stderr and "report" in res.stderr


def test_make_venv_is_quiet_when_the_fonts_are_there(tmp_path: Path) -> None:
    font = tmp_path / "NotoSansTC-Regular.ttf"
    font.write_bytes(b"x")
    res = _venv(font)
    assert res.returncode == 0
    assert "make fonts" not in res.stderr


def test_the_box_image_carries_the_fonts() -> None:
    docker = (ROOT / "deploy" / "docker" / "python.Dockerfile").read_text(encoding="utf-8")
    assert "NotoSansTC-Regular.ttf" in docker and "/opt/trialbox/fonts" in docker
    images = (ROOT / "Makefile").read_text(encoding="utf-8").split("\nimages:", 1)[1].split("\n", 1)[0]
    assert "$(FONTS)" in images
