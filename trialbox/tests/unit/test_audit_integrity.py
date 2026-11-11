"""T-211a (D-355; register CR-042 signing, CR-054 rest; DATA-021, OPS-055): signed audit heads written to off-box
anchor folders, key rotation, and the clock check that makes NTP out of sync a FAIL. Synthetic events only."""

from __future__ import annotations

import json
import os
import socket
import struct
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tb_common import audit, kek
from tb_common.audit import (
    GENESIS,
    HEAD,
    AuditLog,
    AuditSignError,
    canonical,
    line_hash,
    read_public_keys,
    read_signed_heads,
    verify,
    write_head,
)
from tb_common.crypto import ed25519_generate

from tools import audit_verify
from tools.trialbox import doctor

T0 = datetime(2026, 11, 6, 12, tzinfo=UTC)


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    for var in ("TB_KEK_FILE", "TB_KEK_PASSPHRASE", "CREDENTIALS_DIRECTORY", audit.ANCHOR_TARGETS_ENV):
        monkeypatch.delenv(var, raising=False)
    paths = {name: tmp_path / name for name in ("audit", "share", "share2", "secrets", "run")}
    for p in paths.values():
        p.mkdir()
    monkeypatch.setenv("TB_SECRETS_DIR", str(paths["secrets"]))
    monkeypatch.setenv("TB_KEK_FILE", str(paths["run"] / "kek"))
    monkeypatch.setenv("TB_ENV", "DEV")
    return paths


def _events(log: AuditLog, n: int, start: int = 0) -> None:
    for i in range(start, start + n):
        log.append("test.event", ts=T0 + timedelta(minutes=i), actor="tester", detail={"n": i})


def _keys() -> tuple[bytes, bytes]:
    return ed25519_generate()


def _check(audit_dir: Path, share: Path, pub: bytes | None = None) -> audit.VerifyResult:
    trusted = (
        {audit.signing_key_id(pub): pub}
        if pub
        else read_public_keys([share / "keys"] if (share / "keys").is_dir() else [])
    )
    return verify(audit_dir, signed_heads=read_signed_heads(share), trusted_keys=trusted)


def _remove_line_and_rehash(audit_dir: Path, drop: int) -> None:
    """What a process that can write the audit volume does: remove event ``drop`` (1-based), recompute every hash
    after it, and rewrite HEAD.json to match. The unkeyed chain and its anchor then agree."""
    prev, n, last_file = GENESIS, 0, None
    for f in sorted(audit_dir.glob("*.jsonl")):
        out = []
        for raw in f.read_text(encoding="utf-8").splitlines():
            n += 1
            if n == drop:
                continue
            rec = json.loads(raw)
            rec.pop("hash")
            rec["prev_hash"] = prev
            rec["hash"] = prev = line_hash(prev, rec)
            out.append(canonical(rec))
        f.write_text("".join(x + "\n" for x in out), encoding="utf-8")
        last_file = f.name
    write_head(audit_dir, n - 1, prev, last_file)


# ------------------------------------------------------------------------------------------------ acceptance (1)
def test_a_removed_and_recomputed_line_fails_against_the_signed_head(box: dict[str, Path]) -> None:
    priv, pub = _keys()
    log = AuditLog(box["audit"], "UTC")
    _events(log, 6)
    log.sign_head(priv, pub, [box["share"]], ts=T0 + timedelta(hours=1))
    _events(log, 2, start=6)
    assert _check(box["audit"], box["share"], pub).ok
    _remove_line_and_rehash(box["audit"], drop=3)
    assert verify(box["audit"]).ok  # the unkeyed chain and its own anchor agree: the gap D-272 left open
    res = _check(box["audit"], box["share"], pub)
    assert not res.ok and any("does not have the signed hash" in e for e in res.errors), res.errors


def test_dropping_events_below_a_signed_head_fails(box: dict[str, Path]) -> None:
    priv, pub = _keys()
    log = AuditLog(box["audit"], "UTC")
    _events(log, 5)
    log.sign_head(priv, pub, [box["share"]], ts=T0 + timedelta(hours=1))
    for f in box["audit"].glob("*.jsonl"):
        f.unlink()
    (box["audit"] / HEAD).unlink()
    res = _check(box["audit"], box["share"], pub)
    assert not res.ok and any("events were dropped after signing" in e for e in res.errors)


