"""H-132: the lifecycle review's data-loss findings (LR-1, LR-11, LR-13, LR-15, LR-16), each reproduced at master.

Every test here fails on master 00bababf and holds the rule of the card: never delete what this run did not make or
what is not proven safe to delete; put back before removing; a refusal changes nothing. Each names the cell of the
lifecycle matrix (``docs/reviews/lifecycle-deep-review-2026-11-24.md``) it turns green.
"""

from __future__ import annotations

import errno
from pathlib import Path
from typing import Any

import pytest

from tests.unit import test_restore_from_the_host_h100 as h100
from tools.trialbox import backup as bk
from tools.trialbox.update import UpdateFailed


# ------------------------------------------------------------------------------------------------------------ LR-1
# Matrix: "restore, in the container | folder is a mount point | none".
def test_lr1_a_folder_that_cannot_be_renamed_aside_is_never_removed_by_the_put_back(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rename aside fails (EBUSY: a mount point, a folder in use): the put-back must leave the folder as it is.
    On master the move was recorded first and the put-back removed every file of the original."""
    _reg, dirs, priv, pub, keep, env, f = h100._box_db(tmp_path, db_url)
    audit = dirs["audit"]
    before = sorted(p.name for p in audit.iterdir())
    real = Path.rename

    def rename(self: Path, target: Any) -> Any:
        if self == audit:
            raise OSError(errno.EBUSY, "Device or resource busy", str(self))
        return real(self, target)

    monkeypatch.setattr(Path, "rename", rename)
    with pytest.raises(bk.BackupError) as err:
        bk.restore(f, priv, env=env, dirs=dirs, public_key=pub, keep_to=keep)
    assert set(before) <= {p.name for p in audit.iterdir()}, err.value  # (the failure's own audit event is added)
    assert (audit / "after-the-backup.txt").read_text(encoding="utf-8") == "synthetic"
    assert getattr(err.value, "state", None) == "rolled_back", err.value


def test_lr1_a_mount_point_target_is_refused_before_the_first_change(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A target that is a mount point is refused before any database is touched (on master the databases were
    replaced first and the rename failed halfway)."""
    import os

    _reg, dirs, priv, pub, keep, env, f = h100._box_db(tmp_path, db_url)
    src = bk.db_sources(env)[0]
    counts = h100._counts(src)
    real = os.path.ismount
    monkeypatch.setattr(os.path, "ismount", lambda p: Path(p) == dirs["audit"] or real(p))
    with pytest.raises(bk.BackupError, match="mount point.*Nothing was changed") as err:
        bk.restore(f, priv, env=env, dirs=dirs, public_key=pub, keep_to=keep)
    assert getattr(err.value, "state", "unchanged") == "unchanged"
    assert h100._counts(src) == counts  # P-LATER-2, written after the backup, is still there
    assert (dirs["audit"] / "after-the-backup.txt").is_file()
    assert not list(dirs["audit"].parent.glob(f"{dirs['audit'].name}.pre-restore-*"))


# ----------------------------------------------------------------------------------------------------------- LR-11
# Matrix: "update, from the shell | N, engine shared | failed load".
class SharedEngine:
    """A stand-in engine (tags and image ids) that another user changes too; every command is answered and kept."""

    def __init__(self, tags: dict[str, str]) -> None:
        self.tags = dict(tags)
        self.ids = set(tags.values())
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **_kw: Any) -> str:
        from tools.trialbox import update as up

        self.calls.append(list(argv))
        if argv == up.IMAGE_STATE:
            lines = [f"{t} {i}" for t, i in sorted(self.tags.items())]
            return "\n".join(lines + [f"<none>:<none> {i}" for i in sorted(self.ids - set(self.tags.values()))])
        if argv[:2] == ["docker", "tag"]:
            self.tags[argv[3]] = self.tags.get(argv[2], argv[2])
        elif argv[:3] == ["docker", "image", "rm"]:
            ref = argv[-1]
            if ref in self.tags and "-f" not in argv:
                self.tags.pop(ref)
            else:
                self.ids.discard(ref)
                self.tags = {t: i for t, i in self.tags.items() if i != ref}
        return ""


