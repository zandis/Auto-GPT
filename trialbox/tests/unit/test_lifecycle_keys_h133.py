"""H-133: the key operations of the lifecycle review (LR-3, LR-4, LR-6, LR-7), each reproduced on master.

- LR-3: ``rotate-kek`` run as root left ``kek.json``, every wrapped key and the runtime KEK root's (0600): the services
  (the secrets folder's owner) could open no key. Each file is now given to the folder's owner before it takes its name.
- LR-4: ``unseal`` after a restart (the runbook's step, and the installer's re-run) left the runtime KEK and its new
  folder root's; an unreadable KEK was a bare ``PermissionError`` that ``custody()`` did not catch.
- LR-6: ``rotate-kek --backend file`` on a box whose KEK is sealed by the TPM left the credential sealing the old KEK.
  The new KEK is now sealed beside it before the commit and the credential is swapped first in the roll-forward.
- LR-7: ``rotate-kek`` replaced and then renamed the key an interrupted ``rotate pid_map`` had staged under the same
  name. It now refuses while a staged key it did not journal is there; ``rotate pid_map`` takes the folder's lock.

Run as root, the services are a real other account (uid 10001) and a child process of that account reads the files.
Run as an ordinary user, the folder's owner is taken to be uid 10001 and every change of owner is recorded by inode
(an ordinary user cannot give a file away); the same reads are checked against the recorded owner and the mode.
The passphrases and keys here are synthetic.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

import pytest
from tb_common import kek as K
from tb_common.audit import AuditLog

from tests.own_deploy import own_deploy
from tools import keys

pytestmark = pytest.mark.nodb


@pytest.fixture(autouse=True)
def _own_deploy(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """H139-10: the key commands read a deploy folder of this test's own, never the checkout's deploy/.env."""
    own_deploy(monkeypatch, tmp_path_factory.mktemp("box") / "deploy")


OLD = "synthetic-h133-" + "lifecycle-old-passphrase"  # synthetic
NEW = "synthetic-h133-" + "lifecycle-new-passphrase"  # synthetic
DEV = {"TB_ENV": "DEV"}  # a key ceremony is refused on a PRODUCTION box (rc1)
SERVICES = 10001  # the services' account on a box (deploy/install.sh)
ROOT = os.geteuid() == 0


class Owners:
    """Who owns a file: the real owner as root; as an ordinary user, the owner a chown to SERVICES gave it."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.given: dict[tuple[int, int], tuple[int, int]] = {}
        if ROOT:
            return
        real_fchown, real_chown = os.fchown, os.chown

        def fchown(fd: int, uid: int, gid: int) -> None:
            if uid != SERVICES:
                real_fchown(fd, uid, gid)
                return
            st = os.fstat(fd)
            self.given[(st.st_dev, st.st_ino)] = (uid, gid)

        def chown(path: Any, uid: int, gid: int, *, dir_fd: int | None = None, follow_symlinks: bool = True) -> None:
            if uid != SERVICES:
                real_chown(path, uid, gid, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
                return
            st = os.stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
            self.given[(st.st_dev, st.st_ino)] = (uid, gid)

        monkeypatch.setattr(os, "fchown", fchown)
        monkeypatch.setattr(os, "chown", chown)
        # the secrets folder of this test belongs to the services: what the box's own folder is (D-887)
        monkeypatch.setattr(K, "services_owner", lambda _sec: (SERVICES, SERVICES), raising=False)

    def give(self, path: Path) -> None:
        """What the installer's hand-over (D-887) does."""
        os.chown(path, SERVICES, SERVICES, follow_symlinks=False)

    def owner(self, path: Path) -> int:
        st = os.lstat(path)
        return self.given.get((st.st_dev, st.st_ino), (st.st_uid, st.st_gid))[0]

    def services_read(self, folder: Path, names: list[str]) -> dict[str, bool]:
        """Whether the services' account opens each file of ``folder`` (and searches the folder) to read."""
        if ROOT:
            return _child_reads(folder, names)
        fst = os.stat(folder)
        searchable = (self.owner(folder) == SERVICES and fst.st_mode & stat.S_IXUSR) or fst.st_mode & stat.S_IXOTH
        out = {}
        for n in names:
            p = folder / n
            if not p.is_file():
                out[n] = False
                continue
            m = os.stat(p).st_mode
            out[n] = bool(searchable) and bool((self.owner(p) == SERVICES and m & stat.S_IRUSR) or m & stat.S_IROTH)
        return out


def _child_reads(folder: Path, names: list[str]) -> dict[str, bool]:
    """Root: a child that takes on uid 10001 opens each name in ``folder`` (by a descriptor of the folder opened
    before, so the test's own temporary folders above it, 0700 root, are not in the way). Never prints a value."""
    dfd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:  # the child: no exception may leave it
        code = 0
        try:
            os.close(r)
            os.setgroups([])
            os.setgid(SERVICES)
            os.setuid(SERVICES)
            got = {}
            for n in names:
                try:
                    fd = os.open(n, os.O_RDONLY, dir_fd=dfd)
                    os.read(fd, 1)
                    os.close(fd)
                    got[n] = True
                except OSError:
                    got[n] = False
            os.write(w, json.dumps(got).encode())
        except BaseException:  # a child of a fork never returns into pytest
            code = 1
        finally:
            os._exit(code)
    os.close(w)
    os.close(dfd)
    data = b""
    while chunk := os.read(r, 65536):
        data += chunk
    os.close(r)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0, "the services' child could not run"
    seen: dict[str, bool] = json.loads(data)
    return seen


def _state(folder: Path) -> dict[str, str]:
    """Each file of ``folder`` by name and digest (an assertion's diff never shows a key file's bytes)."""
    return {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in folder.iterdir()}


def _pp(path: Path, text: str) -> Path:
    path.write_text(text + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def _served(sec: Path) -> list[str]:
    """The files of the secrets folder the services read: kek.json and every wrapped key."""
    return sorted([K.META_FILE, *(f.name for f in sec.glob("*.wrapped"))])


def _passphrase_box(tmp: Path, own: Owners, *, pid_map: bool = False) -> dict[str, Path]:
    """A DEV box sealed under OLD, unsealed to its run folder, handed to the services as the installer does."""
    sec = tmp / "sec"
    sec.mkdir()
    for name in ("site_hmac.key", "objects.key", *(("pid_map.key",) if pid_map else ())):
        (sec / name).write_bytes(os.urandom(32))
    rc = keys.main(["init", "--backend", "passphrase", "--secrets", str(sec), "--scrypt-n", "1024",
                    "--passphrase-file", str(_pp(tmp / "init.pass", OLD))], env={})  # fmt: skip
    assert rc == 0
    run = tmp / "run" / "trialbox"
    rc = keys.main(["unseal", "--secrets", str(sec), "--out", str(run / "kek"),
                    "--passphrase-file", str(_pp(tmp / "unseal.pass", OLD))], env={})  # fmt: skip
    assert rc == 0
    for f in (sec, *sec.iterdir(), run, run / "kek"):  # seal_keys.sh's hand-over (D-887)
        own.give(f)
    audit = tmp / "audit"
    AuditLog(audit).append("test.box_ready", actor="tester")
    return {"sec": sec, "run": run, "audit": audit, "tmp": tmp}


def _rotate_argv(b: dict[str, Path]) -> list[str]:
    return ["rotate-kek", "--backend", "passphrase", "--secrets", str(b["sec"]), "--scrypt-n", "1024",
            "--passphrase-file", str(_pp(b["tmp"] / "old.pass", OLD)),
            "--new-passphrase-file", str(_pp(b["tmp"] / "new.pass", NEW)),
            "--audit-dir", str(b["audit"]), "--out", str(b["run"] / "kek")]  # fmt: skip


def _opens(sec: Path, kek: bytes) -> bool:
    meta = K.read_meta(sec) or {}
    if K.kek_id(kek) != meta.get("kek_id"):
        return False
    return all(K.unwrap(kek, K.read_wrapped(sec / f.name[: -len(K.WRAPPED_SUFFIX)]), f.name[: -len(K.WRAPPED_SUFFIX)])
               for f in sec.glob("*.wrapped"))  # fmt: skip


def _runtime_opens(b: dict[str, Path]) -> bool:
    return _opens(b["sec"], (b["run"] / "kek").read_bytes())


def test_lr3_after_rotate_kek_as_root_the_services_still_open_kek_json_every_key_and_the_runtime_kek(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Matrix cell "rotate-kek | KEK passphrase, runtime KEK present, services as uid 10001 | none" (LR-3)."""
    own = Owners(monkeypatch)
    b = _passphrase_box(tmp_path, own)
    served = _served(b["sec"])
    assert all(own.services_read(b["sec"], served).values())  # before: the services open every key
    assert own.services_read(b["run"], ["kek"]) == {"kek": True}
    # every rename in the secrets folder and of the runtime KEK: the file already the services' as it takes its name
    late: list[str] = []
    real_replace = os.replace

    def replace(src: Any, dst: Any) -> None:
        d = Path(str(dst))
        served = d.parent == b["sec"] and (d.name == K.META_FILE or d.name.endswith(K.WRAPPED_SUFFIX))
        if (served or d == b["run"] / "kek") and own.owner(Path(str(src))) != SERVICES:
            late.append(d.name)
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", replace)
    assert keys.main(_rotate_argv(b), env=DEV) == 0
    monkeypatch.setattr(os, "replace", real_replace)
    assert late == []
    assert own.services_read(b["sec"], served) == dict.fromkeys(served, True)
    assert own.services_read(b["run"], ["kek"]) == {"kek": True}
    assert _runtime_opens(b)


def test_lr4_unseal_after_a_restart_leaves_a_runtime_kek_and_folder_the_services_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Matrix cells "unseal by hand | KEK passphrase or shamir, services as another uid | none", "seal, second run |
    KEK passphrase, after a reboot | none" (the installer's re-run is this unseal) and "boot after power cut | KEK
    passphrase, KEK gone from tmpfs | power cut" (LR-4)."""
    own = Owners(monkeypatch)
    b = _passphrase_box(tmp_path, own)
    (b["run"] / "kek").unlink()  # a restart: /run is a tmpfs
    b["run"].rmdir()
    b["run"].parent.rmdir()
    rc = keys.main(["unseal", "--secrets", str(b["sec"]), "--out", str(b["run"] / "kek"),
                    "--passphrase-file", str(_pp(tmp_path / "again.pass", OLD))], env={})  # fmt: skip
    assert rc == 0
    assert own.services_read(b["run"], ["kek"]) == {"kek": True}
    assert stat.S_IMODE(os.stat(b["run"] / "kek").st_mode) == 0o600
    assert stat.S_IMODE(os.stat(b["run"]).st_mode) & 0o077 == 0  # the KEK's folder is no one else's to list
    assert _runtime_opens(b)


def test_lr4_a_kek_file_that_cannot_be_read_is_a_kek_error_that_custody_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LR-4: the services' load of a KEK they cannot read was a bare PermissionError; ``custody()`` (the doctor's key
    check) raised instead of reporting it."""
    own = Owners(monkeypatch)
    b = _passphrase_box(tmp_path, own)
    kek_file = b["run"] / "kek"
    real = Path.read_bytes

    def read_bytes(self: Path) -> bytes:
        if self == kek_file:
            raise PermissionError(errno.EACCES, "Permission denied", str(self))
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    with pytest.raises(K.KekError) as exc:
        K.load_kek(b["sec"], {"TB_KEK_FILE": str(kek_file)})
    assert str(kek_file) in str(exc.value) and "PermissionError" in str(exc.value)
    c = K.custody(b["sec"], {"TB_KEK_FILE": str(kek_file)})
    assert c.kek == "refused" and any(str(kek_file) in p for p in c.problems)


STANDIN = """#!{py} -I
# a stand-in for systemd-creds: "sealed" is the plain bytes behind a marker (synthetic keys only)
import sys
verb, args = sys.argv[1], [a for a in sys.argv[2:] if not a.startswith("--")]
src, dst = (args + ["-", "-"])[:2]
data = sys.stdin.buffer.read() if src == "-" else open(src, "rb").read()
if verb == "encrypt":
    out = b"STANDIN-SEALED:" + data
elif verb == "decrypt" and data.startswith(b"STANDIN-SEALED:"):
    out = data[len(b"STANDIN-SEALED:"):]
else:
    sys.exit(1)
if dst == "-":
    sys.stdout.buffer.write(out)
else:
    open(dst, "wb").write(out)
"""


def _tpm_box(tmp: Path, own: Owners, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """A TPM box as seal_keys.sh leaves it: the KEK sealed to the credential, kek.json back end file, unsealed."""
    tool = tmp / "bin" / "systemd-creds"
    tool.parent.mkdir()
    tool.write_text(STANDIN.format(py=sys.executable), encoding="utf-8")
    tool.chmod(0o755)
    cred = tmp / "credstore.encrypted" / K.CREDENTIAL
    cred.parent.mkdir(mode=0o700)
    monkeypatch.setattr(keys, "CREDENTIAL_FILE", cred, raising=False)
    monkeypatch.setattr(keys, "_creds_tool", lambda: str(tool), raising=False)
    sec = tmp / "sec"
    sec.mkdir()
    for name in ("site_hmac.key", "objects.key"):
        (sec / name).write_bytes(os.urandom(32))
    plain = tmp / "kek.new"
    plain.write_bytes(os.urandom(K.KEK_LEN))
    plain.chmod(0o600)
    cred.write_bytes(b"STANDIN-SEALED:" + plain.read_bytes())
    cred.chmod(0o600)
    assert keys.main(["init", "--backend", "file", "--secrets", str(sec), "--kek-in", str(plain)], env={}) == 0
    run = tmp / "run" / "trialbox"
    assert keys.main(["unseal", "--secrets", str(sec), "--from", str(plain), "--out", str(run / "kek")], env={}) == 0
    plain.unlink()
    for f in (sec, *sec.iterdir(), run, run / "kek"):
        own.give(f)
    audit = tmp / "audit"
    AuditLog(audit).append("test.box_ready", actor="tester")
    media = tmp / "media"
    media.mkdir()
    return {"sec": sec, "run": run, "audit": audit, "tmp": tmp, "cred": cred, "media": media}


def _unsealed_from(cred: Path) -> bytes:
    data = cred.read_bytes()
    assert data.startswith(b"STANDIN-SEALED:")
    return data[len(b"STANDIN-SEALED:") :]


def _sealed_opens(b: dict[str, Path]) -> bool:
    """Whether the KEK in the credential (what the boot unseal opens) opens every key under kek.json's name."""
    return _opens(b["sec"], _unsealed_from(b["cred"]))


def test_lr6_rotate_kek_on_a_tpm_box_seals_the_new_kek_to_the_credential_the_boot_unseal_opens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Matrix cell "rotate-kek | KEK TPM, sealed credential | none" (LR-6): the runbook's rotation (a custodian left)
    left the credential on the old KEK, so the next boot's unseal was refused and, with no new escrow set, the keys
    were lost at that reboot."""
    own = Owners(monkeypatch)
    b = _tpm_box(tmp_path, own, monkeypatch)
    old_id = (K.read_meta(b["sec"]) or {})["kek_id"]
    assert _sealed_opens(b)
    rc = keys.main(["rotate-kek", "--backend", "file", "--secrets", str(b["sec"]), "--kek-out",
                    str(b["media"] / "kek.new"), "--audit-dir", str(b["audit"]), "--out", str(b["run"] / "kek")],
                   env={**DEV, "TB_KEK_FILE": str(b["run"] / "kek")})  # fmt: skip
    assert rc == 0
    assert (K.read_meta(b["sec"]) or {})["kek_id"] != old_id
    assert _sealed_opens(b)  # what trialbox-unseal.service opens at the next boot
    assert stat.S_IMODE(os.stat(b["cred"]).st_mode) == 0o600
    assert not (b["cred"].parent / (K.CREDENTIAL + ".next")).exists()
    assert own.services_read(b["sec"], _served(b["sec"])) == dict.fromkeys(_served(b["sec"]), True)


def test_lr6_a_rotation_on_a_tpm_box_cut_short_keeps_every_key_opening_with_the_sealed_kek_or_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LR-6, the card's invariant: a kill at every rename of the rotation (the journal's writes, the sealed new KEK
    beside the credential, the staged keys, the commit, the credential, each key, kek.json, the done event). At each
    stop every key is either as it was (it opens with the KEK sealed before) or opens with the KEK sealed in the
    credential now, so some credential always opens it; ``status --audit-dir`` then finishes or rolls back, and
    every key opens with the credential in place."""
    own = Owners(monkeypatch)
    real_replace = os.replace

    class Killed(BaseException):
        pass

    stops = 0
    for stop_at in range(1, 60):
        tmp = tmp_path / str(stop_at)
        tmp.mkdir()
        b = _tpm_box(tmp, own, monkeypatch)
        old = _unsealed_from(b["cred"])
        before = {f.name: f.read_bytes() for f in b["sec"].glob("*.wrapped")}
        seen = [0]

        def replace(src: Any, dst: Any, _stop: int = stop_at, _seen: list[int] = seen) -> None:
            _seen[0] += 1
            if _seen[0] == _stop:
                raise Killed
            real_replace(src, dst)

        monkeypatch.setattr(os, "replace", replace)
        try:
            keys.main(["rotate-kek", "--backend", "file", "--secrets", str(b["sec"]), "--kek-out",
                       str(b["media"] / "kek.new"), "--audit-dir", str(b["audit"])],
                      env={**DEV, "TB_KEK_FILE": str(b["run"] / "kek")})  # fmt: skip
            killed = False
        except Killed:
            killed = True
        monkeypatch.setattr(os, "replace", real_replace)
        sealed = _unsealed_from(b["cred"])
        for f in b["sec"].glob("*.wrapped"):
            name = f.name[: -len(K.WRAPPED_SUFFIX)]
            doc = K.read_wrapped(b["sec"] / name)
            as_was = f.read_bytes() == before[f.name] and doc.get("kek_id") == K.kek_id(old)
            opens = K.kek_id(sealed) == doc.get("kek_id")
            assert as_was or opens, (stop_at, f.name)
        assert keys.main(["status", "--secrets", str(b["sec"]), "--audit-dir", str(b["audit"])],
                         env={"TB_KEK_FILE": str(tmp / "none")}) in (0, 1)  # fmt: skip
        assert _sealed_opens(b), stop_at
        if not killed:  # every rename of the rotation was a stop
            break
        stops += 1
    assert stops >= 8  # the journal twice, the sealed KEK, two staged keys, kek.json.next, the credential, the keys


def test_lr6_a_credential_sealing_another_kek_is_never_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LR-6, the card's last rule: a rotation never destroys a key it did not make. The credential on this host may
    seal another secrets folder's KEK (another box's, a test's): it is left as it is, and --seal-tpm is refused."""
    own = Owners(monkeypatch)
    b = _tpm_box(tmp_path, own, monkeypatch)
    b["cred"].write_bytes(b"STANDIN-SEALED:" + os.urandom(K.KEK_LEN))  # the host's own box, not this folder
    kept = b["cred"].read_bytes()
    argv = ["rotate-kek", "--backend", "file", "--secrets", str(b["sec"]), "--audit-dir", str(b["audit"])]
    env = {**DEV, "TB_KEK_FILE": str(b["run"] / "kek")}
    before = _state(b["sec"])
    assert keys.main([*argv, "--kek-out", str(b["media"] / "a.kek"), "--seal-tpm"], env=env) == 1
    assert _state(b["sec"]) == before and b["cred"].read_bytes() == kept
    assert keys.main([*argv, "--kek-out", str(b["media"] / "b.kek")], env=env) == 0
    assert b["cred"].read_bytes() == kept
    assert not (b["cred"].parent / (K.CREDENTIAL + ".next")).exists()
    assert _runtime_opens(b)


def test_lr6_a_seal_holding_the_credential_folder_makes_rotate_kek_refuse_with_nothing_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LR-6 with #1457 (1457-1): the TPM credential is the host's. seal_keys.sh, sealing another secrets folder, holds
    an exclusive flock on the credential's folder (its fd 5); a rotation that would read or swap the credential takes
    the same lock and is refused while it is held, with nothing changed. Released, the rotation goes through."""
    import fcntl

    own = Owners(monkeypatch)
    b = _tpm_box(tmp_path, own, monkeypatch)
    argv = ["rotate-kek", "--backend", "file", "--secrets", str(b["sec"]), "--audit-dir", str(b["audit"]),
            "--out", str(b["run"] / "kek")]  # fmt: skip
    env = {**DEV, "TB_KEK_FILE": str(b["run"] / "kek")}
    before, cred = _state(b["sec"]), b["cred"].read_bytes()
    fd = os.open(b["cred"].parent, os.O_RDONLY | os.O_DIRECTORY)  # what seal_keys.sh's `exec 5<` and `flock -n 5` take
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert keys.main([*argv, "--kek-out", str(b["media"] / "a.kek")], env=env) == 1
        assert _state(b["sec"]) == before and b["cred"].read_bytes() == cred
        assert sorted(f.name for f in b["cred"].parent.iterdir()) == [K.CREDENTIAL]
        assert not (b["media"] / "a.kek").exists()
    finally:
        os.close(fd)
    assert keys.main([*argv, "--kek-out", str(b["media"] / "b.kek")], env=env) == 0
    assert _sealed_opens(b) and _runtime_opens(b)


def test_lr6_rotate_kek_on_a_tpm_box_without_the_sealing_tool_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LR-6: no systemd-creds on a box with a sealed credential: refused before anything changes."""
    own = Owners(monkeypatch)
    b = _tpm_box(tmp_path, own, monkeypatch)
    monkeypatch.setattr(keys, "_creds_tool", lambda: None)
    before = _state(b["sec"])
    cred = b["cred"].read_bytes()
    rc = keys.main(["rotate-kek", "--backend", "file", "--secrets", str(b["sec"]), "--kek-out",
                    str(b["media"] / "kek.new"), "--audit-dir", str(b["audit"])],
                      env={**DEV, "TB_KEK_FILE": str(b["run"] / "kek")})  # fmt: skip
    assert rc == 1
    assert _state(b["sec"]) == before
    assert b["cred"].read_bytes() == cred and not (b["media"] / "kek.new").exists()


def test_lr7_rotate_kek_refuses_while_a_pid_map_rotation_cut_short_has_its_key_staged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Matrix cells "rotate-kek | prior interrupted rotate pid_map | none" and "rotate pid_map | wrapped key | KILL /
    power cut" (LR-7): the staged key is the only copy of the key the re-keyed rows are under; rotate-kek wrote over
    it and renamed it away."""
    own = Owners(monkeypatch)
    b = _passphrase_box(tmp_path, own, pid_map=True)
    old = (b["run"] / "kek").read_bytes()
    staged = b["sec"] / "pid_map.key.wrapped.next"  # what `rotate pid_map` leaves when killed after its commit
    new_pid_key = os.urandom(32)
    K._write_private(staged, (json.dumps(K.wrap(old, new_pid_key, "pid_map.key"), indent=1, sort_keys=True) +
                              "\n").encode())  # fmt: skip
    kept = staged.read_bytes()
    before = _state(b["sec"])
    rc = keys.main(_rotate_argv(b), env=DEV)
    assert rc == 1
    assert staged.read_bytes() == kept
    assert K.unwrap(old, json.loads(kept), "pid_map.key") == new_pid_key
    assert _state(b["sec"]) == before


def test_lr7_rotate_pid_map_waits_for_a_kek_rotation_cut_short_and_for_the_folder_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LR-7, the other way round: ``rotate pid_map`` staged its key under a KEK a rotation was replacing, and its
    staged name is the one rotate-kek stages and rolls back. Refused before the database is reached."""
    own = Owners(monkeypatch)
    b = _passphrase_box(tmp_path, own, pid_map=True)
    env = {"TB_KEK_FILE": str(b["run"] / "kek"), "TB_ENV": "DEV"}
    argv = ["rotate", "pid_map", "--secrets", str(b["sec"]), "--db-url", "postgresql://h133@127.0.0.1:1/none"]
    monkeypatch.setattr(keys, "DEFAULT_DEPLOY", str(tmp_path / "deploy"))
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy" / ".env").write_text("TB_ENV=DEV\n", encoding="utf-8")
    journal = b["sec"] / K.ROTATION_JOURNAL
    journal.write_text(json.dumps({"format": keys.JOURNAL_FORMAT, "step": "staging", "keys": ["pid_map.key"]}),
                       encoding="utf-8")  # fmt: skip
    before = _state(b["sec"])
    assert keys.main(argv, env=env) == 1
    assert _state(b["sec"]) == before
    journal.unlink()
    with keys._Locked(b["sec"]):  # a rotate-kek running
        before = _state(b["sec"])
        assert keys.main(argv, env=env) == 1
        assert _state(b["sec"]) == before


class _RootSeen:
    """``os`` as tb_common.kek sees it in the owner test as an ordinary user: everything real but the effective uid."""

    def __getattr__(self, name: str) -> Any:
        return getattr(os, name)

    @staticmethod
    def geteuid() -> int:
        return 0


#: variables a caller could set to steer who gets the key files; none may change it (the card's rule)
STEER = {"SUDO_UID": "0", "SUDO_GID": "0", "SUDO_USER": "root", "TB_SERVICES_UID": "4242", "TB_SECRETS_OWNER": "0:0",
         "TB_UID": "0", "TB_GID": "0", "USER": "root", "LOGNAME": "root"}  # fmt: skip


def test_lr3_lr4_the_owner_comes_from_the_secrets_folder_never_from_a_caller_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LR-3, LR-4: who gets the files is the secrets folder's owner, read from the folder; a variable in the process
    environment or in the mapping a command is given changes nothing. As an ordinary user the effective uid is taken
    to be root for the seam (``os.geteuid``), so the real ``services_owner`` and the real unseal run; the owner is
    then this user, the folder's own."""
    sec = tmp_path / "sec"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(os.urandom(32))
    rc = keys.main(["init", "--backend", "passphrase", "--secrets", str(sec), "--scrypt-n", "1024",
                    "--passphrase-file", str(_pp(tmp_path / "init.pass", OLD))], env={})  # fmt: skip
    assert rc == 0
    if ROOT:
        for f in (sec, *sec.iterdir()):
            os.chown(f, SERVICES, SERVICES)
    else:  # the seam: tb_common.kek sees an effective uid of root; tools.keys's own checks see this user
        monkeypatch.setattr(K, "os", _RootSeen())
    st = os.stat(sec)
    want = (st.st_uid, st.st_gid)
    assert want[0] != 0
    assert K.services_owner(sec) == want
    for k, v in STEER.items():
        monkeypatch.setenv(k, v)
    assert K.services_owner(sec) == want
    run = tmp_path / "run" / "trialbox"
    rc = keys.main(["unseal", "--secrets", str(sec), "--out", str(run / "kek"),
                    "--passphrase-file", str(_pp(tmp_path / "unseal.pass", OLD))], env=dict(STEER))  # fmt: skip
    assert rc == 0
    for p in (run, run / "kek"):
        got = os.stat(p)
        assert (got.st_uid, got.st_gid) == want, p
    assert stat.S_IMODE(os.stat(run).st_mode) == 0o700 and stat.S_IMODE(os.stat(run / "kek").st_mode) == 0o600
    monkeypatch.setattr(K, "os", os)
    root_owned = tmp_path / "root-owned"
    root_owned.mkdir()
    if ROOT:  # a folder root owns: the writer keeps the files, whatever the variables say
        assert K.services_owner(root_owned) is None
    else:  # not root: never a hand-over
        assert K.services_owner(sec) is None
