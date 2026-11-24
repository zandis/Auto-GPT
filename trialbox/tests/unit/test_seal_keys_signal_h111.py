"""H-111 (external review H-BK-1, High): a signal during the TPM seal destroyed the only KEK after the keys were wrapped.

deploy/hardening/seal_keys.sh (KEK_BACKEND=tpm, no kek.json, plain site keys) set a trap that shredded the new KEK and
removed the new credential on EXIT, INT, TERM and HUP, ran `tools.keys init` (kek.json written, each key wrapped under
the new KEK, the plain file removed), and only then moved the sealed credential into place. A SIGTERM, SIGHUP or
Ctrl-C in between left wrapped keys and no KEK anywhere: site_hmac.key and pid_map.key could not be recovered.

The invariant now: at every instant either a key is there plain, as it was, or the KEK that opens its wrapped copy is
sealed in the credential's final place. The credential is sealed and placed before any key is wrapped and nothing in
the script removes it; a signal exits; a re-run finishes what a stopped run began.

Here a host root of its own (TB_HOST_ROOT), a stand-in sealing tool whose "sealed" credential is a copy of the KEK,
and a stand-in python3 on PATH that runs the keys commands and, at a named step, sends a signal to the script (its
process group, as Ctrl-C does, or the shell alone) and checks the invariant at every step. The product reads none of
the stand-ins' variables. The keys are synthetic. No TPM is used: the real sealing tool is not exercised here.
"""

from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from tb_common import kek as K

ROOT = Path(__file__).resolve().parents[2]
SEAL = ROOT / "deploy" / "hardening" / "seal_keys.sh"
NAMES = ("site_hmac.key", "pid_map.key")

pytestmark = pytest.mark.nodb

# the stand-ins' shared helper: fire a signal at a named step, and check the invariant at every step
HOOK = r"""
import json, os, signal, sys, time
from pathlib import Path
from tb_common import kek as K

D = Path(os.environ["STANDIN_DIR"])


def invariant(point):
    keys = json.loads((D / "keys.json").read_text())
    sec, cred = Path(os.environ["STANDIN_SECRETS"]), Path(os.environ["STANDIN_CRED"])
    for name, hexkey in keys.items():
        want = bytes.fromhex(hexkey)
        p = sec / name
        if p.is_file() and p.read_bytes() == want:
            continue
        try:
            ok = cred.is_file() and K.unwrap(cred.read_bytes(), K.read_wrapped(p), name) == want
        except K.KekError:
            ok = False
        if not ok:
            with open(D / "violations", "a") as fh:
                fh.write(f"{point}: {name} is neither plain nor opened by the placed credential\n")


def hook(point):
    invariant(point)
    if os.environ.get("STANDIN_AT") != point:
        return
    (D / f"fired-{point}").write_text("")
    sig = getattr(signal, "SIG" + os.environ["STANDIN_SIG"])
    pg = os.getpgid(0)
    if os.environ.get("STANDIN_SCOPE") == "group":
        os.killpg(pg, sig)  # as Ctrl-C or a service stop does: every process of the script
        time.sleep(5)
    else:
        os.kill(pg, sig)  # the script's shell alone (the session leader)
"""

# the stand-in python3: the keys init through the hook (after the place, after each wrap), the rest as it is
PY = r"""
import os, sys
sys.path.insert(0, os.environ["STANDIN_DIR"])
from hook import hook

args = sys.argv[1:]
real = os.environ["STANDIN_PY"]
if args[:3] == ["-m", "tools.keys", "init"]:
    hook("after_place")
    from tb_common import kek as K
    orig, n = K.store_key, []
    def store(*a, **k):
        out = orig(*a, **k)
        n.append(1)
        # the second key is wrapped and its plain file not yet removed; the first is wrapped and its plain file gone
        hook("during_init" if len(n) == 2 else f"wrap-{len(n)}")
        return out
    K.store_key = store
    from tools import keys
    rc = keys.main(["init", *args[3:]])
    hook("after_init")
    sys.exit(rc)
os.execv(real, [real, *args])
"""

