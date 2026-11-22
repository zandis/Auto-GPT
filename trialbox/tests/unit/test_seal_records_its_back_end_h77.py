"""H-77 (install-test F-22): the box records which KEK back end sealed its site keys, as the seal step ran it.

After an install nothing on the box said which back end sealed the keys: seal_keys.sh chose it (tpm, then
hardening.conf's KEK_BACKEND, then TB_KEK_BACKEND) and said it only in a log line, and under tpm the key tool's own
kek.json says ``file``. seal_keys.sh now writes ``kek-backend`` beside the keys once its last step has passed, and
install.sh copies that word into deploy/.env (TB_KEK_BACKEND, where the host check reads it); it never works the back
end out itself. A dry run, a TPM that cannot seal and a box whose KEK exists already write no record."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from tb_common import kek as K

ROOT = Path(__file__).resolve().parents[2]
SEAL = ROOT / "deploy" / "hardening" / "seal_keys.sh"
INSTALL = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
PHRASE = "synthetic-h77-phrase-not-real"
SEAL_OK = 'case "$1" in has-tpm2) exit 0 ;; encrypt) cp "$4" "$5" ;; esac\n'
SEAL_FAILS = 'case "$1" in has-tpm2) exit 0 ;; encrypt) echo "TPM2 operation failed" >&2; exit 1 ;; esac\n'

pytestmark = pytest.mark.nodb


def _host(tmp: Path, creds: str | None = SEAL_OK, tpm: bool = True) -> dict[str, str]:
    """A host root of its own (the layout test_seal_keys_order.py uses): two plain keys, /dev/tpmrm0 when ``tpm``,
    a stand-in systemd-creds whose shell body is ``creds`` (None: not installed)."""
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
        "TB_KEK_PASSPHRASE": PHRASE,
    }


def _conf(tmp: Path, backend: str) -> Path:
    shares = tmp / "media"
    shares.mkdir(exist_ok=True)
    conf = tmp / "hardening.conf"
    conf.write_text(f"KEK_BACKEND={backend}\nKEK_SHARES_OUT={shares}\n", encoding="utf-8")
    return conf


def _seal(tmp: Path, env: dict[str, str], conf: Path | None = None, *extra: str) -> subprocess.CompletedProcess[str]:
    args = ["sh", str(SEAL), "--secrets", str(tmp / "secrets"), "--conf", str(conf or tmp / "no-such.conf"), *extra]
    return subprocess.run(args, capture_output=True, text=True, env=env, check=False)


def _record(tmp: Path) -> Path:
    return tmp / "secrets" / "kek-backend"


def _no_record(tmp: Path) -> None:
    assert not _record(tmp).exists()
    assert not (tmp / "secrets" / "kek-backend.tmp").exists()


@pytest.mark.parametrize("backend", ["tpm", "shamir", "passphrase"])
def test_each_back_end_records_its_own_name(tmp_path: Path, backend: str) -> None:
    res = _seal(tmp_path, _host(tmp_path), _conf(tmp_path, backend))
    assert res.returncode == 0, res.stderr
    rec = _record(tmp_path)
    assert rec.read_text(encoding="utf-8") == backend + "\n"
    assert rec.stat().st_mode & 0o777 == 0o600  # no wider than the keys beside it
    assert (tmp_path / "secrets" / K.META_FILE).stat().st_mode & 0o077 == 0
    assert not (tmp_path / "secrets" / "kek-backend.tmp").exists()
    assert f"the KEK back end is recorded: {backend}" in res.stdout


def test_a_tpm_that_cannot_seal_records_nothing_and_keeps_an_earlier_record(tmp_path: Path) -> None:
    env = _host(tmp_path, SEAL_FAILS)
    _record(tmp_path).write_text("shamir\n", encoding="utf-8")  # an earlier record, whatever it said
    res = _seal(tmp_path, {**env, "TB_KEK_BACKEND": "tpm"})
    assert res.returncode != 0 and "nothing was changed" in res.stderr
    assert not (tmp_path / "secrets" / K.META_FILE).exists()
    assert (tmp_path / "secrets" / "site_hmac.key").is_file()  # still plain
    assert _record(tmp_path).read_text(encoding="utf-8") == "shamir\n"
    assert not (tmp_path / "secrets" / "kek-backend.tmp").exists()


@pytest.mark.parametrize("creds", ['case "$1" in has-tpm2) echo partial; exit 1 ;; esac\n', None])
def test_an_unusable_or_missing_tpm_records_nothing(tmp_path: Path, creds: str | None) -> None:
    res = _seal(tmp_path, _host(tmp_path, creds), _conf(tmp_path, "tpm"))
    assert res.returncode != 0
    _no_record(tmp_path)


def test_the_environment_overrides_hardening_conf_and_the_record_says_what_ran(tmp_path: Path) -> None:
    res = _seal(tmp_path, {**_host(tmp_path), "TB_KEK_BACKEND": "passphrase"}, _conf(tmp_path, "shamir"))
    assert res.returncode == 0, res.stderr
    meta = K.read_meta(tmp_path / "secrets")
    assert meta is not None and meta["backend"] == "passphrase"
    assert _record(tmp_path).read_text(encoding="utf-8") == "passphrase\n"
    assert not list((tmp_path / "media").iterdir())  # shamir never ran


def test_the_environment_overrides_the_other_way_too(tmp_path: Path) -> None:
    res = _seal(tmp_path, {**_host(tmp_path), "TB_KEK_BACKEND": "tpm"}, _conf(tmp_path, "passphrase"))
    assert res.returncode == 0, res.stderr
    assert _record(tmp_path).read_text(encoding="utf-8") == "tpm\n"
    assert (tmp_path / "host" / "etc" / "credstore.encrypted" / "trialbox-kek").is_file()


@pytest.mark.parametrize("backend", ["tpm", "shamir", "passphrase"])
def test_a_dry_run_records_nothing(tmp_path: Path, backend: str) -> None:
    res = _seal(tmp_path, _host(tmp_path), _conf(tmp_path, backend), "--dry-run")
    assert res.returncode == 0, res.stderr
    _no_record(tmp_path)
    assert not (tmp_path / "secrets" / K.META_FILE).exists()


def test_a_box_with_a_kek_already_keeps_its_record_as_it_was(tmp_path: Path) -> None:
    """A re-run: the script cannot tell an existing seal's back end (tpm's kek.json says file), so it writes none."""
    env = _host(tmp_path)
    assert _seal(tmp_path, {**env, "TB_KEK_BACKEND": "passphrase"}).returncode == 0
    res = _seal(tmp_path, {**env, "TB_KEK_BACKEND": "tpm"})  # another back end asked on the re-run
    assert res.returncode == 0, res.stderr
    assert "the KEK exists" in res.stdout
    assert _record(tmp_path).read_text(encoding="utf-8") == "passphrase\n"
    _record(tmp_path).unlink()
    assert _seal(tmp_path, {**env, "TB_KEK_BACKEND": "tpm"}).returncode == 0
    _no_record(tmp_path)  # none is guessed for an existing seal


# ---- install.sh: the seal block as it stands, run with the real seal_keys.sh in a folder laid out as an installer's
SEAL_BLOCK = INSTALL[
    INSTALL.index('HB_CONF="$ROOT/deploy/site/hardening.conf"') : INSTALL.index("# D-378: the services")
]


def _install(
    tmp: Path, env: dict[str, str], conf_text: str | None, profile: str = "standard", site: str = "VALIDATION"
) -> subprocess.CompletedProcess[str]:
    (tmp / "deploy" / "site").mkdir(parents=True)
    (tmp / "deploy" / "hardening").symlink_to(ROOT / "deploy" / "hardening")
    (tmp / "tools").symlink_to(ROOT / "tools")
    (tmp / "libs").symlink_to(ROOT / "libs")
    (tmp / "deploy" / ".env").write_text("TB_ENV=VALIDATION\n", encoding="utf-8")
    if conf_text is not None:
        (tmp / "deploy" / "site" / "hardening.conf").write_text(conf_text, encoding="utf-8")
    script = (
        "set -euo pipefail\n"
        f'ROOT="{tmp}"\ncd "$ROOT"\nHOST_PROFILE={profile}\nTB_ENV_SITE={site}\nIMAGE_PY=unused\n'
        'say() { echo "==> $*"; }\n'
        'die() { echo "install: $*" >&2; exit 1; }\n'
        "id() { echo 0; }\n"  # the block's root check; CI runs non-root
        'envset() { sed -i "/^$1=/d" deploy/.env && printf \'%s=%s\\n\' "$1" "$2" >> deploy/.env; }\n'
        f"{SEAL_BLOCK}\n"
    )
    return subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=False,
        env={**env, "TB_SECRETS_HOST_DIR": str(tmp / "secrets")},
    )  # fmt: skip


def _env_value(tmp: Path) -> list[str]:
    lines = (tmp / "deploy" / ".env").read_text(encoding="utf-8").splitlines()
    return [ln.removeprefix("TB_KEK_BACKEND=") for ln in lines if ln.startswith("TB_KEK_BACKEND=")]


@pytest.mark.parametrize(("conf", "asked"), [("tpm", "passphrase"), ("passphrase", "tpm"), ("shamir", None)])
def test_install_copies_the_back_end_seal_keys_recorded(tmp_path: Path, conf: str, asked: str | None) -> None:
    """THE INVARIANT: the back end deploy/.env names is the one the sealing step ran, never one worked out again.
    hardening.conf says one, the environment another; the installer's line and deploy/.env equal seal_keys.sh's
    record, which equals what sealed the keys."""
    env = _host(tmp_path)
    if asked:
        env["TB_KEK_BACKEND"] = asked
    (tmp_path / "media").mkdir()
    res = _install(tmp_path, env, f"KEK_BACKEND={conf}\nKEK_SHARES_OUT={tmp_path / 'media'}\n")
    assert res.returncode == 0, res.stderr
    ran = asked or conf
    recorded = _record(tmp_path).read_text(encoding="utf-8").strip()
    assert recorded == ran
    assert _env_value(tmp_path) == [recorded]
    assert f"the KEK back end that sealed the keys: {recorded} " in res.stdout
    cred = tmp_path / "host" / "etc" / "credstore.encrypted" / "trialbox-kek"
    meta = K.read_meta(tmp_path / "secrets")
    assert meta is not None
    assert cred.is_file() == (ran == "tpm")  # what sealed the keys is what the record says
    assert meta["backend"] == ("file" if ran == "tpm" else ran)


def test_install_invents_no_back_end_when_seal_keys_records_none(tmp_path: Path) -> None:
    """A box sealed before the record (kek.json there, no kek-backend): deploy/.env is left as it was."""
    env = {**_host(tmp_path), "TB_KEK_BACKEND": "passphrase"}
    assert _seal(tmp_path, env).returncode == 0
    _record(tmp_path).unlink()
    res = _install(tmp_path, {**env, "TB_KEK_BACKEND": "tpm"}, "KEK_BACKEND=shamir\n")
    assert res.returncode == 0, res.stderr
    assert _env_value(tmp_path) == []
    assert "no record of the KEK back end" in res.stderr
    _no_record(tmp_path)


def test_install_on_a_poc_host_without_a_tpm_records_nothing(tmp_path: Path) -> None:
    res = _install(tmp_path, _host(tmp_path, None, tpm=False), None, profile="poc", site="TEST")
    assert res.returncode == 0, res.stderr
    assert "not sealed (host profile poc" in res.stdout
    assert _env_value(tmp_path) == []
    _no_record(tmp_path)


def test_install_fails_and_records_nothing_when_the_tpm_cannot_seal(tmp_path: Path) -> None:
    res = _install(tmp_path, _host(tmp_path, SEAL_FAILS), "KEK_BACKEND=tpm\n")
    assert res.returncode != 0 and "the site keys are not sealed" in res.stderr
    assert _env_value(tmp_path) == []
    _no_record(tmp_path)


def test_install_does_not_work_the_back_end_out_itself() -> None:
    """Only seal_keys.sh decides: after the seal the installer reads the record and nothing else."""
    after = SEAL_BLOCK[SEAL_BLOCK.index("sh deploy/hardening/seal_keys.sh") :]
    after = after[after.index("\n", after.index("|| die")) :]  # the lines after the seal's own refusal
    assert '"$SEC_DIR/kek-backend"' in after and "envset TB_KEK_BACKEND" in after
    for guess in ("has-tpm2", "hb_load_conf", "KEK_BACKEND=", "${TB_KEK_BACKEND", "$HB_CONF", "/dev/tpm"):
        assert guess not in after, guess


@pytest.mark.parametrize("backend", ["passphrase", "shamir"])
def test_no_secret_in_the_record_or_any_output(tmp_path: Path, backend: str) -> None:
    env = _host(tmp_path)
    (tmp_path / "media").mkdir()
    res = _install(tmp_path, env, f"KEK_BACKEND={backend}\nKEK_SHARES_OUT={tmp_path / 'media'}\n")
    assert res.returncode == 0, res.stderr
    rec = _record(tmp_path).read_text(encoding="utf-8")
    assert rec == backend + "\n"  # the name only: no passphrase, no share, no path
    seen = rec + res.stdout + res.stderr + (tmp_path / "deploy" / ".env").read_text(encoding="utf-8")
    assert PHRASE not in seen
    for share in (tmp_path / "media").glob("share-*.txt"):
        body = share.read_text(encoding="utf-8").strip()
        assert body and body not in seen


@pytest.mark.parametrize(("backend", "step"), [("tpm", "init"), ("passphrase", "check"), ("tpm", "check")])
def test_a_later_step_that_fails_records_nothing(tmp_path: Path, backend: str, step: str) -> None:
    """The record is the seal's last word: a wrap or the closing `tools.keys check` that fails leaves none."""
    env = _host(tmp_path)
    fake = tmp_path / "bin" / "python3"  # the host's python3, but `tools.keys <step>` fails
    fake.write_text(
        f'#!/bin/sh\ncase " $* " in *" tools.keys {step} "*) echo "{step} failed" >&2; exit 1 ;; esac\n'
        f'exec "{sys.executable}" "$@"\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    _record(tmp_path).write_text("shamir\n", encoding="utf-8")
    res = _seal(tmp_path, {**env, "TB_KEK_BACKEND": backend})
    assert res.returncode != 0
    assert _record(tmp_path).read_text(encoding="utf-8") == "shamir\n"  # the earlier record, untouched
    assert not (tmp_path / "secrets" / "kek-backend.tmp").exists()


def test_install_copies_no_record_that_is_not_a_back_end_name(tmp_path: Path) -> None:
    env = {**_host(tmp_path), "TB_KEK_BACKEND": "passphrase"}
    assert _seal(tmp_path, env).returncode == 0
    _record(tmp_path).write_text("tpm; echo x\n", encoding="utf-8")
    res = _install(tmp_path, env, None)
    assert res.returncode == 0, res.stderr
    assert _env_value(tmp_path) == []
    assert "no record of the KEK back end" in res.stderr


def test_the_record_is_written_whole_then_renamed() -> None:
    """A reader never sees half a record: written to kek-backend.tmp, then renamed over kek-backend."""
    seal = SEAL.read_text(encoding="utf-8")
    tail = seal[seal.index('REC="$SECRETS/kek-backend"') :]
    assert '> "$REC.tmp"' in tail and 'mv -f "$REC.tmp" "$REC"' in tail
    assert '> "$REC"' not in tail and '>> "$REC' not in tail
