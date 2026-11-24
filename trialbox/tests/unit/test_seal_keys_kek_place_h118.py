"""H-118 (review of #1457, 1457-6; the integrator's ruling 7125021924): no caller's TB_KEK_FILE decides where the
unsealed KEK goes.

deploy/hardening/seal_keys.sh took the place of the unsealed KEK from the caller's TB_KEK_FILE: a value such as
/etc/trialbox.kek wrote the plain KEK to persistent disk, and D-887's hand-over then gave that folder (/etc) to the
services' user. The place is now fixed: the box's own (/run/trialbox/kek, a tmpfs), the one the boot unseal unit writes
and the services read. A caller's TB_KEK_FILE is not used, and one line says so.

A host root of its own (TB_HOST_ROOT) and a stand-in sealing tool whose "sealed" credential is a copy of the KEK. The
keys are synthetic. No TPM is used.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from tb_common import kek as K

ROOT = Path(__file__).resolve().parents[2]
SEAL = ROOT / "deploy" / "hardening" / "seal_keys.sh"
NAMES = ("site_hmac.key", "pid_map.key")
PHRASE = "a long synthetic phrase h118"  # synthetic

pytestmark = pytest.mark.nodb

CREDS = 'case "$1" in has-tpm2) exit 0 ;; encrypt) cp "$4" "$5" ;; decrypt) cp "$3" "$4" ;; *) exit 2 ;; esac\n'


def _host(tmp: Path, backend: str) -> tuple[dict[str, str], dict[str, bytes], Path]:
    """A box: plain keys, /dev/tpmrm0, the stand-in sealing tool, and a caller's TB_KEK_FILE in a folder of its own."""
    hr = tmp / "host"
    (hr / "dev").mkdir(parents=True)
    (hr / "dev" / "tpmrm0").write_text("")
    sec = tmp / "secrets"
    sec.mkdir()
    keys = {name: os.urandom(32) for name in NAMES}  # synthetic
    for name, key in keys.items():
        (sec / name).write_bytes(key)
        (sec / name).chmod(0o600)
    b = tmp / "bin"
    b.mkdir()
    (b / "systemd-creds").write_text("#!/bin/sh\n" + CREDS)
    (b / "systemd-creds").chmod(0o755)
    callers = tmp / "callers-folder"
    callers.mkdir()
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith(("TB_", "PYTHON"))},
        "PATH": f"{b}:{Path(sys.executable).parent}:/usr/bin:/bin",
        "TB_HOST_ROOT": str(hr),
        "TB_SYSTEMD": "0",
        "TB_KEK_BACKEND": backend,
        "TB_KEK_FILE": str(callers / "kek"),  # the caller's: never where the KEK goes
    }
    return env, keys, callers


def _seal(tmp: Path, env: dict[str, str], *more: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(SEAL), "--secrets", str(tmp / "secrets"), "--conf", str(tmp / "no-such.conf"), *more],
        capture_output=True, text=True, env=env, check=False, timeout=120,
    )  # fmt: skip


def _phrase(tmp: Path) -> str:
    f = tmp / "kek.pass"
    f.write_text(PHRASE + "\n", encoding="utf-8")
    f.chmod(0o600)
    return str(f)


def _the_box_place(tmp: Path) -> Path:
    return tmp / "host" / "run" / "trialbox" / "kek"


def _opens(tmp: Path, keys: dict[str, bytes], kek: bytes) -> None:
    for name, want in keys.items():
        assert K.unwrap(kek, K.read_wrapped(tmp / "secrets" / name), name) == want