CREDS = r"""#!/bin/sh
hook() { "$STANDIN_PY" -c 'import sys; sys.path.insert(0, sys.argv[1]); from hook import hook; hook(sys.argv[2])' "$STANDIN_DIR" "$1"; }
case "$1" in
  has-tpm2) exit 0 ;;
  encrypt)
    [ -e "$STANDIN_DIR/fail-seal" ] && { echo "TPM2 operation failed" >&2; exit 1; }
    hook before_seal; cp "$4" "$5"; hook after_seal ;;
  decrypt) cp "$3" "$4" ;;
  *) exit 2 ;;
esac
"""


def _host(tmp: Path) -> tuple[dict[str, str], dict[str, bytes]]:
    hr = tmp / "host"
    (hr / "dev").mkdir(parents=True)
    (hr / "dev" / "tpmrm0").write_text("")
    sec = tmp / "secrets"
    sec.mkdir()
    keys = {name: os.urandom(32) for name in NAMES}  # synthetic
    for name, key in keys.items():
        (sec / name).write_bytes(key)
        (sec / name).chmod(0o600)
    d = tmp / "standin"
    d.mkdir()
    (d / "keys.json").write_text(json.dumps({n: k.hex() for n, k in keys.items()}))
    (d / "hook.py").write_text(HOOK)
    (d / "py_standin.py").write_text(PY)
    b = tmp / "bin"
    b.mkdir()
    (b / "systemd-creds").write_text(CREDS)
    (b / "python3").write_text('#!/bin/sh\nexec "$STANDIN_PY" "$STANDIN_DIR/py_standin.py" "$@"\n')
    for f in b.iterdir():
        f.chmod(0o755)
    (tmp / "units").mkdir()
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith(("TB_", "STANDIN_"))},
        "PATH": f"{b}:/usr/bin:/bin",
        "PYTHONPATH": f"{ROOT / 'libs'}:{ROOT}",
        "TB_HOST_ROOT": str(hr),
        "TB_KEK_BACKEND": "tpm",
        "TB_KEK_FILE": str(hr / "run" / "trialbox" / "kek"),
        "TB_SYSTEMD_DIR": str(tmp / "units"),
        "STANDIN_PY": sys.executable,
        "STANDIN_DIR": str(d),
        "STANDIN_SECRETS": str(sec),
        "STANDIN_CRED": str(_cred(tmp)),
    }
    return env, keys


def _cred(tmp: Path) -> Path:
    return tmp / "host" / "etc" / "credstore.encrypted" / "trialbox-kek"


def _seal(tmp: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(SEAL), "--secrets", str(tmp / "secrets"), "--conf", str(tmp / "no-such.conf")],
        capture_output=True, text=True, env=env, check=False, start_new_session=True, timeout=120,
    )  # fmt: skip


def _violations(tmp: Path) -> str:
    v = tmp / "standin" / "violations"
    return v.read_text() if v.exists() else ""


def _keys_open(tmp: Path, keys: dict[str, bytes]) -> None:
    """Each key is there plain as it was, or its wrapped copy opens under the KEK of the placed credential."""
    sec, cred = tmp / "secrets", _cred(tmp)
    for name, want in keys.items():
        if (sec / name).is_file() and (sec / name).read_bytes() == want:
            continue
        assert cred.is_file(), f"{name} is wrapped and no credential holds its KEK"
        assert K.unwrap(cred.read_bytes(), K.read_wrapped(sec / name), name) == want


def _sealed_and_done(tmp: Path, keys: dict[str, bytes]) -> None:
    sec, cred = tmp / "secrets", _cred(tmp)
    kek = cred.read_bytes()
    assert len(kek) == K.KEK_LEN
    meta = K.read_meta(sec)
    assert meta is not None and meta["kek_id"] == K.kek_id(kek)
    for name, want in keys.items():
        assert not (sec / name).exists(), f"{name} is still plain"
        assert K.unwrap(kek, K.read_wrapped(sec / name), name) == want
    assert (tmp / "host" / "run" / "trialbox" / "kek").read_bytes() == kek
    assert not (tmp / "host" / "run" / "trialbox" / "kek.new").exists()
    assert not cred.with_name("trialbox-kek.new").exists()
    assert (tmp / "units" / "trialbox-unseal.service").is_file()


