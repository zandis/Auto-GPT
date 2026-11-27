"""P-28 (E2E R1): the box ran with plain site keys although the install was given a KEK passphrase; runbook 22's
unseal answered "nothing to unseal".

install.sh dropped the passphrase in two ways: on the poc host profile without a usable TPM it printed "not sealed"
whenever ``TB_KEK_BACKEND`` was unset, passphrase or not; and on a site box without a TPM and without a back end named
it sealed with the default (tpm), which fails there. A passphrase given to the install is now the site asking for a
seal: the keys are sealed under it, by the real seal step (``deploy/hardening/seal_keys.sh``), and the record and
``deploy/.env`` say ``passphrase``. The class (RC3): an answer the install was given is never dropped with a note."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from tb_common import kek as K

from tests.unit.test_seal_records_its_back_end_h77 import PHRASE, SEAL_BLOCK, _apart, _env_value, _host, _record

pytestmark = pytest.mark.nodb


def _install(tmp: Path, env: dict[str, str], *, profile: str, site: str, phrase: str = PHRASE,
             conf: str | None = None) -> subprocess.CompletedProcess[str]:  # fmt: skip
    """The seal block of install.sh as it stands, as test_seal_records_its_back_end_h77 runs it, with the passphrase
    on stdin whether or not a back end is named (the installer reads it before the block)."""
    root = Path(__file__).resolve().parents[2]
    (tmp / "deploy" / "site").mkdir(parents=True, exist_ok=True)
    (tmp / "deploy" / "hardening").symlink_to(root / "deploy" / "hardening")
    (tmp / "tools").symlink_to(root / "tools")
    (tmp / "libs").symlink_to(root / "libs")
    (tmp / "deploy" / ".env").write_text(f"TB_ENV={site}\n", encoding="utf-8")
    if conf is not None:
        (tmp / "deploy" / "site" / "hardening.conf").write_text(conf, encoding="utf-8")
    script = (
        "set -euo pipefail\n"
        f'ROOT="{tmp}"\ncd "$ROOT"\nHOST_PROFILE={profile}\nTB_ENV_SITE={site}\nIMAGE_PY=unused\n'
        'say() { echo "==> $*"; }\n'
        'die() { echo "install: $*" >&2; exit 1; }\n'
        "id() { echo 0; }\n"
        'KEYS_OK=1\nPP_KEEP=0\nKP_FILE=""\nstop_or_warn() { shift 2; die "$*"; }\n'
        'KP_VALUE=""; IFS= read -r KP_VALUE || :\n'
        f"{SEAL_BLOCK}\n"
    )
    env, _ = _apart(env)
    return subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=False,
        input=phrase + "\n" if phrase else "", env={**env, "TB_SECRETS_HOST_DIR": str(tmp / "secrets")},
    )  # fmt: skip


def _sealed_under_the_passphrase(tmp: Path, res: subprocess.CompletedProcess[str]) -> None:
    assert res.returncode == 0, res.stderr
    assert "not sealed" not in res.stdout
    meta = K.read_meta(tmp / "secrets")
    assert meta is not None and meta["backend"] == "passphrase"
    assert _record(tmp).read_text(encoding="utf-8") == "passphrase\n"
    assert _env_value(tmp) == ["passphrase"]
    assert PHRASE not in res.stdout + res.stderr


def test_the_e2e_box_poc_without_a_tpm_seals_under_the_given_passphrase(tmp_path: Path) -> None:
    res = _install(tmp_path, _host(tmp_path, None, tpm=False), profile="poc", site="VALIDATION")
    _sealed_under_the_passphrase(tmp_path, res)


def test_a_production_box_without_a_tpm_and_no_back_end_named_seals_under_it(tmp_path: Path) -> None:
    res = _install(tmp_path, _host(tmp_path, None, tpm=False), profile="site", site="PRODUCTION")
    _sealed_under_the_passphrase(tmp_path, res)


def test_a_back_end_the_site_named_still_wins(tmp_path: Path) -> None:
    (tmp_path / "media").mkdir()
    conf = f"KEK_BACKEND=shamir\nKEK_SHARES_OUT={tmp_path / 'media'}\n"
    res = _install(tmp_path, _host(tmp_path, None, tpm=False), profile="site", site="PRODUCTION", conf=conf)
    assert res.returncode == 0, res.stderr
    assert K.read_meta(tmp_path / "secrets")["backend"] == "shamir"  # type: ignore[index]


def test_poc_without_a_passphrase_is_unchanged(tmp_path: Path) -> None:
    res = _install(tmp_path, _host(tmp_path, None, tpm=False), profile="poc", site="TEST", phrase="")
    assert res.returncode == 0, res.stderr
    assert "not sealed (host profile poc" in res.stdout
    assert K.read_meta(tmp_path / "secrets") is None