A, B, T0, T1, X = (f"sha256:{c * 64}" for c in "abcef")


def _loaded_beside_another_user() -> tuple[SharedEngine, tuple[dict[str, str], set[str]]]:
    eng = SharedEngine({"app:1": A, "theirs:1": T0})
    from tools.trialbox import update as up

    before = up.image_state(eng)
    eng.tags["app:1"] = B  # the load: the archive pins app:1 at config B
    eng.ids.add(B)
    eng.tags["theirs:2"] = X  # meanwhile another user of the engine pulls X and moves its own tag
    eng.ids.add(X)
    eng.tags["theirs:1"] = T1
    eng.ids.add(T1)
    return eng, before


def test_lr11_the_undo_of_a_failed_load_touches_only_what_the_archive_made(tmp_path: Path) -> None:
    from tools.trialbox import update as up

    eng, before = _loaded_beside_another_user()
    point = up.Point()
    point.extra[up.LOAD_BEFORE] = {"image": "app.tar", "tags": before[0], "ids": sorted(before[1]),
                                   "scope_tags": ["app:1"], "scope_ids": [B]}  # fmt: skip
    up.undo_recorded_load(point, eng)
    assert eng.tags == {"app:1": A, "theirs:1": T1, "theirs:2": X}  # the other user's tags as that user left them
    assert {A, T0, T1, X} <= eng.ids and B not in eng.ids  # the load's own image gone, nobody else's


def test_lr11_a_record_that_names_no_scope_removes_nothing(tmp_path: Path) -> None:
    """A record written before the fix (no scope): nothing is removed; the rollback's own retag of the pinned tags
    (``restore_images``) puts the bundle's tags back."""
    from tools.trialbox import update as up

    eng, before = _loaded_beside_another_user()
    point = up.Point()
    point.extra[up.LOAD_BEFORE] = {"image": "app.tar", "tags": before[0], "ids": sorted(before[1])}
    assert up.undo_recorded_load(point, eng) == []
    assert not [c for c in eng.calls if c[:3] == ["docker", "image", "rm"]]
    assert eng.tags["theirs:1"] == T1 and X in eng.ids


def test_lr11_the_scope_is_read_from_the_bytes_handed_to_the_load() -> None:
    """An archive swapped after its pins were read names its own tags in the bytes the load gets: those are this
    load's, and only those."""
    import io
    import json
    import tarfile

    from tools.trialbox import update as up

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in (("blobs/x", b"\0" * 1500), ("manifest.json", json.dumps(
                [{"Config": f"blobs/sha256/{'f' * 64}", "RepoTags": ["swapped:1"]}]).encode())):  # fmt: skip
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    raw = buf.getvalue()
    w = up.TarWatch()
    for i in range(0, len(raw), 333):  # in pieces that cut headers and data anywhere
        w.feed(raw[i : i + 333])
    assert w.scope() == ({"swapped:1"}, {X})


# ----------------------------------------------------------------------------------------------------------- LR-13
# Matrix: "restore, on the host | fresh | HUP (terminal gone)" (and the sweep half of "... | KILL").
def test_lr13_a_hangup_with_the_terminal_gone_still_tells_the_container_and_waits_for_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import signal
    import subprocess
    import sys

    from tools.trialbox import box_restore

    sent: list[int] = []

    class Proc:
        returncode = 1
        n = 0

        def __init__(self, *a: object, **kw: object) -> None:
            pass

        def communicate(self) -> tuple[str, str]:
            Proc.n += 1
            if Proc.n == 1:
                raise box_restore.HostInterrupted("SIGHUP")
            return '{"ok": false, "state": "rolled_back"}', ""

        def send_signal(self, sig: int) -> None:
            sent.append(sig)

    class Gone:
        """The closed session's terminal: every write fails."""

        def write(self, _s: str) -> int:
            raise OSError(5, "Input/output error")

        def flush(self) -> None:
            raise OSError(5, "Input/output error")

    monkeypatch.setattr(subprocess, "Popen", Proc)
    monkeypatch.setattr(sys, "stderr", Gone())
    code, out = box_restore._call(["docker", "run"], {}, {"PATH": "/usr/bin"})
    assert sent == [signal.SIGTERM] and code == 1 and '"rolled_back"' in out