def _stopped_then_rerun(tmp: Path, at: str, sig: str, scope: str) -> None:
    env, keys = _host(tmp)
    res = _seal(tmp, {**env, "STANDIN_AT": at, "STANDIN_SIG": sig, "STANDIN_SCOPE": scope})
    assert (tmp / "standin" / f"fired-{at}").exists(), res.stdout + res.stderr  # the signal was sent at that step
    # a signal exits with its own code (128 + its number); it never carries on to the next step
    assert res.returncode == 128 + getattr(signal, "SIG" + sig), res.stdout + res.stderr
    _keys_open(tmp, keys)
    assert not (tmp / "host" / "run" / "trialbox" / "kek.new").exists()  # the plain copy in /run is gone
    again = _seal(tmp, env)
    assert again.returncode == 0, again.stdout + again.stderr
    _sealed_and_done(tmp, keys)
    assert _violations(tmp) == ""


@pytest.mark.parametrize("scope", ["group", "shell"])
@pytest.mark.parametrize("sig", ["TERM", "HUP", "INT"])
def test_a_signal_during_keys_init_leaves_keys_that_open_and_a_rerun_completes(
    tmp_path: Path, sig: str, scope: str
) -> None:
    """The reviewer's case: the signal comes after a key is wrapped and before its plain file is removed."""
    _stopped_then_rerun(tmp_path, "during_init", sig, scope)


@pytest.mark.parametrize("scope", ["group", "shell"])
@pytest.mark.parametrize("at", ["before_seal", "after_seal", "after_place", "after_init"])
def test_a_kill_at_each_step_of_the_sealing_block(tmp_path: Path, at: str, scope: str) -> None:
    _stopped_then_rerun(tmp_path, at, "TERM", scope)


def test_the_invariant_holds_at_every_step_of_a_full_seal(tmp_path: Path) -> None:
    """At each step (before and after the seal, after the place, after each key's wrap, after keys init) every key is
    plain as it was or opens under the KEK of the credential in its final place."""
    env, keys = _host(tmp_path)
    res = _seal(tmp_path, env)
    assert res.returncode == 0, res.stdout + res.stderr
    assert _violations(tmp_path) == ""
    _sealed_and_done(tmp_path, keys)


def test_a_failed_seal_leaves_the_plain_keys_untouched(tmp_path: Path) -> None:
    env, keys = _host(tmp_path)
    (tmp_path / "standin" / "fail-seal").write_text("")
    res = _seal(tmp_path, env)
    assert res.returncode != 0 and "nothing was changed" in res.stderr
    sec = tmp_path / "secrets"
    assert not (sec / K.META_FILE).exists()
    for name, want in keys.items():
        assert (sec / name).read_bytes() == want and not K.wrapped_path(sec / name).exists()
    assert not list((tmp_path / "host").rglob("trialbox-kek*")) and not list((tmp_path / "host").rglob("kek.new"))


def test_a_credential_beside_wrapped_keys_without_kek_json_is_still_refused(tmp_path: Path) -> None:
    """A credential is reused only when no key is wrapped yet: kek.json lost from a sealed box stays a stop."""
    env, keys = _host(tmp_path)
    assert _seal(tmp_path, env).returncode == 0
    (tmp_path / "secrets" / K.META_FILE).unlink()
    res = _seal(tmp_path, env)
    assert res.returncode != 0 and "put kek.json back from the backup" in res.stderr
    _keys_open(tmp_path, keys)


def test_a_wrap_stopped_before_the_plain_file_went_is_finished_by_keys_wrap(tmp_path: Path) -> None:
    """tools.keys wrap: a key there plain and wrapped, the wrapped one opening to the plain one under this KEK (a run
    stopped between the two), is finished; one that does not open to it is still refused, and both are kept."""
    from tools import keys as tk

    sec = tmp_path / "secrets"
    sec.mkdir()
    kek = os.urandom(K.KEK_LEN)
    K.write_meta(sec, K.new_meta("file", kek))
    same, other = os.urandom(32), os.urandom(32)
    (sec / "site_hmac.key").write_bytes(same)
    K.store_key(sec / "site_hmac.key", same, kek)
    assert tk.wrap_plain(sec, kek)[0].startswith("site_hmac.key")
    assert not (sec / "site_hmac.key").exists()
    assert K.unwrap(kek, K.read_wrapped(sec / "site_hmac.key"), "site_hmac.key") == same
    (sec / "pid_map.key").write_bytes(other)
    K.store_key(sec / "pid_map.key", os.urandom(32), kek)
    with pytest.raises(K.KekError, match="plain and wrapped"):
        tk.wrap_plain(sec, kek)
    assert (sec / "pid_map.key").read_bytes() == other and K.wrapped_path(sec / "pid_map.key").exists()


