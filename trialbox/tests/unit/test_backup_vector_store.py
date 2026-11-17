"""D-971: the nightly backup reads the lake's vector store (``embed_cache.duckdb``) only while no build writes it.

Lane B2's answer on #639 (2026-11-16): the vector store is the one lake file written in place, by a build that holds
its snapshot's build lock (``locks/<snapshot>.build.lock``) for the whole build and the lake lock only at its start and
swap. The backup read it after letting the lake lock go (PERF-011, D-755), so a rebuild running at that moment could
put a half-written store in the backup. It is now read under the lake lock with every build lock taken, the locks held
for that read only, and the manifest records how long the backup waited and held them."""

from __future__ import annotations

import fcntl
import threading
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_backup_without_pause import _lake_files
from tools.trialbox import backup as bk


@pytest.fixture
def site(db_url: str, tmp_path: Path) -> dict[str, Any]:
    from tb_common.db import Database

    Database.connect(db_url, "site").migrate(["CREATE TABLE marks (n BIGINT PRIMARY KEY)"])
    lake = tmp_path / "lake"
    _lake_files(lake, "old", ("a", "b"))
    (lake / ".rebuild.lock").write_text("")
    (lake / "embed_cache.duckdb").write_bytes(b"vectors " * 512)
    priv, pub = tmp_path / "it.key", tmp_path / "box.pub"
    bk.keygen(priv, pub)
    return {"lake": lake, "priv": priv, "pub": pub, "env": {"TB_DB_URL": db_url, "TB_SITE_ID": "CGMH"},
            "nas": tmp_path / "nas", "tmp": tmp_path}  # fmt: skip


def _backup(s: dict[str, Any]) -> Path:
    return bk.backup([s["nas"]], s["pub"], env=s["env"], dirs={"lake": s["lake"]})[0]


def _hold_build(lake: Path, snapshot: str) -> Any:
    (lake / "locks").mkdir(exist_ok=True)
    fh = (lake / "locks" / f"{snapshot}.build.lock").open("a")
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # as lake.store.BuildLock takes it
    return fh


def test_the_vector_store_is_backed_up_and_the_wait_and_hold_are_recorded(site: dict[str, Any]) -> None:
    f = _backup(site)
    out = site["tmp"] / "x"
    m = bk.unpack(f, site["priv"], out)
    assert (out / "dirs" / "lake" / "embed_cache.duckdb").read_bytes() == b"vectors " * 512
    rec = m["lake_store"]
    assert rec["files"] == ["embed_cache.duckdb"] and rec["locked"] is True
    assert rec["waited_s"] >= 0 and rec["held_s"] >= 0


def test_the_store_and_its_wal_are_read_together(site: dict[str, Any]) -> None:
    (site["lake"] / "embed_cache.duckdb.wal").write_bytes(b"wal")
    m = bk.unpack(_backup(site), site["priv"], site["tmp"] / "x")
    assert m["lake_store"]["files"] == ["embed_cache.duckdb", "embed_cache.duckdb.wal"]


def test_a_running_build_is_waited_for(site: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bk, "LAKE_QUIET_POLL_S", 0.05)
    fh = _hold_build(site["lake"], "S")
    real, seen = bk._add, list[bool]()

    def add(tar: Any, path: Path, arcname: str) -> Any:
        if arcname == "dirs/lake/embed_cache.duckdb":
            seen.append(fh.closed)  # read only once the build let go of its lock
        return real(tar, path, arcname)

    monkeypatch.setattr(bk, "_add", add)
    threading.Timer(0.3, fh.close).start()  # the build ends
    m = bk.unpack(_backup(site), site["priv"], site["tmp"] / "x")
    assert seen == [True]
    assert m["lake_store"]["waited_s"] >= 0.2


def test_a_build_that_outlasts_the_wait_fails_the_backup_by_name(
    site: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bk, "LAKE_QUIET_WAIT_S", 0.2)
    monkeypatch.setattr(bk, "LAKE_QUIET_POLL_S", 0.05)
    fh = _hold_build(site["lake"], "2026-11-16")
    try:
        with pytest.raises(bk.BackupError, match=r"a lake rebuild ran for the whole wait \(2026-11-16"):
            _backup(site)
    finally:
        fh.close()
    assert not list(site["nas"].glob("*.tbbak"))


def test_an_idle_build_lock_file_does_not_stop_the_backup(site: dict[str, Any]) -> None:
    _hold_build(site["lake"], "S").close()  # a build ran and ended: its lock file stays (BuildLock never deletes it)
    assert _backup(site).is_file()


def test_the_lake_lock_is_held_for_the_store_read_only(site: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """While the store is read a build's start (the lake lock) waits; before it, the served files' read does not
    hold the lock (PERF-011), and after it the lock is free again."""
    real, held = bk._add, dict[str, bool]()

    def lock_free() -> bool:
        with (site["lake"] / ".rebuild.lock").open("a") as fh:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            return True

    def add(tar: Any, path: Path, arcname: str) -> Any:
        if arcname in ("dirs/lake/embed_cache.duckdb", "dirs/lake/CURRENT"):
            held[arcname] = not lock_free()
        return real(tar, path, arcname)

    (site["lake"] / "CURRENT").write_text("S\n")
    monkeypatch.setattr(bk, "_add", add)
    _backup(site)
    assert held == {"dirs/lake/CURRENT": False, "dirs/lake/embed_cache.duckdb": True}
    assert lock_free()


def test_a_lake_without_a_store_records_nothing(site: dict[str, Any]) -> None:
    (site["lake"] / "embed_cache.duckdb").unlink()
    assert "lake_store" not in bk.unpack(_backup(site), site["priv"], site["tmp"] / "x")
