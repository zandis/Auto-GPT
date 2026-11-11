"""D-281 on the console's EDC pages and /api/v1: a signed value is locked and changes only with a reason after the
password (and, with TOTP on, a code) is typed again; signing refusals are audited; the trail shows how each signer
re-authenticated and whether each signature still verifies. Synthetic data only (``tests.edc_kit``)."""

from __future__ import annotations

import dataclasses
from typing import Any

from console import totp
from fastapi.testclient import TestClient

from tests import edc_kit as k
from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_edc_pages import NO, PW, _csrf, _ready, _seen, eb  # noqa: F401 - the fixture is used by name
from tests.console.test_identity import Clock, _events


def _confirm_and_sign(eb: dict[str, Any]) -> tuple[TestClient, dict[str, dict[str, Any]]]:  # noqa: F811
    _ready(eb)
    crc, _ = login(eb["app"], "crc", PW)
    page = crc.get("/studies/GZQO/edc").text
    crc.post("/studies/GZQO/edc/drafts", data={"csrf": _csrf(page), "record": NO, "visit": "",
                                               "visit_date": k.VISIT_DATE})  # fmt: skip
    drafts = {d["item"]: d for d in eb["svc"].store.drafts("GZQO", NO)}
    rev = crc.get(f"/studies/GZQO/edc/review/{NO}").text
    for item in ("weight", "urate"):
        crc.post(f"/studies/GZQO/edc/decide/{drafts[item]['id']}", data={"csrf": _csrf(rev), "action": "confirm",
                                                                         "record": NO})  # fmt: skip
    rev = crc.get(f"/studies/GZQO/edc/review/{NO}").text
    r = crc.post("/studies/GZQO/edc/sign", data={"csrf": _csrf(rev), "record": NO, "password": PW, "meaning_ack": "1",
                                                 "seen": _seen(rev)}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text[-400:]
    return crc, drafts


def test_a_signed_value_changes_only_after_the_password_again(eb: dict[str, Any]) -> None:  # noqa: F811
    crc, drafts = _confirm_and_sign(eb)
    w = drafts["weight"]["id"]
    rev = crc.get(f"/studies/GZQO/edc/review/{NO}").text
    assert 'data-testid="locked-edit-weight"' in rev and 'data-testid="unlock-password-edit-weight"' in rev
    assert 'data-testid="unlock-password-reject-weight"' in rev  # withdrawing a signed value needs it too
    edit = {"csrf": _csrf(rev), "action": "edit", "value": "73", "reason": "scale re-read", "source": "ward sheet",
            "record": NO}  # fmt: skip
    r = crc.post(f"/studies/GZQO/edc/decide/{w}", data=edit)  # no password: the orchestrator refuses
    assert r.status_code == 409 and "edc.locked" in r.text
    r = crc.post(f"/studies/GZQO/edc/decide/{w}", data={**edit, "password": "wrong-password-0000"})
    assert r.status_code == 401  # the wrong password changes nothing and counts toward the lockout
    assert eb["svc"].store.draft("GZQO", w)["final"] == "72.5"
    r = crc.post(f"/studies/GZQO/edc/decide/{w}", data={**edit, "password": PW}, follow_redirects=False)
    assert r.status_code == 303, r.text[-400:]
    now = eb["svc"].store.draft("GZQO", w)
    assert now["final"] == "73" and now["signature_id"] is None
    events = _events(eb["backend"].audit_dir)
    assert [e["event"] for e in events if e["event"] == "console.edc_reauth_failed"] == ["console.edc_reauth_failed"]
    trail = crc.get(f"/studies/GZQO/edc/trail/{NO}").text
    assert "password typed again" in trail and 'data-testid="trail-sig-broken"' not in trail
    voids = eb["svc"].trail("GZQO", NO)["voids"]
    assert [(v["draft_id"], v["reason"], v["by_user"]) for v in voids] == [(w, "scale re-read", "crc")]


def test_reject_of_a_signed_value_needs_the_password_too(eb: dict[str, Any]) -> None:  # noqa: F811
    crc, drafts = _confirm_and_sign(eb)
    u = drafts["urate"]["id"]
    rev = crc.get(f"/studies/GZQO/edc/review/{NO}").text
    assert 'data-testid="unlock-password-reject-urate"' in rev
    body = {"csrf": _csrf(rev), "action": "reject", "reason": "wrong lab", "record": NO}
    assert crc.post(f"/studies/GZQO/edc/decide/{u}", data=body).status_code == 409
    r = crc.post(f"/studies/GZQO/edc/decide/{u}", data={**body, "password": PW}, follow_redirects=False)
    assert r.status_code == 303 and eb["svc"].store.draft("GZQO", u)["fate"] == "rejected"


def test_api_v1_unlock_with_totp_needs_a_fresh_code(eb: dict[str, Any]) -> None:  # noqa: F811
    _ready(eb)
    app = eb["app"]
    ident = app.state.identity
    clock = Clock()
    ident.now = clock.unix
    ident.settings = dataclasses.replace(ident.settings, mfa="totp")
    secret = totp.new_secret()
    eb["users"].set_totp("crc", ident.box.seal("crc", secret), totp.step_at(clock.unix()) - 5)
    c = TestClient(app)
    first = totp.totp(secret, clock.unix() - totp.STEP_SECONDS)
    tok = c.post("/api/v1/session", json={"username": "crc", "password": PW, "code": first}).json()["token"]
    hd = {"authorization": f"Bearer {tok}"}
    drafts = {d["item"]: d for d in c.post("/api/v1/studies/GZQO/edc/drafts", json={"record": NO,
              "visit_date": k.VISIT_DATE}, headers=hd).json()["drafts"]}  # fmt: skip
    t = drafts["tophus"]["id"]
    c.post(f"/api/v1/studies/GZQO/edc/drafts/{t}/decide", json={"action": "confirm"}, headers=hd)
    shown = c.get(f"/api/v1/studies/GZQO/edc/drafts?record={NO}", headers=hd).json()["drafts"]
    seen = {str(d["id"]): d["sha"] for d in shown if d["fate"] == "confirmed" and d["signature_id"] is None}
    code = totp.totp(secret, clock.unix())
    r = c.post("/api/v1/studies/GZQO/edc/sign", json={"record": NO, "password": PW, "otp": code, "meaning_ack": True,
                                                      "seen": seen}, headers=hd)  # fmt: skip
    assert r.status_code == 200 and r.json()["signature"]["method"] == "password+totp"
    body = {"action": "reject", "reason": "wrong subject", "password": PW}
    r = c.post(f"/api/v1/studies/GZQO/edc/drafts/{t}/decide", json=body, headers=hd)  # the password alone
    assert r.status_code == 401 and r.json()["error"] == "edc.err.edc.otp"
    clock.tick(seconds=totp.STEP_SECONDS)
    r = c.post(f"/api/v1/studies/GZQO/edc/drafts/{t}/decide",
               json={**body, "otp": totp.totp(secret, clock.unix())}, headers=hd)  # fmt: skip
    assert r.status_code == 200 and r.json()["draft"]["fate"] == "rejected"
    sig = eb["svc"].store.signatures("GZQO")[0]
    assert sig["method"] == "password+totp" and eb["svc"].store.intact(sig)


def test_signing_refusals_are_audited(eb: dict[str, Any]) -> None:  # noqa: F811
    _ready(eb)
    crc, _ = login(eb["app"], "crc", PW)
    page = crc.get("/studies/GZQO/edc").text
    crc.post("/studies/GZQO/edc/drafts", data={"csrf": _csrf(page), "record": NO, "visit": "",
                                               "visit_date": k.VISIT_DATE})  # fmt: skip
    drafts = {d["item"]: d for d in eb["svc"].store.drafts("GZQO", NO)}
    rev = crc.get(f"/studies/GZQO/edc/review/{NO}").text
    crc.post(f"/studies/GZQO/edc/decide/{drafts['weight']['id']}", data={"csrf": _csrf(rev), "action": "confirm",
                                                                         "record": NO})  # fmt: skip
    rev = crc.get(f"/studies/GZQO/edc/review/{NO}").text
    r = crc.post("/studies/GZQO/edc/sign", data={"csrf": _csrf(rev), "record": NO, "password": PW,
                                                 "seen": _seen(rev)})  # fmt: skip
    assert r.status_code == 400
    r = crc.post("/studies/GZQO/edc/sign", data={"csrf": _csrf(rev), "record": NO, "password": PW, "meaning_ack": "1",
                                                 "seen": ""})  # fmt: skip
    assert r.status_code == 400
    got = [e["detail"] for e in _events(eb["backend"].audit_dir) if e["event"] == "console.edc_refused"]
    assert got == [{"record": NO, "code": "edc.meaning_ack"}, {"record": NO, "code": "edc.sign_changed"}]
    assert not eb["svc"].store.signatures("GZQO")