def test_the_passphrase_path_after_a_ctrl_c_during_keys_init(tmp_path: Path) -> None:
    """The passphrase back end has no trap and its KEK comes again from the passphrase: a Ctrl-C during keys init loses
    nothing, and a re-run with the passphrase completes (the half-done wrap is finished)."""
    env, keys = _host(tmp_path)
    phrase = tmp_path / "kek.pass"
    phrase.write_text("a long synthetic phrase h111\n")
    phrase.chmod(0o600)
    env = {**env, "TB_KEK_BACKEND": "passphrase"}
    args = ["sh", str(SEAL), "--secrets", str(tmp_path / "secrets"), "--conf", str(tmp_path / "no-such.conf"),
            "--kek-passphrase-file", str(phrase), "--keep-kek-passphrase-file"]  # fmt: skip
    hit = {**env, "STANDIN_AT": "during_init", "STANDIN_SIG": "INT", "STANDIN_SCOPE": "group"}
    res = subprocess.run(args, capture_output=True, text=True, env=hit, check=False, start_new_session=True,
                         timeout=120)  # fmt: skip
    assert (tmp_path / "standin" / "fired-during_init").exists() and res.returncode != 0, res.stdout + res.stderr
    sec = tmp_path / "secrets"
    meta = K.read_meta(sec)
    assert meta is not None and meta["backend"] == "passphrase"
    kek = K.derive_from_passphrase("a long synthetic phrase h111", meta)
    for name, want in keys.items():
        p = sec / name
        assert (p.is_file() and p.read_bytes() == want) or K.unwrap(kek, K.read_wrapped(p), name) == want
    (tmp_path / "host" / "run" / "trialbox" / "kek").unlink(missing_ok=True)
    again = subprocess.run(args, capture_output=True, text=True, env=env, check=False, timeout=120)
    assert again.returncode == 0, again.stdout + again.stderr
    for name, want in keys.items():
        assert not (sec / name).exists() and K.unwrap(kek, K.read_wrapped(sec / name), name) == want


# review of #1457: a hook that holds a run at a named step until the test lets it go (1457-1)
WAIT = r"""
def hook(point):
    invariant(point)
    tag = os.environ.get("STANDIN_TAG", "")
    if os.environ.get("STANDIN_WAIT") == point:
        (D / f"at-{tag}-{point}").write_text("")
        while not (D / f"go-{tag}").exists():
            time.sleep(0.05)
"""


def _until(cond: Callable[[], bool], what: str, timeout: float = 60) -> None:
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, what
        time.sleep(0.05)


def test_two_runs_at_once_never_leave_keys_the_placed_credential_cannot_open(tmp_path: Path) -> None:
    """Review of #1457 (1457-1): a second run that started while the first had sealed its credential and not placed
    it shared kek.new: the first wrapped the keys under the second's KEK, placed its own credential and said done;
    after a reboot nothing opened them. The second run is now refused, and the keys open under the placed credential."""
    env, keys = _host(tmp_path)
    d = tmp_path / "standin"
    (d / "hook.py").write_text(HOOK + WAIT)
    argv = ["sh", str(SEAL), "--secrets", str(tmp_path / "secrets"), "--conf", str(tmp_path / "no-such.conf")]

    def start(tag: str, at: str) -> subprocess.Popen[str]:
        return subprocess.Popen(argv, env={**env, "STANDIN_TAG": tag, "STANDIN_WAIT": at}, text=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)  # fmt: skip

    first = start("A", "after_seal")
    _until((d / "at-A-after_seal").exists, "the first run never reached its seal")
    second = start("B", "before_seal")
    _until(lambda: (d / "at-B-before_seal").exists() or second.poll() is not None, "the second run hung")
    (d / "go-A").write_text("")
    assert first.wait(timeout=120) == 0
    (d / "go-B").write_text("")
    second.wait(timeout=120)
    _keys_open(tmp_path, keys)
    meta = K.read_meta(tmp_path / "secrets")
    assert meta is not None and meta["kek_id"] == K.kek_id(_cred(tmp_path).read_bytes())
    _sealed_and_done(tmp_path, keys)


