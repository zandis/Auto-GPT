"""D-894 (TB-SOP-03 §5): the escrow copy of a TPM-sealed KEK. ``python -m tools.keys escrow-shares`` splits the
unsealed KEK into custodians' shares on removable media only, threshold at least 2 and under the count, recorded in
``kek.json`` with fingerprints and names only and as an audit event; ``unseal --share`` opens it on a new board as a
witnessed event with its own record; ``rotate-kek`` makes a new set; ``ceremony-record`` lists it; ``doctor`` WARNs
on a set of an older KEK. Every key and share is made in the test's tmp folder; outputs are checked for its absence.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest
from tb_common import kek as K

from tests.own_deploy import own_deploy
from tests.unit.test_kek import _cli, box  # noqa: F401
from tools import key_escrow as ke
from tools.trialbox import doctor


@pytest.fixture(autouse=True)
def _own_deploy(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """H139-10: the key commands read a deploy folder of this test's own, never the checkout's deploy/.env."""
    own_deploy(monkeypatch, tmp_path_factory.mktemp("box") / "deploy")


NAMES = ["--custodian", "Custodian One", "--custodian", "Custodian Two", "--custodian", "Custodian Three"]


@pytest.fixture
def tpm(box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:  # noqa: F811
    """A file-back-end (TPM) box, unsealed, with a media folder the media check accepts and an audit folder."""
    rc, out = _cli(capsys, "init", "--secrets", str(box["sec"]), "--backend", "file", "--kek-out",
                   str(box["tmp"] / "sealed.kek"))  # fmt: skip
    assert rc == 0, out
    rc, out = _cli(capsys, "unseal", "--secrets", str(box["sec"]), "--from", str(box["tmp"] / "sealed.kek"))
    assert rc == 0, out
    media, audit = box["tmp"] / "usb", box["tmp"] / "audit"
    media.mkdir()
    audit.mkdir()
    real = ke.media_problem
    monkeypatch.setattr(ke, "media_problem", lambda out, sec: None if K._inside(out, media) else real(out, sec))
    return {**box, "media": media, "audit": audit, "deploy": box["tmp"] / "deploy"}


def _escrow(b: dict[str, Path], *extra: str, names: list[str] = NAMES) -> list[str]:
    return ["escrow-shares", "--secrets", str(b["sec"]), "--escrow-out", str(b["media"]), "--audit-dir",
            str(b["audit"]), *names, *extra]  # fmt: skip


def _files(b: dict[str, Path], where: str = "media") -> list[Path]:
    return sorted(b[where].glob("escrow-*.txt"))


def _events(b: dict[str, Path], event: str) -> list[dict[str, Any]]:
    rows = [json.loads(x) for f in b["audit"].rglob("*.jsonl") for x in f.read_text().splitlines()]
    return [e for e in rows if e["event"] == event]


def _kek(b: dict[str, Path]) -> bytes:
    return (b["tmp"] / "sealed.kek").read_bytes()


# ------------------------------------------------------------------------------------------------ the media


def test_shares_go_only_to_removable_media(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sec = tmp_path / "secrets"
    sec.mkdir()
    assert "is not there" in str(ke.media_problem(tmp_path / "no-such-usb", sec))
    (sec / "x").mkdir()
    assert "inside the secrets folder" in str(ke.media_problem(sec / "x", sec))
    (tmp_path / "disk").mkdir()
    assert "same disk as the secrets folder" in str(ke.media_problem(tmp_path / "disk", sec))
    devs = {sec: 1, tmp_path / "disk": 2, Path("/"): 3}
    monkeypatch.setattr(ke, "_dev", lambda p: devs[p])
    monkeypatch.setattr(ke, "removable", lambda dev: False)
    assert "not on removable media" in str(ke.media_problem(tmp_path / "disk", sec))
    monkeypatch.setattr(ke, "removable", lambda dev: True)
    assert ke.media_problem(tmp_path / "disk", sec) is None
    devs[Path("/")] = 2
    assert "system disk" in str(ke.media_problem(tmp_path / "disk", sec))


def test_removable_reads_sysfs(tmp_path: Path) -> None:
    sysfs = tmp_path / "sys"

    def disk(major_minor: str, path: str, flag: str) -> int:
        d = sysfs / "devices" / path
        d.mkdir(parents=True)
        (d.parent / "removable").write_text(flag + "\n")
        (sysfs / "dev" / "block").mkdir(parents=True, exist_ok=True)
        (sysfs / "dev" / "block" / major_minor).symlink_to(d)
        major, minor = (int(x) for x in major_minor.split(":"))
        return os.makedev(major, minor)

    assert ke.removable(disk("8:17", "pci0000:00/usb1/1-1/host6/block/sdb/sdb1", "0"), sysfs)  # on USB
    assert ke.removable(disk("179:1", "platform/mmc0/block/mmcblk0/mmcblk0p1", "1"), sysfs)  # a card reader
    assert not ke.removable(disk("259:1", "pci0000:00/nvme/nvme0/block/nvme0n1/nvme0n1p1", "0"), sysfs)  # fixed
    assert not ke.removable(os.makedev(9, 9), sysfs)  # not a block device sysfs knows


# ------------------------------------------------------------------------------------------------ making the set


def test_escrow_shares_on_media_recorded_by_fingerprint_and_name_only(
    tpm: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    rc, out = _cli(capsys, *_escrow(tpm))
    assert rc == 0, out
    files = _files(tpm)
    assert len(files) == 3 and all(stat.S_IMODE(f.stat().st_mode) == 0o600 for f in files)
    meta = K.read_meta(tpm["sec"])
    assert meta is not None
    esc = meta["escrow"]
    assert esc["threshold"] == 2 and esc["count"] == 3 and esc["kek_id"] == meta["kek_id"]
    assert [r["custodian"] for r in esc["shares"]] == ["Custodian One", "Custodian Two", "Custodian Three"]
    assert [r["fingerprint"] for r in esc["shares"]] == [ke.share_fingerprint(f.read_text()) for f in files]
    (ev,) = _events(tpm, ke.EVENT)
    assert ev["detail"]["shares"] == esc["shares"] and ev["detail"]["set_id"] == esc["set_id"]
    seen = out + (tpm["sec"] / K.META_FILE).read_text() + json.dumps(ev)
    assert _kek(tpm).hex() not in seen
    for f in files:
        body = f.read_text().strip()
        assert body not in seen and body.rsplit("-", 2)[-2] not in seen  # neither the share nor its data
    assert not list(tpm["sec"].glob("escrow-*")) and not list(tpm["tmp"].glob("escrow-*"))  # only on the media
    assert K.kek_from_escrow(meta, [files[0].read_text(), files[2].read_text()]) == _kek(tpm)


@pytest.mark.parametrize(
    ("extra", "names", "said"),
    [
        (["--threshold", "1"], NAMES, "at least 2 custodians"),
        (["--threshold", "3", "--shares", "3"], NAMES, "fewer than the shares"),
        (["--threshold", "4", "--shares", "3"], NAMES, "fewer than the shares"),
        ([], NAMES[:4], "3 shares and 2 custodians"),
        ([], [*NAMES[:4], "--custodian", "Custodian One"], "named twice"),
    ],
)
def test_each_bad_split_is_refused_and_nothing_is_written(
    tpm: dict[str, Path], capsys: pytest.CaptureFixture[str], extra: list[str], names: list[str], said: str
) -> None:
    before = (tpm["sec"] / K.META_FILE).read_text()
    rc, out = _cli(capsys, *_escrow(tpm, *extra, names=names))
    assert rc == 1 and said in out, out
    assert not _files(tpm) and (tpm["sec"] / K.META_FILE).read_text() == before and not _events(tpm, ke.EVENT)


def test_refused_off_removable_media_without_an_audit_folder_or_without_the_kek(
    tpm: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    fixed = tpm["tmp"] / "fixed"
    fixed.mkdir()
    rc, out = _cli(capsys, *_escrow(tpm), "--escrow-out", str(fixed))
    assert rc == 1 and "same disk" in out and not list(fixed.iterdir())
    rc, out = _cli(capsys, *_escrow(tpm), "--escrow-out", str(tpm["sec"]))
    assert rc == 1 and "inside the secrets folder" in out
    rc, out = _cli(capsys, *_escrow(tpm), "--audit-dir", str(tpm["tmp"] / "no-audit"))
    assert rc == 1 and "no audit folder" in out and not _files(tpm)
    tpm["kek"].unlink()  # locked: the KEK is not unsealed here
    rc, out = _cli(capsys, *_escrow(tpm))
    assert rc == 1 and "not unsealed" in out and not _files(tpm)


def test_only_a_tpm_box_and_only_one_set_per_kek(
    tpm: dict[str, Path], capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert _cli(capsys, *_escrow(tpm))[0] == 0
    rc, out = _cli(capsys, *_escrow(tpm))
    assert rc == 1 and "already has escrow set" in out and "rotate-kek" in out and len(_files(tpm)) == 3
    sh = tmp_path / "shamir"
    sh.mkdir()
    (sh / "site_hmac.key").write_bytes(os.urandom(32))
    assert (
        _cli(capsys, "init", "--secrets", str(sh), "--backend", "shamir", "--shares-out", str(tmp_path / "st"))[0] == 0
    )
    rc, out = _cli(capsys, *_escrow(tpm), "--secrets", str(sh))
    assert rc == 1 and "back end file" in out and "already the KEK's recovery copy" in out


# ------------------------------------------------------------------------------------------------ a new board


def test_a_new_board_opens_the_kek_from_escrow_as_a_witnessed_event_then_rotates_onto_its_tpm(
    tpm: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert _cli(capsys, *_escrow(tpm))[0] == 0
    one, two, three = _files(tpm)
    kek = _kek(tpm)
    tpm["kek"].unlink()  # the board died: no TPM credential, nothing unsealed
    base = ["unseal", "--secrets", str(tpm["sec"]), "--audit-dir", str(tpm["audit"]), "--deploy", str(tpm["deploy"])]
    rc, out = _cli(capsys, *base, "--share", str(one), "--share", str(three))
    assert rc == 1 and "--witness" in out and not tpm["kek"].exists()
    rc, out = _cli(capsys, *base, "--share", str(one), "--share", str(three), "--witness", "Custodian Two")
    assert rc == 1 and "not one of the escrow custodians" in out
    rc, out = _cli(capsys, *base, "--share", str(one), "--witness", "Witness Four")
    assert rc == 1 and "1 share(s) given; 2 are needed" in out and not tpm["kek"].exists()
    rc, out = _cli(capsys, *base, "--share", str(one), "--share", str(three), "--witness", "Witness Four")
    assert rc == 0, out
    assert tpm["kek"].read_bytes() == kek and kek.hex() not in out
    (rec,) = sorted((tpm["deploy"] / "site").glob("escrow-use-*.json"))
    doc = json.loads(rec.read_text())
    assert [s["custodian"] for s in doc["shares"]] == ["Custodian One", "Custodian Three"]
    assert doc["witness"] == "Witness Four" and "Witness Four: ____" in rec.with_suffix(".md").read_text()
    (ev,) = _events(tpm, ke.USE_EVENT)
    assert ev["detail"]["witness"] == "Witness Four" and one.read_text().strip() not in rec.read_text() + json.dumps(ev)
    # onto the new board's TPM, with a new set: the old shares open nothing
    media2 = tpm["media"] / "new"
    media2.mkdir()
    rc, out = _cli(capsys, "rotate-kek", "--secrets", str(tpm["sec"]), "--backend", "file", "--kek-out",
                   str(tpm["tmp"] / "new.kek"), "--escrow-out", str(media2), "--audit-dir", str(tpm["audit"]),
                   *NAMES)  # fmt: skip
    assert rc == 0, out
    meta = K.read_meta(tpm["sec"])
    assert meta is not None and meta["escrow"]["kek_id"] == meta["kek_id"] != K.kek_id(kek)
    with pytest.raises(K.KekError, match="another set"):
        K.kek_from_escrow(meta, [one.read_text(), two.read_text()])
    new = sorted(media2.glob("escrow-*.txt"))
    assert K.kek_from_escrow(meta, [new[1].read_text(), new[2].read_text()]) == (tpm["tmp"] / "new.kek").read_bytes()
    assert len(_events(tpm, ke.EVENT)) == 2


def test_escrow_out_is_for_a_tpm_kek_and_its_split_is_checked_before_anything(
    tpm: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    before = (tpm["sec"] / K.META_FILE).read_text()
    rot = ["rotate-kek", "--secrets", str(tpm["sec"]), "--escrow-out", str(tpm["media"]), "--audit-dir",
           str(tpm["audit"])]  # fmt: skip
    rc, out = _cli(capsys, *rot, "--backend", "shamir", "--shares-out", str(tpm["tmp"] / "st"), *NAMES)
    assert rc == 1 and "--backend file" in out
    rc, out = _cli(capsys, *rot, "--backend", "file", "--kek-out", str(tpm["tmp"] / "n.kek"), "--escrow-threshold",
                   "1", *NAMES)  # fmt: skip
    assert rc == 1 and "at least 2" in out and not (tpm["tmp"] / "n.kek").exists()
    assert (tpm["sec"] / K.META_FILE).read_text() == before and not _files(tpm)


# ------------------------------------------------------------------------------------------------ record and doctor


def _doctor(b: dict[str, Path]) -> doctor.Check:
    inp = doctor.DoctorInputs(env={"TB_ENV": "PRODUCTION", "TB_SECRETS_DIR": str(b["sec"])}, deploy=b["deploy"])
    return doctor.check_key_custody_record(inp)


def _record(b: dict[str, Path], *names: str) -> list[str]:
    for f in (b["deploy"] / "site").glob("key-ceremony-*"):  # an earlier record, filed (the test runs in a second)
        f.rename(f.with_name(f.name.replace("key-ceremony-2", "key-ceremony-1")))
    return ["ceremony-record", "--secrets", str(b["sec"]), "--deploy", str(b["deploy"]), "--audit-dir",
            str(b["audit"]), *names, "--witness", "Witness Four"]  # fmt: skip


def test_the_ceremony_record_lists_the_set_and_the_doctor_warns_on_an_older_or_unrecorded_set(
    tpm: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    rc, out = _cli(capsys, *_record(tpm, "--custodian", "IT Lead"))
    assert rc == 0, out
    md = sorted((tpm["deploy"] / "site").glob("key-ceremony-*.md"))[-1].read_text()
    assert "Escrow: none" in md and _doctor(tpm).status == "PASS"
    assert _cli(capsys, *_escrow(tpm))[0] == 0
    d = _doctor(tpm)
    assert d.status == "WARN" and "made after the newest ceremony record" in d.detail
    rc, out = _cli(capsys, *_record(tpm, "--custodian", "IT Lead", *NAMES[:4]))
    assert rc == 1 and "Custodian Three are not named" in out
    rc, out = _cli(capsys, *_record(tpm, *NAMES))
    assert rc == 0, out
    (jf,) = [f for f in sorted((tpm["deploy"] / "site").glob("key-ceremony-*.json")) if "escrow" in f.read_text()][-1:]
    rec = json.loads(jf.read_text())
    meta = K.read_meta(tpm["sec"])
    assert meta is not None and rec["escrow"]["shares"] == meta["escrow"]["shares"]
    assert "| 3 of 3 | Custodian Three |" in jf.with_suffix(".md").read_text()
    assert _doctor(tpm).status == "PASS"
    # a rotation without a new set: the old set is kept, said, and refused on the record until a new one is made
    rc, out = _cli(capsys, "rotate-kek", "--secrets", str(tpm["sec"]), "--backend", "file", "--kek-out",
                   str(tpm["tmp"] / "n.kek"), "--audit-dir", str(tpm["audit"]))  # fmt: skip  # every rotation is an audit event (ruling 7114085298)
    assert rc == 0 and "opens the old KEK only" in out
    d = _doctor(tpm)
    assert d.status == "WARN" and "older KEK" in d.detail and "escrow-shares" in d.detail
    rc, out = _cli(capsys, *_record(tpm, *NAMES))
    assert rc == 1 and "older KEK" in out
    media2 = tpm["media"] / "2"
    media2.mkdir()
    assert _cli(capsys, *_escrow(tpm), "--escrow-out", str(media2))[0] == 0  # allowed: the kept set is stale
    assert _cli(capsys, *_record(tpm, *NAMES))[0] == 0 and _doctor(tpm).status == "PASS"
