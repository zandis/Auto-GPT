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
from tests.unit import test_update_safety as us_t
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


def test_lr1_a_move_recorded_before_a_failed_rename_never_deletes_the_live_folder(tmp_path: Path) -> None:
    """OCR 1474-5 (its test body): on a folder that is not a mount point the move recorded before a rename that never
    happened made the put-back delete the live folder and still say "put back as it was before the restore"."""
    dest = tmp_path / "lake"
    dest.mkdir()
    for i in range(3):
        (dest / f"f{i}").write_text("live", encoding="utf-8")
    moved = [(dest, dest.with_name("lake.pre-restore-X"), True, None)]  # recorded; the rename never happened
    ok, words = bk._put_back({}, [], {}, moved, {})
    gone = (sorted(p.name for p in dest.iterdir()) if dest.is_dir() else []) != ["f0", "f1", "f2"]
    assert not (gone and (ok or "put back as it was" in words)), words  # never a "put back" over a folder gone
    assert not gone  # master: the folder is empty, ok is True and the words say "put back as it was"


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


def test_lr11_a_tag_moved_back_takes_the_new_image_it_pointed_at(tmp_path: Path) -> None:
    """The rehearsal's swapped-stream case on a real engine (#1481 CI): the box held ``app:1`` at A; the failed load
    re-pointed it at a new image whose id the archive's names do not give (the engine's own digest). The undo moves
    the tag back and removes that image too; an untagged image another user pulled meanwhile stays."""
    from tools.trialbox import update as up

    eng = SharedEngine({"app:1": A})
    before = up.image_state(eng)
    eng.tags["app:1"] = B  # the load: the pinned name re-pointed at a new image
    eng.ids.add(B)
    eng.ids.add(X)  # meanwhile another user's untagged image
    up.undo_load(before, eng, ({"app:1"}, {T1}))  # the archive named another digest than the engine's id
    assert eng.tags == {"app:1": A} and B not in eng.ids and X in eng.ids


@pytest.mark.parametrize("swap_tag", ["app:1", "db:16"])
def test_lr11_a_stream_without_a_rollback_point_undoes_the_swapped_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, swap_tag: str
) -> None:
    """``stream_image`` called as the rehearsal's probe calls it (no rollback point): an archive swapped after the pin
    read, another image under the pinned name the box already holds. The refusal leaves the engine as it was."""
    import hashlib
    import io
    import json
    import subprocess
    import tarfile

    from tools.trialbox import update as up

    def archive(tag: str, config: str) -> bytes:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            for name, data in (("layer.tar", b"\0" * 4096),
                               ("manifest.json", json.dumps([{"Config": f"{config}.json", "RepoTags": [tag]}]).encode())):  # fmt: skip
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
        return buf.getvalue()

    original = archive("app:1", "c" * 64)
    swapped = archive(swap_tag, "e" * 64)
    size = len(swapped) + 3 * up.HOLD_BACK
    stick = tmp_path / "stick.bin"
    stick.write_bytes(swapped + b"\0" * (size - len(swapped)))  # the stick after the swap
    p = up.Streamed(stick, "engine.tar", "image", hashlib.sha256(original).hexdigest(), size, 0)
    eng = SharedEngine({"app:1": A})
    new_id = "sha256:" + "d" * 64  # the engine's own id for the swapped image (not the archive's config digest)

    class Load:
        def __init__(self, *a: object, **kw: object) -> None:
            self.stdin = io.BytesIO()
            self.stdin.close = lambda: None  # type: ignore[method-assign]
            # the pinned name: the load says it; a new name (db:16): it says nothing (a late registration)
            self.stdout = io.BytesIO(b"Loaded image: app:1\n" if swap_tag == "app:1" else b"")

        def wait(self, timeout: float | None = None) -> int:
            # the pinned name: the engine's own id; a new name: the archive's config digest, named only by the bytes
            iid = new_id if swap_tag == "app:1" else "sha256:" + "e" * 64
            eng.tags[swap_tag] = iid
            eng.ids.add(iid)
            return 0

        def kill(self) -> None:
            pass

    monkeypatch.setattr(subprocess, "Popen", Load)
    with pytest.raises(up.UpdateFailed, match="undone"):
        up.stream_image(p, {"app:1": "sha256:" + "c" * 64}, set(), eng)
    assert eng.tags == {"app:1": A} and eng.ids == {A}  # master 513758e3: the new image stayed, untagged


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
HOST_ENGINE = "/var/lib/docker"


