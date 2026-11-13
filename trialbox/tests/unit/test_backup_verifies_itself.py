"""NEW-B-21 (D-662): the backup checks what it stored against its own manifest before it is sealed.

The owner's decision on a finding of NEW-B-17: the nightly has no private key and never opened what it wrote, so a
backup whose manifest was wrong (the hard-link fault) was recorded as good and could not be restored. Each stored
file's hash is now checked against the manifest on the plain stream, before encryption; a backup that does not
verify is failed, with the file names, never recorded as good."""

from __future__ import annotations

import os
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_backup import _backup, box  # noqa: F401 (box: a fixture)
from tools.trialbox import backup as bk
from tools.trialbox import backup_schedule as bs


def _left(tmp_path: Path) -> list[str]:
    return sorted(p.name for d in ("nas", "usbdisk") if (tmp_path / d).is_dir() for p in (tmp_path / d).iterdir())


def test_a_backup_whose_manifest_is_wrong_about_a_file_is_refused_and_leaves_nothing(
    box: dict[str, object],  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = bk._add

    def wrong(tar: Any, path: Path, arcname: str) -> tuple[str, int]:
        sha, size = real(tar, path, arcname)
        return ("0" * 64, size) if arcname.endswith("log.jsonl") else (sha, size)

    monkeypatch.setattr(bk, "_add", wrong)
    with pytest.raises(bk.BackupError) as exc:
        _backup(box, tmp_path)
    assert str(exc.value) == (
        "changed: dirs/audit/2026/log.jsonl; the backup was not written: its content does not match its manifest "
        "(1 changed, 0 unlisted)"
    )
    assert _left(tmp_path) == []  # no backup file, no part file, no sidecar: nothing a restore could pick up


def test_the_fault_of_new_b_17_is_caught_when_the_backup_is_made(
    box: dict[str, object],  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two names of one file, and ``_add`` as it was before NEW-B-17: the second name is stored as a link with no
    bytes and listed with the hash of nothing. The check reads the stream as a restore would."""
    dirs: dict[str, Path] = box["dirs"]  # type: ignore[assignment]
    work = dirs["audit"] / "sitesetup" / "ws" / "lake" / "db"
    (work / "gen").mkdir(parents=True)
    (work / "2026-11-02.duckdb").write_bytes(b"duck" * 1000)
    os.link(work / "2026-11-02.duckdb", work / "gen" / "2026-11-02.g1.duckdb")

    def add_as_it_was(tar: tarfile.TarFile, path: Path, arcname: str) -> tuple[str, int]:
        with path.open("rb") as fh:
            info = tar.gettarinfo(arcname=arcname, fileobj=fh)  # a link member for the second name: no bytes
            hr = bk._HashReader(fh)
            tar.addfile(info, hr)
        return hr.sha.hexdigest(), hr.n

    monkeypatch.setattr(bk, "_add", add_as_it_was)
    with pytest.raises(
        bk.BackupError, match=r"changed: dirs/audit/sitesetup/ws/lake/db/gen/.*\(1 changed, 0 unlisted\)"
    ):
        _backup(box, tmp_path)
    assert _left(tmp_path) == []


def test_the_nightly_records_such_a_backup_as_failed_with_the_file_never_as_good(
    box: dict[str, object],  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.unit.test_backup_schedule import T0, _cfg, _offbox

    real = bk._add

    def wrong(tar: Any, path: Path, arcname: str) -> tuple[str, int]:
        sha, size = real(tar, path, arcname)
        return ("0" * 64, size) if arcname.endswith("log.jsonl") else (sha, size)

    cfg = _cfg(tmp_path)
    events: list[tuple[str, dict[str, Any]]] = []
    good = bs.nightly(cfg, lambda targets: _backup(box, tmp_path), lambda e, d: events.append((e, d)), now=T0,
                      classify=_offbox({"nas"}))  # fmt: skip
    assert good["ok"], good["errors"]
    monkeypatch.setattr(bk, "_add", wrong)
    later = datetime(2026, 11, 14, 2, 0, tzinfo=UTC)
    res = bs.nightly(cfg, lambda targets: _backup(box, tmp_path, now=later), lambda e, d: events.append((e, d)),
                     now=later, classify=_offbox({"nas"}))  # fmt: skip
    assert not res["ok"] and res["file"] is None
    assert any("does not match its manifest" in e and "dirs/audit/2026/log.jsonl" in e for e in res["errors"])
    assert res["good_at"] == good["good_at"] and res["good_file"] == good["good_file"]  # the earlier one stays good
    assert events[-1][0] == "backup.failed"


def test_a_good_backup_is_checked_and_restores_as_before(box: dict[str, object], tmp_path: Path) -> None:  # noqa: F811
    files = _backup(box, tmp_path)
    assert bk.verify(files[0], box["priv"])["ok"]  # type: ignore[arg-type]
    assert bk.LAST_CHECK["files"] == bk.verify(files[0], box["priv"])["files"]  # type: ignore[arg-type]
    assert bk.LAST_CHECK["bytes"] > 1_000_000  # every stored byte was read back from the stream


def test_a_file_that_changed_while_it_was_read_and_was_stored_twice_still_verifies(
    box: dict[str, object],  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_add`` stores a file again when it changed under the read; the later copy is the one the manifest names
    and a restore extracts. The check must judge the later copy, as a restore does."""
    dirs: dict[str, Path] = box["dirs"]  # type: ignore[assignment]
    target = dirs["audit"] / "2026" / "list.json"
    target.write_text("one")
    real_stat = Path.stat
    hit = {"n": 0}

    def stat(self: Path, **kw: Any) -> Any:
        if self == target and hit["n"] == 0 and target.read_text() == "one":
            hit["n"] = 1
            target.write_text("two!")  # rewritten while the backup read it
        return real_stat(self, **kw)

    monkeypatch.setattr(Path, "stat", stat)
    files = _backup(box, tmp_path)
    monkeypatch.undo()
    into = tmp_path / "out"
    bk.unpack(files[0], box["priv"], into)  # type: ignore[arg-type]
    assert hit["n"] == 1 and (into / "dirs/audit/2026/list.json").read_text() == "two!"


# ------------------------------------------------------------------------------------------------ review fixes
def test_what_the_nightly_records_keeps_the_verdict_and_the_count_however_many_files(
    box: dict[str, object],  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A record keeps the END of an error (the nightly its last 400 characters, the box's command runner its last
    600): the verdict and the counts are at the end, so they are never what is cut off."""
    dirs: dict[str, Path] = box["dirs"]  # type: ignore[assignment]
    for i in range(14):
        f = dirs["audit"] / "parquet" / f"snapshot=2026-11-{i + 1:02d}" / "observation-part-000000000001.parquet"
        f.parent.mkdir(parents=True)
        f.write_bytes(b"x" * 10)
    real = bk._add

    def wrong(tar: Any, path: Path, arcname: str) -> tuple[str, int]:
        sha, size = real(tar, path, arcname)
        return ("0" * 64, size) if arcname.endswith(".parquet") else (sha, size)

    monkeypatch.setattr(bk, "_add", wrong)
    with pytest.raises(bk.BackupError) as exc:
        _backup(box, tmp_path)
    kept = f"backup failed: BackupError: {str(exc.value)[-400:]}"[-400:]
    assert kept.endswith("the backup was not written: its content does not match its manifest (15 changed, 0 unlisted)")
    assert "and 5 more" in kept and "snapshot=2026-11-10" in kept  # 14 here and the box's own Parquet file


def test_a_stream_the_check_cannot_read_leaves_nothing_either(
    box: dict[str, object],  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(self: Any, member: Any) -> Any:
        raise ValueError("cannot read")

    monkeypatch.setattr(tarfile.TarFile, "extractfile", broken)
    with pytest.raises(bk.BackupError, match="could not be read back"):
        _backup(box, tmp_path)
    assert _left(tmp_path) == []
