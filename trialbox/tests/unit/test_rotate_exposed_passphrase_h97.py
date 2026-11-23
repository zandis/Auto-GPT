"""H-97, D-1092 (the integrator's ruling 7101844662; finding H96-04): a PRODUCTION box whose KEK passphrase is exposed
rotates it under rc1. Rotating a leaked key is a safety action, not one of rc1's refused ceremonies (R22-34).

The exception is narrow: ``tools.keys rotate-kek`` on a box sealed under a passphrase, to a new passphrase
(``--backend passphrase``) given only by H-96's file or stdin form (``--new-passphrase-file`` or
``--new-passphrase-stdin``), with no escrow set, and only as an audit event (``keys.rotate_kek``: who, when, the box,
the two KEK ids; never a value) in its audit folder. Every other rotate-kek and every neighbouring ceremony stays
refused on PRODUCTION with rc1's words, and nothing changes. The passphrases here are synthetic.
"""

from __future__ import annotations

import io
import json
import os
import pwd
import sys
from pathlib import Path

import pytest
from tb_common import kek as K
from tb_common import rc1_refusals

from tools import keys

pytestmark = pytest.mark.nodb
OLD = "synthetic-h97-" + "the-exposed-passphrase"  # synthetic
NEW = "synthetic-h97-" + "the-new-passphrase-here"  # synthetic
PRODUCTION_ENVS: tuple[dict[str, str], ...] = ({}, {"TB_ENV": "PRODUCTION"})  # unset is PRODUCTION (D-127)


