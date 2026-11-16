"""PERF-010 R3a (D-968): the restic runner. One repository per backup target; the first is made and written by
``backup``, each other one is made with the first's chunker parameters (so it deduplicates the same) and filled by
``restic copy``; ``forget`` keeps the newest N snapshots of the lake; ``restore`` gives a snapshot back. The
password reaches restic through its environment only, never its argument list, and an error says what failed without
a password in it. restic itself is a stand-in here (tests/fixtures/restic/fake_restic.py): the real binary is pinned
in the image (R1) and runs in the box rehearsal (R4)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from tools.trialbox import restic_repo as rr

FAKE = Path(__file__).resolve().parents[1] / "fixtures" / "restic" / "fake_restic.py"
PW = "ab" * 32
pytestmark = pytest.mark.nodb


@pytest.fixture
def restic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    log = tmp_path / "restic.log"
    monkeypatch.setenv("FAKE_RESTIC_LOG", str(log))
    monkeypatch.setenv(rr.CMD_ENV, f"{sys.executable} {FAKE}")
    return log


def _calls(log: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]


def _lake(tmp_path: Path) -> tuple[Path, list[str]]:
    root = tmp_path / "lake"
    files = ["db/2026-11-01.duckdb", "parquet/snapshot=2026-11-01/part-0.parquet", "db/2026-11-01.duckdb.sha256"]
    for rel in files:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(rel.encode())
    return root, files


def _repo(tmp_path: Path, name: str = "t1", pw: str = PW) -> rr.Repo:
    return rr.Repo(tmp_path / name / rr.REPO_DIR, pw)


def test_a_new_target_gets_a_repository_and_a_second_run_keeps_it(tmp_path: Path, restic: Path) -> None:
    repo = _repo(tmp_path)
    assert repo.ensure() is True
    assert repo.ensure() is False
    assert (tmp_path / "t1" / rr.REPO_DIR / "config").is_file()


def test_a_repository_of_another_key_is_refused(tmp_path: Path, restic: Path) -> None:
    _repo(tmp_path).ensure()
    other = _repo(tmp_path, pw="cd" * 32)
    with pytest.raises(rr.ResticError, match="another password") as e:
        other.ensure()
    assert PW not in str(e.value) and "cd" * 32 not in str(e.value)


def test_backup_takes_exactly_the_listed_files_and_names_the_snapshot(tmp_path: Path, restic: Path) -> None:
    root, files = _lake(tmp_path)
    (root / "db" / "not-listed.duckdb").write_bytes(b"x")
    repo = _repo(tmp_path)
    repo.ensure()
    sid = repo.backup(root, files, tag=rr.LAKE_TAG)
    assert len(sid) >= 8
    out = tmp_path / "restored"
    repo.restore(sid, out)
    got = rr.restored_root(out, root)
    assert sorted(str(p.relative_to(got)) for p in got.rglob("*") if p.is_file()) == sorted(files)
    assert (got / files[0]).read_bytes() == files[0].encode()


def test_a_file_that_vanished_fails_the_backup(tmp_path: Path, restic: Path) -> None:
    """restic says 3 when a listed file could not be read: an incomplete snapshot is not a backup."""
    root, files = _lake(tmp_path)
    repo = _repo(tmp_path)
    repo.ensure()
    with pytest.raises(rr.ResticError, match="incomplete"):
        repo.backup(root, [*files, "db/gone.duckdb"], tag=rr.LAKE_TAG)


def test_the_other_targets_are_copies_with_the_same_chunker(tmp_path: Path, restic: Path) -> None:
    root, files = _lake(tmp_path)
    first, second = _repo(tmp_path, "t1"), _repo(tmp_path, "t2")
    first.ensure()
    sid = first.backup(root, files, tag=rr.LAKE_TAG)
    assert second.ensure(like=first) is True
    second.copy_from(first, sid)
    out = tmp_path / "from-second"
    second.restore(sid, out)
    assert (rr.restored_root(out, root) / files[1]).read_bytes() == files[1].encode()
    init = next(c for c in _calls(restic) if "init" in c["argv"] and str(second.path) in c["argv"])
    assert "--copy-chunker-params" in init["argv"] and "--from-repo" in init["argv"]


def test_forget_keeps_the_newest(tmp_path: Path, restic: Path) -> None:
    root, files = _lake(tmp_path)
    repo = _repo(tmp_path)
    repo.ensure()
    ids = [repo.backup(root, files, tag=rr.LAKE_TAG) for _ in range(4)]
    repo.forget(keep=2, tag=rr.LAKE_TAG)
    assert repo.snapshot_ids() == ids[-2:]


def test_the_password_never_reaches_an_argument_list(tmp_path: Path, restic: Path) -> None:
    root, files = _lake(tmp_path)
    first, second = _repo(tmp_path, "t1"), _repo(tmp_path, "t2")
    first.ensure()
    sid = first.backup(root, files, tag=rr.LAKE_TAG)
    second.ensure(like=first)
    second.copy_from(first, sid)
    calls = _calls(restic)
    assert calls and all(c["password_set"] for c in calls)
    assert all(PW not in json.dumps(c["argv"]) for c in calls)


def test_outside_restic_settings_do_not_choose_the_repository(
    tmp_path: Path, restic: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RESTIC_REPOSITORY", str(tmp_path / "elsewhere"))
    monkeypatch.setenv("RESTIC_PASSWORD", "outside")
    repo = _repo(tmp_path)
    assert repo.ensure() is True
    assert not (tmp_path / "elsewhere").exists() and (repo.path / "config").is_file()
    assert repo.ensure() is False  # it opens with the box's password, not the outside one
    with pytest.raises(rr.ResticError, match="another password"):
        _repo(tmp_path, pw="outside").ensure()


def test_a_missing_restic_is_said_plainly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(rr.CMD_ENV, str(tmp_path / "no-such-restic"))
    with pytest.raises(rr.ResticError, match="restic is not"):
        _repo(tmp_path).ensure()
