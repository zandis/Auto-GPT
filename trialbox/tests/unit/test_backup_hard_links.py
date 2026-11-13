"""NEW-B-17 (D-537): a directory the backup takes whole may hold two names of one file (hard links).

The nightly's ``backup-drill`` and ``update-drill`` failed with "backup content does not match its manifest": the
site set-up's work lake (``orch/sitesetup/<ws>/lake``) holds each date's DuckDB file under two or three names
(``db/<date>.duckdb``, its generation, a reader's link), and the tar writer made the second name a link with no
bytes, so the manifest recorded the hash of nothing for a file a restore writes whole."""

from __future__ import annotations

import hashlib
import os
import tarfile
from pathlib import Path

import pytest

from tests.unit.test_backup import _backup, box  # noqa: F401 (box: a fixture)
from tools.trialbox import backup as bk


def test_the_second_name_of_one_file_is_recorded_with_its_bytes(tmp_path: Path) -> None:
    a, b = tmp_path / "2026-11-02.duckdb", tmp_path / "2026-11-02.g1.duckdb"
    a.write_bytes(b"duck" * 1000)
    os.link(a, b)
    want = hashlib.sha256(a.read_bytes()).hexdigest()
    with tarfile.open(tmp_path / "a.tar", "w") as tar:
        first = bk._add(tar, a, "dirs/box/lake/db/2026-11-02.duckdb")
        second = bk._add(tar, b, "dirs/box/lake/db/gen/2026-11-02.g1.duckdb")
    assert first == (want, 4000) and second == (want, 4000)
    with tarfile.open(tmp_path / "a.tar") as tar:
        members = tar.getmembers()
        assert [m.isreg() for m in members] == [True, True]  # each name stands alone: no member needs another
        assert [tar.extractfile(m).read() for m in members] == [a.read_bytes()] * 2  # type: ignore[union-attr]


def test_a_backup_of_a_folder_with_two_names_of_one_file_verifies_and_restores(
    box: dict[str, object],  # noqa: F811
    tmp_path: Path,
) -> None:
    dirs: dict[str, Path] = box["dirs"]  # type: ignore[assignment]
    work = dirs["audit"] / "sitesetup" / "ws" / "lake" / "db"  # any directory taken whole (only "lake" has rules)
    (work / "gen").mkdir(parents=True)
    (work / "2026-11-02.duckdb").write_bytes(b"duck" * 1000)
    os.link(work / "2026-11-02.duckdb", work / "gen" / "2026-11-02.g1.duckdb")
    files = _backup(box, tmp_path)
    assert bk.verify(files[0], box["priv"])["ok"]  # type: ignore[arg-type]
    into = tmp_path / "out"
    manifest = bk.unpack(files[0], box["priv"], into)  # type: ignore[arg-type]
    rel = "dirs/audit/sitesetup/ws/lake/db"
    for name in (f"{rel}/2026-11-02.duckdb", f"{rel}/gen/2026-11-02.g1.duckdb"):
        assert (into / name).read_bytes() == b"duck" * 1000 and manifest["sizes"][name] == 4000


# ------------------------------------------------------------------------------------------------ review fixes
def _as_before_the_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_add`` as it was: the tar writer's link member is not seen, so it is stored with no bytes."""
    monkeypatch.setattr(tarfile.TarInfo, "islnk", lambda self: False)


def test_a_backup_written_before_the_fix_is_still_restorable(
    box: dict[str, object],  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The nightly never opens what it wrote (it has no private key), so such backups were recorded as good. Their
    bytes are whole: only the manifest's entry for the second name is the hash of nothing."""
    dirs: dict[str, Path] = box["dirs"]  # type: ignore[assignment]
    work = dirs["audit"] / "sitesetup" / "ws" / "lake" / "db"
    (work / "gen").mkdir(parents=True)
    (work / "2026-11-02.duckdb").write_bytes(b"duck" * 1000)
    os.link(work / "2026-11-02.duckdb", work / "gen" / "2026-11-02.g1.duckdb")
    with monkeypatch.context() as mp:
        _as_before_the_fix(mp)
        files = _backup(box, tmp_path)
    into = tmp_path / "out"
    manifest = bk.unpack(files[0], box["priv"], into)  # type: ignore[arg-type]
    first, second = (f"dirs/audit/sitesetup/ws/lake/db/{n}" for n in ("2026-11-02.duckdb", "gen/2026-11-02.g1.duckdb"))
    assert (into / second).read_bytes() == b"duck" * 1000
    # the manifest a restore works from names what the file is, not the fault
    assert manifest["files"][second] == manifest["files"][first] == hashlib.sha256(b"duck" * 1000).hexdigest()
    assert manifest["sizes"][second] == 4000
    assert bk.verify(files[0], box["priv"])["ok"]  # type: ignore[arg-type]


def test_only_a_second_name_of_a_file_that_verifies_is_read_so(tmp_path: Path) -> None:
    """The reading rule is exact: the entry is the hash of nothing with size 0, and the extracted file IS (the same
    file as) a listed one whose hash holds. Anything else stays a mismatch."""
    nothing = hashlib.sha256(b"").hexdigest()
    good = hashlib.sha256(b"x").hexdigest()
    (tmp_path / "a").write_bytes(b"x")
    os.link(tmp_path / "a", tmp_path / "b")
    (tmp_path / "alone").write_bytes(b"x")  # the same bytes, but a file of its own: not a second name
    (tmp_path / "c").write_bytes(b"y")
    os.link(tmp_path / "c", tmp_path / "d")  # a second name of a file that does NOT verify
    m = {
        "files": {"a": good, "b": nothing, "alone": nothing, "c": good, "d": nothing, "e": good},
        "sizes": {"a": 1, "b": 0, "alone": 0, "c": 1, "d": 0, "e": 1},
    }
    os.link(tmp_path / "a", tmp_path / "e")
    m["files"]["e"] = hashlib.sha256(b"z").hexdigest()  # a wrong hash that is not the fault's: never read so
    bad = ["b", "alone", "c", "d", "e"]
    assert bk._second_names(tmp_path, m, bad) == ["alone", "c", "d", "e"]
    assert m["files"]["b"] == good and m["sizes"]["b"] == 1
