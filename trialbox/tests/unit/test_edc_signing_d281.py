"""D-281 EDC signature controls (fix group FG D-281): the record lock (CR-035), the keyed signature over the whole act
and its check before send and export (CR-036), append-only trail tables, the audit line inside the transaction
(SEC-6), audited refusals (SEC-7), the plain legal reason in the ODM file (REG-021) and the REDCap version call
answered in plain text (STD-060). Synthetic data only (``tests.edc_kit``)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import httpx
import pytest
from edc import odm
from edc.store import KEY_ENV, KEY_FILE, SIG_VERSION, EdcError, EdcStore, _legacy_sha, sign_key_of
from fastapi import FastAPI
from fastapi.testclient import TestClient
from rc_bridge.client import RedcapClient
from tb_common.audit import AuditLog

from tests import edc_kit as k

NS = {"o": "http://www.cdisc.org/ns/odm/v1.3"}
SHEET = {"text": "ward scale sheet", "day": "2026-11-05"}


def _drafts(svc: Any) -> dict[str, dict[str, Any]]:
    return {d["item"]: d for d in svc.store.drafts(k.STUDY, k.RECORD)}


def _signed(tmp_path: Path) -> tuple[Any, dict[str, dict[str, Any]], dict[str, Any]]:
    svc, _, _ = k.service(tmp_path)
    k.ready(svc)
    built = svc.build(k.STUDY, k.RECORD, k.PID, "", k.VISIT_DATE, "crc")
    for d in built:
        if d["state"] == "drafted":
            svc.decide(k.STUDY, d["id"], "confirm", by="crc")
    sig = svc.sign(k.STUDY, k.RECORD, "", signer="crc", printed_name="Chen Mei", role="coordinator",
                   meaning="transcribed", meaning_text="I checked each value.", lang="en", seen=k.seen(svc),
                   method="password+totp")  # fmt: skip
    return svc, _drafts(svc), sig


def _events(svc: Any) -> list[dict[str, Any]]:
    out = []
    for f in sorted(Path(svc.audit.directory).glob("*.jsonl")):
        out += [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
    return out


# ------------------------------------------------------------------ CR-035: the record lock
def test_a_signed_value_is_locked_until_the_person_re_authenticates(tmp_path: Path) -> None:
    svc, d, sig = _signed(tmp_path)
    w = d["weight"]["id"]
    for action, kw in (("edit", {"value": "73", "reason": "re-read", "citation": SHEET}),
                       ("reject", {"reason": "wrong subject"}), ("confirm", {})):  # fmt: skip
        with pytest.raises(EdcError) as e:
            svc.decide(k.STUDY, w, action, by="crc2", **kw)
        assert (e.value.code, e.value.status) == ("edc.locked", 423)
    assert _drafts(svc)["weight"]["signature_id"] == sig["id"]  # nothing was unlinked quietly
    with pytest.raises(EdcError) as e:  # unlocked, but no reason: refused
        svc.decide(k.STUDY, w, "edit", value="73", citation=SHEET, by="crc", unlock=True)
    assert e.value.code == "edc.reason"
    out = svc.decide(k.STUDY, w, "edit", value="73", reason="scale re-read", citation=SHEET, by="crc", unlock=True)
    assert out["final"] == "73" and out["signature_id"] is None
    voids = svc.trail(k.STUDY, k.RECORD)["voids"]
    assert [(v["signature_id"], v["draft_id"], v["action"], v["reason"], v["by_user"]) for v in voids] == [
        (sig["id"], w, "edit", "scale re-read", "crc")
    ]
    # the other values stay signed and sendable; the changed one waits for a new signature
    assert {x["item"] for x in svc.store.sendable(k.STUDY)} == {"brthdat", "sex", "urate", "mh_gout", "tophus"}


def test_a_sent_value_is_locked_too(tmp_path: Path) -> None:
    svc, d, _ = _signed(tmp_path)
    assert svc.send_redcap(k.STUDY, "crc")["count"] == 6
    with pytest.raises(EdcError) as e:
        svc.decide(k.STUDY, d["urate"]["id"], "edit", value="8.5", reason="lab re-read", citation=SHEET, by="crc")
    assert e.value.code == "edc.locked"


def test_the_orchestrator_unlocks_only_after_re_authentication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator.edc_api import router
    from tb_common.service_auth import actor_header

    svc, d, _ = _signed(tmp_path)
    app = FastAPI()
    app.include_router(router(lambda: svc))
    c = TestClient(app)
    path = f"/studies/{k.STUDY}/edc/drafts/{d['weight']['id']}/decide"
    body = {"action": "edit", "value": "73", "reason": "re-read", "citation": SHEET}
    # DEV/TEST without a token: the console says "unlock" only after it re-authenticated the person
    r = c.post(path, json=body, headers=actor_header("crc", role="coordinator"))
    assert r.status_code == 423 and r.json()["detail"]["code"] == "edc.locked"
    # with a token: only an assertion made right after the password check unlocks; a body flag counts for nothing
    monkeypatch.setenv("TB_SERVICE_TOKEN", "edc-test-token-0123456789abcdef")
    r = c.post(path, json={**body, "unlock": True}, headers=actor_header("crc", "s1", role="coordinator"))
    assert r.status_code == 423
    r = c.post(path, json=body, headers=actor_header("crc", "reauth-0123abcd", role="coordinator"))
    assert r.status_code == 200 and r.json()["final"] == "73"


# ------------------------------------------------------------------ CR-036: the keyed binding over the whole act
def test_the_signature_covers_the_whole_act_and_is_checked_before_send_and_export(tmp_path: Path) -> None:
    svc, _, sig = _signed(tmp_path)
    assert sig["sig_version"] == SIG_VERSION and sig["method"] == "password+totp" and sig["key_id"]
    assert svc.store.intact(sig)
    for col, val in (("printed_name", "Someone Else"), ("meaning_text", "I did not check."), ("signer", "eve"),
                     ("at", "2026-11-11T00:00:00+09:00"), ("method", "password"), ("role", "investigator"),
                     ("visit", "week_2"), ("lang", "ja"), ("drafts", "{}")):  # fmt: skip
        assert not svc.store.intact({**sig, col: val}), col
    # another key cannot vouch for the same row
    other = EdcStore(sign_key=b"another-key-of-32-bytes-for-test")
    assert not other.intact(sig)
    assert other.sendable(k.STUDY) == [] and other.signed(k.STUDY) == []
    other.close()
    assert len(svc.store.sendable(k.STUDY)) == 6 and len(svc.store.signed(k.STUDY)) == 6


def test_a_rewritten_signature_row_stops_send_and_export(tmp_path: Path) -> None:
    """A writer who goes around the trigger (the table owner) and rewrites the row cannot re-make the keyed hash."""
    svc, _, sig = _signed(tmp_path)
    with svc.store.db.transaction() as tx:
        tx.execute("ALTER TABLE signature DISABLE TRIGGER signature_append_only")
        tx.execute("UPDATE signature SET printed_name = 'Someone Else' WHERE id = ?", (sig["id"],))
        tx.execute("ALTER TABLE signature ENABLE TRIGGER signature_append_only")
    assert svc.store.sendable(k.STUDY) == [] and svc.store.signed(k.STUDY) == []
    assert svc.send_redcap(k.STUDY, "crc")["count"] == 0
    trail = svc.trail(k.STUDY, k.RECORD)["signatures"]
    assert [s["intact"] for s in trail] == [False]


def test_an_old_unkeyed_signature_is_checked_by_its_own_rule(tmp_path: Path) -> None:
    svc, _, sig = _signed(tmp_path)
    shas = {int(i): str(v) for i, v in json.loads(sig["drafts"]).items()}
    old = {**sig, "sig_version": 1, "content_sha": _legacy_sha(shas)}
    assert svc.store.intact(old)
    assert not svc.store.intact({**old, "drafts": json.dumps({"1": "0" * 64})})
    assert not svc.store.intact({**sig, "sig_version": 7})  # an unknown version never passes


@pytest.mark.parametrize("table", ["signature", "decision", "sent", "signature_void", "switch_event", "map_event"])
def test_the_trail_tables_are_append_only(tmp_path: Path, table: str) -> None:
    svc, d, _ = _signed(tmp_path)
    svc.send_redcap(k.STUDY, "crc")
    svc.decide(k.STUDY, d["weight"]["id"], "edit", value="73", reason="re-read", citation=SHEET, by="crc", unlock=True)
    assert svc.store.db.fetchval(f"SELECT count(*) FROM {table}") > 0
    for stmt in (f"UPDATE {table} SET at = 'x'", f"DELETE FROM {table}", f"TRUNCATE {table}"):
        with pytest.raises(Exception, match="append-only"):
            svc.store.db.execute(stmt)
    # a second store on the same schema finds the triggers there and adds none
    again = EdcStore()
    names = again.db.fetchall("SELECT tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid JOIN "
                              "pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = current_schema() "
                              "AND NOT t.tgisinternal")  # fmt: skip
    again.close()
    assert len(names) == len({n[0] for n in names}) == 12


def test_the_signature_key(tmp_path: Path) -> None:
    assert sign_key_of({"TB_ENV": "TEST"}) == sign_key_of({"TB_ENV": "DEV"})  # a fixed key on a test box only
    with pytest.raises(EdcError) as e:
        sign_key_of({"TB_ENV": "PRODUCTION"})
    assert e.value.code == "edc.sign_key"
    made = sign_key_of({"TB_ENV": "PRODUCTION"}, tmp_path / "secrets")  # made once in the secrets folder
    f = tmp_path / "secrets" / KEY_FILE
    assert len(made) == 32 and (f.stat().st_mode & 0o777) == 0o600
    assert sign_key_of({}, tmp_path / "secrets") == made  # never replaced
    named = tmp_path / "elsewhere.key"
    named.write_bytes(b"short")
    with pytest.raises(EdcError):
        sign_key_of({KEY_ENV: str(named)}, tmp_path / "secrets")
    with pytest.raises(EdcError):
        EdcStore(sign_key=b"short")


# ------------------------------------------------------------------ SEC-6: the audit line inside the transaction
class _Broken(AuditLog):
    def append(self, event: str, *a: Any, **kw: Any) -> Any:
        if event in ("edc.sign", "edc.decide") and "refused" not in (kw.get("detail") or {}):
            raise OSError("the audit volume is full")
        return super().append(event, *a, **kw)


def test_no_signature_and_no_decision_without_its_audit_line(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    k.ready(svc)
    built = {d["item"]: d for d in svc.build(k.STUDY, k.RECORD, k.PID, "", k.VISIT_DATE, "crc")}
    svc.decide(k.STUDY, built["weight"]["id"], "confirm", by="crc")
    svc.audit = _Broken(tmp_path / "audit2")
    with pytest.raises(OSError):
        svc.decide(k.STUDY, built["urate"]["id"], "confirm", by="crc")
    assert _drafts(svc)["urate"]["fate"] == "open"  # rolled back
    assert [r["action"] for r in svc.trail(k.STUDY, k.RECORD)["decisions"]] == ["confirm"]
    with pytest.raises(OSError):
        svc.sign(k.STUDY, k.RECORD, "", signer="crc", printed_name="Chen Mei", role="coordinator",
                 meaning="transcribed", meaning_text="I checked each value.", lang="en", seen=k.seen(svc))  # fmt: skip
    assert svc.store.signatures(k.STUDY) == [] and _drafts(svc)["weight"]["signature_id"] is None


def test_the_signature_audit_line_names_the_method_and_the_hash(tmp_path: Path) -> None:
    svc, _, sig = _signed(tmp_path)
    ev = [e for e in _events(svc) if e["event"] == "edc.sign"]
    assert len(ev) == 1 and ev[0]["detail"]["content_sha"] == sig["content_sha"]
    assert ev[0]["detail"]["method"] == "password+totp" and ev[0]["detail"]["signature"] == sig["id"]


# ------------------------------------------------------------------ SEC-7: refusals are audited
def test_refusals_are_audited(tmp_path: Path) -> None:
    from orchestrator.edc_api import router
    from tb_common.service_auth import actor_header

    svc, d, _ = _signed(tmp_path)
    with pytest.raises(EdcError):
        svc.decide(k.STUDY, 999_999, "confirm", by="crc")
    with pytest.raises(EdcError):
        svc.decide(k.STUDY, d["weight"]["id"], "edit", value="abc", reason="x", citation=SHEET, by="crc", unlock=True)
    with pytest.raises(EdcError):
        svc.decide(k.STUDY, d["weight"]["id"], "reject", reason="x", by="crc")  # locked
    app = FastAPI()
    app.include_router(router(lambda: svc))
    c = TestClient(app)
    sign = {"record": k.RECORD, "printed_name": "x", "meaning_text": "x", "seen": {}}
    assert c.post(f"/studies/{k.STUDY}/edc/sign", json=sign, headers=actor_header("v1", role="viewer")
                  ).status_code == 403  # fmt: skip
    svc.set_switch(k.STUDY, False, by="pi", role="investigator")
    with pytest.raises(EdcError):
        svc.sign(k.STUDY, k.RECORD, "", signer="crc", printed_name="Chen Mei", role="coordinator",
                 meaning="transcribed", meaning_text="x", lang="en", seen={})  # fmt: skip
    with pytest.raises(EdcError):
        svc.decide(k.STUDY, d["weight"]["id"], "confirm", by="crc")
    got = [(e["event"], e["detail"].get("refused") or e["detail"].get("code")) for e in _events(svc)
           if e["detail"].get("refused") or e["event"] == "edc.refused"]  # fmt: skip
    assert got == [("edc.decide", "edc.no_draft"), ("edc.decide", "edc.invalid"), ("edc.decide", "edc.locked"),
                   ("edc.refused", "edc.role"), ("edc.sign", "edc.off"), ("edc.decide", "edc.off")]  # fmt: skip


def test_a_missing_re_authentication_at_signing_is_audited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator.edc_api import router
    from tb_common.service_auth import actor_header

    svc, _, _ = k.service(tmp_path)
    k.ready(svc)
    app = FastAPI()
    app.include_router(router(lambda: svc))
    monkeypatch.setenv("TB_SERVICE_TOKEN", "edc-test-token-0123456789abcdef")
    sign = {"record": k.RECORD, "printed_name": "x", "meaning_text": "x", "seen": {}}
    r = TestClient(app).post(f"/studies/{k.STUDY}/edc/sign", json=sign,
                             headers=actor_header("crc", "s1", role="coordinator"))  # fmt: skip
    assert r.status_code == 403
    ev = [e for e in _events(svc) if e["event"] == "edc.refused"]
    assert [(e["actor"], e["ruleset"], e["detail"]) for e in ev] == [
        ("crc", k.STUDY, {"action": "sign", "code": "edc.reauth_needed"})
    ]


# ------------------------------------------------------------------ REG-021: no conformance claim in the file
def test_the_odm_file_makes_no_part_11_claim(tmp_path: Path) -> None:
    svc, _, _ = _signed(tmp_path)
    text = svc.export_odm(k.STUDY, "crc")
    root = ET.fromstring(text)
    reason = root.find(".//o:SignatureDef/o:LegalReason", NS)
    assert reason is not None and reason.text == odm.LEGAL_REASON
    assert odm.LEGAL_REASON == "Electronic signature of the person named; see the site's validation summary"
    assert "Part 11" not in text and "ER/ES" not in text and "CFR" not in text


# ------------------------------------------------------------------ STD-060: the REDCap version call
@pytest.mark.parametrize("answer", ["16.0.8", '"16.0.8"', "16.0.8\n"])
def test_the_version_call_reads_plain_text(answer: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert b"content=version" in request.content
        return httpx.Response(200, text=answer, headers={"content-type": "text/html; charset=UTF-8"})

    rc = RedcapClient(
        "https://rc.example/",
        "0123456789ABCDEF0123456789ABCDEF",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert rc.version() == "16.0.8" and rc.check_version() == "16.0.8"