def _pp(path: Path, text: str) -> Path:
    path.write_text(text + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def _box(tmp: Path, capsys: pytest.CaptureFixture[str], backend: str = "passphrase") -> dict[str, Path]:
    """A box sealed under OLD (init stays allowed on PRODUCTION), with its audit folder; the KEK not unsealed."""
    sec = tmp / "sec"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(os.urandom(32))
    if backend == "passphrase":
        argv = ["--passphrase-file", str(_pp(tmp / "init.pass", OLD)), "--scrypt-n", "1024"]
    else:
        argv = ["--kek-out", str(tmp / "kek.out")]
    assert keys.main(["init", "--backend", backend, "--secrets", str(sec), *argv], env={}) == 0
    capsys.readouterr()
    audit = tmp / "audit"
    audit.mkdir()
    return {"sec": sec, "audit": audit, "runtime": tmp / "kek.runtime", "tmp": tmp}


def _site_key(sec: Path, phrase: str) -> bytes:
    meta = K.read_meta(sec) or {}
    return K.unwrap(K.derive_from_passphrase(phrase, meta), K.read_wrapped(sec / "site_hmac.key"), "site_hmac.key")


def _events(audit: Path) -> list[dict[str, object]]:
    return [json.loads(x) for f in audit.rglob("*.jsonl") for x in f.read_text(encoding="utf-8").splitlines() if x]


def _everything(b: dict[str, Path]) -> str:
    return "".join(f.read_text(encoding="utf-8", errors="replace") for f in b["audit"].rglob("*") if f.is_file())


@pytest.mark.parametrize("env", PRODUCTION_ENVS, ids=["unset", "PRODUCTION"])
@pytest.mark.parametrize("form", ["file", "stdin"])
def test_a_production_box_rotates_its_exposed_passphrase_and_the_rotation_is_audited(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, form: str,
    env: dict[str, str],
) -> None:  # fmt: skip
    """THE RULE (D-1092): on a PRODUCTION box (TB_ENV unset or PRODUCTION) rotate-kek rotates the passphrase KEK to a
    new passphrase from a root-only file or stdin: every wrapped key opens under the new one, and one audit event
    keys.rotate_kek says who, when, the box and the two KEK ids, holding no passphrase."""
    b = _box(tmp_path, capsys)
    site = _site_key(b["sec"], OLD)
    old_id = (K.read_meta(b["sec"]) or {})["kek_id"]
    argv = ["rotate-kek", "--backend", "passphrase", "--secrets", str(b["sec"]), "--scrypt-n", "1024",
            "--audit-dir", str(b["audit"])]  # fmt: skip
    if form == "file":
        argv += ["--passphrase-file", str(_pp(tmp_path / "old.pass", OLD)),
                 "--new-passphrase-file", str(_pp(tmp_path / "new.pass", NEW))]  # fmt: skip
    else:
        argv += ["--passphrase-stdin", "--new-passphrase-stdin"]
        monkeypatch.setattr(sys, "stdin", io.StringIO(f"{OLD}\n{NEW}\n"))
    rc = keys.main(argv, env={**env, "TB_KEK_FILE": str(b["runtime"])})
    out = capsys.readouterr()
    assert rc == 0, out.err
    meta = K.read_meta(b["sec"]) or {}
    assert meta["backend"] == "passphrase" and meta["kek_id"] != old_id
    assert _site_key(b["sec"], NEW) == site  # the keys are under the new passphrase
    events = [e for e in _events(b["audit"]) if e.get("event") == keys.ROTATE_EVENT]
    assert len(events) == 1
    detail = events[0]["detail"]
    assert isinstance(detail, dict)
    assert detail["old_kek_id"] == old_id and detail["new_kek_id"] == meta["kek_id"]
    assert detail["environment"] == "PRODUCTION" and detail["rule"] == "D-1092" and detail["at"] and detail["box"]
    who = detail["who"]
    assert isinstance(who, dict) and who["uid"] == os.geteuid() and who["user"] == pwd.getpwuid(os.geteuid()).pw_name
    assert events[0]["actor"] == keys.ROTATE_ACTOR
    for phrase in (OLD, NEW):
        assert phrase not in _everything(b) and phrase not in out.out + out.err
    assert f"audit: {keys.ROTATE_EVENT} in {b['audit']}" in out.out
    if form == "file":
        assert not (tmp_path / "old.pass").exists() and not (tmp_path / "new.pass").exists()  # removed once used


def _refused_and_unchanged(b: dict[str, Path], argv: list[str], env: dict[str, str],
                           capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    before = {f.name: f.read_bytes() for f in b["sec"].iterdir() if f.is_file()}
    assert keys.main(argv, env=env) == 1, argv
    err = capsys.readouterr().err.strip()
    assert err == "keys: " + rc1_refusals.text("rc1.key_ceremonies", environment="PRODUCTION"), (argv, err)
    assert {f.name: f.read_bytes() for f in b["sec"].iterdir() if f.is_file()} == before, argv
    assert _events(b["audit"]) == [], argv


@pytest.mark.parametrize("env", PRODUCTION_ENVS, ids=["unset", "PRODUCTION"])
def test_the_neighbouring_ceremonies_stay_refused_on_a_production_box(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], env: dict[str, str]
) -> None:
    """rc1's other refusals are exactly as before: on the same PRODUCTION passphrase box, rotate-kek to another back
    end, with an escrow set, or with the new passphrase from neither the file nor stdin (the terminal's own prompt),
    and the ceremony record, escrow shares, restic key and pid map key: each refused with rc1's words, nothing
    changed, no audit event."""
    b = _box(tmp_path, capsys)
    sec, audit = ["--secrets", str(b["sec"])], ["--audit-dir", str(b["audit"])]
    old = ["--passphrase-file", str(_pp(tmp_path / "old.pass", OLD)), "--keep-passphrase-files"]
    new = ["--new-passphrase-file", str(_pp(tmp_path / "new.pass", NEW))]
    for argv in (
        ["rotate-kek", *sec, "--backend", "file", "--kek-out", str(tmp_path / "k.out"), *audit, *old],
        ["rotate-kek", *sec, "--backend", "file", "--kek-out", str(tmp_path / "k.out"), *audit, *old, *new],
        ["rotate-kek", *sec, "--backend", "shamir", "--shares-out", str(tmp_path / "shares"), *audit, *old],
        ["rotate-kek", *sec, "--backend", "kms", *audit, *old],
        ["rotate-kek", *sec, "--backend", "passphrase", *audit, *old],  # the new one from neither form
        ["rotate-kek", *sec, "--backend", "passphrase", "--escrow-out", str(tmp_path / "media"), *audit, *old, *new],
        ["ceremony-record", *sec, "--deploy", str(tmp_path / "deploy-k"), *audit],
        ["escrow-shares", *sec, "--escrow-out", str(tmp_path / "media"), *audit],
        ["restic-key", *sec],
        ["rotate", "pid_map", *sec],
    ):
        _refused_and_unchanged(b, argv, env, capsys)
    assert (tmp_path / "new.pass").exists() and not (tmp_path / "shares").exists()


def test_a_box_not_sealed_under_a_passphrase_cannot_rotate_to_one_on_production(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The exception is a passphrase box's own: a file-back-end (TPM) box asking for a passphrase is refused."""
    b = _box(tmp_path, capsys, backend="file")
    argv = ["rotate-kek", "--backend", "passphrase", "--secrets", str(b["sec"]), "--scrypt-n", "1024",
            "--new-passphrase-file", str(_pp(tmp_path / "new.pass", NEW)), "--audit-dir", str(b["audit"])]  # fmt: skip
    _refused_and_unchanged(b, argv, {}, capsys)


def test_without_an_audit_folder_or_with_a_wrong_old_passphrase_nothing_changes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No audit folder: refused before anything is read or written, D-1092 named, the new passphrase's file kept. A
    wrong old passphrase: nothing changed and no audit event."""
    b = _box(tmp_path, capsys)
    before = (b["sec"] / K.META_FILE).read_bytes()
    base = ["rotate-kek", "--backend", "passphrase", "--secrets", str(b["sec"]), "--scrypt-n", "1024",
            "--new-passphrase-file", str(_pp(tmp_path / "new.pass", NEW))]  # fmt: skip
    for audit in (["--audit-dir", str(tmp_path / "no-such-folder")], []):
        assert keys.main([*base, *audit], env={"TB_KEK_FILE": str(b["runtime"])}) == 1
        err = capsys.readouterr().err
        assert "D-1092" in err and "audit folder" in err and NEW not in err
        assert (b["sec"] / K.META_FILE).read_bytes() == before and (tmp_path / "new.pass").exists()
    wrong = _pp(tmp_path / "wrong.pass", "synthetic-h97-not-the-current-one")
    rc = keys.main([*base, "--passphrase-file", str(wrong), "--audit-dir", str(b["audit"])],
                   env={"TB_KEK_FILE": str(b["runtime"])})  # fmt: skip
    capsys.readouterr()
    assert rc == 1 and (b["sec"] / K.META_FILE).read_bytes() == before and _events(b["audit"]) == []
    assert _site_key(b["sec"], OLD)  # still the old passphrase's


def test_a_callers_dev_environment_does_not_widen_or_skip_the_rule(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The box's deploy/.env says PRODUCTION and the caller exports TB_ENV=DEV: the stricter one holds (R22-34's
    review), so the rotation of another back end is still refused, and the passphrase rotation still writes its
    audit event."""
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text("TB_ENV=PRODUCTION\n", encoding="utf-8")
    monkeypatch.setattr(keys, "DEFAULT_DEPLOY", str(deploy))
    monkeypatch.setenv("TB_ENV", "DEV")
    b = _box(tmp_path, capsys)
    env = {"TB_ENV": "DEV", "TB_KEK_FILE": str(b["runtime"])}
    old = ["--passphrase-file", str(_pp(tmp_path / "old.pass", OLD)), "--keep-passphrase-files"]
    _refused_and_unchanged(b, ["rotate-kek", "--secrets", str(b["sec"]), "--backend", "file", "--kek-out",
                               str(tmp_path / "k.out"), "--audit-dir", str(b["audit"]), *old], env, capsys)  # fmt: skip
    rc = keys.main(["rotate-kek", "--backend", "passphrase", "--secrets", str(b["sec"]), "--scrypt-n", "1024", *old,
                    "--new-passphrase-file", str(_pp(tmp_path / "new.pass", NEW)), "--audit-dir", str(b["audit"])],
                   env=env)  # fmt: skip
    assert rc == 0, capsys.readouterr().err
    assert [e["event"] for e in _events(b["audit"])] == [keys.ROTATE_EVENT]


@pytest.mark.parametrize("box_env", ["DEV", "TEST", "VALIDATION"])
@pytest.mark.parametrize("backend", ["passphrase", "file"])
def test_every_rotation_on_a_poc_box_is_an_audit_event(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, box_env: str, backend: str
) -> None:
    """The integrator's ruling 7114085298: on a PoC box (its deploy/.env says DEV, TEST or VALIDATION) every KEK
    rotation writes keys.rotate_kek (who, when, the box, the environment, the two KEK ids and the new back end; never
    a value), and without an audit folder it is refused before anything is changed."""
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text(f"TB_ENV={box_env}\n", encoding="utf-8")
    monkeypatch.setattr(keys, "DEFAULT_DEPLOY", str(deploy))
    b = _box(tmp_path, capsys)
    old_id = (K.read_meta(b["sec"]) or {})["kek_id"]
    before = (b["sec"] / K.META_FILE).read_bytes()
    argv = ["rotate-kek", "--backend", backend, "--secrets", str(b["sec"]), "--scrypt-n", "1024", "--passphrase-file",
            str(_pp(tmp_path / "old.pass", OLD)), "--keep-passphrase-files"]  # fmt: skip
    if backend == "passphrase":
        argv += ["--new-passphrase-file", str(_pp(tmp_path / "new.pass", NEW))]
    else:
        argv += ["--kek-out", str(tmp_path / "new.kek")]
    env = {"TB_KEK_FILE": str(b["runtime"])}
    assert keys.main(argv, env=env) == 1  # no audit folder: refused
    err = capsys.readouterr().err
    assert "audit event on every box" in err and (b["sec"] / K.META_FILE).read_bytes() == before
    assert keys.main([*argv, "--audit-dir", str(b["audit"])], env=env) == 0, capsys.readouterr().err
    out = capsys.readouterr().out
    meta = K.read_meta(b["sec"]) or {}
    events = [e for e in _events(b["audit"]) if e.get("event") == keys.ROTATE_EVENT]
    assert len(events) == 1 and f"audit: {keys.ROTATE_EVENT} in {b['audit']}" in out
    detail = events[0]["detail"]
    assert isinstance(detail, dict)
    assert detail["environment"] == box_env and detail["rule"] == "7114085298" and detail["backend"] == backend
    assert detail["old_kek_id"] == old_id and detail["new_kek_id"] == meta["kek_id"] != old_id
    assert isinstance(detail["who"], dict) and detail["at"] and detail["box"]
    assert OLD not in _everything(b) and NEW not in _everything(b)