@pytest.mark.parametrize("backend", ["tpm", "passphrase"])
def test_a_callers_kek_file_never_decides_where_the_unsealed_kek_goes(tmp_path: Path, backend: str) -> None:
    env, keys, callers = _host(tmp_path, backend)
    more = ("--kek-passphrase-file", _phrase(tmp_path)) if backend == "passphrase" else ()
    res = _seal(tmp_path, env, *more)
    assert res.returncode == 0, res.stdout + res.stderr
    assert not list(callers.iterdir()), "the unsealed KEK went where the caller's TB_KEK_FILE said"
    kek = _the_box_place(tmp_path).read_bytes()
    assert len(kek) == K.KEK_LEN and _the_box_place(tmp_path).stat().st_mode & 0o077 == 0
    _opens(tmp_path, keys, kek)
    assert f"TB_KEK_FILE in the environment ({callers / 'kek'}) is not used" in res.stdout


def test_a_rerun_unseals_to_the_box_place_too(tmp_path: Path) -> None:
    """The kek.json branch (a re-run after a restart): the KEK opened from the passphrase goes to the box's place."""
    env, keys, callers = _host(tmp_path, "passphrase")
    assert _seal(tmp_path, env, "--kek-passphrase-file", _phrase(tmp_path)).returncode == 0
    _the_box_place(tmp_path).unlink()  # a restart since: the tmpfs is empty
    res = _seal(tmp_path, env, "--kek-passphrase-file", _phrase(tmp_path))
    assert res.returncode == 0, res.stdout + res.stderr
    assert not list(callers.iterdir())
    _opens(tmp_path, keys, _the_box_place(tmp_path).read_bytes())


def test_no_callers_folder_is_handed_to_the_services_user(tmp_path: Path) -> None:
    """D-887's hand-over gives the KEK's folder to the secrets folder's owner: only ever the box's own /run folder.
    Stand-ins: `id -u` says root, `chown` records what it is asked."""
    env, _, callers = _host(tmp_path, "tpm")
    b, log = tmp_path / "bin", tmp_path / "chown.log"
    (b / "id").write_text('#!/bin/sh\n[ "$1" = -u ] && { echo 0; exit 0; }\nexec /usr/bin/id "$@"\n')
    (b / "chown").write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{log}"\n')
    for f in ("id", "chown"):
        (b / f).chmod(0o755)
    if os.geteuid() == 0:
        os.chown(tmp_path / "secrets", 10001, 10001)
    res = _seal(tmp_path, env)
    assert res.returncode == 0, res.stdout + res.stderr
    asked = log.read_text().split()
    assert str(_the_box_place(tmp_path)) in asked and str(_the_box_place(tmp_path).parent) in asked
    assert not [a for a in asked if a.startswith(str(callers))], asked


# ------------------------------------------------------------------- the plain KEK's own folder (#1457's review, 1457-9)
SEEN = (
    'case "$1" in has-tpm2) exit 0 ;;\n'
    '  encrypt) stat -c "%n %u %a" "$(dirname "$4")" >> "$SEEN_LOG"; cp "$4" "$5" ;;\n'
    '  decrypt) cp "$3" "$4" ;; *) exit 2 ;; esac\n'
)


def test_the_plain_kek_is_made_in_a_folder_of_its_own_never_handed_over(tmp_path: Path) -> None:
    """The plain KEK (kek.new) was made in /run/trialbox, the folder D-887 hands to the services' user, where a name
    can be swapped for a link. It is made in /run/trialbox-seal: this run's, mode 0700, and never handed over."""
    env, keys, _ = _host(tmp_path, "tpm")
    (tmp_path / "bin" / "systemd-creds").write_text("#!/bin/sh\n" + SEEN)
    b, log = tmp_path / "bin", tmp_path / "chown.log"
    (b / "id").write_text('#!/bin/sh\n[ "$1" = -u ] && { echo 0; exit 0; }\nexec /usr/bin/id "$@"\n')
    (b / "chown").write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{log}"\n')
    for f in ("id", "chown"):
        (b / f).chmod(0o755)
    if os.geteuid() == 0:
        os.chown(tmp_path / "secrets", 10001, 10001)
    seen = tmp_path / "seen.log"
    res = _seal(tmp_path, {**env, "SEEN_LOG": str(seen)})
    assert res.returncode == 0, res.stdout + res.stderr
    folder = tmp_path / "host" / "run" / "trialbox-seal"
    assert seen.read_text().split() == [str(folder), str(os.geteuid()), "700"]
    assert not list((tmp_path / "host").rglob("kek.new"))
    assert str(folder) not in log.read_text(), "the plain KEK's folder was handed to the services' user"
    _opens(tmp_path, keys, _the_box_place(tmp_path).read_bytes())