def test_lr13_a_second_restore_is_refused_while_the_first_ones_container_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Busy(h100.Recorder):
        def __call__(self, argv: list[str], **kw: object) -> str:
            if argv[1:3] == ["container", "inspect"]:
                self.calls.append(list(argv))
                return "running\n"
            return super().__call__(argv, **kw)

    deploy = h100._box(tmp_path)
    work = deploy / ".restore-first"  # the first restore's work folder, its put-back dumps inside
    work.mkdir(mode=0o700)
    (work / "pre-restore.dump").write_bytes(b"synthetic")
    rec = Busy(running=["db", "console"])
    code, seen = h100._restore(deploy, tmp_path, monkeypatch, rec, "{}", 0, "--restart")
    err = capsys.readouterr().err
    assert code == 2 and not seen and "still exists" in err, err
    assert (work / "pre-restore.dump").is_file()  # never swept from under the running restore
    assert not [c for c in rec.calls if "stop" in c]  # nothing stopped


def test_lr13_the_restore_container_has_one_fixed_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    deploy = h100._box(tmp_path)
    code, seen = h100._restore(deploy, tmp_path, monkeypatch, h100.Recorder(), "{}", 0)
    ((argv, _values),) = seen
    assert code == 0 and h100._value(argv, "--name") == "trialbox-restore"


# ----------------------------------------------------------------------------------------------------------- LR-15
# Matrix: "restore, on the host | Docker root not the default | none".
def _box_without_the_volume_setting(tmp_path: Path) -> Path:
    deploy = h100._box(tmp_path)
    env = deploy / ".env"
    env.write_text("".join(ln for ln in env.read_text(encoding="utf-8").splitlines(keepends=True)
                           if not ln.startswith("TB_DOCKER_VOLUMES=")), encoding="utf-8")  # fmt: skip
    return deploy


def test_lr15_a_data_root_elsewhere_is_asked_of_the_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    elsewhere = tmp_path / "data-disk" / "docker" / "volumes"

    class Engine(h100.Recorder):
        def __call__(self, argv: list[str], **kw: object) -> str:
            if argv[1:3] == ["volume", "inspect"]:
                self.calls.append(list(argv))
                vol = argv[-1]
                if vol in ("trialbox_lake-data", "trialbox_audit-data"):
                    (elsewhere / vol / "_data").mkdir(parents=True, exist_ok=True)
                    return f"{elsewhere / vol / '_data'}\n"
                raise UpdateFailed(f"no such volume: {vol}")
            return super().__call__(argv, **kw)

    deploy = _box_without_the_volume_setting(tmp_path)
    code, seen = h100._restore(deploy, tmp_path, monkeypatch, Engine(), "{}", 0)
    ((argv, _values),) = seen
    assert code == 0
    assert f"{elsewhere / 'trialbox_lake-data'}:/var/lib/docker/volumes/trialbox_lake-data" in h100._mounts(argv)
    dirs = [argv[i + 1] for i, x in enumerate(argv) if x == "--dir"]
    assert sorted(dirs) == ["audit=/var/lib/docker/volumes/trialbox_audit-data/_data",
                            "lake=/var/lib/docker/volumes/trialbox_lake-data/_data"]  # fmt: skip


