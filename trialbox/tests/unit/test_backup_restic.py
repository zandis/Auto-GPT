"""PERF-010 R3b (D-968): the lake's served files (``db/``, ``parquet/``: the bulk, which changes little night to
night) go to restic; the ``.tbbak`` keeps everything else, encrypted to the hospital's key, and the lake's manifest
(path, sha256, size) with the restic snapshot's id. A restore restores the snapshot and checks every file against
that sealed manifest before anything is put in place. The served files are given to restic under the lake's lock,
held for restic's whole read (a rebuild's swap waits; lane B2 may relax this to the listing only). restic is the
stand-in of tests/fixtures/restic; the keys and shares are made in tmp folders."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_backup_without_pause import _lake_files, _sidecar_ok, _swap
from tests.unit.test_kek import _cli, box  # noqa: F401
from tests.unit.test_restic_password import _shares, stewards  # noqa: F401
from tools.trialbox import backup as bk
from tools.trialbox import restic_repo as rr

FAKE = Path(__file__).resolve().parents[1] / "fixtures" / "restic" / "fake_restic.py"


@pytest.fixture
def site(stewards: dict[str, Path], db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:  # noqa: F811
    from tb_common.db import Database

    monkeypatch.setenv(rr.CMD_ENV, f"{sys.executable} {FAKE}")
    Database.connect(db_url, "site").migrate(["CREATE TABLE marks (n BIGINT PRIMARY KEY)"])
    lake = tmp_path / "lake"
    _lake_files(lake, "old", ("a", "b"))
    (lake / ".rebuild.lock").write_text("")
    (lake / "CURRENT").write_text("S\n")
    (lake / "source.jsonl").write_text('{"night": 1}\n')
    priv, pub = tmp_path / "it.key", tmp_path / "box.pub"
    bk.keygen(priv, pub)
    rr.make_key(stewards["sec"], os.environ)
    env = {
        "TB_DB_URL": db_url,
        "TB_SITE_ID": "CGMH",
        rr.CMD_ENV: os.environ[rr.CMD_ENV],
        "TB_KEK_FILE": os.environ["TB_KEK_FILE"],
    }  # the unsealed KEK, as the backup container gets it
    return {**stewards, "lake": lake, "priv": priv, "pub": pub, "env": env, "nas": tmp_path / "nas",
            "usb": tmp_path / "usb", "pw": rr.password(stewards["sec"], os.environ)}  # fmt: skip


def _backup(s: dict[str, Any], **kw: Any) -> Path:
    return bk.backup([s["nas"], s["usb"]], s["pub"], env=s["env"], dirs={"lake": s["lake"]},
                     restic_secrets=s["sec"], **kw)[0]  # fmt: skip


def _members(f: Path, priv: Path, tmp: Path) -> set[str]:
    out = tmp / "plain"
    bk.unpack(f, priv, out, restic_pw=None, lake_from_restic=False)
    return {str(p.relative_to(out)) for p in out.rglob("*") if p.is_file()}


def test_the_lake_goes_to_restic_and_the_rest_stays_sealed(site: dict[str, Any], tmp_path: Path) -> None:
    f = _backup(site)
    names = _members(f, site["priv"], tmp_path)
    assert "dirs/lake/source.jsonl" in names and "dirs/lake/CURRENT" in names
    assert "dirs/lake/db/S.duckdb.sha256" in names  # the sidecars are small: they stay in the sealed file
    assert not {n for n in names if n.endswith((".duckdb", ".parquet"))}  # the bulk is in restic only
    for t in (site["nas"], site["usb"]):
        assert (t / rr.REPO_DIR / "config").is_file() and (t / rr.ESCROW).is_file()


def test_a_restore_checks_restics_files_against_the_sealed_manifest(site: dict[str, Any], tmp_path: Path) -> None:
    f = _backup(site)
    out = tmp_path / "x"
    m = bk.unpack(f, site["priv"], out, restic_pw=site["pw"])
    got = out / "dirs" / "lake"
    assert sorted(p.name for p in (got / "parquet" / "snapshot=S").glob("*.parquet")) == ["a.parquet", "b.parquet"]
    assert all(_sidecar_ok(p) for p in [got / "db" / "S.duckdb", *(got / "parquet" / "snapshot=S").glob("*.parquet")])
    assert set(m["restic"]["files"]) == {"db/S.duckdb", "parquet/snapshot=S/a.parquet", "parquet/snapshot=S/b.parquet"}
    res = bk.restore(f, site["priv"], env=site["env"], dirs={"lake": tmp_path / "restored"}, no_copy=True,
                     restic_pw=site["pw"])  # fmt: skip
    assert res["lake_check"] == {"snapshots": 1, "problems": [], "unsigned": 0, "checked": True}


def test_the_second_target_restores_alone(site: dict[str, Any], tmp_path: Path) -> None:
    """Each target holds a whole backup: the USB disk's copy of the file and its restic copy restore without the NAS."""
    _backup(site)
    usb_file = next(site["usb"].glob(f"*{bk.SUFFIX}"))
    m = bk.unpack(usb_file, site["priv"], tmp_path / "x", restic_pw=site["pw"])
    assert (tmp_path / "x" / "dirs" / "lake" / "db" / "S.duckdb").is_file() and m["restic"]["snapshot"]


