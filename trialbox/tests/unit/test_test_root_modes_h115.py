"""H-115: the test root ``make test`` marks is closed to others whatever the runner's umask.

Under an ordinary user's umask 002, ``/var/tmp/trialbox-<uid>`` and the test root came out 0775. The product's checks
that walk the real folders from ``/`` then rightly refused every tree a test built below them. ``mark_test_root``
makes the folders it creates 0700. It takes group and others' write from the test root and the folders up to the
per-user scratch root, and from a test root left 0775 by an earlier run. It never changes a folder above the scratch
root."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from tools import pglocal

pytestmark = pytest.mark.nodb


def _mode(p: Path) -> int:
    return stat.S_IMODE(os.lstat(p).st_mode)


def test_the_folders_it_creates_are_0700_under_umask_002(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    above = tmp_path / "above"
    above.mkdir()
    above.chmod(0o755)
    monkeypatch.setenv("TB_SCRATCH", str(above / "scratch"))
    old = os.umask(0o002)
    try:
        root = pglocal.mark_test_root(above / "scratch" / "tb-tests-x")
    finally:
        os.umask(old)
    assert _mode(above / "scratch") == 0o700 and _mode(root) == 0o700
    assert (root / pglocal.MARKER).is_file()


def test_a_root_left_0775_by_an_earlier_run_is_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    above = tmp_path / "above"
    scratch = above / "scratch"
    root = scratch / "tb-tests-x"
    root.mkdir(parents=True)
    (root / pglocal.MARKER).touch()
    for folder in (above, scratch, root):
        folder.chmod(0o775)
    root.chmod(0o771)  # the search bit a database server's account was given stays
    monkeypatch.setenv("TB_SCRATCH", str(scratch))
    assert pglocal.mark_test_root(root) == root
    assert (_mode(scratch), _mode(root)) == (0o755, 0o751)
    assert _mode(above) == 0o775  # above the per-user scratch root: never changed


def test_a_root_outside_the_scratch_root_closes_only_itself(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_SCRATCH", str(tmp_path / "scratch"))
    mine = tmp_path / "elsewhere"
    mine.mkdir()
    mine.chmod(0o775)
    root = mine / "tb-tests-y"
    root.mkdir()
    root.chmod(0o775)
    pglocal.mark_test_root(root)
    assert (_mode(mine), _mode(root)) == (0o775, 0o755)
