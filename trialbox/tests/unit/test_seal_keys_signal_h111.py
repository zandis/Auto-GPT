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
import subprocess
import sys
from pathlib import Path

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