def test_two_secrets_folders_on_one_host_never_leave_keys_the_credential_cannot_open(tmp_path: Path) -> None:
    """Review of #1457 (1457-1, the rest): kek.new and the credential belong to the host, the first lock to one secrets
    folder. A run for a second folder that started while the first had sealed and not placed shared kek.new: the first
    wrapped its keys under the second's KEK, placed its own credential and said done. One TPM seal at a time on a
    host now: the second is refused, and the first run's keys open under the placed credential."""
    env, keys = _host(tmp_path)
    d = tmp_path / "standin"
    (d / "hook.py").write_text(HOOK + WAIT)
    other = tmp_path / "secrets2"
    other.mkdir()
    for name in NAMES:
        (other / name).write_bytes(os.urandom(32))
        (other / name).chmod(0o600)

    def start(sec: Path, tag: str, at: str) -> subprocess.Popen[str]:
        argv = ["sh", str(SEAL), "--secrets", str(sec), "--conf", str(tmp_path / "no-such.conf")]
        return subprocess.Popen(argv, env={**env, "STANDIN_TAG": tag, "STANDIN_WAIT": at}, text=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)  # fmt: skip

    first = start(tmp_path / "secrets", "A", "after_seal")
    _until((d / "at-A-after_seal").exists, "the first run never reached its seal")
    second = start(other, "B", "before_seal")
    _until(lambda: (d / "at-B-before_seal").exists() or second.poll() is not None, "the second run hung")
    (d / "go-A").write_text("")
    assert first.wait(timeout=120) == 0
    (d / "go-B").write_text("")
    # review of #1457 (1457-10): the second is refused by the host lock and changes nothing of its own folder
    assert second.wait(timeout=120) == 1
    assert second.stderr is not None and "on this host holds" in second.stderr.read()
    assert not (other / K.META_FILE).exists() and all((other / n).is_file() for n in NAMES)
    _sealed_and_done(tmp_path, keys)


