"""I-7 (D-883): `make rehearse-box` says what it lacks before it builds anything: a Trivy database the release gates
accept, and the disk the media and the reloaded images need. Before, both failed half an hour in (the gates in the
media step, a full disk in the load)."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from tools.rehearse_box import preflight

ROOT = Path(__file__).resolve().parents[2]
NOW = dt.datetime(2026, 11, 15, 12, tzinfo=dt.UTC)
GB = 1 << 30

pytestmark = pytest.mark.nodb


def _db(cache: Path, days_old: int) -> Path:
    for sub in ("db", "java-db"):
        (cache / sub).mkdir(parents=True, exist_ok=True)
        when = (NOW - dt.timedelta(days=days_old)).isoformat()
        (cache / sub / "metadata.json").write_text(json.dumps({"UpdatedAt": when}), encoding="utf-8")
    return cache


def test_a_fresh_db_and_room_pass(tmp_path: Path) -> None:
    cache = _db(tmp_path / "trivy", 1)
    got = preflight.problems(tmp_path, cache, min_free_gb=30, now=NOW, free=lambda p: 100 * GB)
    assert got == []


def test_no_db_names_make_trivy_db(tmp_path: Path) -> None:
    got = preflight.problems(tmp_path, tmp_path / "none", min_free_gb=30, now=NOW, free=lambda p: 100 * GB)
    assert got and all("make trivy-db" in p for p in got)


def test_an_old_db_names_make_trivy_db(tmp_path: Path) -> None:
    cache = _db(tmp_path / "trivy", 30)
    got = preflight.problems(tmp_path, cache, min_free_gb=30, now=NOW, free=lambda p: 100 * GB)
    assert got and "days old" in got[0] and "make trivy-db" in got[0]


def test_too_little_disk_names_the_folder_the_need_and_the_knob(tmp_path: Path) -> None:
    cache = _db(tmp_path / "trivy", 1)
    got = preflight.problems(tmp_path, cache, min_free_gb=30, now=NOW, free=lambda p: 12 * GB)
    assert len(got) == 1
    assert str(tmp_path) in got[0] and "12.0 GB free" in got[0] and "30 GB" in got[0]
    assert "TB_REHEARSE_MIN_FREE_GB" in got[0]


def test_the_docker_root_is_checked_when_it_is_a_local_folder(tmp_path: Path) -> None:
    cache = _db(tmp_path / "trivy", 1)
    droot = tmp_path / "docker"
    droot.mkdir()
    got = preflight.problems(
        tmp_path / "w", cache, min_free_gb=30, now=NOW, docker_root=droot,
        free=lambda p: 5 * GB if p == droot else 100 * GB,
    )  # fmt: skip
    assert len(got) == 1 and "Docker's root" in got[0] and str(droot) in got[0]
    # a remote daemon's root (not a folder here) is not checked
    assert preflight.problems(tmp_path / "w", cache, min_free_gb=30, now=NOW, docker_root=tmp_path / "remote",
                              free=lambda p: 100 * GB) == []  # fmt: skip


def test_rehearse_runs_the_preflight_in_its_first_step() -> None:
    text = (ROOT / "tools/rehearse_box/rehearse.sh").read_text(encoding="utf-8")
    body = text[text.index("preconditions() {") : text.index("\n}\n", text.index("preconditions() {"))]
    assert "tools.rehearse_box.preflight" in body and "TB_REHEARSE_MIN_FREE_GB" in body
    assert "TRIVY_CACHE" in body
