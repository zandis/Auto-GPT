"""T-210b (CR-041 second third, OPS-058; D-347): the site keys under a KEK, the unseal, the inventory and rotation.

Every key, KEK, share and passphrase here is made in the test's own tmp folder; nothing reads a real key file. No
assertion prints key material: outputs are checked for its absence.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path

import pytest
from adapter.pidmap import PidMap, load_map_key
from tb_common import kek as K
from tb_common.crypto import KeyMissingError, create_key, key_fingerprint, load_key

from tools import keys as keys_cli
from tools.trialbox import doctor

ROOT = Path(__file__).resolve().parents[2]
CHEAP_N = "1024"  # scrypt cost for the tests only (kek.json records it)


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """A secrets folder with the two site keys plain (as keys-init leaves them), and a runtime KEK path outside it."""
    for var in ("TB_KEK_FILE", "TB_KEK_PASSPHRASE", "TB_KEK_NEW_PASSPHRASE", "CREDENTIALS_DIRECTORY", "TB_SECRETS_DIR"):
        monkeypatch.delenv(var, raising=False)
    sec = tmp_path / "secrets"
    sec.mkdir()
    create_key(sec / "site_hmac.key")
    create_key(sec / "pid_map.key")
    run = tmp_path / "run"
    run.mkdir()
    monkeypatch.setenv("TB_KEK_FILE", str(run / "kek"))
    return {"sec": sec, "kek": run / "kek", "shares": tmp_path / "stewards", "tmp": tmp_path}


def _cli(capsys: pytest.CaptureFixture[str], *argv: str, env: dict[str, str] | None = None) -> tuple[int, str]:
    rc = keys_cli.main(list(argv), {**os.environ, **(env or {})})
    out = capsys.readouterr()
    return rc, out.out + out.err


def _no_material(text: str, *secrets: bytes) -> None:
    for s in secrets:
        assert s.hex() not in text, "key material in the output"


def _init_shamir(box: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> tuple[bytes, bytes]:
    site, pmk = (box["sec"] / "site_hmac.key").read_bytes(), (box["sec"] / "pid_map.key").read_bytes()
    rc, out = _cli(capsys, "init", "--secrets", str(box["sec"]), "--backend", "shamir", "--shares-out",
                   str(box["shares"]))  # fmt: skip
    assert rc == 0, out
    _no_material(out, site, pmk)
    return site, pmk


def _shares(box: dict[str, Path]) -> list[Path]:
    return sorted(box["shares"].glob("share-*.txt"))


def _share_args(files: list[Path]) -> list[str]:
    return [arg for f in files for arg in ("--share", str(f))]


# ------------------------------------------------------------------------------------------------ the primitives


def test_shamir_any_two_of_three_give_the_kek_and_one_does_not() -> None:
    kek = os.urandom(32)
    set_id, shares = K.make_shares(kek, 2, 3)
    meta = K.new_meta("shamir", kek, threshold=2, count=3, set_id=set_id)
    for a, b in ((0, 1), (0, 2), (1, 2), (2, 0)):
        assert K.kek_from_shares(meta, [shares[a].text(), shares[b].text()]) == kek
    with pytest.raises(K.KekError, match="1 share"):
        K.kek_from_shares(meta, [shares[0].text()])


def test_a_share_reused_twice_is_refused() -> None:
    kek = os.urandom(32)
    set_id, shares = K.make_shares(kek, 2, 3)
    meta = K.new_meta("shamir", kek, threshold=2, count=3, set_id=set_id)
    with pytest.raises(K.KekError, match="given twice"):
        K.kek_from_shares(meta, [shares[1].text(), shares[1].text()])


def test_shares_of_another_set_are_refused_and_a_typo_fails_the_check() -> None:
    kek = os.urandom(32)
    set_id, shares = K.make_shares(kek, 2, 3)
    _, other = K.make_shares(kek, 2, 3)  # the same KEK split again: another set
    meta = K.new_meta("shamir", kek, threshold=2, count=3, set_id=set_id)
    with pytest.raises(K.KekError, match="another set"):
        K.kek_from_shares(meta, [other[0].text(), other[1].text()])
    t = shares[0].text()
    typo = t[:20] + ("0" if t[20] != "0" else "1") + t[21:]
    with pytest.raises(K.KekError, match="check"):
        K.parse_share(typo)


def test_three_of_five_round_trip() -> None:
    secret = os.urandom(32)
    parts = K.split_secret(secret, 3, 5)
    assert K.combine_shares([parts[4], parts[0], parts[2]]) == secret
    assert K.combine_shares(parts[:2]) != secret  # two of a 3-of-5 give nothing useful


def test_passphrase_back_end_round_trips_and_a_wrong_one_is_refused(tmp_path: Path) -> None:
    sec = tmp_path / "s"
    sec.mkdir()
    params = {**K.passphrase_params(), "n": int(CHEAP_N)}
    kek = K.derive_from_passphrase("correct horse battery", params)
    K.write_meta(sec, K.new_meta("passphrase", kek, **params))
    env = {"TB_KEK_FILE": str(tmp_path / "none"), "TB_KEK_PASSPHRASE": "correct horse battery"}
    assert K.load_kek(sec, env) == kek
    with pytest.raises(K.KekError, match="not this box's passphrase"):
        K.load_kek(sec, {**env, "TB_KEK_PASSPHRASE": "wrong horse battery"})


def test_wrap_binds_the_name_and_the_kek_and_detects_tampering() -> None:
    kek, key = os.urandom(32), os.urandom(32)
    doc = K.wrap(kek, key, "pid_map.key")
    assert K.unwrap(kek, doc, "pid_map.key") == key
    assert doc["fingerprint"] == key_fingerprint(key) == K.fingerprint(key)
    with pytest.raises(K.KekError, match="holds the key"):  # pid_map.key.wrapped renamed to site_hmac.key.wrapped
        K.unwrap(kek, doc, "site_hmac.key")
    with pytest.raises(K.KekError, match="damaged"):  # and its name field edited too: the associated data differs
        K.unwrap(kek, {**doc, "name": "site_hmac.key"}, "site_hmac.key")
    with pytest.raises(K.KekError, match="wrapped under KEK"):
        K.unwrap(os.urandom(32), doc, "pid_map.key")
    blob = bytearray(base64.b64decode(doc["blob"]))
    blob[-1] ^= 1
    with pytest.raises(K.KekError, match="damaged"):
        K.unwrap(kek, {**doc, "blob": base64.b64encode(bytes(blob)).decode()}, "pid_map.key")


# ------------------------------------------------------------------------------------------------ loading a key


def test_the_kek_file_may_not_sit_in_the_secrets_folder_or_be_readable_by_others(tmp_path: Path) -> None:
    sec = tmp_path / "s"
    sec.mkdir()
    kek = os.urandom(32)
    K.write_meta(sec, K.new_meta("file", kek))
    inside = sec / "kek"
    inside.write_bytes(kek)
    with pytest.raises(K.KekError, match="inside the secrets folder"):
        K.load_kek(sec, {"TB_KEK_FILE": str(inside)})
    loose = tmp_path / "kek"
    loose.write_bytes(kek)
    loose.chmod(0o644)
    with pytest.raises(K.KekError, match="readable by group or others"):
        K.load_kek(sec, {"TB_KEK_FILE": str(loose)})
    loose.chmod(0o600)
    assert K.load_kek(sec, {"TB_KEK_FILE": str(loose)}) == kek
    other = tmp_path / "other"
    K._write_private(other, os.urandom(32))
    with pytest.raises(K.KekError, match="not this box's KEK"):
        K.load_kek(sec, {"TB_KEK_FILE": str(other)})


def test_a_systemd_credential_is_a_kek_source(tmp_path: Path) -> None:
    sec, creds = tmp_path / "s", tmp_path / "creds"
    sec.mkdir()
    kek = os.urandom(32)
    K.write_meta(sec, K.new_meta("file", kek))
    K._write_private(creds / K.CREDENTIAL, kek)
    env = {"TB_KEK_FILE": str(tmp_path / "absent"), "CREDENTIALS_DIRECTORY": str(creds)}
    assert K.load_kek(sec, env) == kek


def test_load_key_opens_a_wrapped_site_key_and_fails_closed_without_the_kek(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    site, _ = _init_shamir(box, capsys)
    assert not (box["sec"] / "site_hmac.key").exists()  # the plain file is gone
    with pytest.raises(K.KekLockedError, match="not unsealed"):
        load_key(box["sec"] / "site_hmac.key")
    # keys-init (create_key) never makes a new site key beside the wrapped one
    assert create_key(box["sec"] / "site_hmac.key") is False
    assert not (box["sec"] / "site_hmac.key").exists()
    rc, out = _cli(capsys, "unseal", "--secrets", str(box["sec"]), *_share_args(_shares(box)[:2]))
    assert rc == 0, out
    assert load_key(box["sec"] / "site_hmac.key") == site
    assert box["kek"].stat().st_mode & 0o077 == 0


def test_a_plain_copy_beside_a_wrapped_key_is_refused(box: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    _init_shamir(box, capsys)
    (box["sec"] / "site_hmac.key").write_bytes(os.urandom(32))
    with pytest.raises(K.KekError, match="plain beside"):
        load_key(box["sec"] / "site_hmac.key")


def test_the_pid_map_key_is_never_auto_created_in_validation_or_production(tmp_path: Path) -> None:
    for env in ({"TB_ENV": "PRODUCTION"}, {"TB_ENV": "VALIDATION"}, {"TB_ENV": " production "}):
        with pytest.raises(KeyMissingError, match="install ceremony"):
            load_map_key(tmp_path / "pid_map.key", env)
        assert not (tmp_path / "pid_map.key").exists()
    # DEV, TEST and tools that set no TB_ENV (the demo walks): made on first use; install.sh always writes TB_ENV
    assert len(load_map_key(tmp_path / "pid_map.key", {})) == 32


def test_in_a_folder_with_a_kek_the_pid_map_key_is_made_wrapped(tmp_path: Path) -> None:
    sec = tmp_path / "s"
    sec.mkdir()
    kek = os.urandom(32)
    K.write_meta(sec, K.new_meta("file", kek))
    K._write_private(tmp_path / "kek", kek)
    env = {"TB_ENV": "TEST", "TB_KEK_FILE": str(tmp_path / "kek")}
    key = load_map_key(sec / "pid_map.key", env)
    assert not (sec / "pid_map.key").exists() and (sec / "pid_map.key.wrapped").exists()
    assert load_map_key(sec / "pid_map.key", env) == key


# ------------------------------------------------------------------------------------------------ tools/keys.py


def test_init_writes_one_share_file_each_wraps_both_keys_and_prints_no_material(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    site, pmk = _init_shamir(box, capsys)
    files = _shares(box)
    assert len(files) == 3 and all(f.stat().st_mode & 0o077 == 0 for f in files)
    meta = json.loads((box["sec"] / "kek.json").read_text())
    assert meta["backend"] == "shamir" and meta["threshold"] == 2 and "kek" not in meta
    for name, key in (("site_hmac.key", site), ("pid_map.key", pmk)):
        assert not (box["sec"] / name).exists()
        doc = json.loads((box["sec"] / f"{name}.wrapped").read_text())
        assert doc["fingerprint"] == key_fingerprint(key) and key.hex() not in json.dumps(doc)
    rc, out = _cli(capsys, "status", "--secrets", str(box["sec"]), "--json")
    assert rc == 0
    st = json.loads(out)
    assert st["keys"] == {"site_hmac.key": "wrapped", "pid_map.key": "wrapped"} and st["kek"] == "locked"
    shares = [f.read_text().strip() for f in files]
    for text in (out, *(json.dumps(st),)):
        _no_material(text, site, pmk)
        assert not any(s in text for s in shares)
    rc, out = _cli(
        capsys, "init", "--secrets", str(box["sec"]), "--backend", "file", "--kek-out", str(box["tmp"] / "k")
    )
    assert rc == 1 and "already has a KEK" in out


def test_unseal_refuses_a_reused_share_and_a_share_of_another_box(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _init_shamir(box, capsys)
    one = str(_shares(box)[0])
    rc, out = _cli(capsys, "unseal", "--secrets", str(box["sec"]), "--share", one, "--share", one)
    assert rc == 1 and "given twice" in out and not box["kek"].exists()
    other = {"sec": tmp_path / "other-sec", "shares": tmp_path / "other-stewards", "tmp": tmp_path}
    other["sec"].mkdir()
    create_key(other["sec"] / "site_hmac.key")
    assert _cli(capsys, "init", "--secrets", str(other["sec"]), "--backend", "shamir", "--shares-out",
                str(other["shares"]))[0] == 0  # fmt: skip
    theirs = [str(p) for p in sorted(other["shares"].glob("*.txt"))[:2]]
    rc, out = _cli(capsys, "unseal", "--secrets", str(box["sec"]), "--share", theirs[0], "--share", theirs[1])
    assert rc == 1 and "another set" in out and not box["kek"].exists()


def test_unseal_refuses_a_kek_path_inside_the_secrets_folder(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _init_shamir(box, capsys)
    two = _share_args(_shares(box)[1:])
    rc, out = _cli(capsys, "unseal", "--secrets", str(box["sec"]), "--out", str(box["sec"] / "kek"), *two)
    assert rc == 1 and "inside the secrets folder" in out and not (box["sec"] / "kek").exists()


def test_passphrase_init_then_wrap_and_unseal(box: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    site = (box["sec"] / "site_hmac.key").read_bytes()

    # H-96 (ruling 7094934985): the passphrase from a file only root can read, never the environment
    def phrase_file(text: str) -> str:
        f = box["tmp"] / "kek.pass"
        f.write_text(text + "\n", encoding="utf-8")
        f.chmod(0o600)
        return str(f)

    rc, out = _cli(capsys, "init", "--secrets", str(box["sec"]), "--backend", "passphrase", "--scrypt-n", CHEAP_N,
                   "--passphrase-file", phrase_file("a long synthetic test phrase"))  # fmt: skip
    assert rc == 0, out
    assert "a long synthetic test phrase" not in out
    rc, out = _cli(capsys, "unseal", "--secrets", str(box["sec"]), "--passphrase-file",
                   phrase_file("wrong but long enough"))  # fmt: skip
    assert rc == 1 and "not this box's passphrase" in out
    assert _cli(capsys, "unseal", "--secrets", str(box["sec"]), "--passphrase-file",
                phrase_file("a long synthetic test phrase"))[0] == 0  # fmt: skip
    assert load_key(box["sec"] / "site_hmac.key") == site


def test_rotate_kek_rewraps_every_key_and_the_old_shares_stop_working(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    site, pmk = _init_shamir(box, capsys)
    old = [str(p) for p in _shares(box)]
    assert _cli(capsys, "unseal", "--secrets", str(box["sec"]), "--share", old[0], "--share", old[2])[0] == 0
    old_id = json.loads((box["sec"] / "kek.json").read_text())["kek_id"]
    (box["tmp"] / "audit").mkdir(exist_ok=True)  # every rotation is an audit event (ruling 7114085298)
    rc, out = _cli(capsys, "rotate-kek", "--secrets", str(box["sec"]), "--backend", "shamir", "--threshold", "2",
                   "--shares", "3", "--shares-out", str(box["tmp"] / "new-stewards"),
                   "--audit-dir", str(box["tmp"] / "audit"))  # fmt: skip
    assert rc == 0, out
    meta = json.loads((box["sec"] / "kek.json").read_text())
    assert meta["kek_id"] != old_id
    assert load_key(box["sec"] / "site_hmac.key") == site  # the runtime KEK file holds the new KEK
    assert load_key(box["sec"] / "pid_map.key") == pmk
    assert not list(box["sec"].glob("*.next"))
    box["kek"].unlink()
    rc, out = _cli(capsys, "unseal", "--secrets", str(box["sec"]), "--share", old[0], "--share", old[2])
    assert rc == 1 and "another set" in out


def test_check_for_update_refuses_wrapped_keys_with_the_kek_locked(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    rc, out = _cli(capsys, "check", "--secrets", str(box["sec"]), "--for-update", env={"TB_ENV": "PRODUCTION"})
    assert rc == 0 and "plain in PRODUCTION" in out  # plain keys: a warning, not a refusal
    _init_shamir(box, capsys)
    rc, out = _cli(capsys, "check", "--secrets", str(box["sec"]), "--for-update")
    assert rc == 1 and "not unsealed" in out
    assert _cli(capsys, "check", "--secrets", str(box["sec"]))[0] == 0  # without --for-update a locked KEK is no fault
    two = _share_args(_shares(box)[:2])
    assert _cli(capsys, "unseal", "--secrets", str(box["sec"]), *two)[0] == 0
    assert _cli(capsys, "check", "--secrets", str(box["sec"]), "--for-update")[0] == 0


def test_the_inventory_names_every_key_of_ops_058_with_a_rotation_rule(capsys: pytest.CaptureFixture[str]) -> None:
    rc, out = _cli(capsys, "inventory", "--json")
    rows = json.loads(out)
    names = " ".join(r["key"] for r in rows)
    for k in ("KEK", "site_hmac.key", "pid_map.key", "totp.key", "backup key pair", "service tokens",
              "database passwords", "pgBackRest", "Caddy", "Authelia", "OIDC"):  # fmt: skip
        assert k in names, k
    assert all(r["rotation"] and r["holder"] and r["breaks"] and r["compromise"] for r in rows)
    site = next(r for r in rows if r["key"] == "site_hmac.key")
    assert site["rotation"].startswith("never")
    rc, out = _cli(capsys, "rotate", "site_hmac")
    assert rc == 2 and "never" in out


def test_rotate_pid_map_reencrypts_every_row(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], db_url: str
) -> None:
    _init_shamir(box, capsys)
    two = _share_args(_shares(box)[:2])
    assert _cli(capsys, "unseal", "--secrets", str(box["sec"]), *two)[0] == 0
    pm = PidMap(box["sec"] / "pid_map.key", db_url)
    pm.upsert_many([("a" * 32, "00000001"), ("b" * 32, "00000002")])
    pm.upsert_identity([("a" * 32, {"name": "Synthetic Test"})])
    old_id = pm.key_id
    pm.close()
    rc, out = _cli(capsys, "rotate", "pid_map", "--secrets", str(box["sec"]), "--db-url", db_url)
    assert rc == 0 and "3 row(s)" in out, out
    pm = PidMap(box["sec"] / "pid_map.key", db_url)
    try:
        assert pm.key_id != old_id
        assert pm.resolve_many(["a" * 32, "b" * 32]) == {"a" * 32: "00000001", "b" * 32: "00000002"}
        assert pm.identity("a" * 32) == {"name": "Synthetic Test"}
        assert pm._db.fetchall("SELECT pid FROM pid_map WHERE key_id = ?", (old_id,)) == []
    finally:
        pm.close()
    assert not list(box["sec"].glob("*.next"))


def test_the_orchestrator_resolves_chart_numbers_through_a_wrapped_pid_map_key(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], db_url: str
) -> None:
    from orchestrator.scenarios.screen import resolve_mrns

    _init_shamir(box, capsys)
    two = _share_args(_shares(box)[:2])
    assert _cli(capsys, "unseal", "--secrets", str(box["sec"]), *two)[0] == 0
    pm = PidMap(box["sec"] / "pid_map.key", db_url)
    pm.upsert_many([("c" * 32, "00000003")])
    pm.close()
    assert resolve_mrns(box["sec"], ["c" * 32], db_url) == {"c" * 32: "00000003"}


# ------------------------------------------------------------------------------------------------ doctor


def _doctor(sec: Path, env: str, **extra: str) -> doctor.Check:
    inp = doctor.DoctorInputs(env={"TB_ENV": env, "TB_SECRETS_DIR": str(sec), **extra})
    return doctor.check_key_custody(inp)


def test_doctor_fails_plain_site_keys_in_production_and_warns_in_dev(box: dict[str, Path]) -> None:
    assert _doctor(box["sec"], "PRODUCTION").status == "FAIL"
    assert _doctor(box["sec"], "VALIDATION").status == "FAIL"
    assert _doctor(box["sec"], "DEV").status == "WARN"


def test_doctor_passes_wrapped_and_unsealed_and_warns_when_locked(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    site, _ = _init_shamir(box, capsys)
    c = _doctor(box["sec"], "PRODUCTION", TB_KEK_FILE=str(box["kek"]))
    assert c.status == "WARN" and "not unsealed" in c.detail
    two = _share_args(_shares(box)[:2])
    assert _cli(capsys, "unseal", "--secrets", str(box["sec"]), *two)[0] == 0
    c = _doctor(box["sec"], "PRODUCTION", TB_KEK_FILE=str(box["kek"]))
    assert c.status == "PASS", c.detail
    _no_material(c.detail, site)
    # the T-612 check reads the wrapped site key through the KEK too
    site_check = doctor.check_site_key(doctor.DoctorInputs(env={"TB_SECRETS_DIR": str(box["sec"]),
                                                                "TB_KEK_FILE": str(box["kek"])}))  # fmt: skip
    assert site_check.status == "PASS" and key_fingerprint(site) in site_check.detail


def test_doctor_fails_a_kek_in_the_secrets_folder_and_a_mismatched_wrap(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _init_shamir(box, capsys)
    two = _share_args(_shares(box)[:2])
    assert _cli(capsys, "unseal", "--secrets", str(box["sec"]), *two)[0] == 0
    (box["sec"] / "kek").write_bytes(box["kek"].read_bytes())
    c = _doctor(box["sec"], "DEV", TB_KEK_FILE=str(box["kek"]))
    assert c.status == "FAIL" and "beside the keys" in c.detail
    (box["sec"] / "kek").unlink()
    doc = json.loads((box["sec"] / "pid_map.key.wrapped").read_text())
    (box["sec"] / "pid_map.key.wrapped").write_text(json.dumps({**doc, "kek_id": "0" * 32}))
    c = _doctor(box["sec"], "DEV", TB_KEK_FILE=str(box["kek"]))
    assert c.status == "FAIL" and "kek.json names" in c.detail


# ------------------------------------------------------------------------------------------------ apply_update.sh


def test_apply_update_is_refused_before_anything_when_the_kek_is_locked(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _init_shamir(box, capsys)
    bundle = box["tmp"] / "bundle.tar"
    bundle.write_bytes(b"not a bundle")
    env = {k: v for k, v in os.environ.items() if k not in ("TB_KEK_FILE", "CREDENTIALS_DIRECTORY")}
    env.update({"TB_SECRETS_HOST_DIR": str(box["sec"]), "TB_KEK_FILE": str(box["kek"]), "TMPDIR": str(box["tmp"])})
    r = subprocess.run(["sh", str(ROOT / "tools/apply_update.sh"), str(bundle), "--dry-run"], check=False, env=env,
                       capture_output=True, text=True, timeout=60)  # fmt: skip
    assert r.returncode == 1, r.stdout + r.stderr
    assert "not unsealed" in r.stderr and "update REFUSED: the site keys" in r.stderr
    assert "REJECTED" not in r.stderr  # refused before the verifier ran