def test_a_seal_while_another_process_holds_the_secrets_folder_is_refused_and_changes_nothing(tmp_path: Path) -> None:
    """Review of #1457 (1457-10): the per-folder lock (a key command, or a seal by another back end) had no test once the
    host lock covered the TPM path: a seal while the folder is held is refused before anything is made."""
    import fcntl

    env, keys = _host(tmp_path)
    fd = os.open(tmp_path / "secrets", os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # as tools.keys rotate-kek holds it
        res = _seal(tmp_path, env)
    finally:
        os.close(fd)
    assert res.returncode == 1, res.stdout + res.stderr
    assert "or a key command holds" in res.stderr
    for name, want in keys.items():
        assert (tmp_path / "secrets" / name).read_bytes() == want
    assert not (tmp_path / "secrets" / K.META_FILE).exists() and not _cred(tmp_path).exists()


def _root_stand_ins(tmp: Path) -> Path:
    """`id -u` says root, `chown` records what it is asked, and `find` records its sweep, then runs: run as an ordinary
    user (CI) no file is root's, so the sweep finds nothing to hand over, and the sweep itself is what is shown. The
    secrets folder is the services' user's (uid 10001) when the test itself runs as root, as D-887 finds it on a box."""
    b, log = tmp / "bin", tmp / "chown.log"
    (b / "id").write_text('#!/bin/sh\n[ "$1" = -u ] && { echo 0; exit 0; }\nexec /usr/bin/id "$@"\n')
    (b / "chown").write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{log}"\n')
    (b / "find").write_text(f'#!/bin/sh\nprintf "find %s\\n" "$*" >> "{log}"\nexec /usr/bin/find "$@"\n')
    for f in ("id", "chown", "find"):
        (b / f).chmod(0o755)
    if os.geteuid() == 0:
        os.chown(tmp / "secrets", 10001, 10001)
    return log


def test_a_rerun_after_a_stop_hands_the_kek_and_the_new_files_to_the_services_user(tmp_path: Path) -> None:
    """Review of #1457 (1457-2): a re-run after a stop during keys init goes through the kek.json branch, which
    unseals the KEK from the credential and said done before D-887's hand-over: the runtime KEK and the files the runs
    made stayed root's, and the services (the secrets folder's owner) could not open them."""
    env, keys = _host(tmp_path)
    log = _root_stand_ins(tmp_path)
    res = _seal(tmp_path, {**env, "STANDIN_AT": "during_init", "STANDIN_SIG": "TERM", "STANDIN_SCOPE": "group"})
    assert res.returncode == 143, res.stdout + res.stderr
    log.unlink(missing_ok=True)
    again = _seal(tmp_path, env)
    assert again.returncode == 0, again.stdout + again.stderr
    _sealed_and_done(tmp_path, keys)
    asked = log.read_text() if log.is_file() else ""
    assert str(tmp_path / "host" / "run" / "trialbox" / "kek") in asked, "the re-run left the runtime KEK root's"
    # review of #1457 (1457-7): chown -h, never through a link
    sweep = f"find {tmp_path / 'secrets'} -maxdepth 1 -type f -user 0 -exec chown -h"
    assert sweep in asked, (
        "the re-run never handed the files it made (kek.json, the wrapped keys) to the services' user"
    )
    if os.geteuid() == 0:  # review of #1457 (1457-8); H-133 (integrator 7138572054): as root the files end the
        # services' user's (the key commands give them at the write; the sweep reaches any left root's: here `chown`
        # only records, so a file still root's must be one it was asked for), modes as written
        sec = tmp_path / "secrets"
        for f in (sec / K.META_FILE, *sorted(sec.glob("*.wrapped"))):
            assert os.stat(f).st_uid == 10001, f"the re-run left {f.name} root's"
        left = sorted(f for f in sec.iterdir() if f.is_file() and os.lstat(f).st_uid == 0)
        unreached = [f.name for f in left if str(f) not in asked]
        assert unreached == [], f"files left root's that the hand-over never reached: {unreached}"
        modes = {f.name: stat.S_IMODE(os.lstat(f).st_mode) for f in sec.iterdir() if f.is_file()}
        want = {name: 0o644 if name.endswith(".pub") else 0o600 for name in modes}
        assert modes == want, f"the hand-over changed a file's mode: { {k: oct(v) for k, v in modes.items()} }"


def test_a_plain_key_goes_only_once_its_wrapped_copy_is_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review of #1457 (1457-3): wrap_plain renamed the wrapped copy into place (an fsync of the file only) and removed
    the plain file with no fsync of the folder between: after a power cut the folder could hold neither name. Each
    plain file goes only after a folder fsync that follows its wrapped copy's rename (the H-111 branch's key too)."""
    from tools import keys as tk

    sec = tmp_path / "secrets"
    sec.mkdir()
    kek = os.urandom(K.KEK_LEN)
    K.write_meta(sec, K.new_meta("file", kek))
    for name in NAMES:
        (sec / name).write_bytes(os.urandom(32))
    # the first key wrap_plain takes was left plain and wrapped by a stopped run: no earlier fsync can stand for its own
    first = next(n for n in K.PROTECTED if n in NAMES)
    K.store_key(sec / first, (sec / first).read_bytes(), kek)
    events: list[str] = []
    real_fsync, real_replace, real_unlink = os.fsync, os.replace, Path.unlink
    here = sec.stat()

    def fsync(fd: int) -> None:
        st = os.fstat(fd)
        if stat.S_ISDIR(st.st_mode) and os.path.samestat(st, here):
            events.append("fsync-dir")
        real_fsync(fd)

    def replace(src: Any, dst: Any, *a: Any, **k: Any) -> None:
        events.append(f"replace:{Path(dst).name}")
        real_replace(src, dst, *a, **k)

    def unlink(self: Path, *a: Any, **k: Any) -> None:
        events.append(f"unlink:{self.name}")
        real_unlink(self, *a, **k)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(Path, "unlink", unlink)
    tk.wrap_plain(sec, kek)
    for name in NAMES:
        gone = events.index(f"unlink:{name}")
        placed = max((i for i, e in enumerate(events[:gone]) if e == f"replace:{name}.wrapped"), default=-1)
        assert "fsync-dir" in events[placed + 1 : gone], (name, events)


def test_the_kek_opened_from_the_credential_is_owner_only(tmp_path: Path) -> None:
    """Review of #1457 (1457-4): a re-run opens the placed credential to kek.new; the sealing tool writes its output
    with the caller's umask, so under umask 022 the plain KEK was 0644. The stand-in writes the way the tool does (a
    plain open of the output) and records the mode."""
    env, keys = _host(tmp_path)
    creds = tmp_path / "bin" / "systemd-creds"
    opened = 'decrypt) cat "$3" > "$4" && stat -c %a "$4" > "$STANDIN_DIR/opened-mode" ;;'
    creds.write_text(CREDS.replace('decrypt) cp "$3" "$4" ;;', opened))
    res = _seal(tmp_path, {**env, "STANDIN_AT": "after_place", "STANDIN_SIG": "TERM", "STANDIN_SCOPE": "group"})
    assert res.returncode == 143, res.stdout + res.stderr
    again = subprocess.run(
        ["sh", "-c", 'umask 022; exec sh "$@"', "sh", str(SEAL), "--secrets", str(tmp_path / "secrets"),
         "--conf", str(tmp_path / "no-such.conf")],
        capture_output=True, text=True, env=env, check=False, timeout=120,
    )  # fmt: skip
    assert again.returncode == 0, again.stdout + again.stderr
    _sealed_and_done(tmp_path, keys)
    assert (tmp_path / "standin" / "opened-mode").read_text().strip() == "600"


def test_a_second_signal_during_the_clean_up_leaves_no_plain_kek(tmp_path: Path) -> None:
    """Review of #1457 (1457-5): Ctrl-C twice, or a stop that sends TERM again, while the EXIT trap shreds kek.new: the
    TERM trap's exit cut the clean-up short and the shred was killed, so the plain KEK stayed in /run (and a re-run,
    through the kek.json branch, never removes it). A stand-in shred has TERM sent twice to the group as it starts."""
    env, keys = _host(tmp_path)
    d = tmp_path / "standin"
    (d / "sender.py").write_text(
        "import os, signal, sys, time\n"
        "for _ in range(2):\n"
        "    try:\n        os.killpg(int(sys.argv[1]), signal.SIGTERM)\n"
        "    except ProcessLookupError:\n        break\n"
        "    time.sleep(0.15)\n"
    )
    shred = tmp_path / "bin" / "shred"
    shred.write_text(
        "#!/bin/sh\n"
        '"$STANDIN_PY" -c \'import os, subprocess, sys; subprocess.Popen([sys.executable, sys.argv[1], '
        'str(os.getpgid(0))], start_new_session=True)\' "$STANDIN_DIR/sender.py"\n'
        'sleep 1\nexec /usr/bin/shred "$@"\n'
    )
    shred.chmod(0o755)
    _seal(tmp_path, env)
    time.sleep(1)
    _keys_open(tmp_path, keys)
    assert not (tmp_path / "host" / "run" / "trialbox" / "kek.new").exists(), "the plain KEK copy stayed in /run"


def test_the_kek_opened_from_the_credential_is_never_written_through_a_link(tmp_path: Path) -> None:
    """Review of #1457 (1457-4, its untested half): a name already at kek.new (a link left there) is removed before
    the credential is opened, so the plain KEK is never written through it to where the link points."""
    env, keys = _host(tmp_path)
    # the stand-in notes a link at its output; the evidence would not last: the clean-up's shred empties the link's
    # target through the link before it removes it
    creds = tmp_path / "bin" / "systemd-creds"
    seen = 'decrypt) [ -L "$4" ] && : > "$STANDIN_DIR/through-a-link"; cp "$3" "$4" ;;'
    creds.write_text(CREDS.replace('decrypt) cp "$3" "$4" ;;', seen))
    res = _seal(tmp_path, {**env, "STANDIN_AT": "after_place", "STANDIN_SIG": "TERM", "STANDIN_SCOPE": "group"})
    assert res.returncode == 143, res.stdout + res.stderr
    target = tmp_path / "elsewhere"
    target.write_bytes(b"")
    (tmp_path / "host" / "run" / "trialbox" / "kek.new").symlink_to(target)
    again = _seal(tmp_path, env)
    assert again.returncode == 0, again.stdout + again.stderr
    _sealed_and_done(tmp_path, keys)
    assert not (tmp_path / "standin" / "through-a-link").exists(), "the credential was opened through the link"
    assert target.read_bytes() == b""


def test_a_seal_held_before_the_host_lock_never_moves_a_new_credential_over_a_placed_one(tmp_path: Path) -> None:
    """Review of #1457 (1457-11): the credential is looked for before the host lock is taken. A seal for a second
    folder held there (stopped, or slow) while the first seal ran to its end then took the lock, sealed a KEK of its
    own and moved it over the first's credential: the first folder's keys opened under no credential, and both runs
    said done. The second is now refused under the lock, and the first's credential stays."""
    env, keys = _host(tmp_path)
    d = tmp_path / "standin"
    other = tmp_path / "secrets2"
    other.mkdir()
    for name in NAMES:
        (other / name).write_bytes(os.urandom(32))
        (other / name).chmod(0o600)
    held = tmp_path / "bin-held"
    held.mkdir()
    # the second run's mkdir (in arm, after the credential was looked for, before the lock) waits for a go
    (held / "mkdir").write_text(
        '#!/bin/sh\n: > "$STANDIN_DIR/held"\nwhile [ ! -e "$STANDIN_DIR/go-held" ]; do sleep 0.05; done\n'
        'exec /bin/mkdir "$@"\n'
    )
    (held / "mkdir").chmod(0o755)
    argv = ["sh", str(SEAL), "--secrets", str(other), "--conf", str(tmp_path / "no-such.conf")]
    second = subprocess.Popen(argv, env={**env, "PATH": f"{held}:{env['PATH']}"}, text=True,
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)  # fmt: skip
    _until((d / "held").exists, "the second run never reached its lock")
    first = _seal(tmp_path, env)
    assert first.returncode == 0, first.stdout + first.stderr
    kek = _cred(tmp_path).read_bytes()
    (d / "go-held").write_text("")
    assert second.wait(timeout=120) == 1
    assert _cred(tmp_path).read_bytes() == kek, "a new credential was moved over the placed one"
    _sealed_and_done(tmp_path, keys)
    assert not (other / K.META_FILE).exists() and all((other / n).is_file() for n in NAMES)


