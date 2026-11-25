"""OCR escape pass (i), esc-i-1 (folded into #1469's 1469-6 and 1469-8): a host path below a folder this user may not
search (the container engine's 0710 root:root data root on a runner, a 0700 parent) is measured on the last folder the
walk can see, never a PermissionError (Path.exists() raises it there).

The unreadable folder is a stand-in: every look below it (os.stat, which Path.exists asks) answers PermissionError, as
the kernel answers a user who may not search the folder. So the cases run alike as root (who may search any folder) and
as an ordinary user, and nothing outside tmp_path is looked at. The real mode-000 folder sits beside it in
test_update_size_roles_h121.py (test_1469_8_..., test_h121_the_update_path_runs_as_a_non_root_user_...)."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast

import pytest

from tools import fetch_weights, packs
from tools.trialbox import backup_schedule, update

WALKS: dict[str, Callable[[Path], Path]] = {
    "update": update._existing,
    "backup_schedule": backup_schedule._existing,
    "packs": packs._existing,
    "fetch_weights": fetch_weights._existing,
}


@pytest.fixture
def engine_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A folder that is there, below which this user may not look: os.stat of any path below it is refused."""
    root = tmp_path / "engine-root"
    (root / "volumes" / "trialbox_db-pg" / "_data").mkdir(parents=True)
    real_stat = os.stat
    below = str(root) + os.sep

    def stat(p: Any, *a: Any, **k: Any) -> os.stat_result:
        if os.fspath(p).startswith(below):
            raise PermissionError(13, "Permission denied", os.fspath(p))
        return real_stat(p, *a, **k)

    monkeypatch.setattr(os, "stat", stat)
    yield root


def test_the_stand_in_refuses_as_the_kernel_refuses_a_user_who_may_not_search(engine_root: Path) -> None:
    """The stand-in is what the walks met on the runner: Path.exists() raises below the folder, not False."""
    assert engine_root.exists()
    with pytest.raises(PermissionError):
        (engine_root / "volumes").exists()


@pytest.mark.parametrize("walk", WALKS.values(), ids=WALKS.keys())
def test_a_path_below_a_folder_this_user_may_not_search_is_measured_on_that_folder(
    engine_root: Path, walk: Callable[[Path], Path]
) -> None:
    assert walk(engine_root / "volumes" / "trialbox_db-pg" / "_data") == engine_root
    assert walk(engine_root.parent / "not-made" / "deeper") == engine_root.parent


def test_backup_schedule_resolves_a_target_below_an_unreadable_folder(engine_root: Path) -> None:
    assert backup_schedule._resolve(engine_root / "volumes" / "x") == engine_root / "volumes" / "x"


def test_the_update_s_space_check_never_raises_on_an_unreadable_engine_root(engine_root: Path, tmp_path: Path) -> None:
    u = update.Updater(box=cast(Any, None), updates_dir=tmp_path, say=lambda s: None, disk_free=lambda p: 10**15)
    notes = u.space([(engine_root, 1, "images"), (engine_root / "volumes", 1, "rollback script (largest database)")])
    assert len(notes) == 1 and notes[0].startswith(f"{engine_root}: needs"), notes