def _no_host_engine_folder(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every path under the host's real engine folder that the code under test stats, lists or opens (none may be):
    a unit test never reaches a real host path (CI's runner has one, 0710 root; a session's container may not)."""
    import builtins
    import os

    touched: list[str] = []

    def guard(real: Any) -> Any:
        def wrapped(path: Any, *a: Any, **kw: Any) -> Any:
            if isinstance(path, (str, os.PathLike)) and os.fspath(path).startswith(HOST_ENGINE):
                touched.append(os.fspath(path))
            return real(path, *a, **kw)

        return wrapped

    for mod, name in ((os, "stat"), (os, "lstat"), (os, "listdir"), (os, "scandir"), (builtins, "open")):
        monkeypatch.setattr(mod, name, guard(getattr(mod, name)))
    return touched


def _box_without_the_volume_setting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A box file with no TB_DOCKER_VOLUMES; the engine's default folder is the test's own (empty) stand-in."""
    from tools.trialbox import box_restore

    monkeypatch.setattr(box_restore, "DEFAULT_VOLUMES", tmp_path / "engine-default" / "volumes")
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

    touched = _no_host_engine_folder(monkeypatch)
    deploy = _box_without_the_volume_setting(tmp_path, monkeypatch)
    code, seen = h100._restore(deploy, tmp_path, monkeypatch, Engine(), "{}", 0)
    ((argv, _values),) = seen
    assert code == 0
    assert f"{elsewhere / 'trialbox_lake-data'}:/var/lib/docker/volumes/trialbox_lake-data" in h100._mounts(argv)
    dirs = [argv[i + 1] for i, x in enumerate(argv) if x == "--dir"]
    assert sorted(dirs) == ["audit=/var/lib/docker/volumes/trialbox_audit-data/_data",
                            "lake=/var/lib/docker/volumes/trialbox_lake-data/_data"]  # fmt: skip
    assert touched == []  # no path of the host's own engine folder


def test_lr15_no_folder_of_the_box_found_is_refused_before_anything_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    touched = _no_host_engine_folder(monkeypatch)
    deploy = _box_without_the_volume_setting(tmp_path, monkeypatch)
    rec = h100.Recorder(running=["db", "console"])
    code, seen = h100._restore(deploy, tmp_path, monkeypatch, rec, "{}", 0, "--restart")
    err = capsys.readouterr().err
    assert code == 2 and not seen and "no data folder of the box was found" in err, err
    assert not [c for c in rec.calls if "stop" in c]  # a refusal stops nothing
    assert touched == []  # no path of the host's own engine folder


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


# ----------------------------------------------------------------------------------------------------------- LR-10
# Matrix: "update, after the check | N | KILL".
@pytest.mark.parametrize("step", ["refdata", "finish"])
def test_lr10_a_kill_after_the_check_is_finished_forward_never_rolled_back(tmp_path: Path, step: str) -> None:
    """After the check the new release is in service and writes rows; a kill in "refdata" or "finish" is finished
    by ``rollback <bundle>`` forward: no rollback (the pre-update dump never goes over the live databases), the
    release recorded, the marker gone, audited ``update.applied`` with ``recovered``."""
    from tools import update_status as us
    from tools.trialbox import update as up

    updates = tmp_path / "updates"
    us.write_atomic(updates / us.INSTALLED, {"format": us.INSTALLED_FORMAT, "release_seq": 1, "bundle_id": "B0",
                                             "state": {}})  # fmt: skip

    class Killed(BaseException):
        pass

    def kill(at: str) -> None:
        if at == step:
            raise Killed

    plan = us_t._plan(tmp_path)
    with pytest.raises(Killed):
        up.Updater(us_t.Recorder(), updates, say=lambda _m: None, on_step=kill).run(plan)
    assert (us.marker(updates) or {}).get("step") == step
    box = us_t.Recorder()
    got = up.Updater(box, updates, say=lambda _m: None).recover("B1")
    assert got["ok"] and "rollback" not in box.calls, box.calls
    assert us.marker(updates) is None and not (updates / "B1" / "rollback").exists()
    assert us.installed(updates)["release_seq"] == 2 and us.installed(updates)["bundle_id"] == "B1"
    ((event, detail),) = box.audits
    assert event == "update.applied" and detail["recovered"] is True


def _killed_after_the_check(tmp_path: Path, step: str) -> Path:
    from tools import update_status as us
    from tools.trialbox import update as up

    updates = tmp_path / "updates"
    us.write_atomic(updates / us.INSTALLED, {"format": us.INSTALLED_FORMAT, "release_seq": 1, "bundle_id": "B0",
                                             "state": {}})  # fmt: skip

    class Killed(BaseException):
        pass

    def kill(at: str) -> None:
        if at == step:
            raise Killed

    with pytest.raises(Killed):
        up.Updater(us_t.Recorder(), updates, say=lambda _m: None, on_step=kill).run(us_t._plan(tmp_path))
    return updates


@pytest.mark.parametrize("step", ["refdata", "finish"])
def test_lr10_finishing_forward_twice_ends_the_same(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step: str) -> None:
    """Ruling (a): every step of finishing forward may run again. A kill inside the first finish (after its health
    check and audit, before the clean-up) and a second ``rollback <bundle>`` end as one finish did: the release
    recorded once, the marker gone, never a rollback."""
    from tools import update_status as us
    from tools.trialbox import update as up

    updates = _killed_after_the_check(tmp_path, step)
    recorded = (updates / us.INSTALLED).read_text(encoding="utf-8")

    class Killed(BaseException):
        pass

    real = up.Updater._done

    def killed(self: Any, *a: Any) -> None:
        raise Killed

    monkeypatch.setattr(up.Updater, "_done", killed)
    first = us_t.Recorder()
    with pytest.raises(Killed):
        up.Updater(first, updates, say=lambda _m: None).recover("B1")
    monkeypatch.setattr(up.Updater, "_done", real)
    second = us_t.Recorder()
    assert up.Updater(second, updates, say=lambda _m: None).recover("B1")["finished_forward"]
    assert first.calls == second.calls == ["check"]  # the health check each time, never a rollback
    assert (updates / us.INSTALLED).read_text(encoding="utf-8") == recorded
    assert us.marker(updates) is None and not (updates / "B1" / "rollback").exists()


def test_lr10_finishing_forward_counts_every_service_and_a_shortfall_stops_in_a_named_state(tmp_path: Path) -> None:
    """Ruling (b), (c): the full health check after finishing forward, N of M; a shortfall (or a check that fails)
    rolls nothing back: the marker stays in ``finish forward failed``, audited, with the command that tries again;
    that command then finishes it."""
    from tools import update_status as us
    from tools.trialbox import update as up

    updates = _killed_after_the_check(tmp_path, "refdata")

    class Short(us_t.Recorder):
        missing: tuple[str, ...] = ("console",)

        def health(self) -> tuple[list[str], list[str]]:
            return ["db", "orchestrator"], list(self.missing)

    box = Short()
    with pytest.raises(up.UpdateFailed) as err:
        up.Updater(box, updates, say=lambda _m: None).recover("B1")
    msg = str(err.value)
    assert "console" in msg and "2 of 3" in msg and "nothing was rolled back" in msg
    assert "tools/apply_update.sh rollback B1" in msg and "rollback" not in box.calls
    assert (us.marker(updates) or {}).get("step") == up.FORWARD_FAILED
    assert us.installed(updates)["bundle_id"] == "B1"  # the checked release stays recorded
    ((event, detail),) = box.audits
    assert event == "update.finish_failed" and detail["next"] == "tools/apply_update.sh rollback B1"
    healthy = Short()
    healthy.missing = ()
    got = up.Updater(healthy, updates, say=lambda _m: None).recover("B1")
    assert got["finished_forward"] and got["health"] == "2 of 2" and us.marker(updates) is None


def test_lr10_a_failed_check_while_finishing_forward_rolls_nothing_back(tmp_path: Path) -> None:
    from tools import update_status as us
    from tools.trialbox import update as up

    updates = _killed_after_the_check(tmp_path, "finish")
    box = us_t.Recorder(fail="check")
    with pytest.raises(up.UpdateFailed, match="nothing was rolled back"):
        up.Updater(box, updates, say=lambda _m: None).recover("B1")
    assert "rollback" not in box.calls and (us.marker(updates) or {}).get("step") == up.FORWARD_FAILED


def test_lr10_a_kill_before_the_check_keeps_the_full_rollback(tmp_path: Path) -> None:
    from tools.trialbox import update as up

    updates = _killed_after_the_check(tmp_path, "rulesets")
    box = us_t.Recorder()
    got = up.Updater(box, updates, say=lambda _m: None).recover("B1")
    assert got["ok"] and "rollback" in box.calls and "finished_forward" not in got


def test_lr10_the_compose_box_counts_every_service_it_defines() -> None:
    from tools.trialbox import update as up

    answers = {"config": "db\nconsole\nmigrate-once\norchestrator\n",
               "ps": "db running healthy 0\nconsole running starting 0\nmigrate-once exited  0\n"}  # fmt: skip
    box = up.ComposeBox(Path("/nonexistent/deploy"), lambda argv, **kw: answers["config" if "config" in argv else "ps"])
    assert box.health() == (["db", "migrate-once"], ["console", "orchestrator"])


# ------------------------------------------------------------------------------------------------------------ LR-2
# Matrix: "poc.sh up / reset / down | installed site box | none".
@pytest.mark.parametrize("action", ["reset", "down", "up", "status", "report", "logs"])
def test_lr2_poc_sh_does_nothing_on_an_installed_box(tmp_path: Path, action: str) -> None:
    """``deploy/poc.sh`` is in every box's host tree. On a host that records an install, every action is refused
    before anything runs: no engine command (``reset`` ran ``compose down -v`` on the site's project), no folder."""
    import os
    import shutil
    import subprocess

    repo = Path(__file__).resolve().parents[2]
    root = tmp_path / "root"
    (root / "deploy" / "updates").mkdir(parents=True)
    shutil.copy2(repo / "deploy/poc.sh", root / "deploy/poc.sh")
    shutil.copy2(repo / ".env.example", root / ".env.example")
    (root / "deploy/updates/installed.json").write_text('{"bundle_id": "synthetic"}', encoding="utf-8")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "docker.log"
    (bindir / "docker").write_text(f'#!/bin/sh\necho "$*" >> {log}\nexit 0\n', encoding="utf-8")
    (bindir / "docker").chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TB_", "COMPOSE_"))}
    env["PATH"] = f"{bindir}:/usr/bin:/bin"
    before = sorted(p.relative_to(root) for p in root.rglob("*"))
    res = subprocess.run(["bash", str(root / "deploy/poc.sh"), action], capture_output=True, text=True, env=env,
                         timeout=60, check=False)  # fmt: skip
    assert res.returncode == 1 and "installed box" in res.stderr and "Nothing was done" in res.stderr, res.stderr
    assert not log.exists()  # no engine command at all
    assert sorted(p.relative_to(root) for p in root.rglob("*")) == before


# ----------------------------------------------------------------------------------------- OCR review of #1481
def test_ocr1481_1_an_oversized_manifest_in_the_stream_is_never_held_and_never_handed_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OCR 1481-1: an archive swapped on the stick whose manifest.json claims 64 MiB: TarWatch held every byte of it
    (and copied it again at each chunk) while the load got it all; now the load is stopped before it gets any."""
    import hashlib
    import io
    import subprocess
    import tarfile

    from tools.trialbox import update as up

    info = tarfile.TarInfo("manifest.json")
    info.size = 64 << 20
    stick = tmp_path / "stick.bin"
    with stick.open("wb") as fh:
        fh.write(info.tobuf(format=tarfile.USTAR_FORMAT))
        fh.write(b" " * (6 << 20))
    p = up.Streamed(stick, "engine.tar", "image", hashlib.sha256(b"the signed archive").hexdigest(),
                    stick.stat().st_size, 0)  # fmt: skip
    eng = SharedEngine({"app:1": A})
    written: list[int] = []

    class Load:
        def __init__(self, *a: object, **kw: object) -> None:
            self.stdin = io.BytesIO()
            self.stdin.write = lambda b: written.append(len(b)) or len(b)  # type: ignore[method-assign]
            self.stdin.close = lambda: None  # type: ignore[method-assign]
            self.stdout = io.BytesIO(b"")

        def wait(self, timeout: float | None = None) -> int:
            return 1

        def kill(self) -> None:
            pass

    monkeypatch.setattr(subprocess, "Popen", Load)
    with pytest.raises(up.UpdateFailed):
        up.stream_image(p, {"app:1": B}, set(), eng)
    assert sum(written) == 0 and eng.tags == {"app:1": A}
    w = up.TarWatch()
    w.feed(info.tobuf(format=tarfile.USTAR_FORMAT) + b" " * (2 << 20))
    assert w.too_big and not w._data


@pytest.mark.parametrize("how", ["pax-path", "hardlink"])
def test_ocr1481_2_a_manifest_named_another_way_is_seen_or_refused(how: str) -> None:
    import io
    import json
    import tarfile

    from tools.trialbox import update as up

    data = json.dumps([{"Config": "f" * 64 + ".json", "RepoTags": ["theirs:1"]}]).encode()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tf:
        if how == "pax-path":
            i = tarfile.TarInfo("x")
            i.size = len(data)
            i.pax_headers = {"path": "manifest.json"}
            tf.addfile(i, io.BytesIO(data))
        else:
            i = tarfile.TarInfo("m")
            i.size = len(data)
            tf.addfile(i, io.BytesIO(data))
            link = tarfile.TarInfo("manifest.json")
            link.type = tarfile.LNKTYPE
            link.linkname = "m"
            tf.addfile(link)
    w = up.TarWatch()
    w.feed(buf.getvalue())
    assert w.scope()[0] == {"theirs:1"} or getattr(w, "too_big", False) or getattr(w, "unsure", False)


@pytest.mark.parametrize(("step", "load_cut"), [("refdata", True), ("finish", False)])
def test_ocr1481_3_a_retry_after_finish_forward_failed_names_the_step_that_was_cut(
    tmp_path: Path, step: str, load_cut: bool
) -> None:
    """OCR 1481-3: the retry's ``update.applied`` said the reference-data load was cut short when the kill came in
    "finish" (the load had ended), and named "finish forward failed" as the step the update was interrupted in."""
    from tools.trialbox import update as up

    updates = _killed_after_the_check(tmp_path, step)

    class Short(us_t.Recorder):
        missing: tuple[str, ...] = ("console",)

        def health(self) -> tuple[list[str], list[str]]:
            return ["db"], list(self.missing)

    with pytest.raises(up.UpdateFailed):
        up.Updater(Short(), updates, say=lambda _m: None).recover("B1")
    healthy = Short()
    healthy.missing = ()
    up.Updater(healthy, updates, say=lambda _m: None).recover("B1")
    ((event, detail),) = healthy.audits
    assert event == "update.applied" and detail["error"] == f"interrupted at step {step!r}", detail
    assert (detail["refdata_failed"] is not None) is load_cut, detail


@pytest.mark.parametrize("known", [False, True])
def test_ocr1481_4_lr15_an_unreadable_engine_volume_folder_is_refused_and_never_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], known: bool
) -> None:
    """Escape check (i): the engine's volume folder present but not searchable by this user (CI's runner: 0710 root).
    The stand-in makes it unreadable for any user, root included (a mode-000 folder is readable by root)."""
    touched = _no_host_engine_folder(monkeypatch)
    deploy = _box_without_the_volume_setting(tmp_path, monkeypatch)
    from tools.trialbox import box_restore

    engine = Path(box_restore.DEFAULT_VOLUMES)
    (engine / "trialbox_lake-data" / "_data").mkdir(parents=True)

    class Engine(h100.Recorder):
        def __call__(self, argv: list[str], **kw: object) -> str:
            if argv[1:3] == ["volume", "inspect"]:
                if known and argv[-1] == "trialbox_lake-data":
                    return f"{engine / 'trialbox_lake-data' / '_data'}\n"
                raise UpdateFailed(f"no such volume: {argv[-1]}")
            return super().__call__(argv, **kw)

    real_is_dir = Path.is_dir

    def is_dir(self: Path) -> bool:
        if str(self).startswith(str(engine)):
            raise PermissionError(13, "Permission denied", str(self))
        return real_is_dir(self)

    monkeypatch.setattr(Path, "is_dir", is_dir)
    rec = Engine(running=["db", "console"])
    code, seen = h100._restore(deploy, tmp_path, monkeypatch, rec, "{}", 0, "--restart")
    err = capsys.readouterr().err
    assert code == 2 and not seen, err
    assert ("cannot be read here" if known else "no data folder of the box was found") in err, err
    assert not [c for c in rec.calls if "stop" in c] and touched == []


def test_ocr1481_5_poc_sh_does_nothing_when_the_install_record_cannot_be_looked_for(tmp_path: Path) -> None:
    """OCR 1481-5 (escape check (i)): ``deploy/updates`` present but not searchable by the user who runs poc.sh: ``-e``
    is false there, and ``down`` ran on the box's project. (As root the folder stays searchable and the record is
    found; the refusal holds either way.)"""
    import os
    import shutil
    import subprocess

    repo = Path(__file__).resolve().parents[2]
    root = tmp_path / "root"
    (root / "deploy" / "updates").mkdir(parents=True)
    shutil.copy2(repo / "deploy/poc.sh", root / "deploy/poc.sh")
    shutil.copy2(repo / ".env.example", root / ".env.example")
    (root / "deploy/updates/installed.json").write_text('{"bundle_id": "synthetic"}', encoding="utf-8")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "docker.log"
    (bindir / "docker").write_text(f'#!/bin/sh\necho "$*" >> {log}\nexit 0\n', encoding="utf-8")
    (bindir / "docker").chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TB_", "COMPOSE_"))}
    env["PATH"] = f"{bindir}:/usr/bin:/bin"
    (root / "deploy" / "updates").chmod(0o000)
    try:
        res = subprocess.run(["bash", str(root / "deploy/poc.sh"), "down"], capture_output=True, text=True, env=env,
                             timeout=60, check=False)  # fmt: skip
    finally:
        (root / "deploy" / "updates").chmod(0o755)
    assert res.returncode == 1 and "Nothing was done" in res.stderr, res.stderr
    assert not log.exists()