def test_lr15_no_folder_of_the_box_found_is_refused_before_anything_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    deploy = _box_without_the_volume_setting(tmp_path)
    rec = h100.Recorder(running=["db", "console"])
    code, seen = h100._restore(deploy, tmp_path, monkeypatch, rec, "{}", 0, "--restart")
    err = capsys.readouterr().err
    assert code == 2 and not seen and "no data folder of the box was found" in err, err
    assert not [c for c in rec.calls if "stop" in c]  # a refusal stops nothing


# ----------------------------------------------------------------------------------------------------------- LR-16
# Matrix: "restore, on the host | KEK TPM / KEK file, restic backup | none" (stand-in restic, its lock rule modelled).
FAKE_RESTIC = Path(__file__).resolve().parents[1] / "fixtures" / "restic" / "fake_restic.py"
LOCKING = """import os, sys
a = sys.argv[1:]
# restic's lock rule: every command but those given --no-lock writes a lock file into the repository; a repository
# bound read-only (the host restore's and verify's mount of the backup's folder) refuses that
if os.environ.get("H132_READ_ONLY") == "1" and "--no-lock" not in a and ("restore" in a or "snapshots" in a):
    print("Fatal: unable to create lock in backend: read-only file system", file=sys.stderr)
    sys.exit(1)
os.execv(sys.executable, [sys.executable, sys.argv[0].rsplit("/", 1)[0] + "/fake_restic.py",
                          *[x for x in a if x != "--no-lock"]])
"""


def test_lr16_a_restic_lake_restores_from_a_repository_bound_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil
    import sys

    from tools.trialbox import restic_repo as rr

    tools = tmp_path / "bin"
    tools.mkdir()
    shutil.copy(FAKE_RESTIC, tools / "fake_restic.py")
    (tools / "locking_restic.py").write_text(LOCKING, encoding="utf-8")
    monkeypatch.setenv(rr.CMD_ENV, f"{sys.executable} {tools / 'locking_restic.py'}")
    root = tmp_path / "lake"
    (root / "db").mkdir(parents=True)
    (root / "db" / "synthetic.duckdb").write_bytes(b"synthetic")
    repo = rr.Repo(tmp_path / "nas" / rr.REPO_DIR, "ab" * 32)
    repo.ensure()
    sid = repo.backup(root, ["db/synthetic.duckdb"], tag=rr.LAKE_TAG)
    monkeypatch.setenv("H132_READ_ONLY", "1")  # from here on the repository is the read-only bind
    out = tmp_path / "restored"
    rr.Repo(tmp_path / "nas" / rr.REPO_DIR, "ab" * 32).restore(sid, out)
    assert (rr.restored_root(out, root) / "db" / "synthetic.duckdb").read_bytes() == b"synthetic"


def test_lr16_backup_verify_sees_the_files_beside_the_backup(tmp_path: Path) -> None:
    """The sidecar, the restic repository and its escrow file lie beside the backup file: verify's container gets
    the folder (read-only), not the file alone."""
    from tools.trialbox import launch

    argv = launch.container_argv(["backup-verify", "nas/f.tbbak", "--key", "/media/usb/k.key"],
                                 launch.COMMANDS["backup-verify"], {}, tmp_path, 1000, 1000)  # fmt: skip
    assert f"{tmp_path}/nas:{tmp_path}/nas:ro" in argv
    assert f"{tmp_path}/nas/f.tbbak" in argv[argv.index("tools.trialbox") :]


def test_lr16_the_runbook_names_how_a_restic_backup_is_opened() -> None:
    root = Path(__file__).resolve().parents[2]
    for page in ("docs/runbook/05-updates-backup-restore-secrets.md",
                 "docs/runbook/22-disaster-recovery-with-measured-rpo-and-rto.md"):  # fmt: skip
        text = (root / page).read_text(encoding="utf-8")
        assert "--restic-from-box" in text and "--restic-share" in text, page
