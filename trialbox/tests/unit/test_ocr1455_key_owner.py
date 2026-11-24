"""OCR #1455 (1455-3): a plain site key another user owns is a secret that user can read, whatever its mode."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from tb_common import kek as K

from tests.unit import test_host_baseline as hb
from tests.unit.test_external_pass_h110 import _kept

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]


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


# D-1461's key-owner rule, one rule for the host check and H-133's hand-over (the integrator's ruling 7141781119)
COMPOSE = ROOT / "deploy" / "docker-compose.yml"


def _compose_uids(text: str) -> set[str]:
    """The uid each service that mounts the secrets volume (``tb-secrets``) runs as: its own ``user:``, else the
    one of the ``*py`` anchor it merges."""
    anchor = re.search(r"^x-[\w-]+: &py\n((?:  .*\n|\n)*)", text, re.M)
    py_user = re.search(r'^  user: "?(\d+):\d+"?$', anchor.group(1), re.M) if anchor else None
    uids: set[str] = set()
    body = text[text.index("\nservices:\n") :]
    for m in re.finditer(r"^  ([\w-]+):\n((?:    .*\n|\n)*)", body, re.M):
        block = m.group(2)
        if "tb-secrets:" not in block:
            continue
        own = re.search(r'^    user: "?(\d+):\d+"?$', block, re.M)
        if own:
            uids.add(own.group(1))
        elif "<<: *py" in block and py_user:
            uids.add(py_user.group(1))
        else:
            uids.add("?")
    return uids


def test_the_services_uid_of_the_rule_is_the_compose_file_s_user() -> None:
    """The rule's services uid is one constant (libs/tb_common/kek.py SERVICES_UID), tied to the user every service
    that mounts the secrets volume runs as in deploy/docker-compose.yml: a compose file that runs them as another
    uid fails here."""
    text = COMPOSE.read_text(encoding="utf-8")
    uids = _compose_uids(text)
    assert uids == {str(K.SERVICES_UID)}, uids
    moved = text.replace('  user: "10001:10001"\n', '  user: "10002:10002"\n', 1)  # the *py anchor's
    assert _compose_uids(moved) == {"10002"}  # the mismatch this test exists to catch


class _Seen:
    """``os`` as tb_common.kek sees it: root, and a secrets folder owned by ``uid`` (the rest real)."""

    def __init__(self, uid: int) -> None:
        self.uid = uid

    def __getattr__(self, name: str) -> object:
        return getattr(os, name)

    @staticmethod
    def geteuid() -> int:
        return 0

    @staticmethod
    def getuid() -> int:
        return 0

    def stat(self, path: object) -> os.stat_result:
        st = os.stat(path)  # type: ignore[arg-type]
        return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink, self.uid, self.uid, *st[6:10]))


@pytest.mark.parametrize("uid", [0, 10001, 4242], ids=["root", "the services", "another user"])
def test_the_host_check_and_the_hand_over_read_one_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uid: int
) -> None:
    """On the combined tree (H-133's hand-over, #1478, and this card's host check): a key owned by ``uid`` passes the
    host check exactly when D-1461's rule allows it, and the hand-over gives a key to a secrets folder's owner
    exactly when the rule allows that owner (root keeps its own). Run as root, as the box's check runs."""
    allowed = K.key_owner_allowed(uid, 0)
    args, env = hb._box(tmp_path, plain=True, env_name="PRODUCTION")
    hb._stubs(tmp_path, {"stat": f'case "$*" in *%u*.key) echo {uid} ;; *) /usr/bin/stat "$@" ;; esac\n',
                         "id": 'case "$1" in -u) echo 0 ;; *) /usr/bin/id "$@" ;; esac\n'})  # fmt: skip
    r = hb._sh(args, env)
    assert ("site_hmac.key is owned by uid" not in r.stdout) is allowed, r.stdout
    monkeypatch.setattr(K, "os", _Seen(uid))
    handed = K.services_owner(tmp_path)
    assert handed == (None if uid == 0 or not allowed else (uid, uid)), handed
    assert allowed is (uid != 4242)
