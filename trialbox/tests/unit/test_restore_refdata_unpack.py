"""10G-1 (D-1323): a restore unpacks the reference packs on disk, beside the kept packs, never in a tmpfs /tmp
(``backup.reload_refdata``; the installer and the update use ``TMPDIR=/data/objects`` for the same reason)."""

from __future__ import annotations

import contextlib
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tools.trialbox import backup as bk


def test_reload_refdata_unpacks_beside_the_kept_packs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import tb_common.refdata as rd

    kept = tmp_path / "deploy" / "refdata" / "loaded"
    kept.mkdir(parents=True)
    (kept / "pack-a.tar").write_bytes(b"synthetic")
    seen: list[str] = []
    loaded: list[str] = []

    @contextlib.contextmanager
    def opened(path: Path) -> Iterator[Path]:
        d = Path(tempfile.mkdtemp(prefix="tb-refdata-"))  # what the real one does
        seen.append(str(d.parent))
        yield d
        d.rmdir()

    class Store:
        def __init__(self, url: str) -> None: ...
        def __enter__(self) -> Store:
            return self

        def __exit__(self, *a: Any) -> None: ...
        def load(self, pack: Path, by: str) -> None:
            loaded.append(by)

    monkeypatch.setattr(rd, "opened", opened)
    monkeypatch.setattr(rd, "RefStore", Store)
    monkeypatch.setattr(rd, "verify", lambda pack: {"pack_id": "pack-a"})
    monkeypatch.delenv("TB_REFDATA_UNPACK_DIR", raising=False)
    src = bk.DbSource("trialbox_wf", "postgresql://x@db/trialbox_wf", ())
    before = tempfile.tempdir
    out = bk.reload_refdata(src, [{"pack_id": "pack-a", "origin": "vendor"}], kept)
    assert out == {"reloaded": ["pack-a"], "missing": []} and loaded == ["trialbox restore"]
    assert seen == [str(kept.parent)]  # on the disk that holds the packs, not the temporary folder
    assert tempfile.tempdir == before  # put back after the block
    # TB_REFDATA_UNPACK_DIR names it (a container's volume); an explicit folder wins over both
    monkeypatch.setenv("TB_REFDATA_UNPACK_DIR", str(tmp_path / "vol"))
    assert bk.refdata_unpack_dir(kept) == tmp_path / "vol"
    bk.reload_refdata(src, [{"pack_id": "pack-a", "origin": "vendor"}], kept)
    bk.reload_refdata(src, [{"pack_id": "pack-a", "origin": "vendor"}], kept, unpack_in=tmp_path / "given")
    assert seen[1:] == [str(tmp_path / "vol"), str(tmp_path / "given")]
    assert not list((tmp_path / "vol").iterdir()) and not list(kept.parent.glob("tb-refdata-*"))
