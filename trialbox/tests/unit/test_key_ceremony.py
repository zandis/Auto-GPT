"""TB-SOP-03 (D-893): ``python -m tools.keys ceremony-record`` writes the record the key custodians sign (IQ-05). It
holds fingerprints and names only; it is refused before ``keys init`` and while a key is plain; for shamir each share
has one named custodian; a passphrase box's record says it is not a site's ceremony; the ceremony is an audit event;
and ``trialbox doctor`` WARNs (never FAILs) on a site box whose KEK has no record."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tb_common.crypto import create_key

from tests.unit.test_kek import CHEAP_N, _cli, _init_shamir, _no_material, _shares, box  # noqa: F401
from tools import key_ceremony as kc
from tools.trialbox import backup as bk
from tools.trialbox import doctor

PEOPLE = ["--custodian", "Custodian One", "--custodian", "Custodian Two", "--custodian", "Custodian Three",
          "--witness", "Witness Four"]  # fmt: skip


def _record_args(b: dict[str, Path], *extra: str) -> list[str]:
    (b["tmp"] / "audit").mkdir(exist_ok=True)  # a box's audit folder is always there
    return ["ceremony-record", "--secrets", str(b["sec"]), "--deploy", str(b["tmp"] / "deploy"),
            "--audit-dir", str(b["tmp"] / "audit"), *extra]  # fmt: skip


def _records(b: dict[str, Path]) -> list[Path]:
    return sorted((b["tmp"] / "deploy" / "site").glob("key-ceremony-*.json"))


def test_refused_before_init_and_while_a_key_is_plain(box: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    rc, out = _cli(capsys, *_record_args(box), *PEOPLE)
    assert rc == 1 and "keys init first" in out and not _records(box)
    _init_shamir(box, capsys)
    create_key(box["sec"] / "objects.key")  # a key made after the KEK, not wrapped yet
    rc, out = _cli(capsys, *_record_args(box), *PEOPLE)
    assert rc == 1 and "objects.key still plain" in out and not _records(box)


def test_a_shamir_record_names_one_custodian_per_share_with_fingerprints_and_no_material(
    box: dict[str, Path],  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    site, pmk = _init_shamir(box, capsys)
    shares = _shares(box)
    bk.keygen(box["tmp"] / "usb" / "backup.key", box["tmp"] / "deploy" / "secrets" / "backup.pub")
    rc, out = _cli(capsys, *_record_args(box, "--shares-dir", str(box["shares"])), *PEOPLE)
    assert rc == 0, out
    (jf,) = _records(box)
    rec = json.loads(jf.read_text(encoding="utf-8"))
    md = jf.with_suffix(".md").read_text(encoding="utf-8")
    assert rec["kek"]["backend"] == "shamir" and rec["kek"]["threshold"] == 2 and rec["kek"]["count"] == 3
    assert [s["custodian"] for s in rec["shares"]] == ["Custodian One", "Custodian Two", "Custodian Three"]
    assert [s["fingerprint"] for s in rec["shares"]] == [
        kc.share_fingerprint(f.read_text(encoding="utf-8")) for f in shares
    ]
    assert set(rec["keys"]) == {"site_hmac.key", "pid_map.key"} and rec["backup_key"]
    assert "Witness Four: ____" in md and "Custodian Three: ____" in md and not rec["not_a_site_ceremony"]
    for text in (md, jf.read_text(encoding="utf-8"), out):
        _no_material(text, site, pmk)
        for f in shares:  # no share text, only its fingerprint
            assert f.read_text(encoding="utf-8").strip() not in text
    events = [json.loads(x) for f in (box["tmp"] / "audit").rglob("*.jsonl") for x in f.read_text().splitlines()]
    (ev,) = [e for e in events if e["event"] == kc.EVENT]
    assert ev["detail"]["custodians"] == rec["custodians"] and ev["detail"]["keys"] == rec["keys"]


def test_each_share_needs_one_named_custodian_and_the_witness_is_another_person(
    box: dict[str, Path],  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    _init_shamir(box, capsys)
    rc, out = _cli(capsys, *_record_args(box), "--custodian", "Only One", "--witness", "W")
    assert rc == 1 and "3 shares were made and 1 custodians" in out
    rc, out = _cli(capsys, *_record_args(box), *PEOPLE[:6], "--witness", "Custodian One")
    assert rc == 1 and "witness is not one of the custodians" in out and not _records(box)


def test_a_passphrase_box_gets_a_record_marked_not_a_site_ceremony(
    box: dict[str, Path],  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    phrase = box["sec"].parent / "kek.pass"  # H-96 (ruling 7094934985): a file only root can read, not the environment
    phrase.write_text("a long synthetic test phrase\n", encoding="utf-8")
    phrase.chmod(0o600)
    rc, _ = _cli(capsys, "init", "--secrets", str(box["sec"]), "--backend", "passphrase", "--scrypt-n", CHEAP_N,
                 "--passphrase-file", str(phrase))  # fmt: skip
    assert rc == 0
    rc, out = _cli(capsys, *_record_args(box), "--custodian", "IT Lead", "--witness", "Owner")
    assert rc == 0 and "NOT a site's key ceremony" in out
    (jf,) = _records(box)
    rec = json.loads(jf.read_text(encoding="utf-8"))
    assert rec["not_a_site_ceremony"] and rec["shares"] == []
    assert "NOT A SITE'S KEY CEREMONY" in jf.with_suffix(".md").read_text(encoding="utf-8")
    assert "a long synthetic test phrase" not in jf.read_text(encoding="utf-8") + out


def test_every_back_end_says_what_it_means_after_a_power_loss_and_when_a_custodian_leaves() -> None:
    assert "after a power loss" in kc.MEANING["file"] and "after a power loss" in kc.MEANING["shamir"]
    assert "rotate-kek" in kc.MEANING["shamir"] and "not a" in kc.MEANING["passphrase"]
    sop = (Path(__file__).resolve().parents[2] / "docs" / "security" / "10-key-ceremony-and-escrow.md").read_text(
        encoding="utf-8"
    )
    flat = " ".join(sop.split())
    for words in ("TB-SOP-03", "box owner's and hospital IT's choice", "power loss", "custodian leaves",
                  "ceremony-record", "rotate-kek", "backup-keygen", "keys-init"):  # fmt: skip
        assert words in flat, words


def _doctor(b: dict[str, Path], env: str) -> doctor.Check:
    inp = doctor.DoctorInputs(env={"TB_ENV": env, "TB_SECRETS_DIR": str(b["sec"])}, deploy=b["tmp"] / "deploy")
    return doctor.check_key_custody_record(inp)


def test_doctor_warns_on_a_site_box_without_a_record_and_never_fails(
    box: dict[str, Path],  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _doctor(box, "PRODUCTION").status == "PASS"  # no KEK yet: nothing to record
    _init_shamir(box, capsys)
    for env in ("PRODUCTION", "VALIDATION"):
        c = _doctor(box, env)
        assert c.status == "WARN" and "ceremony-record" in c.detail
    assert _doctor(box, "TEST").status == "PASS"
    assert _cli(capsys, *_record_args(box), *PEOPLE)[0] == 0
    ok = _doctor(box, "PRODUCTION")
    assert ok.status == "PASS" and "3 custodian(s)" in ok.detail
    assert doctor.check_key_custody_record in doctor.CHECKS