def test_a_fresh_seal_never_writes_or_shreds_the_kek_through_a_link(tmp_path: Path) -> None:
    """Review of #1457 (1457-9): /run/trialbox is handed to the services' user. A link at kek.new before a fresh seal
    had the plain KEK written through it, and a link put there during the run had the clean-up's shred empty the file
    it points to. A name there is now removed first, and a link is never shredded through."""
    env, keys = _host(tmp_path)
    creds = tmp_path / "bin" / "systemd-creds"
    seen = 'encrypt)\n    [ -L "$4" ] && : > "$STANDIN_DIR/through-a-link";'
    creds.write_text(CREDS.replace("encrypt)", seen, 1))
    run = tmp_path / "host" / "run" / "trialbox"
    run.mkdir(parents=True)
    before, during = tmp_path / "before", tmp_path / "during"
    for f in (before, during):
        f.write_bytes(b"kept\n")
    (run / "kek.new").symlink_to(before)
    # during the run: the stand-in python3 puts a link at kek.new when the keys are checked (after the unseal)
    py = tmp_path / "standin" / "py_standin.py"
    swap = (
        'if args[:3] == ["-m", "tools.keys", "check"]:\n'
        f"    n = Path({str(run / 'kek.new')!r})\n"
        "    n.unlink(missing_ok=True)\n"
        f"    n.symlink_to({str(during)!r})\n"
    )
    py.write_text(PY.replace("os.execv(real", "from pathlib import Path\n" + swap + "os.execv(real", 1))
    res = _seal(tmp_path, env)
    assert res.returncode == 0, res.stdout + res.stderr
    _sealed_and_done(tmp_path, keys)
    assert not (tmp_path / "standin" / "through-a-link").exists(), "the new KEK was written through a link"
    assert before.read_bytes() == b"kept\n" and during.read_bytes() == b"kept\n", "a file was shredded through a link"
