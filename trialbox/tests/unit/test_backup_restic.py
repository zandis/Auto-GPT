"""PERF-010 R3b (D-968): the lake's served files (``db/``, ``parquet/``: the bulk, which changes little night to
night) go to restic; the ``.tbbak`` keeps everything else, encrypted to the hospital's key, and the lake's manifest
(path, sha256, size) with the restic snapshot's id. A restore restores the snapshot and checks every file against
that sealed manifest before anything is put in place. The served files are given to restic under the lake's lock,
held for restic's whole read (a rebuild's swap waits). The vector store, written in place by a build, goes with
them while no build runs (lane B2's answer on #639). restic is the
stand-in of tests/fixtures/restic; the keys and shares are made in tmp folders."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from tests import pg_client
from tests.unit.test_backup_without_pause import _lake_files, _sidecar_ok, _swap
from tests.unit.test_kek import _cli, box  # noqa: F401
from tests.unit.test_restic_password import _shares, stewards  # noqa: F401
from tools.trialbox import backup as bk
from tools.trialbox import restic_repo as rr

FAKE = Path(__file__).resolve().parents[1] / "fixtures" / "restic" / "fake_restic.py"
REPO, ESCROW = rr.repo_dir("CGMH"), rr.escrow_name("CGMH")


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
        **pg_client.env(),
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
        assert (t / REPO / "config").is_file() and (t / ESCROW).is_file()


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
    pw = rr.open_from_target(f.parent, _shares(site)[:2], rr.escrow_for(f))
    bk.unpack(f, site["priv"], tmp_path / "x", restic_pw=pw)
    assert (tmp_path / "x" / "dirs" / "lake" / "db" / "S.duckdb").is_file()


def test_without_the_restic_password_the_lake_is_not_given(site: dict[str, Any], tmp_path: Path) -> None:
    f = _backup(site)
    with pytest.raises(bk.BackupError, match="restic repository"):
        bk.unpack(f, site["priv"], tmp_path / "x")


def test_a_changed_file_in_the_repository_fails_the_restore(site: dict[str, Any], tmp_path: Path) -> None:
    f = _backup(site)
    snap = next((site["nas"] / REPO / "snapshots").iterdir())
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
        assert len(rr.Repo(t / REPO, site["pw"], site["env"]).snapshot_ids()) == 2
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
    assert not (site["nas"] / REPO).exists()


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


# ------------------------------------------------------------------------------------------------ review of D-968


def _snapshots(s: dict[str, Any], t: Path) -> list[str]:
    return rr.Repo(t / REPO, s["pw"], s["env"]).snapshot_ids()


def test_a_file_that_differs_from_its_sidecar_fails_the_backup(site: dict[str, Any]) -> None:
    """A rotted file or a wrong sidecar is found tonight, as without restic, not at every later restore."""
    with (site["lake"] / "parquet" / "snapshot=S" / "a.parquet").open("ab") as fh:
        fh.write(b"rot")
    with pytest.raises(bk.BackupError, match=r"differ from their sidecar.*a\.parquet"):
        _backup(site)
    assert not list(site["nas"].glob(f"*{bk.SUFFIX}"))
    assert _snapshots(site, site["nas"]) == []  # nothing was given to restic


def test_a_failed_copy_leaves_no_file_on_that_target(site: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """The second target gets its sealed file only once its repository holds the snapshot."""

    def broken(self: rr.Repo, src: rr.Repo, snapshot: str) -> None:
        raise rr.ResticError("restic copy failed (exit 1): no space left on device")

    monkeypatch.setattr(rr.Repo, "copy_from", broken)
    with pytest.raises(bk.BackupError, match="got no copy tonight"):
        _backup(site)
    assert not list(site["usb"].glob(f"*{bk.SUFFIX}*"))  # neither the file nor its sidecar
    first = next(site["nas"].glob(f"*{bk.SUFFIX}"))
    assert bk.read_sidecar(first) is not None  # the first target's is whole


def test_a_failed_night_leaves_no_snapshot_and_keep_never_drops_a_needed_one(
    site: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Review of D-968: with keep=2, night 1 good, night 2 failing after restic made its snapshot, night 3 good:
    night 1's file and its snapshot are both kept, and it restores."""
    from datetime import UTC, datetime, timedelta

    t0 = datetime(2026, 11, 1, 4, 45, tzinfo=UTC)
    _backup(site, keep=2, now=t0)
    real = bk._write_sidecar
    calls = {"n": 0}

    def fail_first(file: Path, sha: str) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk full")
        real(file, sha)

    monkeypatch.setattr(bk, "_write_sidecar", fail_first)
    with pytest.raises(OSError):
        _backup(site, keep=2, now=t0 + timedelta(days=1))
    monkeypatch.setattr(bk, "_write_sidecar", real)
    assert len(_snapshots(site, site["nas"])) == 1  # the failed night's snapshot was forgotten at once
    _backup(site, keep=2, now=t0 + timedelta(days=2))
    night1 = sorted(site["nas"].glob(f"*{bk.SUFFIX}"))[0]
    assert "20261101" in night1.name and bk.read_sidecar(night1) is not None
    bk.unpack(night1, site["priv"], tmp_path / "n1", restic_pw=site["pw"])  # its snapshot is still there
    assert len(_snapshots(site, site["nas"])) == 2


def test_forget_frees_space(site: dict[str, Any]) -> None:
    from datetime import UTC, datetime, timedelta

    t0 = datetime(2026, 11, 1, 4, 45, tzinfo=UTC)
    log = site["lake"].parent / "restic.log"
    logged = {**site, "env": {**site["env"], "FAKE_RESTIC_LOG": str(log)}}
    for i in range(3):
        _backup(logged, keep=1, now=t0 + timedelta(days=i))
    import json as _json

    forgets = [c["argv"] for c in map(_json.loads, log.read_text().splitlines()) if "forget" in c["argv"]]
    assert forgets and all("--prune" in a for a in forgets)


