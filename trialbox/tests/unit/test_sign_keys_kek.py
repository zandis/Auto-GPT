"""T-210d: the two signing keys under the KEK, like the site keys (T-210b, D-347).

``audit_sign.key`` (signed audit heads, T-211a) and ``edc_sign.key`` (the EDC signature binding, D-281) are in
``tb_common.kek.PROTECTED``: ``tools.keys`` wraps them, re-wraps them on rotate-kek and lists them in its custody report
and ``doctor``; the two readers open them through the KEK and fail closed when a wrapped key cannot be opened.

Every key, KEK and share is made in the test's own tmp folder; nothing reads a real key file, and no output holds key
material.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from edc.store import KEY_ENV, KEY_FILE, EdcError, sign_key_of
from tb_common import audit
from tb_common import kek as K
from tb_common.audit import AuditLog
from tb_common.crypto import create_key, ed25519_generate

from tools import audit_verify
from tools import keys as keys_cli
from tools.trialbox import doctor

AUDIT = audit.SIGN_KEY_FILE
EDC = KEY_FILE


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """A secrets folder with the site keys and both signing keys plain, and a runtime KEK path outside it."""
    for var in ("TB_KEK_FILE", "TB_KEK_PASSPHRASE", "TB_KEK_NEW_PASSPHRASE", "CREDENTIALS_DIRECTORY", "TB_SECRETS_DIR",
                KEY_ENV, audit.ANCHOR_TARGETS_ENV):  # fmt: skip
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("TB_ENV", "DEV")
    sec = tmp_path / "secrets"
    sec.mkdir()
    create_key(sec / "site_hmac.key")
    create_key(sec / "pid_map.key")
    priv, pub = ed25519_generate()
    K.store_key(sec / AUDIT, priv, None)
    (sec / audit.SIGN_PUB_FILE).write_bytes(pub)
    create_key(sec / EDC)
    run = tmp_path / "run"
    run.mkdir()
    monkeypatch.setenv("TB_KEK_FILE", str(run / "kek"))
    paths = {"sec": sec, "kek": run / "kek", "shares": tmp_path / "stewards", "tmp": tmp_path}
    for name in ("audit", "share"):
        paths[name] = tmp_path / name
        paths[name].mkdir()
    return paths


def _cli(capsys: pytest.CaptureFixture[str], *argv: str, env: dict[str, str] | None = None) -> tuple[int, str]:
    rc = keys_cli.main(list(argv), {**os.environ, **(env or {})})
    out = capsys.readouterr()
    return rc, out.out + out.err


def _init_and_unseal(box: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> list[str]:
    rc, out = _cli(capsys, "init", "--secrets", str(box["sec"]), "--backend", "shamir", "--shares-out",
                   str(box["shares"]))  # fmt: skip
    assert rc == 0, out
    shares = [str(p) for p in sorted(box["shares"].glob("share-*.txt"))]
    rc, out = _cli(capsys, "unseal", "--secrets", str(box["sec"]), "--share", shares[0], "--share", shares[1])
    assert rc == 0, out
    return shares


def _file_kek(sec: Path, tmp: Path) -> dict[str, str]:
    """A folder with a KEK of the file back end, unsealed at ``tmp/kek``: the env a service would have."""
    kek = os.urandom(K.KEK_LEN)
    K.write_meta(sec, K.new_meta("file", kek))
    K._write_private(tmp / "kek", kek)
    return {"TB_KEK_FILE": str(tmp / "kek")}


def _doctor(sec: Path, env: str, **extra: str) -> doctor.Check:
    return doctor.check_key_custody(doctor.DoctorInputs(env={"TB_ENV": env, "TB_SECRETS_DIR": str(sec), **extra}))


# ------------------------------------------------------------------------------------------------ PROTECTED, custody


def test_both_signing_keys_are_protected_and_optional() -> None:
    assert AUDIT in K.PROTECTED and EDC in K.PROTECTED
    assert AUDIT in K.OPTIONAL and EDC in K.OPTIONAL
    assert "site_hmac.key" not in K.OPTIONAL and "pid_map.key" not in K.OPTIONAL


def test_custody_lists_a_signing_key_only_when_the_box_has_it(tmp_path: Path) -> None:
    sec = tmp_path / "s"
    sec.mkdir()
    create_key(sec / "site_hmac.key")
    c = K.custody(sec, {})
    assert AUDIT not in c.keys and EDC not in c.keys  # a box with neither yet: nothing missing
    create_key(sec / EDC)
    c = K.custody(sec, {})
    assert c.keys[EDC] == "plain" and EDC in c.plain and AUDIT not in c.keys
    assert c.fingerprints[EDC] == K.fingerprint((sec / EDC).read_bytes())


def test_doctor_fails_a_plain_signing_key_in_production_and_warns_in_dev(tmp_path: Path) -> None:
    sec = tmp_path / "s"
    sec.mkdir()
    create_key(sec / EDC)
    for env, want in (("PRODUCTION", "FAIL"), ("VALIDATION", "FAIL"), ("DEV", "WARN")):
        c = _doctor(sec, env)
        assert c.status == want and EDC in c.detail, (env, c)
    (sec / EDC).unlink()
    priv, _ = ed25519_generate()
    K.store_key(sec / AUDIT, priv, None)
    c = _doctor(sec, "PRODUCTION")
    assert c.status == "FAIL" and AUDIT in c.detail


def test_doctor_fails_a_signing_key_both_plain_and_wrapped(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _init_and_unseal(box, capsys)
    (box["sec"] / EDC).write_bytes(os.urandom(32))  # a key put beside the wrapped one by hand
    c = _doctor(box["sec"], "DEV", TB_KEK_FILE=str(box["kek"]))
    assert c.status == "FAIL" and "edc_sign.key is there in plain beside its wrapped form" in c.detail


# ------------------------------------------------------------------------------------------------ wrap, rotate-kek


def test_init_wraps_both_signing_keys_and_prints_no_material(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    audit_key, edc_key = (box["sec"] / AUDIT).read_bytes(), (box["sec"] / EDC).read_bytes()
    rc, out = _cli(capsys, "init", "--secrets", str(box["sec"]), "--backend", "shamir", "--shares-out",
                   str(box["shares"]))  # fmt: skip
    assert rc == 0, out
    assert f"wrapped {AUDIT}" in out and f"wrapped {EDC}" in out
    assert audit_key.hex() not in out and edc_key.hex() not in out and b"PRIVATE KEY" not in out.encode()
    for name, key in ((AUDIT, audit_key), (EDC, edc_key)):
        assert not (box["sec"] / name).exists()
        doc = json.loads(K.wrapped_path(box["sec"] / name).read_text())
        assert doc["name"] == name and doc["fingerprint"] == K.fingerprint(key)
    rc, out = _cli(capsys, "status", "--secrets", str(box["sec"]), "--json")
    st = json.loads(out)
    assert st["keys"][AUDIT] == st["keys"][EDC] == "wrapped"


def test_wrap_wraps_a_signing_key_made_plain_after_the_ceremony(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _init_and_unseal(box, capsys)
    K.wrapped_path(box["sec"] / EDC).unlink()  # say the EDC key was made plain later, by hand
    create_key(box["sec"] / EDC)
    key = (box["sec"] / EDC).read_bytes()
    rc, out = _cli(capsys, "wrap", "--secrets", str(box["sec"]))
    assert rc == 0 and f"wrapped {EDC}" in out, out
    assert not (box["sec"] / EDC).exists()
    assert sign_key_of({"TB_ENV": "PRODUCTION", "TB_KEK_FILE": str(box["kek"])}, box["sec"]) == key


def test_rotate_kek_rewraps_both_signing_keys_and_the_readers_open_them(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    audit_key, edc_key = (box["sec"] / AUDIT).read_bytes(), (box["sec"] / EDC).read_bytes()
    _init_and_unseal(box, capsys)
    old_id = json.loads((box["sec"] / K.META_FILE).read_text())["kek_id"]
    AuditLog(box["tmp"] / "audit").append("test.box_ready", actor="tester")  # the box's chain (7114085298, F3)
    rc, out = _cli(capsys, "rotate-kek", "--secrets", str(box["sec"]), "--backend", "shamir", "--shares-out",
                   str(box["tmp"] / "new-stewards"), "--audit-dir", str(box["tmp"] / "audit"))  # fmt: skip
    assert rc == 0 and "4 key(s) re-wrapped" in out, out
    new_id = json.loads((box["sec"] / K.META_FILE).read_text())["kek_id"]
    assert new_id != old_id
    for name in (AUDIT, EDC):
        assert json.loads(K.wrapped_path(box["sec"] / name).read_text())["kek_id"] == new_id
    assert audit_verify._load_pair(box["sec"])[0] == audit_key
    assert sign_key_of({"TB_ENV": "PRODUCTION", "TB_KEK_FILE": str(box["kek"])}, box["sec"]) == edc_key
    assert not list(box["sec"].glob("*.next"))


def test_rotate_kek_waits_for_an_audit_key_rotation_cut_short(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _init_and_unseal(box, capsys)
    priv, _ = ed25519_generate()
    kek = box["kek"].read_bytes()
    K.store_key(box["sec"] / "audit_sign.next.key", priv, kek)  # what --rotate-key stages before it records
    before = (box["sec"] / K.META_FILE).read_text()
    rc, out = _cli(capsys, "rotate-kek", "--secrets", str(box["sec"]), "--backend", "shamir", "--shares-out",
                   str(box["tmp"] / "new-stewards"))  # fmt: skip
    assert rc == 1 and "audit_sign.next.key.wrapped" in out and "not finished" in out
    assert (box["sec"] / K.META_FILE).read_text() == before
    assert not (box["tmp"] / "new-stewards").exists()


# ------------------------------------------------------------------------------------------------ the audit reader


def test_the_audit_key_is_read_through_the_kek_and_fails_closed(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    audit_key = (box["sec"] / AUDIT).read_bytes()
    _init_and_unseal(box, capsys)
    assert audit_verify._load_pair(box["sec"])[0] == audit_key
    AuditLog(box["audit"]).append("test.event", actor="tester", detail={"n": 1})
    a, s = str(box["audit"]), str(box["sec"])
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    assert audit_verify.main([a, "--sign-head", "--to", str(box["share"]), "--secrets", s]) == 0
    kek = box["kek"].read_bytes()
    box["kek"].unlink()  # the KEK not unsealed
    with pytest.raises(K.KekLockedError):
        audit_verify._load_pair(box["sec"])
    assert audit_verify.main([a, "--sign-head", "--to", str(box["share"]), "--secrets", s]) == 1
    assert "not signed" in capsys.readouterr().err
    K._write_private(box["kek"], kek)
    (box["sec"] / AUDIT).write_bytes(audit_key)  # a plain copy beside the wrapped key
    with pytest.raises(K.KekError, match="plain beside"):
        audit_verify._load_pair(box["sec"])
    (box["sec"] / AUDIT).unlink()
    w = K.wrapped_path(box["sec"] / AUDIT)
    w.write_text(json.dumps({**json.loads(w.read_text()), "blob": "AAAA"}))  # damaged
    assert audit_verify.main([a, "--sign-head", "--to", str(box["share"]), "--secrets", s]) == 1
    assert "does not open" in capsys.readouterr().err


def test_an_audit_key_wrapped_under_another_name_is_refused(tmp_path: Path) -> None:
    sec = tmp_path / "s"
    sec.mkdir()
    env = _file_kek(sec, tmp_path)
    kek = (tmp_path / "kek").read_bytes()
    priv, pub = ed25519_generate()
    K.store_key(sec / EDC, priv, kek)
    os.replace(K.wrapped_path(sec / EDC), K.wrapped_path(sec / AUDIT))  # the EDC key renamed to the audit key
    (sec / audit.SIGN_PUB_FILE).write_bytes(pub)
    with pytest.raises(K.KekError, match="holds the key"):
        K.load_key_file(sec / AUDIT, env)


# ------------------------------------------------------------------------------------------------ the EDC reader


def test_the_edc_key_is_made_wrapped_in_a_folder_with_a_kek(tmp_path: Path) -> None:
    sec = tmp_path / "s"
    sec.mkdir()
    env = {"TB_ENV": "PRODUCTION", **_file_kek(sec, tmp_path)}
    key = sign_key_of(env, sec)
    assert len(key) == 32 and not (sec / EDC).exists() and K.wrapped_path(sec / EDC).exists()
    assert sign_key_of(env, sec) == key  # never replaced
    assert K.custody(sec, env).keys[EDC] == "wrapped"


def test_the_edc_key_is_never_made_plain_in_validation_or_production(tmp_path: Path) -> None:
    for env in ("PRODUCTION", "VALIDATION", " production "):
        with pytest.raises(EdcError, match="has no KEK") as e:
            sign_key_of({"TB_ENV": env}, tmp_path / "s")
        assert e.value.code == "edc.sign_key" and e.value.status == 500
        assert not K.key_present(tmp_path / "s" / EDC)
    made = sign_key_of({"TB_ENV": "TEST"}, tmp_path / "s")  # DEV and TEST: made plain on first use
    assert (tmp_path / "s" / EDC).read_bytes() == made
    assert sign_key_of({"TB_ENV": "PRODUCTION"}, tmp_path / "s") == made  # a plain key still loads; doctor FAILs it


def test_the_edc_key_fails_closed_when_its_wrapped_form_cannot_be_opened(tmp_path: Path) -> None:
    sec = tmp_path / "s"
    sec.mkdir()
    env = {"TB_ENV": "PRODUCTION", **_file_kek(sec, tmp_path)}
    key = sign_key_of(env, sec)
    for name in ("PRODUCTION", "VALIDATION", "DEV", "TEST"):  # locked: refused everywhere, no fixed key, none made
        with pytest.raises(EdcError, match="not unsealed"):
            sign_key_of({"TB_ENV": name, "TB_KEK_FILE": str(tmp_path / "nowhere")}, sec)
    assert not (sec / EDC).exists()
    other = tmp_path / "other-kek"
    K._write_private(other, os.urandom(K.KEK_LEN))
    with pytest.raises(EdcError, match="not this box's KEK"):
        sign_key_of({"TB_ENV": "PRODUCTION", "TB_KEK_FILE": str(other)}, sec)
    (sec / EDC).write_bytes(os.urandom(32))
    with pytest.raises(EdcError, match="plain beside"):
        sign_key_of(env, sec)
    (sec / EDC).unlink()
    w = K.wrapped_path(sec / EDC)
    doc = json.loads(w.read_text())
    w.write_text(json.dumps({**doc, "blob": "AAAA"}))
    with pytest.raises(EdcError, match="does not open"):
        sign_key_of(env, sec)
    w.write_text(json.dumps(doc))
    assert sign_key_of(env, sec) == key


def test_a_named_edc_key_file_is_opened_under_its_folders_kek(tmp_path: Path) -> None:
    sec, other = tmp_path / "s", tmp_path / "orchestrator-only"
    sec.mkdir()
    other.mkdir()
    env = {"TB_ENV": "PRODUCTION", **_file_kek(other, tmp_path)}
    named = other / "edc.key"
    K.store_key(named, os.urandom(32), (tmp_path / "kek").read_bytes())
    key = sign_key_of({**env, KEY_ENV: str(named)}, sec)
    assert key == K.load_key_file(named, env) and not K.key_present(sec / EDC)
    named.with_name("empty.key").write_bytes(b"")
    with pytest.raises(EdcError, match="empty"):
        sign_key_of({**env, KEY_ENV: str(named.with_name("empty.key"))}, sec)
