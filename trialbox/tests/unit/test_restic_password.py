"""PERF-010 R2 (D-968): restic's repository password is a box key like the others. It is made on the box only under
the KEK and only wrapped (a box without a KEK has no incremental backup), opened only into restic's own process
environment, named in the key inventory and the custody report, and redacted by name in the support bundle. One
escrow file is written beside each repository: the wrapped key and what the custodians need to rebuild the KEK from
their shares (no salt, no names), only when shares cover the KEK (a shamir KEK, or a TPM KEK with current escrow
shares, D-894). The custodians open a dead box's repository from the target and their shares; the target alone opens
nothing. Every key and share is made in the test's tmp folder."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
from tb_common import kek as K

from tests.unit.test_kek import _cli, box  # noqa: F401
from tests.unit.test_key_escrow import _escrow, _files, tpm  # noqa: F401
from tools import keys as keys_cli
from tools import support_bundle
from tools.trialbox import restic_repo as rr


@pytest.fixture
def stewards(box: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> dict[str, Path]:  # noqa: F811
    """A shamir box (the stewards hold the KEK's shares), unsealed at TB_KEK_FILE, with a target folder."""
    rc, out = _cli(capsys, "init", "--secrets", str(box["sec"]), "--backend", "shamir", "--shares-out",
                   str(box["shares"]))  # fmt: skip
    assert rc == 0, out
    shares = sorted(box["shares"].glob("share-*.txt"))
    rc, out = _cli(capsys, "unseal", "--secrets", str(box["sec"]), "--share", str(shares[0]), "--share",
                   str(shares[1]))  # fmt: skip
    assert rc == 0, out
    (box["tmp"] / "target").mkdir()
    return {**box, "target": box["tmp"] / "target"}


def _shares(b: dict[str, Path]) -> list[str]:
    return [p.read_text(encoding="utf-8") for p in sorted(b["shares"].glob("share-*.txt"))]


def test_restic_key_is_a_protected_key() -> None:
    assert "restic.key" in K.PROTECTED and "restic.key" in K.OPTIONAL  # made at the first incremental backup
    rows = {r["key"]: r for r in keys_cli.INVENTORY}
    assert "restic.key" in rows and "restic.key" in rows["KEK (key-encryption key)"]["protects"]
    assert "escrow" in rows["restic.key"]["holder"]


def test_made_wrapped_under_the_kek_and_never_plain(
    stewards: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    sec = stewards["sec"]
    rc, out = _cli(capsys, "restic-key", "--secrets", str(sec))
    assert rc == 0, out
    assert (sec / "restic.key.wrapped").is_file() and not (sec / "restic.key").exists()
    assert stat.S_IMODE((sec / "restic.key.wrapped").stat().st_mode) == 0o600
    key = K.load_key_file(sec / "restic.key")
    assert len(key) == 32 and key.hex() not in out  # the fingerprint is printed, never the key
    assert K.fingerprint(key) in out
    rc, out = _cli(capsys, "restic-key", "--secrets", str(sec))  # a second run keeps it
    assert rc == 0 and "kept" in out and K.load_key_file(sec / "restic.key") == key
    assert K.custody(sec).keys["restic.key"] == "wrapped"


def test_a_box_without_a_kek_gets_no_restic_key(box: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    rc, out = _cli(capsys, "restic-key", "--secrets", str(box["sec"]))
    assert rc == 1 and "KEK" in out
    assert not K.key_present(box["sec"] / "restic.key")


def test_a_locked_kek_makes_no_key_at_all(stewards: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    """Review of D-968: kek.json there but the KEK not unsealed must never fall through to a plain key: the key is
    written wrapped or not at all (make_key does not use create_key_file's plain branch)."""
    monkeypatch.setenv("TB_KEK_FILE", str(stewards["tmp"] / "nowhere"))
    with pytest.raises(K.KekError):
        rr.make_key(stewards["sec"], os.environ)
    assert not K.key_present(stewards["sec"] / "restic.key")


def test_a_plain_restic_key_is_refused_when_made_and_when_opened(stewards: dict[str, Path]) -> None:
    sec = stewards["sec"]
    (sec / "restic.key").write_bytes(os.urandom(32))
    with pytest.raises(rr.ResticKeyError, match="plain"):
        rr.make_key(sec, os.environ)
    with pytest.raises(rr.ResticKeyError, match="plain"):
        rr.password(sec, os.environ)


def test_a_locked_box_cannot_open_it(stewards: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    rr.make_key(stewards["sec"], os.environ)
    monkeypatch.setenv("TB_KEK_FILE", str(stewards["tmp"] / "nowhere"))
    with pytest.raises(K.KekError):
        rr.password(stewards["sec"], os.environ)


def test_the_password_goes_only_into_restics_environment(stewards: dict[str, Path]) -> None:
    rr.make_key(stewards["sec"], os.environ)
    pw = rr.password(stewards["sec"], os.environ)
    base = {"PATH": "/usr/bin", "RESTIC_PASSWORD_FILE": "/etc/x", "RESTIC_PASSWORD_COMMAND": "cat /etc/x",
            "RESTIC_REPOSITORY": "s3:elsewhere", "RESTIC_FROM_REPOSITORY": "/x", "RESTIC_FROM_PASSWORD": "y"}  # fmt: skip
    env = rr.restic_env(pw, base)
    assert env == {"PATH": "/usr/bin", "RESTIC_PASSWORD": pw}  # nothing from outside chooses a password or repository
    assert "RESTIC_PASSWORD" not in base
    assert pw == K.load_key_file(stewards["sec"] / "restic.key").hex()


def test_the_stewards_shares_open_the_repository_from_the_target_alone(stewards: dict[str, Path]) -> None:
    sec, target = stewards["sec"], stewards["target"]
    rr.make_key(sec, os.environ)
    pw = rr.password(sec, os.environ)
    there = rr.escrow_copy(sec, target)
    assert [p.name for p in target.iterdir()] == [rr.ESCROW]  # one file, no temporary left
    assert stat.S_IMODE(there.stat().st_mode) == 0o600
    text = there.read_text(encoding="utf-8")
    assert pw not in text and "salt" not in text
    doc = json.loads(text)
    assert set(doc["kek"]) == {"backend", "kek_id", "set_id", "threshold"}
    shares = _shares(stewards)
    assert rr.open_from_target(target, shares[1:]) == pw  # any two of the three
    with pytest.raises(K.KekError, match="needed"):
        rr.open_from_target(target, shares[:1])


def test_a_tpm_kek_with_its_escrow_shares(tpm: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    """D-894: the custodians' escrow shares of a TPM KEK open the repository from the target; the custodians' names
    and share fingerprints stay on the box."""
    sec, target = tpm["sec"], tpm["tmp"] / "target"
    target.mkdir()
    rr.make_key(sec, os.environ)
    pw = rr.password(sec, os.environ)
    with pytest.raises(rr.ResticKeyError, match="not covered by escrow shares"):
        rr.escrow_copy(sec, target)  # no escrow set yet: no copy the custodians could not open
    assert not list(target.iterdir())
    assert _cli(capsys, *_escrow(tpm))[0] == 0
    there = rr.escrow_copy(sec, target)
    text = there.read_text(encoding="utf-8")
    assert "Custodian" not in text
    assert set(json.loads(text)["kek"]["escrow"]) == {"set_id", "threshold", "kek_id"}
    one, _, three = _files(tpm)
    assert rr.open_from_target(target, [one.read_text(), three.read_text()]) == pw


def test_after_rotate_kek_the_copy_waits_for_new_escrow_shares(
    tpm: dict[str, Path],  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Review of D-968: rotate-kek re-wraps restic.key under a new KEK, and the old escrow set opens only the old
    one. Until escrow-shares is run again the copy on the target is kept, so the old shares still open it."""
    sec, target = tpm["sec"], tpm["tmp"] / "target"
    target.mkdir()
    rr.make_key(sec, os.environ)
    pw = rr.password(sec, os.environ)
    assert _cli(capsys, *_escrow(tpm))[0] == 0
    old_shares = [f.read_text() for f in _files(tpm)]
    rr.escrow_copy(sec, target)
    before = (target / rr.ESCROW).read_bytes()
    rc, out = _cli(capsys, "rotate-kek", "--secrets", str(sec), "--backend", "file", "--kek-out",
                   str(tpm["tmp"] / "new.kek"))  # fmt: skip
    assert rc == 0, out
    rc, out = _cli(capsys, "unseal", "--secrets", str(sec), "--from", str(tpm["tmp"] / "new.kek"))
    assert rc == 0, out
    assert rr.password(sec, os.environ) == pw  # the same key, re-wrapped
    with pytest.raises(rr.ResticKeyError, match="older KEK"):
        rr.escrow_copy(sec, target)
    assert (target / rr.ESCROW).read_bytes() == before
    assert rr.open_from_target(target, old_shares[:2]) == pw  # the custodians can still open it
    for f in _files(tpm):
        f.unlink()
    assert _cli(capsys, *_escrow(tpm))[0] == 0  # the new set
    rr.escrow_copy(sec, target)
    new_shares = [f.read_text() for f in _files(tpm)]
    assert rr.open_from_target(target, new_shares[1:]) == pw
    with pytest.raises(K.KekError):
        rr.open_from_target(target, old_shares[:2])


def test_a_passphrase_kek_has_no_shares_and_gets_no_copy(
    box: dict[str, Path],  # noqa: F811
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A passphrase KEK has no custodians' shares: its salt and parameters never go to the target."""
    pp = box["tmp"] / "kek.pass"  # H-96 (ruling 7094934985): tools.keys takes it from a root-only file, not the env
    pp.write_text("a passphrase long enough for the rule here\n", encoding="utf-8")
    pp.chmod(0o600)
    rc, out = _cli(
        capsys, "init", "--secrets", str(box["sec"]), "--backend", "passphrase", "--passphrase-file", str(pp)
    )
    assert rc == 0, out
    monkeypatch.setenv("TB_KEK_PASSPHRASE", "a passphrase long enough for the rule here")  # the library's own path
    target = box["tmp"] / "target"
    target.mkdir()
    rr.make_key(box["sec"], os.environ)
    with pytest.raises(rr.ResticKeyError, match="not covered by escrow shares"):
        rr.escrow_copy(box["sec"], target)
    assert not list(target.iterdir())


def test_another_key_is_refused_and_the_copy_kept(stewards: dict[str, Path]) -> None:
    sec, target = stewards["sec"], stewards["target"]
    rr.make_key(sec, os.environ)
    rr.escrow_copy(sec, target)
    first = (target / rr.ESCROW).read_bytes()
    rr.escrow_copy(sec, target)  # the same key: the same content
    assert json.loads((target / rr.ESCROW).read_bytes()) == json.loads(first)
    (sec / "restic.key.wrapped").unlink()
    rr.make_key(sec, os.environ)
    with pytest.raises(rr.ResticKeyError, match="another restic key"):
        rr.escrow_copy(sec, target)
    assert (target / rr.ESCROW).read_bytes() == first


@pytest.mark.parametrize("planted", ["final", "temporary"])
def test_a_link_on_the_target_is_never_written_through(stewards: dict[str, Path], planted: str) -> None:
    """Review of D-968: whoever can write to a share must not make the box write through a link."""
    sec, target = stewards["sec"], stewards["target"]
    victim = stewards["tmp"] / "victim"
    victim.write_text("keep me", encoding="utf-8")
    rr.make_key(sec, os.environ)
    if planted == "final":
        (target / rr.ESCROW).symlink_to(victim)
        with pytest.raises(rr.ResticKeyError, match="not a plain file"):
            rr.escrow_copy(sec, target)
    else:  # the old fixed temporary name: the write now uses a fresh random name, O_EXCL and O_NOFOLLOW
        (target / f"{rr.ESCROW}.part").symlink_to(victim)
        rr.escrow_copy(sec, target)
        assert not (target / rr.ESCROW).is_symlink()
        assert stat.S_IMODE((target / rr.ESCROW).stat().st_mode) == 0o600
    assert victim.read_text(encoding="utf-8") == "keep me"


def test_the_support_bundle_redacts_it_by_name() -> None:
    """The password exists only in restic's process environment, so the bundle cannot find it by value; a line that
    names it (a log, a dumped environment) is redacted by its name."""
    assert "RESTIC_PASSWORD" in support_bundle.SECRET_SETTINGS
    text, n = support_bundle.redact_secrets("RESTIC_PASSWORD=" + "ab" * 32 + "\n")
    assert n == 1 and "ab" * 32 not in text