def test_each_site_has_its_own_repository_and_escrow_file_on_a_shared_target(site: dict[str, Any]) -> None:
    """Several boxes may back up to one NAS: the names carry the site, so a second box never meets the first's
    repository (which its password would not open) or its escrow file."""
    _backup(site)
    assert (site["nas"] / REPO).is_dir() and (site["nas"] / ESCROW).is_file()
    assert rr.repo_dir("NTUH") != REPO and rr.escrow_name("NTUH") != ESCROW
    assert not (site["nas"] / rr.repo_dir("NTUH")).exists()
    f = next(site["nas"].glob(f"*{bk.SUFFIX}"))
    assert rr.escrow_for(f) == ESCROW


@pytest.mark.parametrize(
    "rel",
    [
        "../../etc/cron.d/x",
        "/etc/passwd",
        "db/../../x",
        "objects/a.parquet",
        "",
        "embed_cache.duckdb.old",
        "x/embed_cache.duckdb",
        "embed_cache.duckdb/../x",
    ],
)
def test_a_forged_restic_record_writes_nothing(site: dict[str, Any], tmp_path: Path, rel: str) -> None:
    """The sealed manifest is encrypted to the hospital's key, not signed: a path in it is checked before use."""
    f = tmp_path / "trialbox-CGMH-x.tbbak"
    f.write_bytes(b"")
    manifest: dict[str, Any] = {"files": {}, "sizes": {}, "restic": {"repository": REPO, "snapshot": "x",
                                "root": "/v/lake", "files": {rel: ["0" * 64, 1]}}}  # fmt: skip
    with pytest.raises(bk.BackupError, match="outside the lake"):
        bk._restore_lake_from_restic(f, tmp_path / "into", manifest, site["pw"])
    assert not (tmp_path / "into").exists()


def test_the_recorded_root_is_not_resolved_again(tmp_path: Path) -> None:
    """A custodian's machine has other links (/var is /private/var on a Mac): the root is taken as recorded."""
    assert rr.restored_root(tmp_path, "/var/lib/docker/volumes/trialbox_lake-data/_data") == (
        tmp_path / "var/lib/docker/volumes/trialbox_lake-data/_data"
    )
    for bad in ("relative/lake", "/v/../etc", "/v//lake"):
        with pytest.raises(rr.ResticError):
            rr.restored_root(tmp_path, bad)


def test_a_restored_link_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "real"
    target.write_bytes(b"x")
    link = tmp_path / "link"
    link.symlink_to(target)
    import hashlib

    sha = hashlib.sha256(b"x").hexdigest()
    assert bk._same_file(target, sha, 1) and not bk._same_file(link, sha, 1)


# lane B2 (#639): the vector store is written in place by a build, which holds its snapshot's build lock for the whole
# build; it goes to restic with the served files, and only while no build runs


def _store(lake: Path) -> bytes:
    data = b"embeddings " * 64
    (lake / "embed_cache.duckdb").write_bytes(data)
    return data


def _hold_build(lake: Path, snapshot: str) -> Any:
    import fcntl

    (lake / "locks").mkdir(exist_ok=True)
    fh = (lake / "locks" / f"{snapshot}.build.lock").open("a")
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # as lake.store.BuildLock takes it
    return fh


def test_the_vector_store_goes_to_restic_and_comes_back(site: dict[str, Any], tmp_path: Path) -> None:
    data = _store(site["lake"])
    f = _backup(site)
    assert "dirs/lake/embed_cache.duckdb" not in _members(f, site["priv"], tmp_path)
    out = tmp_path / "x"
    m = bk.unpack(f, site["priv"], out, restic_pw=site["pw"])
    assert "embed_cache.duckdb" in m["restic"]["files"]
    assert (out / "dirs" / "lake" / "embed_cache.duckdb").read_bytes() == data


def test_a_running_build_is_waited_for(site: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    _store(site["lake"])
    monkeypatch.setattr(bk, "LAKE_QUIET_POLL_S", 0.05)
    fh = _hold_build(site["lake"], "S")
    seen: list[bool] = []
    real = rr.Repo.backup

    def backup(self: rr.Repo, root: Path, files: list[str], *, tag: str) -> str:
        seen.append(fh.closed)  # restic reads only once the build has let go of its lock
        return real(self, root, files, tag=tag)

    monkeypatch.setattr(rr.Repo, "backup", backup)
    threading.Timer(0.3, fh.close).start()  # the build ends
    _backup(site)
    assert seen == [True]


def test_a_build_that_outlasts_the_wait_fails_the_backup_by_name(
    site: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _store(site["lake"])
    monkeypatch.setattr(bk, "LAKE_QUIET_WAIT_S", 0.2)
    monkeypatch.setattr(bk, "LAKE_QUIET_POLL_S", 0.05)
    called: list[int] = []

    def backup(*a: Any, **k: Any) -> str:
        called.append(1)
        return "x"

    monkeypatch.setattr(rr.Repo, "backup", backup)
    fh = _hold_build(site["lake"], "2026-11-16")
    try:
        with pytest.raises(bk.BackupError, match=r"a lake rebuild ran for the whole wait \(2026-11-16"):
            _backup(site)
    finally:
        fh.close()
    assert not called
    for t in (site["nas"], site["usb"]):
        assert not list(t.glob("*.tbbak"))


def test_an_idle_build_lock_file_does_not_stop_the_backup(site: dict[str, Any]) -> None:
    _store(site["lake"])
    _hold_build(site["lake"], "S").close()  # a build ran and ended: its lock file stays (BuildLock never deletes it)
    _backup(site)
