"""PERF-010 R2 (D-968): restic's repository password is a box key like the others. It is made on the box only under
the KEK (never plain: a box without a KEK has no incremental backup), opened only into restic's own process
environment, named in the key inventory and the custody report, kept out of the support bundle, and a copy of its
wrapped form (KEK ciphertext) is written beside each repository, so the custodians' escrow shares (D-894) open a dead
box's repository from the target alone, and the target alone opens nothing. Every key is made in the test's tmp
folder."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
from tb_common import kek as K

from tests.unit.test_kek import _cli, box  # noqa: F401
from tools import keys as keys_cli
from tools import support_bundle
from tools.trialbox import restic_repo as rr


@pytest.fixture
def locked(box: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> dict[str, Path]:  # noqa: F811
    """A box with a file-back-end KEK, unsealed at TB_KEK_FILE."""
    rc, out = _cli(capsys, "init", "--secrets", str(box["sec"]), "--backend", "file", "--kek-out",
                   str(box["tmp"] / "sealed.kek"))  # fmt: skip
    assert rc == 0, out
    rc, out = _cli(capsys, "unseal", "--secrets", str(box["sec"]), "--from", str(box["tmp"] / "sealed.kek"))
    assert rc == 0, out
    return box


def test_restic_key_is_a_protected_key() -> None:
    assert "restic.key" in K.PROTECTED and "restic.key" in K.OPTIONAL  # made at the first incremental backup
    rows = {r["key"]: r for r in keys_cli.INVENTORY}
    assert "restic.key" in rows and "restic.key" in rows["KEK (key-encryption key)"]["protects"]
    assert "escrow" in rows["restic.key"]["holder"]


def test_made_wrapped_under_the_kek_and_never_plain(
    locked: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    sec = locked["sec"]
    rc, out = _cli(capsys, "restic-key", "--secrets", str(sec))
    assert rc == 0, out
    assert (sec / "restic.key.wrapped").is_file() and not (sec / "restic.key").exists()
    assert stat.S_IMODE((sec / "restic.key.wrapped").stat().st_mode) == 0o600
    key = K.load_key_file(sec / "restic.key")
    assert len(key) == 32 and key.hex() not in out  # the fingerprint is printed, never the key
    assert K.fingerprint(key) in out
    # a second run keeps it
    rc, out = _cli(capsys, "restic-key", "--secrets", str(sec))
    assert rc == 0 and K.load_key_file(sec / "restic.key") == key
    assert K.custody(sec).keys["restic.key"] == "wrapped"


def test_a_box_without_a_kek_gets_no_restic_key(box: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    rc, out = _cli(capsys, "restic-key", "--secrets", str(box["sec"]))
    assert rc == 1 and "KEK" in out
    assert not K.key_present(box["sec"] / "restic.key")
    with pytest.raises(rr.ResticKeyError, match="KEK"):
        rr.make_key(box["sec"], os.environ)


def test_a_plain_restic_key_is_refused(locked: dict[str, Path]) -> None:
    sec = locked["sec"]
    (sec / "restic.key").write_bytes(os.urandom(32))
    with pytest.raises(rr.ResticKeyError, match="plain"):
        rr.password(sec, os.environ)


def test_a_locked_box_cannot_open_it(locked: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    rr.make_key(locked["sec"], os.environ)
    monkeypatch.setenv("TB_KEK_FILE", str(locked["tmp"] / "nowhere"))
    with pytest.raises(K.KekError):
        rr.password(locked["sec"], os.environ)


def test_the_password_goes_only_into_restics_environment(locked: dict[str, Path]) -> None:
    rr.make_key(locked["sec"], os.environ)
    pw = rr.password(locked["sec"], os.environ)
    base = {"PATH": "/usr/bin", "RESTIC_PASSWORD_FILE": "/etc/x", "RESTIC_PASSWORD_COMMAND": "cat /etc/x",
            "RESTIC_REPOSITORY": "s3:elsewhere"}  # fmt: skip
    env = rr.restic_env(pw, base)
    assert env["RESTIC_PASSWORD"] == pw and env["PATH"] == "/usr/bin"
    for name in ("RESTIC_PASSWORD_FILE", "RESTIC_PASSWORD_COMMAND", "RESTIC_REPOSITORY"):
        assert name not in env  # nothing from outside chooses the password or the repository
    assert "RESTIC_PASSWORD" not in base
    assert pw == K.load_key_file(locked["sec"] / "restic.key").hex()


def test_escrow_copy_beside_the_repository_opens_with_the_shares_only(locked: dict[str, Path]) -> None:
    sec, target = locked["sec"], locked["tmp"] / "target"
    target.mkdir()
    rr.make_key(sec, os.environ)
    pw = rr.password(sec, os.environ)
    written = rr.escrow_copy(sec, target)
    assert {p.name for p in written} == {rr.ESCROW_KEY, rr.ESCROW_META}
    for p in written:
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
        assert pw not in p.read_text(encoding="utf-8")  # ciphertext and the KEK's description only
    kek = K.load_kek(sec)
    shares = K.split_secret(kek, 2, 3)  # the custodians' shares (D-894)
    rebuilt = K.combine_shares(shares[1:])
    assert rr.open_from_target(target, rebuilt) == pw
    with pytest.raises(K.KekError):
        rr.open_from_target(target, os.urandom(32))
    meta = json.loads((target / rr.ESCROW_META).read_text(encoding="utf-8"))
    assert meta["kek_id"] == K.kek_id(kek)


def test_escrow_copy_is_kept_and_a_different_key_is_refused(locked: dict[str, Path]) -> None:
    sec, target = locked["sec"], locked["tmp"] / "target"
    target.mkdir()
    rr.make_key(sec, os.environ)
    rr.escrow_copy(sec, target)
    first = (target / rr.ESCROW_KEY).read_bytes()
    rr.escrow_copy(sec, target)  # the same key: nothing changes
    assert (target / rr.ESCROW_KEY).read_bytes() == first
    (sec / "restic.key.wrapped").unlink()
    rr.make_key(sec, os.environ)  # another key: the repository's snapshots would no longer open
    with pytest.raises(rr.ResticKeyError, match="another restic key"):
        rr.escrow_copy(sec, target)
    assert (target / rr.ESCROW_KEY).read_bytes() == first


def test_the_support_bundle_hides_the_password() -> None:
    assert "RESTIC_PASSWORD" in support_bundle.SECRET_SETTINGS


def test_after_rotate_kek_the_copy_follows_the_new_kek(
    locked: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """rotate-kek re-wraps restic.key (it is in PROTECTED); the next copy replaces the old one, since the key is the
    same, and the old KEK no longer opens it."""
    sec, target = locked["sec"], locked["tmp"] / "target"
    target.mkdir()
    rr.make_key(sec, os.environ)
    pw = rr.password(sec, os.environ)
    old = K.load_kek(sec)
    rr.escrow_copy(sec, target)
    monkeypatch.setenv("TB_KEK_NEW_PASSPHRASE", "a new passphrase long enough for the rule here")
    rc, out = _cli(capsys, "rotate-kek", "--secrets", str(sec), "--backend", "passphrase")
    assert rc == 0, out
    monkeypatch.setenv("TB_KEK_PASSPHRASE", "a new passphrase long enough for the rule here")
    monkeypatch.setenv("TB_KEK_FILE", str(locked["tmp"] / "nowhere"))
    new = K.load_kek(sec)
    assert new != old and rr.password(sec, os.environ) == pw
    rr.escrow_copy(sec, target)
    assert rr.open_from_target(target, new) == pw
    with pytest.raises(K.KekError):
        rr.open_from_target(target, old)