@pytest.mark.parametrize("what", ["a link", "open to others", "another user's"])
def test_a_seal_folder_that_is_not_this_runs_own_is_refused_and_nothing_changes(tmp_path: Path, what: str) -> None:
    env, keys, _ = _host(tmp_path, "tpm")
    folder = tmp_path / "host" / "run" / "trialbox-seal"
    folder.parent.mkdir(parents=True)
    if what == "a link":
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir(mode=0o700)
        folder.symlink_to(elsewhere)
    elif what == "open to others":
        folder.mkdir()
        folder.chmod(0o755)
    else:
        # mode 0700 but another user's: a stand-in stat says so (an ordinary user cannot make one)
        folder.mkdir(mode=0o700)
        folder.chmod(0o700)
        stat = tmp_path / "bin" / "stat"
        stat.write_text(
            f'#!/bin/sh\nif [ "$3" = "{folder}" ]; then\n'
            '  case "$2" in %u:%a) echo 4242:700 ;; %u) echo 4242 ;; %a) echo 700 ;; *) exec /usr/bin/stat "$@" ;; esac\n'
            '  exit 0\nfi\nexec /usr/bin/stat "$@"\n'
        )
        stat.chmod(0o755)
    res = _seal(tmp_path, env)
    assert res.returncode == 1 and "is not a folder only this user can open" in res.stderr, res.stdout + res.stderr
    sec = tmp_path / "secrets"
    for name, want in keys.items():
        assert (sec / name).read_bytes() == want and not K.wrapped_path(sec / name).exists()
    assert not (sec / K.META_FILE).exists() and not list((tmp_path / "host").rglob("trialbox-kek*"))
    assert not list(tmp_path.rglob("kek.new"))


def test_a_link_at_the_old_place_is_never_written_through(tmp_path: Path) -> None:
    """H-118 (ruling 7138516776): kek.new used to be made in /run/trialbox, the folder handed to the services' user. A
    link left at that old name is neither written nor shredded through by a seal."""
    env, keys, _ = _host(tmp_path, "tpm")
    old = tmp_path / "host" / "run" / "trialbox"
    old.mkdir(parents=True)
    target = tmp_path / "elsewhere"
    target.write_bytes(b"kept\n")
    (old / "kek.new").symlink_to(target)
    res = _seal(tmp_path, env)
    assert res.returncode == 0, res.stdout + res.stderr
    assert target.read_bytes() == b"kept\n", "the plain KEK was written or shredded through the old name"
    assert (old / "kek.new").is_symlink()  # untouched: the seal no longer uses that name
    _opens(tmp_path, keys, _the_box_place(tmp_path).read_bytes())


def test_a_refused_seal_folder_removes_nothing_through_it(tmp_path: Path) -> None:
    """Review of #1482 (1482-2): the folder check runs before the clean-up trap is set, so a refused folder (here a
    link to another folder that holds a file of that name) has nothing removed or shredded through it."""
    env, _, _ = _host(tmp_path, "tpm")
    folder = tmp_path / "host" / "run" / "trialbox-seal"
    folder.parent.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    (elsewhere / "kek.new").write_bytes(b"someone else's file\n")
    folder.symlink_to(elsewhere)
    res = _seal(tmp_path, env)
    assert res.returncode == 1 and "is not a folder only this user can open" in res.stderr, res.stdout + res.stderr
    kept = elsewhere / "kek.new"
    assert kept.is_file() and kept.read_bytes() == b"someone else's file\n", "the clean-up reached through the link"
