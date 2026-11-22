"""10D-16a (D-1373): where a jRCT record from a file is kept (``console.registry_record_page.Store``), with no
database: folders 0700, files 0600 owned by the process's own user, a server-chosen name, the same file kept once,
a planted symbolic link refused. Run as root and as an ordinary user (the modes do not depend on the umask)."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from console.registry_record_page import NotOurs, Store
from tb_common import registry_file as rf

from tests.unit.test_registry_file_10d16a import GOOD, WITH_NAMES

pytestmark = [pytest.mark.nodb]


@pytest.mark.parametrize("umask", [0o000, 0o022, 0o077])
def test_modes_owner_and_names_whatever_the_umask(tmp_path: Path, umask: int) -> None:
    old = os.umask(umask)
    try:
        store = Store(tmp_path / "registry_records")
        rec = rf.read_record(GOOD)
        assert store.keep("GZQO", rf.sha256(GOOD), rec, "crc1", "2026-11-21T00:00:00+00:00") is True
        assert store.keep("GZQO", rf.sha256(GOOD), rec, "crc1", "2026-11-21T00:00:01+00:00") is False
        assert store.keep(
            "GZQO", rf.sha256(WITH_NAMES), rf.read_record(WITH_NAMES), "crc1", "2026-11-21T00:00:02+00:00"
        )
    finally:
        os.umask(old)
    root = tmp_path / "registry_records"
    found = sorted(root.rglob("*"))
    assert [p.relative_to(root).as_posix() for p in found] == sorted(
        ["GZQO", f"GZQO/{rf.sha256(GOOD)}.json", f"GZQO/{rf.sha256(WITH_NAMES)}.json"]
    )
    for p in (root, *found):
        st = p.lstat()
        assert st.st_uid == os.getuid() and st.st_gid == os.getgid()
        assert stat.S_IMODE(st.st_mode) == (0o700 if p.is_dir() else 0o600), (p, oct(st.st_mode))
    got = store.records("GZQO")
    assert [r["record"]["id"] for r in got] == ["jRCT2031260902", "jRCT2031260901"]  # newest first
    assert got[1]["at"] == "2026-11-21T00:00:00+00:00"  # the second keep of the same file wrote nothing


def test_a_planted_link_or_a_bad_name_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "registry_records"
    root.mkdir(mode=0o700)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "GZQO").symlink_to(outside)
    store = Store(root)
    rec = rf.read_record(GOOD)
    with pytest.raises(OSError):
        store.keep("GZQO", rf.sha256(GOOD), rec, "crc1", "2026-11-21T00:00:00+00:00")
    assert list(outside.iterdir()) == []
    for rid, sha in (("../x", rf.sha256(GOOD)), ("gzqo", rf.sha256(GOOD)), ("GZQO2", "../" + "a" * 61)):
        with pytest.raises(ValueError):
            store.keep(rid, sha, rec, "crc1", "2026-11-21T00:00:00+00:00")
    assert store.records("NONE") == []


def test_a_study_code_with_a_line_end_is_refused(tmp_path: Path) -> None:
    """L8: the code is matched whole (no "A" + line end)."""
    store = Store(tmp_path / "registry_records")
    with pytest.raises(ValueError):
        store.keep("GZQO\n", rf.sha256(GOOD), rf.read_record(GOOD), "crc1", "2026-11-21T00:00:00+00:00")
    assert not (tmp_path / "registry_records").exists() or list((tmp_path / "registry_records").iterdir()) == []


def _plant(folder: Path, name: str, **d: object) -> None:
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    base = {"study": "GZQO", "registry": "jRCT", "file_sha256": name, "by": "planted",
            "at": "2026-11-21T00:00:00+00:00", "record": dict.fromkeys(rf.KEPT, "planted")}  # fmt: skip
    (folder / f"{name}.json").write_text(__import__("json").dumps({**base, **d}), encoding="utf-8")


def test_the_store_trusts_nothing_it_did_not_write(tmp_path: Path) -> None:
    """L9: a file whose study or SHA-256 is not its folder and name is never shown, and a write over it, or over a
    dangling link, is refused instead of being reported as kept."""
    root = tmp_path / "registry_records"
    folder = root / "GZQO"
    sha, rec = rf.sha256(GOOD), rf.read_record(GOOD)
    _plant(folder, sha, file_sha256="0" * 64)  # the content's SHA-256 is not its name
    _plant(folder, "1" * 64, study="OTHER")  # another study's record in this folder
    store = Store(root)
    assert store.records("GZQO") == []
    with pytest.raises(NotOurs):
        store.keep("GZQO", sha, rec, "crc1", "2026-11-21T00:00:00+00:00")
    other = rf.sha256(WITH_NAMES)
    (folder / f"{other}.json").symlink_to(tmp_path / "nowhere")  # a dangling link
    with pytest.raises(NotOurs):
        store.keep("GZQO", other, rf.read_record(WITH_NAMES), "crc1", "2026-11-21T00:00:00+00:00")
    assert not (tmp_path / "nowhere").exists()


def test_the_current_record_is_chosen_by_time_not_by_text(tmp_path: Path) -> None:
    """L10: times written with different offsets are compared as times."""
    store = Store(tmp_path / "registry_records")
    store.keep("GZQO", rf.sha256(GOOD), rf.read_record(GOOD), "crc1", "2026-11-21T09:00:00+09:00")  # 00:00 UTC
    store.keep("GZQO", rf.sha256(WITH_NAMES), rf.read_record(WITH_NAMES), "crc1", "2026-11-21T01:00:00+00:00")
    assert [r["record"]["id"] for r in store.records("GZQO")] == ["jRCT2031260902", "jRCT2031260901"]
