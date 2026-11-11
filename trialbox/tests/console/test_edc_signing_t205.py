"""T-205 (D-391): TST-EDC-04, the Part 11-style walk (signature manifestation, re-authentication, reason for change,
record lock, the per-record audit trail and export), once with a local account and once with a directory (OIDC)
account that signs by a fresh sign-in at the identity provider; a ``reauth-`` session a shared service token cannot
forge (SEC-16); the signature meaning pinned in three languages (REG-021); the data-entry reasons for four more problem
codes. Synthetic data only (``tests.edc_kit``)."""

from __future__ import annotations

import dataclasses
import html
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from console.entry_pages import why
from console.i18n import translate
from console.oidc import OidcClient, OidcSettings
from edc import odm
from edc.service import ODM_MEANING
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tb_common.service_auth import actor_header, actor_key

from tests import edc_kit as k
from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_edc_pages import NO, PW, _csrf, _ready, _seen, eb  # noqa: F401 - the fixture is used by name
from tests.console.test_identity import ISSUER, REDIRECT, FakeIdp, _events

MEANING = {
    "en": ODM_MEANING,
    "ja": "この電子署名により、各値をこのページで横に示された出典と照合したこと、およびこれらがこの被験者と来院について"
    "私が確定した値であることを確認します。TrialBox が引用した記載は病院の記録の写しであり、記録そのものではありません。",
    "zh-TW": "本人以此電子簽章確認：已將每個值與本頁其旁所引用的來源核對，且這些是本人就此受試者與訪視所確認的值。"
    "TrialBox 引用的段落是醫院紀錄的複本，並非紀錄本身。",
}


# ------------------------------------------------------------------ REG-021: the words of the signature
def test_the_signature_meaning_is_pinned_in_three_languages() -> None:
    assert ODM_MEANING == (
        "With this electronic signature I confirm that I compared each value with the source cited beside it on this "
        "page, and that these are the values I confirmed for this subject and visit. A passage quoted by TrialBox is "
        "a copy of the hospital record, not the record itself."
    )
    for lang, text in MEANING.items():
        assert translate(lang, "edc.sign.meaning") == text, lang
    # neutral: no regulation named, no claim that the values are correct, no "checked against the hospital record"
    for text in MEANING.values():
        for word in ("Part 11", "ER/ES", "correct", "正しい", "正確", "cited hospital record"):
            assert word not in text
    assert odm.LEGAL_REASON == "Electronic signature of the person named; see the site's validation summary"


