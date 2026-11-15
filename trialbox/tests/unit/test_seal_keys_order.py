"""D-836: the site keys are wrapped only under a KEK that is sealed already; a host that cannot seal is told the fix.

deploy/hardening/seal_keys.sh wrapped the keys and wrote kek.json (tools.keys init) before it sealed the KEK with
systemd-creds, and its trap shredded the only plain copy: a failed seal left a half-sealed box whose keys no one
could open. It also tested only that systemd-creds is on PATH and a /dev/tpm* node exists, not that the TPM is usable
(`systemd-creds has-tpm2`, the TSS2 libraries). The KEK back end can now be chosen with TB_KEK_BACKEND alone: a
hardening.conf written only for it also ran hardening/apply.sh all (the firewall and SSH). The passphrase path runs
here end to end."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from tb_common import kek as K

ROOT = Path(__file__).resolve().parents[2]
SEAL = ROOT / "deploy" / "hardening" / "seal_keys.sh"

pytestmark = pytest.mark.nodb


def _host(tmp: Path, creds: str | None, tpm: bool = True) -> dict[str, str]:
    """A host root of its own: a secrets folder with two plain keys, /dev/tpmrm0 when ``tpm``, and a stand-in
    systemd-creds whose shell body is ``creds`` (None: not installed)."""
    hr = tmp / "host"
    (hr / "dev").mkdir(parents=True)
    if tpm:
        (hr / "dev" / "tpmrm0").write_text("")
    sec = tmp / "secrets"
    sec.mkdir()
    for name in ("site_hmac.key", "pid_map.key"):
        (sec / name).write_bytes(os.urandom(32))
    bindir = tmp / "bin"
    bindir.mkdir()
    if creds is not None:
        f = bindir / "systemd-creds"
        f.write_text("#!/bin/sh\n" + creds, encoding="utf-8")
        f.chmod(0o755)
    return {
        **{k: v for k, v in os.environ.items() if not k.startswith("TB_")},
        "PATH": f"{bindir}:{Path(sys.executable).parent}:/usr/bin:/bin",
        "TB_HOST_ROOT": str(hr),
        "TB_SYSTEMD": "0",
        "TB_KEK_FILE": str(tmp / "kek.runtime"),
    }


def _seal(tmp: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(SEAL), "--secrets", str(tmp / "secrets"), "--conf", str(tmp / "no-such.conf")],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _untouched(tmp: Path) -> None:
    sec = tmp / "secrets"
    assert not (sec / K.META_FILE).exists()
    assert (sec / "site_hmac.key").is_file() and (sec / "pid_map.key").is_file()  # still plain, never wrapped
    assert not list((tmp / "host").rglob("trialbox-kek*"))


SEAL_OK = 'case "$1" in has-tpm2) exit 0 ;; encrypt) cp "$4" "$5" ;; esac\n'


def test_a_failed_seal_changes_nothing(tmp_path: Path) -> None:
    env = _host(
        tmp_path, 'case "$1" in has-tpm2) exit 0 ;; encrypt) echo "TPM2 operation failed" >&2; exit 1 ;; esac\n'
    )
    res = _seal(tmp_path, {**env, "TB_KEK_BACKEND": "tpm"})
    assert res.returncode != 0
    assert "nothing was changed" in res.stderr
    _untouched(tmp_path)


def test_an_unusable_tpm_is_found_first_and_the_fix_is_named(tmp_path: Path) -> None:
    env = _host(tmp_path, 'case "$1" in has-tpm2) echo "partial" ; exit 1 ;; esac\n')
    res = _seal(tmp_path, env)
    assert res.returncode != 0
    assert "has-tpm2" in res.stderr
    assert "TB_KEK_BACKEND=passphrase" in res.stderr and "TB_KEK_PASSPHRASE" in res.stderr
    _untouched(tmp_path)


def test_no_systemd_creds_names_the_fix_too(tmp_path: Path) -> None:
    res = _seal(tmp_path, _host(tmp_path, None))
    assert res.returncode != 0 and "TB_KEK_BACKEND=passphrase" in res.stderr
    _untouched(tmp_path)


def test_the_tpm_path_seals_then_wraps(tmp_path: Path) -> None:
    res = _seal(tmp_path, _host(tmp_path, SEAL_OK))
    assert res.returncode == 0, res.stderr
    sec = tmp_path / "secrets"
    assert (sec / K.META_FILE).is_file()
    assert not (sec / "site_hmac.key").exists() and K.wrapped_path(sec / "site_hmac.key").exists()
    cred = tmp_path / "host" / "etc" / "credstore.encrypted" / "trialbox-kek"
    assert cred.is_file() and not cred.with_name("trialbox-kek.new").exists()
    assert (tmp_path / "kek.runtime").read_bytes() == cred.read_bytes()  # the stand-in "sealed" by copying
    assert not list((tmp_path / "host" / "run").rglob("kek.new"))  # the plain copy is gone


def test_the_passphrase_path_without_a_hardening_conf(tmp_path: Path) -> None:
    env = _host(tmp_path, None, tpm=False)
    res = _seal(tmp_path, {**env, "TB_KEK_BACKEND": "passphrase", "TB_KEK_PASSPHRASE": "a long synthetic phrase"})
    assert res.returncode == 0, res.stderr
    sec = tmp_path / "secrets"
    meta = K.read_meta(sec)
    assert meta is not None and meta["backend"] == "passphrase"
    assert K.wrapped_path(sec / "pid_map.key").exists() and not (sec / "pid_map.key").exists()
    assert (tmp_path / "kek.runtime").stat().st_size == K.KEK_LEN


def test_keys_init_takes_a_kek_that_exists(tmp_path: Path) -> None:
    from tools import keys

    sec = tmp_path / "secrets"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(os.urandom(32))
    kek = tmp_path / "kek.bin"
    kek.write_bytes(os.urandom(K.KEK_LEN))
    assert keys.main(["init", "--backend", "file", "--secrets", str(sec), "--kek-in", str(kek)]) == 0
    assert K.unwrap(kek.read_bytes(), K.read_wrapped(sec / "site_hmac.key"), "site_hmac.key")
    short = tmp_path / "short.bin"
    short.write_bytes(b"x" * 8)
    sec2 = tmp_path / "s2"
    sec2.mkdir()
    assert keys.main(["init", "--backend", "file", "--secrets", str(sec2), "--kek-in", str(short)]) != 0
    assert not (sec2 / K.META_FILE).exists()


def test_the_host_check_asks_has_tpm2_and_the_installer_names_the_fix() -> None:
    check = (ROOT / "deploy" / "check_host.sh").read_text(encoding="utf-8")
    assert "systemd-creds has-tpm2" in check and "TB_KEK_BACKEND=passphrase" in check
    install = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    seal = install[install.index("sh deploy/hardening/seal_keys.sh") :]
    assert "TB_KEK_BACKEND=passphrase" in seal[: seal.index("\n", seal.index("|| die"))]


def test_the_kek_backend_setting_is_declared() -> None:
    from tb_common.config import DECLARED

    assert "TB_KEK_BACKEND" in DECLARED
