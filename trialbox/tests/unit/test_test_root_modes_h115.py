"""H-115: the test root ``make test`` marks is closed to others whatever the runner's umask.

Under an ordinary user's umask 002, ``/var/tmp/trialbox-<uid>`` and the test root came out 0775. The product's checks
that walk the real folders from ``/`` then rightly refused every tree a test built below them. ``mark_test_root``
makes the folders it creates 0700. It takes group and others' write from the test root and the folders up to the
per-user scratch root, and from a test root left 0775 by an earlier run. It never changes a folder above the scratch
root."""

from __future__ import annotations

import contextlib
import os
import stat
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from tools import full_set, pglocal

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


# ------------------------------------------------------------------------------------------------ the review of #1462
def test_the_full_sets_test_root_is_closed_under_umask_002(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """1462-1: tools.full_set (rc1 line 1) makes --out with the runner's umask, inside a clone made the same way. The
    test root it gives the stages lies where mark_test_root closes every folder, so the walk from / meets no folder
    others may write."""
    monkeypatch.setenv("TB_SCRATCH", str(tmp_path / "scratch"))
    out = tmp_path / "clone" / "full-set"
    seen: dict[str, Path] = {}

    def runner(argv: Sequence[str], log: Path, env: dict[str, str]) -> int:
        seen["root"] = Path(env["TB_TEST_ROOT"])
        return 0

    old = os.umask(0o002)
    try:
        full_set.main(["--out", str(out), "--only", "unit", "--runs", "1"], runner)
        root = pglocal.mark_test_root(seen["root"])
    finally:
        os.umask(old)
    assert _mode(out) & 0o022  # the folder full_set made: 0775 under umask 002
    for folder in [root, *root.parents]:
        if folder == tmp_path:
            break
        assert not _mode(folder) & 0o022, folder


def test_a_folder_another_run_makes_at_the_same_moment_is_no_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """1462-2 (D-201): two branches' make test start at once on a host with no scratch root yet; both go on."""
    scratch = tmp_path / "scratch"
    monkeypatch.setenv("TB_SCRATCH", str(scratch))
    real = Path.mkdir

    def racing(self: Path, mode: int = 0o777, parents: bool = False, exist_ok: bool = False) -> None:
        if self == scratch and not self.exists():
            real(self, 0o700)  # the other run's mkdir lands between this run's exists() and its mkdir()
        real(self, mode, parents, exist_ok)

    monkeypatch.setattr(Path, "mkdir", racing)
    root = pglocal.mark_test_root(scratch / "tb-tests-x")
    assert (root / pglocal.MARKER).is_file() and _mode(scratch) == 0o700


def test_a_scratch_root_another_account_made_first_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """1462-3: the default scratch root has a fixed name in a shared folder. Another account may make it before this
    user's first run, and then rename or replace the test root inside it. The run stops instead of using it."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    scratch.chmod(0o777)
    monkeypatch.setenv("TB_SCRATCH", str(scratch))
    if os.geteuid() == 0:
        os.chown(scratch, 65534, 65534)  # root: the folder is really another account's
    else:
        monkeypatch.setattr(os, "geteuid", lambda: os.lstat(scratch).st_uid + 1)  # a user: this run is another's
    with pytest.raises(ValueError, match="not this user's"):
        pglocal.mark_test_root(scratch / "tb-tests-x")
    assert not (scratch / "tb-tests-x" / pglocal.MARKER).exists()


@pytest.mark.parametrize("case", ["a group's shared folder", "TB_SCRATCH=/"])
def test_a_folder_the_user_shares_or_did_not_mean_is_never_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """1462-4: a setgid folder is a group's; with TB_SCRATCH=/ nothing above the test root is the scratch root's."""
    shared = tmp_path / "team"
    shared.mkdir()
    if case == "TB_SCRATCH=/":
        shared.chmod(0o775)
        monkeypatch.setenv("TB_SCRATCH", "/")
    else:
        shared.chmod(0o2775)
        monkeypatch.setenv("TB_SCRATCH", str(shared))
    pglocal.mark_test_root(shared / "tb-tests-x")
    assert _mode(shared) == (0o775 if case == "TB_SCRATCH=/" else 0o2775)


def test_a_scratch_root_named_through_a_link_is_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """1462-5: the scratch root is compared as a real path, as the test root is."""
    real = tmp_path / "real"
    real.mkdir()
    real.chmod(0o775)
    (tmp_path / "link").symlink_to(real)
    monkeypatch.setenv("TB_SCRATCH", str(tmp_path / "link"))
    pglocal.mark_test_root(tmp_path / "link" / "tb-tests-x")
    assert _mode(real) == 0o755


def test_a_root_swapped_for_a_link_between_the_look_and_the_change_moves_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """1462-6: the root is replaced by a link to another folder of this user's right after it is looked at."""
    monkeypatch.setenv("TB_SCRATCH", str(tmp_path / "scratch"))
    victim = tmp_path / "victim"
    victim.mkdir()
    victim.chmod(0o775)
    root = tmp_path / "elsewhere" / "tb-tests-y"
    root.mkdir(parents=True)
    root.chmod(0o775)
    real_lstat, real_open, real_check = os.lstat, os.open, pglocal.check_test_root
    armed: list[bool] = []

    def check(path: Path) -> Path:
        p = real_check(path)
        armed.append(True)  # from here on the root is looked at, then changed
        return p

    def swap() -> None:
        if armed and not root.is_symlink():
            root.rename(tmp_path / "moved")
            root.symlink_to(victim)

    def lstat(path: Any, *a: Any, **k: Any) -> os.stat_result:
        st = real_lstat(path, *a, **k)
        if Path(str(path)) == root:
            swap()
        return st

    def open_(path: Any, *a: Any, **k: Any) -> int:
        if Path(str(path)) == root:
            swap()
        return real_open(path, *a, **k)

    monkeypatch.setattr(pglocal, "check_test_root", check)
    monkeypatch.setattr(os, "lstat", lstat)
    monkeypatch.setattr(os, "open", open_)
    with contextlib.suppress(OSError):
        pglocal.mark_test_root(root)
    assert _mode(victim) == 0o775


@pytest.mark.parametrize("mode", [0o1777, 0o1733])
def test_a_sticky_scratch_root_another_account_made_first_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: int
) -> None:
    """1462-10: a sticky bit keeps others from renaming what this user makes in a folder, never the folder's owner.
    Another account that makes the scratch root first, sticky and open to all, can still swap the test root."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    scratch.chmod(mode)
    monkeypatch.setenv("TB_SCRATCH", str(scratch))
    real_lstat = os.lstat

    def lstat(path: Any, *a: Any, **k: Any) -> os.stat_result:
        st = real_lstat(path, *a, **k)
        if Path(str(path)) == scratch:  # the scratch root is another account's; the test root below is this user's
            fields = list(st)
            fields[4] = st.st_uid + 1
            return os.stat_result(fields)
        return st

    monkeypatch.setattr(os, "lstat", lstat)
    with pytest.raises(ValueError, match="not this user's"):
        pglocal.mark_test_root(scratch / "tb-tests-x")
    assert not (scratch / "tb-tests-x" / pglocal.MARKER).exists()


def test_a_root_swapped_for_a_link_after_the_checks_leaves_no_marker_elsewhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """1462-11: the root is replaced by a link to another folder of this user's, which holds other files, after it is
    checked. The marker is not written through the link: that folder never becomes a test root."""
    monkeypatch.setenv("TB_SCRATCH", str(tmp_path / "scratch"))
    other = tmp_path / "other"
    other.mkdir()
    (other / "notes.txt").write_text("not a test root\n", encoding="utf-8")
    root = tmp_path / "elsewhere" / "tb-tests-z"
    root.mkdir(parents=True)
    real_close = pglocal._close_to_others

    def close_then_swap(folder: Path) -> None:
        real_close(folder)
        if folder == root and not root.is_symlink():  # the last check of the root is done: swap it now
            root.rename(tmp_path / "moved")
            root.symlink_to(other)

    monkeypatch.setattr(pglocal, "_close_to_others", close_then_swap)
    with pytest.raises(OSError):
        pglocal.mark_test_root(root)
    assert not (other / pglocal.MARKER).exists()
    with pytest.raises(ValueError, match="no .tb-test-root marker"):
        pglocal.check_test_root(other)