def test_the_custodians_shares_open_it_without_the_box(site: dict[str, Any], tmp_path: Path) -> None:
    f = _backup(site)
    pw = rr.open_from_target(f.parent, _shares(site)[:2])
    bk.unpack(f, site["priv"], tmp_path / "x", restic_pw=pw)
    assert (tmp_path / "x" / "dirs" / "lake" / "db" / "S.duckdb").is_file()


def test_without_the_restic_password_the_lake_is_not_given(site: dict[str, Any], tmp_path: Path) -> None:
    f = _backup(site)
    with pytest.raises(bk.BackupError, match="restic repository"):
        bk.unpack(f, site["priv"], tmp_path / "x")


def test_a_changed_file_in_the_repository_fails_the_restore(site: dict[str, Any], tmp_path: Path) -> None:
    f = _backup(site)
    snap = next((site["nas"] / rr.REPO_DIR / "snapshots").iterdir())
    victim = next(p for p in (snap / "data").rglob("a.parquet"))
    victim.write_bytes(b"changed on the share")
    with pytest.raises(bk.BackupError, match=r"parquet/snapshot=S/a\.parquet"):
        bk.unpack(f, site["priv"], tmp_path / "x", restic_pw=site["pw"])


def test_the_keep_applies_to_the_snapshots_too(site: dict[str, Any]) -> None:
    from datetime import UTC, datetime, timedelta

    t0 = datetime(2026, 11, 1, 4, 45, tzinfo=UTC)
    for i in range(3):
        _backup(site, keep=2, now=t0 + timedelta(days=i))
    for t in (site["nas"], site["usb"]):
        assert len(rr.Repo(t / rr.REPO_DIR, site["pw"], site["env"]).snapshot_ids()) == 2
        assert len(list(t.glob(f"*{bk.SUFFIX}"))) == 2


def test_a_kek_without_shares_writes_nothing(site: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    def not_covered(meta: Any) -> Any:
        raise rr.ResticKeyError("the KEK (back end passphrase) is not covered by escrow shares")

    monkeypatch.setattr(rr, "public_kek", not_covered)
    with pytest.raises(bk.BackupError, match="not covered by escrow shares"):
        _backup(site)
    assert not site["nas"].exists() or not list(site["nas"].iterdir())


def test_the_lake_lock_is_held_for_restics_whole_read(site: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """A rebuild's swap started while restic reads waits until restic is done: the snapshot is one state."""
    real = rr.Repo.backup
    waited: list[bool] = []

    def backup(self: rr.Repo, root: Path, files: list[str], *, tag: str) -> str:
        t = threading.Thread(target=_swap, args=(site["lake"],))
        t.start()
        t.join(0.5)
        waited.append(t.is_alive())  # the swap is held at the lake's lock
        sid = real(self, root, files, tag=tag)
        threading.Thread(target=t.join).start()
        return sid

    monkeypatch.setattr(rr.Repo, "backup", backup)
    f = _backup(site)
    assert waited == [True]
    m = bk.unpack(f, site["priv"], site["lake"].parent / "x", restic_pw=site["pw"])
    assert set(m["restic"]["files"]) >= {"parquet/snapshot=S/a.parquet", "parquet/snapshot=S/b.parquet"}  # all old


def test_without_restic_nothing_changes(site: dict[str, Any], tmp_path: Path) -> None:
    f = bk.backup([site["nas"]], site["pub"], env=site["env"], dirs={"lake": site["lake"]})[0]
    m = bk.unpack(f, site["priv"], tmp_path / "x")
    assert "restic" not in m and (tmp_path / "x" / "dirs" / "lake" / "db" / "S.duckdb").is_file()
    assert not (site["nas"] / rr.REPO_DIR).exists()


def test_the_command_line(site: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
                          tmp_path: Path) -> None:  # fmt: skip
    """`backup --restic`, then `backup-verify` with the box's key, with the custodians' shares, and without either."""
    from tools.trialbox import __main__ as cli

    for k, v in site["env"].items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("TB_SECRETS_DIR", str(site["sec"]))
    monkeypatch.setenv("TB_BACKUP_DIRS", f"lake={site['lake']}")
    assert cli.main(["backup", "--to", str(site["nas"]), "--public", str(site["pub"]), "--restic"]) == 0
    f = next(site["nas"].glob(f"*{bk.SUFFIX}"))
    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    base = ["backup-verify", str(f), "--key", str(site["priv"]), "--deploy", str(deploy)]
    assert cli.main([*base, "--restic-from-box"]) == 0
    shares = sorted(site["shares"].glob("share-*.txt"))
    assert cli.main([*base, "--restic-share", str(shares[0]), "--restic-share", str(shares[2])]) == 0
    capsys.readouterr()
    assert cli.main(base) != 0
    assert "restic repository" in capsys.readouterr().err
    assert cli.main([*base, "--restic-share", str(shares[0])]) != 0  # one share is not enough
    assert site["pw"] not in capsys.readouterr().out
