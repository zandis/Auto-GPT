"""10D-16a (D-1373): where a jRCT record from a file is kept (``console.registry_record_page.Store``), with no
database: folders 0700, files 0600 owned by the process's own user, a server-chosen name, the same file kept once,
a planted symbolic link refused. Run as root and as an ordinary user (the modes do not depend on the umask)."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from console.registry_record_page import Store
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
