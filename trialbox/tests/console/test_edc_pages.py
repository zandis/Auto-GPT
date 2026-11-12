"""EDC prefill pages and /api/v1 (D-160): who may do what, the review screen, the electronic signature with
re-authentication, send and ODM, in three languages. The orchestrator side is the real ``edc`` service on the test's
own database and the REDCap simulator (``tests.edc_kit``); synthetic data only."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from console.backend import problem_of
from console.sitestore import StudySettings
from fastapi import FastAPI
from fastapi.testclient import TestClient
from orchestrator.datacore_api import DataService
from orchestrator.datacore_api import router as datacore_router
from orchestrator.edc_api import router as edc_router
from tb_common.audit import AuditLog

from tests import edc_kit as k
from tests.console.test_console_app import ADMIN_PW, VIEWER_PW, box, login  # noqa: F401 - the fixture is used by name

PW = "edc-prefill-password-0001"
NO = "GZQO-0001"


def _seen(page: str) -> str:
    m = re.search(r'name="seen" value="([^"]*)"', page)
    assert m
    return m.group(1)


def _csrf(page: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', page)
    assert m
    return m.group(1)


@pytest.fixture
def eb(box: dict[str, Any], tmp_path: Path) -> Iterator[dict[str, Any]]:  # noqa: F811
    svc, sim, token = k.service(tmp_path, records=[{"record_id": "1", "tb_screening_no": NO}])
    dsvc = DataService(svc.dc, AuditLog(tmp_path / "orch-audit"), lambda: k.STAMP, svc.client)
    api = FastAPI()
    api.include_router(edc_router(lambda: svc))
    api.include_router(datacore_router(lambda: dsvc))
    oc = TestClient(api)

    def study_api(method: str, path: str, body: dict[str, Any] | None = None,
                  headers: dict[str, str] | None = None) -> Any:  # fmt: skip
        if path == "/redcap/connections":
            return {"connections": [{"token_ref": "edc"}]}
        kw: dict[str, Any] = {"headers": headers} if headers else {}
        r = oc.request(method, path, json=body, **kw) if body is not None else oc.request(method, path, **kw)
        if r.status_code >= 400:
            raise problem_of(r.status_code, r.text)
        return r.json()

    box["backend"].study_api = study_api
    for name, role in (("crc", "coordinator"), ("drsato", "investigator"), ("cro1", "cro")):
        box["users"].create(name, role, PW, f"{name}@hospa.test")
    h = box["app"].state.helpers
    for user, name, role in (("drsato", "Dr Sato", "pi"), ("crc", "Chen Mei", "crc")):  # the delegation log (D-147)
        h.team.add_entry(
            "GZQO",
            username=user,
            name=name,
            role=role,
            tasks=(),
            start="2026-01-01",
            end=None,
            training_day="2026-01-01",
            training_ref="GCP-1",
            by="admin",
            at="2026-01-01T00:00:00+00:00",
        )
    h.store.assign_screening_no("GZQO", k.PID, StudySettings(), "2026-11-01T00:00:00+00:00")
    assert h.store.screening_no("GZQO", k.PID) == NO
    yield {**box, "svc": svc, "sim": sim, "token": token}


def _ready(b: dict[str, Any], on: bool = True) -> None:
    b["svc"].import_dictionary("GZQO", "edc", "crc", "record_id")
    b["svc"].put_map("GZQO", k.MAP, k.TARGET, "crc")
    if on:
        b["svc"].set_switch("GZQO", True, by="drsato", role="investigator", **k.ACK)


def test_viewer_and_cro_see_nothing(eb: dict[str, Any]) -> None:
    _ready(eb)
    for user, pw in (("viewer", VIEWER_PW), ("cro1", PW)):
        c, _ = login(eb["app"], user, pw)
        assert c.get("/studies/GZQO/edc").status_code in (403, 404)
        assert c.get(f"/studies/GZQO/edc/review/{NO}").status_code in (403, 404)
        assert c.get("/studies/GZQO/edc/export.odm.xml").status_code in (403, 404)


def test_only_the_pi_switches_on_and_the_acknowledgement_is_needed(eb: dict[str, Any]) -> None:
    _ready(eb, on=False)
    crc, _ = login(eb["app"], "crc", PW)
    page = crc.get("/studies/GZQO/edc")
    assert page.status_code == 200 and 'data-testid="edc-pi-only"' in page.text and "edc-switch-on" not in page.text
    r = crc.post("/studies/GZQO/edc/switch", data={"csrf": _csrf(page.text), "on": "1", "kind": "sponsor_letter",
                                                   "reference": "X", "ack_date": "2026-11-01", "reentry_pages": "30",
                                                   "reentry_accuracy": "99"})  # fmt: skip
    assert r.status_code == 403
    pi, _ = login(eb["app"], "drsato", PW)
    page = pi.get("/studies/GZQO/edc").text
    r = pi.post("/studies/GZQO/edc/switch", data={"csrf": _csrf(page), "on": "1", "kind": "sponsor_letter",
                                                  "reference": "", "ack_date": "2026-11-01", "reentry_pages": "30",
                                                  "reentry_accuracy": "99"})  # fmt: skip
    assert r.status_code == 409 and 'data-testid="edc-error"' in r.text and "edc.ack_reference" in r.text
    r = pi.post("/studies/GZQO/edc/switch", data={"csrf": _csrf(page), "on": "1", "kind": "sponsor_letter",
                                                  "reference": "SPN-1", "ack_date": "2026-11-01", "reentry_pages": "30",
                                                  "reentry_accuracy": "98.5"}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    assert eb["svc"].store.switch("GZQO").on and eb["svc"].store.switch("GZQO").reentry_accuracy == 0.985
    # an admin turns it off (stop at once), but never on
    admin, _ = login(eb["app"])
    page = admin.get("/studies/GZQO/edc").text
    r = admin.post("/studies/GZQO/edc/switch", data={"csrf": _csrf(page), "on": "0", "reason": "sponsor asked"},
                   follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and not eb["svc"].store.switch("GZQO").on


def test_review_confirm_sign_with_password_and_send(eb: dict[str, Any]) -> None:
    _ready(eb)
    crc, _ = login(eb["app"], "crc", PW)
    page = crc.get("/studies/GZQO/edc").text
    r = crc.post("/studies/GZQO/edc/drafts", data={"csrf": _csrf(page), "record": NO, "visit": "",
                                                   "visit_date": k.VISIT_DATE}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text[-500:]
    rev = crc.get(f"/studies/GZQO/edc/review/{NO}")
    assert rev.status_code == 200
    assert 'data-testid="confirm-weight"' in rev.text and 'data-testid="confirm-cm_allo"' not in rev.text
    assert 'data-testid="unknown-cm_allo"' in rev.text and "Tophus on the right ear." in rev.text
    drafts = {d["item"]: d for d in eb["svc"].store.drafts("GZQO", NO)}
    csrf = _csrf(rev.text)
    # confirming a value without a citation is refused by the orchestrator even when posted by hand
    r = crc.post(f"/studies/GZQO/edc/decide/{drafts['cm_allo']['id']}", data={"csrf": csrf, "action": "confirm",
                                                                             "record": NO})  # fmt: skip
    assert r.status_code == 409 and "edc.no_citation" in r.text
    r = crc.post(f"/studies/GZQO/edc/decide/{drafts['weight']['id']}", data={"csrf": csrf, "action": "edit",
                                                                            "value": "73", "record": NO})  # fmt: skip
    assert r.status_code == 409 and "edc.reason" in r.text
    for item in ("weight", "urate", "sex"):
        r = crc.post(f"/studies/GZQO/edc/decide/{drafts[item]['id']}", data={"csrf": csrf, "action": "confirm",
                                                                             "record": NO}, follow_redirects=False)  # fmt: skip
        assert r.status_code == 303
    rev = crc.get(f"/studies/GZQO/edc/review/{NO}").text
    assert 'data-testid="edc-sign"' in rev and 'data-testid="edc-meaning"' in rev
    seen = _seen(rev)
    assert seen.count(":") == 3
    # send before signing sends nothing
    crc.post("/studies/GZQO/edc/send", data={"csrf": csrf, "record": NO})
    assert k.client_for(eb["sim"], eb["token"]).records()[0]["weight"] == ""
    # wrong password: nothing signed, audited
    r = crc.post("/studies/GZQO/edc/sign", data={"csrf": csrf, "record": NO, "password": "wrong-password-0000",
                                                 "meaning_ack": "1", "seen": seen})  # fmt: skip
    assert r.status_code == 401 and not eb["svc"].store.signatures("GZQO")
    # no acknowledgement of the meaning: refused
    r = crc.post("/studies/GZQO/edc/sign", data={"csrf": csrf, "record": NO, "password": PW, "seen": seen})
    assert r.status_code == 400 and not eb["svc"].store.signatures("GZQO")
    # what the page showed must still be what is signed: a value changed by someone else since is refused (E-11)
    stale = seen.replace(seen.split(",")[0].split(":")[1], "0" * 64)
    r = crc.post("/studies/GZQO/edc/sign", data={"csrf": csrf, "record": NO, "password": PW, "meaning_ack": "1",
                                                 "seen": stale})  # fmt: skip
    assert r.status_code == 409 and "edc.sign_changed" in r.text and not eb["svc"].store.signatures("GZQO")
    r = crc.post("/studies/GZQO/edc/sign", data={"csrf": csrf, "record": NO, "password": PW, "meaning_ack": "1",
                                                 "seen": seen}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text[-400:]
    sig = eb["svc"].store.signatures("GZQO")[0]
    assert sig["printed_name"] == "Chen Mei"
    assert sig["signer"] == "crc" and sig["meaning"] == "transcribed" and "compared each value" in sig["meaning_text"]
    r = crc.post("/studies/GZQO/edc/send", data={"csrf": csrf, "record": NO}, follow_redirects=False)
    assert r.status_code == 303 and "sent=3" in r.headers["location"]
    row = k.client_for(eb["sim"], eb["token"]).records()[0]
    assert (row["weight"], row["urate"], row["sex"], row["cm_allo"]) == ("72.5", "8.4", "1", "")
    trail = crc.get(f"/studies/GZQO/edc/trail/{NO}")
    assert trail.status_code == 200 and 'data-testid="trail-signatures"' in trail.text
    odm = crc.get("/studies/GZQO/edc/export.odm.xml")
    assert odm.status_code == 200 and "<Signature>" in odm.text and 'ItemOID="weight"' in odm.text


def test_api_v1_follows_the_same_rules(eb: dict[str, Any]) -> None:
    _ready(eb)
    c = TestClient(eb["app"])
    tok = c.post("/api/v1/session", json={"username": "crc", "password": PW}).json()["token"]
    hd = {"authorization": f"Bearer {tok}"}
    r = c.post("/api/v1/studies/GZQO/edc/drafts", json={"record": NO, "visit_date": k.VISIT_DATE}, headers=hd)
    assert r.status_code == 200, r.text
    drafts = {d["item"]: d for d in r.json()["drafts"]}
    r = c.post(f"/api/v1/studies/GZQO/edc/drafts/{drafts['tophus']['id']}/decide", json={"action": "confirm"},
               headers=hd)  # fmt: skip
    assert r.status_code == 200 and r.json()["draft"]["fate"] == "confirmed"
    shown = c.get(f"/api/v1/studies/GZQO/edc/drafts?record={NO}", headers=hd).json()["drafts"]
    seen = {str(d["id"]): d["sha"] for d in shown if d["fate"] == "confirmed" and d["signature_id"] is None}
    r = c.post("/api/v1/studies/GZQO/edc/sign", json={"record": NO, "password": "nope-nope-nope", "meaning_ack": True,
                                                      "seen": seen}, headers=hd)  # fmt: skip
    assert r.status_code == 401
    r = c.post("/api/v1/studies/GZQO/edc/sign", json={"record": NO, "password": PW, "meaning_ack": True,
                                                      "seen": seen}, headers=hd)  # fmt: skip
    assert r.status_code == 200 and r.json()["signature"]["printed_name"] == "Chen Mei"
    r = c.post("/api/v1/studies/GZQO/edc/send", json={"record": NO}, headers=hd)
    assert r.status_code == 200 and r.json()["count"] == 1
    r = c.post("/api/v1/studies/GZQO/edc/switch", json={"on": False}, headers=hd)
    assert r.status_code == 403  # a coordinator never switches
    tok2 = c.post("/api/v1/session", json={"username": "viewer", "password": VIEWER_PW}).json()["token"]
    assert c.get("/api/v1/studies/GZQO/edc", headers={"authorization": f"Bearer {tok2}"}).status_code in (403, 404)
    r = c.get("/api/v1/studies/GZQO/edc/export/odm", headers=hd)
    assert r.status_code == 200 and 'ODMVersion="1.3.2"' in r.json()["text"]


@pytest.mark.parametrize("lang,word", [("ja", "電子署名"), ("zh-TW", "電子簽章"), ("en", "Electronic signature")])
def test_review_page_in_three_languages(eb: dict[str, Any], lang: str, word: str) -> None:
    _ready(eb)
    eb["svc"].build("GZQO", NO, k.PID, "", k.VISIT_DATE, "crc")
    d = {x["item"]: x for x in eb["svc"].store.drafts("GZQO", NO)}
    eb["svc"].decide("GZQO", d["weight"]["id"], "confirm", by="crc")
    crc, csrf = login(eb["app"], "crc", PW)
    crc.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})
    page = crc.get(f"/studies/GZQO/edc/review/{NO}").text
    assert word in page


def test_map_page_reads_the_dictionary_suggests_and_refuses_a_bad_map(eb: dict[str, Any]) -> None:
    crc, _ = login(eb["app"], "crc", PW)
    page = crc.get("/studies/GZQO/edc/map")
    assert page.status_code == 200
    r = crc.post("/studies/GZQO/edc/dictionary", data={"csrf": _csrf(page.text), "token_ref": "edc",
                                                       "record_field": "record_id"}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and "suggest=1" in r.headers["location"]
    page = crc.get(r.headers["location"]).text
    assert 'data-testid="map-weight"' in page and 'data-testid="map-record_id"' not in page
    assert 'value="VS.VSORRES"' in page
    form = {
        "csrf": _csrf(page),
        "token_ref": "edc",
        "key_field": "tb_screening_no",
        "id_field": "record_id",
        "item": ["weight", "mh_gout"],
        "source-weight": "observation",
        "what-weight": "value",
        "codes-weight": "29463-7",
        "unit-weight": "",
        "window_days-weight": "30",
        "cdash-weight": "VS.VSORRES",
        "source-mh_gout": "condition",
        "what-mh_gout": "presence",
        "codes-mh_gout": "",
        "window_days-mh_gout": "0",
    }
    r = crc.post("/studies/GZQO/edc/map", data=form)
    assert r.status_code == 409 and 'data-testid="map-problem-weight"' in r.text and "map-problem-mh_gout" in r.text
    form.update({"unit-weight": "kg", "codes-mh_gout": "M10"})
    r = crc.post("/studies/GZQO/edc/map", data=form, follow_redirects=False)
    assert r.status_code == 303 and len(eb["svc"].store.map("GZQO")) == 2


def test_e10_signing_and_switching_on_need_the_delegation_log(eb: dict[str, Any]) -> None:
    _ready(eb, on=False)
    eb["users"].create("crc2", "coordinator", PW, "crc2@hospa.test")  # not on the study's delegation log
    eb["users"].create("drkato", "investigator", PW, "drkato@hospa.test")  # an investigator, not the logged PI
    kato, _ = login(eb["app"], "drkato", PW)
    page = kato.get("/studies/GZQO/edc")
    r = kato.post("/studies/GZQO/edc/switch", data={"csrf": _csrf(page.text), "on": "1", "kind": "sponsor_letter",
                                                    "reference": "SPN-1", "ack_date": "2026-11-01",
                                                    "reentry_pages": "30", "reentry_accuracy": "99"})  # fmt: skip
    assert r.status_code in (403, 409) and not eb["svc"].store.switch("GZQO").on
    eb["svc"].set_switch("GZQO", True, by="drsato", role="investigator", **k.ACK)
    eb["svc"].build("GZQO", NO, k.PID, "", k.VISIT_DATE, "crc")
    d = {x["item"]: x for x in eb["svc"].store.drafts("GZQO", NO)}
    eb["svc"].decide("GZQO", d["weight"]["id"], "confirm", by="crc")
    c2, _ = login(eb["app"], "crc2", PW)
    rev = c2.get(f"/studies/GZQO/edc/review/{NO}").text
    assert 'data-testid="edc-no-log-entry"' in rev and 'data-testid="edc-sign"' not in rev
    seen = f"{d['weight']['id']}:{k.seen(eb['svc'], NO)[d['weight']['id']]}"
    r = c2.post("/studies/GZQO/edc/sign", data={"csrf": _csrf(rev), "record": NO, "password": PW, "meaning_ack": "1",
                                                "seen": seen})  # fmt: skip
    assert r.status_code == 409 and "own active entry" in r.text and not eb["svc"].store.signatures("GZQO")