# ------------------------------------------------------------------------------------------------ signing and anchors
def test_sign_head_writes_once_to_every_anchor_folder_and_records_it(box: dict[str, Path]) -> None:
    priv, pub = _keys()
    log = AuditLog(box["audit"], "UTC")
    _events(log, 3)
    rec = log.sign_head(priv, pub, [box["share"], box["share2"]], ts=T0 + timedelta(hours=1))
    assert rec["lines"] == 3 and rec["failed"] == []
    for share in (box["share"], box["share2"]):
        heads = read_signed_heads(share)
        assert [h["lines"] for h in heads] == [3]
        assert (share / "keys" / f"{rec['key_id']}.pub").read_bytes() == pub
    last = json.loads((box["audit"] / "2026-11-06.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert last["event"] == audit.SIGNED_EVENT and last["detail"]["anchors"] == 2 and last["detail"]["lines"] == 3
    res = _check(box["audit"], box["share"], pub)
    assert res.ok, res.errors
    assert any("events 1 to 3 are covered" in n for n in res.notes)


def test_a_signed_head_file_is_never_replaced(box: dict[str, Path]) -> None:
    priv, pub = _keys()
    log = AuditLog(box["audit"], "UTC")
    _events(log, 2)
    rec = log.sign_head(priv, pub, [box["share"]], ts=T0)
    path = next((box["share"] / "heads").glob("*.json"))
    with pytest.raises(AuditSignError, match="never replaced"):
        audit.publish_head(box["share"], {**rec, "hash": "f" * 64}, pub)
    assert json.loads(path.read_text(encoding="utf-8"))["hash"] == rec["hash"]


def test_a_changed_or_foreign_signed_head_fails(box: dict[str, Path]) -> None:
    priv, pub = _keys()
    log = AuditLog(box["audit"], "UTC")
    _events(log, 3)
    log.sign_head(priv, pub, [box["share"]], ts=T0)
    path = next((box["share"] / "heads").glob("*.json"))
    rec = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(canonical({**rec, "lines": 2}), encoding="utf-8")
    res = _check(box["audit"], box["share"], pub)
    assert not res.ok and any("signature does not verify" in e for e in res.errors)
    other_priv, other_pub = _keys()
    forged = audit.make_signed_head(3, rec["hash"], rec["file"], other_priv, other_pub, ts=T0)
    path.write_text(canonical(forged), encoding="utf-8")
    res = _check(box["audit"], box["share"], pub)
    assert not res.ok and any("not a trusted key" in e for e in res.errors)


def test_asking_for_signed_heads_and_finding_none_fails(box: dict[str, Path]) -> None:
    _events(AuditLog(box["audit"], "UTC"), 2)
    res = _check(box["audit"], box["share"])
    assert not res.ok and any("none found" in e for e in res.errors)


def test_sign_refuses_a_broken_chain_an_inside_folder_and_a_missing_share(box: dict[str, Path]) -> None:
    priv, pub = _keys()
    log = AuditLog(box["audit"], "UTC")
    _events(log, 3)
    with pytest.raises(AuditSignError, match="inside the audit folder"):
        log.sign_head(priv, pub, [box["audit"] / "heads"])
    with pytest.raises(AuditSignError, match="no anchor folder took"):
        log.sign_head(priv, pub, [box["share"] / "not-mounted"])
    last = json.loads(sorted(box["audit"].glob("*.jsonl"))[-1].read_text(encoding="utf-8").splitlines()[-1])
    assert last["event"] == audit.SIGNED_EVENT and last["detail"]["anchors"] == 0 and last["detail"]["failed"]
    rec = log.sign_head(priv, pub, [box["share"], box["share"] / "not-mounted"])
    assert len(rec["failed"]) == 1
    f = sorted(box["audit"].glob("*.jsonl"))[-1]
    lines = f.read_text(encoding="utf-8").splitlines()
    rec0 = json.loads(lines[0])
    rec0["actor"] = "someone else"
    lines[0] = canonical(rec0)
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(AuditSignError, match="does not verify"):
        log.sign_head(priv, pub, [box["share2"]])
    assert not (box["share2"] / "heads").exists()


def test_a_key_that_is_not_its_public_keys_pair_signs_nothing(box: dict[str, Path]) -> None:
    priv, _ = _keys()
    _, other_pub = _keys()
    log = AuditLog(box["audit"], "UTC")
    _events(log, 1)
    with pytest.raises(AuditSignError, match="not the pair"):
        log.sign_head(priv, other_pub, [box["share"]])


# ------------------------------------------------------------------------------------------------ rotation
def test_a_new_key_is_trusted_only_through_a_rotation_record(box: dict[str, Path]) -> None:
    old_priv, old_pub = _keys()
    new_priv, new_pub = _keys()
    log = AuditLog(box["audit"], "UTC")
    _events(log, 3)
    log.sign_head(old_priv, old_pub, [box["share"]], ts=T0)
    # without a rotation record, a head signed by another key is refused
    log.sign_head(new_priv, new_pub, [box["share2"]], ts=T0 + timedelta(minutes=1))
    res = verify(box["audit"], signed_heads=read_signed_heads(box["share2"]), trusted_keys={
        audit.signing_key_id(old_pub): old_pub})  # fmt: skip
    assert not res.ok and any("no rotation record" in e for e in res.errors)
    # with the old key's hand-over in the chain, the new key's heads verify
    log.rotate_signing_key(old_priv, old_pub, new_pub, actor="tester", reason="yearly rotation")
    log.sign_head(new_priv, new_pub, [box["share"]], ts=T0 + timedelta(minutes=2))
    res = _check(box["audit"], box["share"], old_pub)
    assert res.ok, res.errors
    assert any("handed over" in n for n in res.notes)
    # the old key signing after its rotation is refused
    log.sign_head(old_priv, old_pub, [box["share"]], ts=T0 + timedelta(minutes=3))
    res = _check(box["audit"], box["share"], old_pub)
    assert not res.ok and any("rotated out" in e for e in res.errors)


def test_a_rotated_out_key_endorses_no_other_key(box: dict[str, Path]) -> None:
    old_priv, old_pub = _keys()
    _, new_pub = _keys()
    evil_priv, evil_pub = _keys()
    log = AuditLog(box["audit"], "UTC")
    _events(log, 2)
    log.rotate_signing_key(old_priv, old_pub, new_pub, actor="tester", reason="rotation")
    log.rotate_signing_key(old_priv, old_pub, evil_pub, actor="intruder", reason="leaked key")
    log.sign_head(evil_priv, evil_pub, [box["share"]])
    res = _check(box["audit"], box["share"], old_pub)
    assert not res.ok and any("was rotated out" in e for e in res.errors)


# ------------------------------------------------------------------------------------------------ the command line
def test_cli_init_sign_check_and_rotate(box: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    _events(AuditLog(box["audit"]), 3)
    a, s, share = str(box["audit"]), str(box["secrets"]), str(box["share"])
    assert audit_verify.main([a, "--init-key", "--secrets", s]) == 0
    assert (box["secrets"] / audit.SIGN_KEY_FILE).stat().st_mode & 0o077 == 0
    assert audit_verify.main([a, "--init-key", "--secrets", s]) == 1  # never replaced
    os.environ[audit.ANCHOR_TARGETS_ENV] = share
    try:
        assert audit_verify.main([a, "--sign-head"]) == 0
    finally:
        del os.environ[audit.ANCHOR_TARGETS_ENV]
    pub = box["secrets"] / audit.SIGN_PUB_FILE
    assert audit_verify.main([a, "--heads", share, "--pubkey", str(pub), "--json"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["ok"] and out["lines"] == 4
    assert audit_verify.main([a, "--rotate-key", "yearly", "--actor", "admin", "--to", share]) == 0
    assert not list(box["secrets"].glob("audit_sign.next*"))
    # the first public key is the trust root; the rotation record hands over to the second
    old_pub = next(p for p in box["secrets"].glob("audit_sign.*.pub") if p.name != audit.SIGN_PUB_FILE)
    assert audit_verify.main([a, "--heads", share, "--pubkey", str(old_pub)]) == 0
    _remove_line_and_rehash(box["audit"], drop=2)
    assert audit_verify.main([a]) == 0
    assert audit_verify.main([a, "--heads", share, "--pubkey", str(old_pub)]) == 1
    assert "does not have the signed hash" in capsys.readouterr().out


def test_cli_without_an_anchor_folder_refuses(box: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    assert audit_verify.main([str(box["audit"]), "--sign-head"]) == 2
    assert "TB_AUDIT_ANCHOR_TARGETS" in capsys.readouterr().err


def test_init_key_in_production_needs_the_kek(
    box: dict[str, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    a, s = str(box["audit"]), str(box["secrets"])
    assert audit_verify.main([a, "--init-key", "--secrets", s]) == 1
    assert "no KEK" in capsys.readouterr().err
    key = os.urandom(kek.KEK_LEN)
    kek.write_meta(box["secrets"], kek.new_meta("file", key))
    kf = box["run"] / "kek"
    kf.write_bytes(key)
    kf.chmod(0o600)
    assert audit_verify.main([a, "--init-key", "--secrets", s]) == 0
    assert (box["secrets"] / (audit.SIGN_KEY_FILE + kek.WRAPPED_SUFFIX)).is_file()
    assert not (box["secrets"] / audit.SIGN_KEY_FILE).exists()
    _events(AuditLog(box["audit"]), 1)
    assert audit_verify.main([a, "--sign-head", "--to", str(box["share"])]) == 0
    kf.unlink()  # the KEK not unsealed: nothing is signed
    assert audit_verify.main([a, "--sign-head", "--to", str(box["share2"])]) == 1
    assert "not signed" in capsys.readouterr().err


# ------------------------------------------------------------------------------------------------ the clock (OPS-055)
def _clock(monkeypatch: pytest.MonkeyPatch, synced: bool | None, offset: float | None) -> None:
    monkeypatch.setattr(audit, "kernel_clock_synced", lambda: synced)

    def fake(server: str, timeout: float = 3.0) -> float:
        if offset is None:
            raise OSError("timed out")
        return offset

    monkeypatch.setattr(audit, "sntp_offset", fake)


def _doctor_clock(env: str, **extra: str) -> doctor.Check:
    return doctor.run(doctor.DoctorInputs(env={"TB_ENV": env, **extra}), (doctor.check_clock,))[0]


@pytest.mark.parametrize("env", ["DEV", "PRODUCTION"])
def test_doctor_fails_at_61_seconds_of_skew(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    _clock(monkeypatch, True, 61.0)
    c = _doctor_clock(env, TB_NTP_SERVER="ntp.hospital.test")
    assert c.status == "FAIL" and "+61.0 s" in c.detail
    _clock(monkeypatch, True, -59.0)
    assert _doctor_clock(env, TB_NTP_SERVER="ntp.hospital.test").status == "PASS"


@pytest.mark.parametrize(
    ("env", "want"), [("DEV", "WARN"), ("TEST", "WARN"), ("VALIDATION", "FAIL"), ("PRODUCTION", "FAIL")]
)
def test_ntp_out_of_sync_is_a_fail_on_a_real_box(monkeypatch: pytest.MonkeyPatch, env: str, want: str) -> None:
    _clock(monkeypatch, False, None)
    c = _doctor_clock(env)
    assert c.status == want and "not NTP-synchronised" in c.detail
    _clock(monkeypatch, True, None)
    c = _doctor_clock(env, TB_NTP_SERVER="ntp.hospital.test")
    assert c.status == want and "did not answer" in c.detail
    _clock(monkeypatch, None, None)
    assert _doctor_clock(env).status == want
    _clock(monkeypatch, True, None)
    assert _doctor_clock(env).status == "PASS"


def test_the_skew_limit_is_a_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    _clock(monkeypatch, True, 20.0)
    assert _doctor_clock("PRODUCTION", TB_NTP_SERVER="ntp", TB_CLOCK_MAX_SKEW_S="10").status == "FAIL"


def test_sntp_offset_against_a_local_time_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """One SNTP exchange with a fake server on 127.0.0.1 whose clock is 90 s behind ours."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    now = 1_800_000_000.0

    def serve() -> None:
        _, addr = srv.recvfrom(512)
        t = now - 90 + 2208988800
        ts = struct.pack("!II", int(t), 0)
        srv.sendto(b"\x24" + b"\0" * 31 + ts + ts, addr)

    th = threading.Thread(target=serve, daemon=True)
    th.start()
    monkeypatch.setattr("tb_common.audit.time.time", lambda: now)
    try:
        assert audit.sntp_offset(f"127.0.0.1:{port}", timeout=5) == pytest.approx(90.0)
    finally:
        th.join(5)
        srv.close()


def test_kernel_clock_state_reads_without_changing_anything() -> None:
    assert audit.kernel_clock_synced() in (True, False, None)
