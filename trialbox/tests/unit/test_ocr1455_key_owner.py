"""OCR #1455 (1455-3): a plain site key another user owns is a secret that user can read, whatever its mode."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.unit import test_host_baseline as hb
from tests.unit.test_external_pass_h110 import _kept

pytestmark = pytest.mark.nodb


def test_a_plain_site_key_another_user_owns_fails_the_host_check(tmp_path: Path) -> None:
    args, env = hb._box(tmp_path, plain=True, env_name="PRODUCTION")
    # the check runs as uid 4242 (a stand-in id, as test_external_pass_h110 does for .env): the 0600 key is not its own
    hb._stubs(tmp_path, {"id": 'case "$1" in -u) echo 4242 ;; *) /usr/bin/id "$@" ;; esac\n'})
    if os.geteuid() == 0:  # as root the key is root's, which is right: give it to a third uid, as a box could hold it
        os.chown(tmp_path / "secrets" / "site_hmac.key", 4243, 4243)
    r = hb._sh(args, env)
    kept = _kept(r.stdout).strip().splitlines()
    want = "FAIL  site_hmac.key is owned by uid "
    assert any(k.startswith(want) and k.endswith("[H-94 (5)]") for k in kept), r.stdout


def test_a_plain_site_key_the_services_own_passes_the_owner_check(tmp_path: Path) -> None:
    """The services (uid 10001, deploy/docker-compose.yml) read the keys from the secrets volume, so an unsealed key
    made there is theirs, 0600 (a test box's keys are never sealed, H-106): that owner is not another user. The red
    of the rehearsal's test-boxes step at a1b4e62c (job 138679012027): both keys failed the owner check."""
    args, env = hb._box(tmp_path, plain=True, env_name="PRODUCTION")
    hb._stubs(tmp_path, {"stat": 'case "$*" in *%u*.key) echo 10001 ;; *) /usr/bin/stat "$@" ;; esac\n'})
    r = hb._sh(args, env)
    assert "is owned by uid" not in r.stdout, r.stdout
    assert "site_hmac.key is a plain file" in r.stdout  # the key is still checked: plain, so the facility line