# ------------------------------------------------------------------ TST-EDC-04 with a local account
def _draft_and_confirm(c: TestClient, svc: Any) -> None:
    page = c.get("/studies/GZQO/edc").text
    r = c.post("/studies/GZQO/edc/drafts", data={"csrf": _csrf(page), "record": NO, "visit": "",
                                                 "visit_date": k.VISIT_DATE}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text[-400:]
    rev = c.get(f"/studies/GZQO/edc/review/{NO}").text
    drafts = {d["item"]: d for d in svc.store.drafts("GZQO", NO)}
    for item in ("weight", "urate"):
        r = c.post(f"/studies/GZQO/edc/decide/{drafts[item]['id']}", data={"csrf": _csrf(rev), "action": "confirm",
                                                                           "record": NO}, follow_redirects=False)  # fmt: skip
        assert r.status_code == 303


def _walk_after_signing(eb: dict[str, Any], c: TestClient, signer: str, name: str, method: str,  # noqa: F811
                        unlock: dict[str, str] | None) -> None:  # fmt: skip
    """The rest of TST-EDC-04: what the signature shows, the lock, the reason for change, the trail and the file."""
    svc = eb["svc"]
    sig = svc.store.signatures("GZQO")[-1]
    assert (sig["signer"], sig["printed_name"], sig["meaning"], sig["method"]) == (signer, name, "transcribed", method)
    assert sig["meaning_text"] == ODM_MEANING and sig["lang"] == "en" and sig["at"]
    assert svc.store.intact(sig)
    rev = c.get(f"/studies/GZQO/edc/review/{NO}").text
    assert 'data-testid="signed-by-weight"' in rev and name in rev  # manifestation beside the value (E-12)
    w = next(d for d in svc.store.drafts("GZQO", NO) if d["item"] == "weight")["id"]
    edit = {"csrf": _csrf(rev), "action": "edit", "value": "73", "reason": "scale re-read", "source": "ward sheet",
            "record": NO}  # fmt: skip
    r = c.post(f"/studies/GZQO/edc/decide/{w}", data=edit)  # the record lock: no re-authentication, no change
    assert r.status_code == 409 and "edc.locked" in r.text
    assert svc.store.draft("GZQO", w)["final"] == "72.5"
    if unlock is not None:  # a local account unlocks with a reason and the password again
        r = c.post(f"/studies/GZQO/edc/decide/{w}", data={**edit, **unlock}, follow_redirects=False)
        assert r.status_code == 303, r.text[-400:]
        assert svc.store.draft("GZQO", w)["final"] == "73"
        voids = svc.trail("GZQO", NO)["voids"]
        assert [(v["draft_id"], v["reason"], v["by_user"]) for v in voids] == [(w, "scale re-read", signer)]
    trail = c.get(f"/studies/GZQO/edc/trail/{NO}").text
    assert 'data-testid="trail-signatures"' in trail and name in trail
    assert html.escape(translate("en", f"edc.trail.method.{method}"), quote=False) in trail
    assert 'data-testid="trail-sig-broken"' not in trail
    out = c.get("/studies/GZQO/edc/export.odm.xml")
    assert out.status_code == 200 and "<Signature>" in out.text
    assert html.escape(ODM_MEANING, quote=False) in out.text or ODM_MEANING in out.text
    assert "Part 11" not in out.text


def test_tst_edc_04_with_a_local_account(eb: dict[str, Any]) -> None:  # noqa: F811
    _ready(eb)
    crc, _ = login(eb["app"], "crc", PW)
    _draft_and_confirm(crc, eb["svc"])
    rev = crc.get(f"/studies/GZQO/edc/review/{NO}").text
    assert 'data-testid="edc-password"' in rev and 'data-testid="edc-sign-oidc"' not in rev
    assert html.escape(ODM_MEANING, quote=False) in rev or ODM_MEANING in rev
    r = crc.post("/studies/GZQO/edc/sign", data={"csrf": _csrf(rev), "record": NO, "password": "wrong-password-00",
                                                 "meaning_ack": "1", "seen": _seen(rev)})  # fmt: skip
    assert r.status_code == 401 and not eb["svc"].store.signatures("GZQO")
    r = crc.post("/studies/GZQO/edc/sign", data={"csrf": _csrf(rev), "record": NO, "password": PW,
                                                 "meaning_ack": "1", "seen": _seen(rev)}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text[-400:]
    _walk_after_signing(eb, crc, "crc", "Chen Mei", "password", {"password": PW})


# ------------------------------------------------------------------ TST-EDC-04 with a directory (OIDC) account
def _oidc_on(eb: dict[str, Any], tmp_path: Path) -> FakeIdp:  # noqa: F811
    secret = tmp_path / "oidc_secret"
    secret.write_text("client-secret-value\n")
    settings = OidcSettings(enabled=True, issuer=ISSUER, client_id="trialbox-console", client_secret_file=secret,
                            redirect_url=REDIRECT, group_roles=(("tb-coordinators", "coordinator"),),
                            logout_url="https://auth.hosp.test/logout")  # fmt: skip
    ident = eb["app"].state.identity
    ident.settings = dataclasses.replace(ident.settings, oidc=settings)
    idp = FakeIdp(time.time)
    ident.oidc_client = OidcClient(settings, transport=httpx.MockTransport(idp.handler))
    eb["app"].state.helpers.team.add_entry(
        "GZQO", username="crc.tanaka", name="Tanaka Ken", role="crc", tasks=(), start="2026-01-01", end=None,
        training_day="2026-01-01", training_ref="GCP-1", by="admin", at="2026-01-01T00:00:00+00:00")  # fmt: skip
    return idp


def _oidc_sign_in(eb: dict[str, Any], idp: FakeIdp) -> TestClient:  # noqa: F811
    c = TestClient(eb["app"])
    r = c.get("/auth/oidc/start", follow_redirects=False)
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert "prompt" not in q and "max_age" not in q  # an ordinary sign-in is not forced
    idp.claims = idp.base_claims(q["nonce"][0])
    assert c.get("/auth/oidc/callback", params={"code": "c-1", "state": q["state"][0]}).status_code == 200
    assert c.get("/home", follow_redirects=False).status_code == 200  # signed in
    return c


def _press_sign(c: TestClient) -> dict[str, list[str]]:
    rev = c.get(f"/studies/GZQO/edc/review/{NO}").text
    assert 'data-testid="edc-sign-oidc"' in rev and 'data-testid="edc-password"' not in rev
    r = c.post("/studies/GZQO/edc/sign", data={"csrf": _csrf(rev), "record": NO, "meaning_ack": "1",
                                               "seen": _seen(rev)}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and r.headers["location"].startswith(ISSUER), r.text[-400:]
    return parse_qs(urlparse(r.headers["location"]).query)


def _come_back(c: TestClient, idp: FakeIdp, q: dict[str, list[str]], **claims: Any) -> str:
    """The provider answers the forced sign-in; a claim given as None is left out."""
    got = {**idp.base_claims(q["nonce"][0]), "auth_time": int(time.time()), **claims}
    idp.claims = {key: v for key, v in got.items() if v is not None}
    page = c.get("/auth/oidc/callback", params={"code": "c-2", "state": q["state"][0]})
    assert page.status_code == 200 and 'data-testid="oidc-done"' in page.text
    m = re.search(r'url=([^"]+)"', page.text)
    assert m
    return html.unescape(m.group(1))


def test_tst_edc_04_with_a_directory_account(eb: dict[str, Any], tmp_path: Path) -> None:  # noqa: F811
    _ready(eb)
    idp = _oidc_on(eb, tmp_path)
    c = _oidc_sign_in(eb, idp)
    _draft_and_confirm(c, eb["svc"])
    q = _press_sign(c)
    assert q["prompt"] == ["login"] and q["max_age"] == ["0"]  # the provider asks for the credentials again
    target = _come_back(c, idp, q)
    assert target.startswith("/studies/GZQO/edc/sign/oidc/") and "reauth=" in target
    assert not eb["svc"].store.signatures("GZQO")  # the provider's answer alone signs nothing
    r = c.get(target, follow_redirects=False)
    assert r.status_code == 303 and "signed=1" in r.headers["location"], r.text[-400:]
    assert c.get(target, follow_redirects=False).status_code == 409  # the proof is used up
    assert len(eb["svc"].store.signatures("GZQO")) == 1
    _walk_after_signing(eb, c, "crc.tanaka", "Tanaka Ken", "oidc+mfa", None)
    # a directory account cannot unlock with a password it does not have: the value stays locked
    w = next(d for d in eb["svc"].store.drafts("GZQO", NO) if d["item"] == "weight")["id"]
    rev = c.get(f"/studies/GZQO/edc/review/{NO}").text
    r = c.post(f"/studies/GZQO/edc/decide/{w}", data={"csrf": _csrf(rev), "action": "edit", "value": "73",
                                                      "reason": "re-read", "source": "sheet", "record": NO,
                                                      "password": "anything-at-all"})  # fmt: skip
    assert r.status_code == 409 and eb["svc"].store.draft("GZQO", w)["final"] == "72.5"


@pytest.mark.parametrize(
    "claims,reason",
    [
        ({"auth_time": int(time.time()) - 3600}, "the identity provider did not authenticate the person again"),
        ({"auth_time": None}, "the identity provider did not authenticate the person again"),
        ({"amr": ["pwd"]}, "the identity provider did not report a second factor"),
        ({"sub": "S-9999"}, "another person signed in at the identity provider"),
        ({"preferred_username": "crc.other"}, "another person signed in at the identity provider"),
    ],
)
def test_a_directory_signature_needs_a_fresh_sign_in_with_a_second_factor_by_the_same_person(
    eb: dict[str, Any],  # noqa: F811
    tmp_path: Path,
    claims: dict[str, Any],
    reason: str,
) -> None:
    _ready(eb)
    idp = _oidc_on(eb, tmp_path)
    c = _oidc_sign_in(eb, idp)
    _draft_and_confirm(c, eb["svc"])
    q = _press_sign(c)
    target = _come_back(c, idp, q, **claims)
    assert target.endswith("?reauth_failed=1")
    assert c.get(target, follow_redirects=False).status_code == 401
    assert not eb["svc"].store.signatures("GZQO")
    failed = [e for e in _events(eb["backend"].audit_dir) if e["event"] == "console.reauth_failed"]
    assert failed and failed[-1]["detail"] == {"via": "oidc", "reason": reason}
    assert c.get("/home", follow_redirects=False).status_code == 200  # the session is the one it was


def test_a_proof_works_only_in_the_session_that_pressed_the_button(eb: dict[str, Any], tmp_path: Path) -> None:  # noqa: F811
    _ready(eb)
    idp = _oidc_on(eb, tmp_path)
    c = _oidc_sign_in(eb, idp)
    _draft_and_confirm(c, eb["svc"])
    target = _come_back(c, idp, _press_sign(c))
    other = _oidc_sign_in(eb, idp)  # the same person in another browser
    assert other.get(target, follow_redirects=False).status_code == 409
    assert c.get(target, follow_redirects=False).status_code == 409  # the try used the pending signature up
    assert not eb["svc"].store.signatures("GZQO")


def test_the_new_signing_texts_are_in_three_languages() -> None:
    assert "hospital sign-in" in translate("en", "edc.sign.go_oidc")
    assert "local account" in translate("en", "edc.err.edc.sign_sso")
    for lang in ("en", "ja", "zh-TW"):
        for key in ("edc.err.edc.sign_oidc_page", "edc.err.edc.sign_oidc_expired", "edc.err.edc.reauth_oidc",
                    "edc.err.edc.idp_unreachable", "edc.err.edc.reauth_shared_token", "edc.sign.oidc",
                    "edc.sign.go_oidc", "edc.trail.method.oidc+mfa"):  # fmt: skip
            assert translate(lang, key) != key, (lang, key)


# ------------------------------------------------------------------ SEC-16: a shared token cannot forge reauth-
def test_a_shared_token_cannot_vouch_for_a_re_authentication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator.edc_api import router

    svc, _, _ = k.service(tmp_path)
    k.ready(svc)
    built = svc.build(k.STUDY, k.RECORD, k.PID, "", k.VISIT_DATE, "crc")
    for d in built:
        if d["state"] == "drafted":
            svc.decide(k.STUDY, d["id"], "confirm", by="crc")
    app = FastAPI()
    app.include_router(router(lambda: svc))
    c = TestClient(app)
    sign = {"record": k.RECORD, "printed_name": "Chen Mei", "meaning_text": ODM_MEANING,
            "seen": {str(i): s for i, s in k.seen(svc).items()}}  # fmt: skip
    token = "edc-test-token-0123456789abcdef"
    monkeypatch.setenv("TB_SERVICE_TOKEN", token)
    monkeypatch.setenv("TB_ENV", "VALIDATION")  # one shared token, outside DEV and TEST: anyone with it could sign
    r = c.post(f"/studies/{k.STUDY}/edc/sign", json=sign, headers=actor_header("crc", "reauth-0123abcd",
                                                                               role="coordinator"))  # fmt: skip
    assert r.status_code == 403 and r.json()["detail"]["code"] == "edc.reauth_shared_token"
    assert not svc.store.signatures(k.STUDY)
    # with the console's own key in the orchestrator (per-service tokens, D-138) the same assertion counts
    keys = tmp_path / "actor-keys"
    keys.write_text(actor_key(token).hex() + "\n")
    monkeypatch.setenv("TB_ACTOR_KEYS_FILE", str(keys))
    r = c.post(f"/studies/{k.STUDY}/edc/sign", json={**sign, "method": "oidc+mfa"},
               headers=actor_header("crc", "reauth-0123abcd", role="coordinator"))  # fmt: skip
    assert r.status_code == 200 and r.json()["method"] == "oidc+mfa"
    # and a signed value then stays locked against a shared-token reauth- once the keys file is gone
    monkeypatch.delenv("TB_ACTOR_KEYS_FILE")
    w = next(d for d in svc.store.drafts(k.STUDY, k.RECORD) if d["item"] == "weight")["id"]
    r = c.post(f"/studies/{k.STUDY}/edc/drafts/{w}/decide",
               json={"action": "edit", "value": "73", "reason": "re-read", "citation": {"text": "sheet", "day": ""}},
               headers=actor_header("crc", "reauth-0123abcd", role="coordinator"))  # fmt: skip
    assert r.status_code == 423


# ------------------------------------------------------------------ the data-entry reasons (small extra)
@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_data_entry_explains_decimals_time_email_and_phone(lang: str) -> None:
    labels = {"f": "Weight"}
    other = translate(lang, "dc.why.other")
    for code in ("decimals", "time", "email", "phone"):
        text = why(lang, {"code": code, "field": "f", "places": "2"}, labels)
        assert text != other and "Weight" in text, (lang, code)
    assert "2" in why(lang, {"code": "decimals", "field": "f", "places": "2"}, labels)
