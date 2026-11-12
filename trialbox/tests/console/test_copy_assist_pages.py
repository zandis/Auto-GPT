"""T-302c (D-434) copy-assist pages: the PI turns copy-assist on without the sponsor's acknowledgement; the sheet shows
signed values only, per visit and form, with sources; "copied" ticks per value and per form, an undo with a reason;
the CSV with its export-ledger row; /api/v1 checks the session and the right before the body; who may; opted-out
patients; three languages without a verdict word. The orchestrator is the real ``edc`` service (``tests.edc_kit``);
synthetic data only."""

from __future__ import annotations

import base64
import csv
import io
import json
from pathlib import Path
from typing import Any

import pytest
from console import copy_assist_page, i18n_copyassist
from console.i18n import CATALOGUES
from fastapi.testclient import TestClient
from tb_common.flowledger import exports
from tb_common.wording import check_page

from tests import edc_kit as k
from tests.console.test_console_app import VIEWER_PW, box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_edc_pages import NO, PW, _csrf, eb  # noqa: F401 - the fixture is used by name


def _events(b: dict[str, Any], name: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted((b["dir"] / "audit").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line and json.loads(line).get("event") == name:
                out.append(json.loads(line))
    return out


def _orch(b: dict[str, Any], name: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted(Path(b["svc"].audit.directory).glob("*.jsonl")):
        out += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    return [e for e in out if e["event"] == name]


def _copy_on(b: dict[str, Any]) -> None:
    """The PI turns copy-assist on from the page: no acknowledgement asked."""
    b["svc"].import_dictionary("GZQO", "edc", "crc", "record_id")
    b["svc"].put_map("GZQO", k.MAP, k.TARGET, "crc")
    pi, _ = login(b["app"], "drsato", PW)
    page = pi.get("/studies/GZQO/edc").text
    assert 'data-testid="edc-switch-copy"' in page
    r = pi.post("/studies/GZQO/edc/switch", data={"csrf": _csrf(page), "on": "1", "mode": "copy",
                                                  "reentry_pages": "30", "reentry_accuracy": "99"},
                follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text[-400:]
    assert b["svc"].store.switch("GZQO").state == "copy"


def _signed(b: dict[str, Any], items: tuple[str, ...] = ("weight", "sex")) -> dict[str, dict[str, Any]]:
    svc = b["svc"]
    built = {d["item"]: d for d in svc.build("GZQO", NO, k.PID, "", k.VISIT_DATE, "crc")}
    for item in items:
        svc.decide("GZQO", built[item]["id"], "confirm", by="crc")
    svc.sign("GZQO", NO, "", signer="crc", printed_name="Chen Mei", role="coordinator", meaning="transcribed",
             meaning_text="I checked each value.", lang="en", seen=k.seen(svc, NO), method="password")  # fmt: skip
    svc.decide("GZQO", built["urate"]["id"], "confirm", by="crc")  # decided, not signed
    return built


def test_copy_assist_sheet_ticks_and_file(eb: dict[str, Any]) -> None:  # noqa: F811
    _copy_on(eb)
    built = _signed(eb)
    crc, _ = login(eb["app"], "crc", PW)
    home = crc.get("/studies/GZQO/edc").text
    assert f'data-testid="edc-copy-{NO}"' in home and 'data-testid="edc-new-form"' in home
    assert 'data-testid="edc-send-all"' not in home  # nothing goes to the sponsor's EDC in copy-assist
    r = crc.get(f"/studies/GZQO/edc/copy/{NO}")
    assert r.status_code == 200, r.text[-400:]
    page = r.text
    assert 'data-testid="copy-value-weight"' in page and 'data-testid="copy-value-sex"' in page
    assert 'data-testid="copy-value-urate"' not in page  # never an unsigned value
    assert 'data-testid="copy-waiting-event_1_arm_1"' in page
    assert page.index('data-testid="copy-row-sex"') < page.index('data-testid="copy-row-weight"')  # the form order
    assert 'data-testid="copy-word-sex"' in page and ">Male<" in page
    assert "72.5" in page and "Chen Mei" in page
    assert _orch(eb, "edc.copy_view")[-1]["detail"]["values"] == 2
    assert _events(eb, "console.edc_copy")[-1]["detail"]["action"] == "view"
    # tick one value, then the rest of the form
    csrf = _csrf(page)
    r = crc.post(f"/studies/GZQO/edc/copy/{NO}/tick", data={"csrf": csrf, "draft": str(built["weight"]["id"]),
                                                             "action": "copied"}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and "done=copied" in r.headers["location"]
    page = crc.get(f"/studies/GZQO/edc/copy/{NO}").text
    assert 'data-testid="copy-ticked-weight"' in page and 'data-testid="copy-tick-sex"' in page
    # an unsigned value cannot be ticked, even when posted by hand; audited
    r = crc.post(f"/studies/GZQO/edc/copy/{NO}/tick", data={"csrf": csrf, "draft": str(built["urate"]["id"]),
                                                             "action": "copied"})  # fmt: skip
    assert r.status_code == 409 and "edc.tick_not_signed" in r.text
    assert _orch(eb, "edc.copy_tick")[-1]["detail"]["refused"] == "edc.tick_not_signed"
    r = crc.post(f"/studies/GZQO/edc/copy/{NO}/tick", data={"csrf": csrf, "draft": str(built["sex"]["id"]),
                                                             "action": "copied"}, follow_redirects=False)  # fmt: skip
    page = crc.get(f"/studies/GZQO/edc/copy/{NO}").text
    assert 'data-testid="copy-form-done-event_1_arm_1-demographics"' in page
    # undo needs a reason
    r = crc.post(f"/studies/GZQO/edc/copy/{NO}/tick", data={"csrf": csrf, "draft": str(built["sex"]["id"]),
                                                             "action": "undone"})  # fmt: skip
    assert r.status_code == 409 and "edc.reason" in r.text
    r = crc.post(f"/studies/GZQO/edc/copy/{NO}/tick", data={"csrf": csrf, "draft": str(built["sex"]["id"]),
                                                             "action": "undone", "reason": "wrong visit"},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    # the plain file: the same sheet, through the export ledger
    f = crc.get(f"/studies/GZQO/edc/copy.csv?record={NO}")
    assert f.status_code == 200 and f.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(f.content.decode("utf-8-sig"))))
    assert [(x["item"], x["value"]) for x in rows] == [("sex", "1"), ("weight", "72.5")]
    assert rows[0]["word"] == "Male" and rows[0]["copied_by"] == "" and rows[1]["copied_by"] == "crc"
    assert rows[1]["signed_by"] == "Chen Mei" and rows[1]["source"]
    flow = [x for x in exports(eb["dir"] / "audit") if x.filename.endswith(".csv")]
    assert flow and flow[-1].identifier_level == "pseudonymised" and flow[-1].ruleset == "GZQO"
    assert flow[-1].channel == "console_download" and "edc.copy" in flow[-1].approval
    assert _orch(eb, "edc.copy_view")[-1]["detail"]["format"] == "csv"
    whole = crc.get("/studies/GZQO/edc/copy.csv")
    assert whole.status_code == 200 and len(list(csv.DictReader(io.StringIO(whole.content.decode("utf-8-sig"))))) == 2
    assert "72.5" not in json.dumps(_orch(eb, "edc.copy_view") + _orch(eb, "edc.copy_tick"))  # no value audited


def test_who_may_and_the_api(eb: dict[str, Any]) -> None:  # noqa: F811
    _copy_on(eb)
    built = _signed(eb)
    for user, pw in (("viewer", VIEWER_PW), ("cro1", PW)):
        c, _ = login(eb["app"], user, pw)
        assert c.get(f"/studies/GZQO/edc/copy/{NO}").status_code in (403, 404)
        assert c.get("/studies/GZQO/edc/copy.csv").status_code in (403, 404)
    admin, _ = login(eb["app"])
    assert admin.get(f"/studies/GZQO/edc/copy/{NO}").status_code == 403  # no patient-level row (D-280)
    c = TestClient(eb["app"])
    # the session before the body: an empty body without a token is 401, never 422
    assert c.post(f"/api/v1/studies/GZQO/edc/copy/{NO}/tick", content=b"").status_code == 401
    tok = c.post("/api/v1/session", json={"username": "crc", "password": PW}).json()["token"]
    hd = {"authorization": f"Bearer {tok}"}
    r = c.get(f"/api/v1/studies/GZQO/edc/copy?record={NO}", headers=hd)
    assert r.status_code == 200, r.text
    vals = [v for vis in r.json()["records"][0]["visits"] for f in vis["forms"] for v in f["values"]]
    assert {v["item"] for v in vals} == {"weight", "sex"} and all(v["source"] for v in vals)
    assert c.post(f"/api/v1/studies/GZQO/edc/copy/{NO}/tick", json={"x": 1}, headers=hd).status_code == 422
    r = c.post(f"/api/v1/studies/GZQO/edc/copy/{NO}/tick", json={"drafts": [built["weight"]["id"]]}, headers=hd)
    assert r.status_code == 200 and len(r.json()["ticks"]) == 1
    r = c.post(f"/api/v1/studies/GZQO/edc/copy/{NO}/tick", json={"drafts": [built["urate"]["id"]]}, headers=hd)
    assert r.status_code == 409
    vtok = c.post("/api/v1/session", json={"username": "viewer", "password": VIEWER_PW}).json()["token"]
    r = c.post(f"/api/v1/studies/GZQO/edc/copy/{NO}/tick", json={"drafts": [built["weight"]["id"]]},
               headers={"authorization": f"Bearer {vtok}"})  # fmt: skip
    assert r.status_code in (403, 404)


class _Gone:
    def __init__(self, pids: set[str]) -> None:
        self.pids = pids

    def active(self) -> set[str]:
        return self.pids


def test_an_opted_out_patient_is_not_shown(eb: dict[str, Any]) -> None:  # noqa: F811
    _copy_on(eb)
    _signed(eb)
    eb["app"].state.helpers.optout = _Gone({k.PID})
    eb["svc"].optouts = lambda: frozenset({k.PID})
    crc, _ = login(eb["app"], "crc", PW)
    assert crc.get(f"/studies/GZQO/edc/copy/{NO}").status_code == 409
    assert crc.get(f"/studies/GZQO/edc/copy.csv?record={NO}").status_code == 409
    whole = crc.get("/studies/GZQO/edc/copy.csv")
    assert whole.status_code == 200 and NO not in whole.content.decode("utf-8-sig")


@pytest.mark.parametrize(("lang", "title"), [("ja", "転記支援"), ("zh-TW", "轉錄輔助"), ("en", "Copy-assist")])
def test_the_page_in_three_languages(eb: dict[str, Any], lang: str, title: str) -> None:  # noqa: F811
    _copy_on(eb)
    _signed(eb)
    crc, csrf = login(eb["app"], "crc", PW)
    crc.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
    page = crc.get(f"/studies/GZQO/edc/copy/{NO}").text
    assert title in page and not check_page(page)


def test_the_catalogues() -> None:
    assert copy_assist_page.VIEW == "edc.copy"
    assert set(i18n_copyassist.EN) == set(i18n_copyassist.JA) == set(i18n_copyassist.ZH)
    for lang, cat in CATALOGUES.items():
        assert all(key in cat for key in i18n_copyassist.EN), lang
        assert not check_page(" ".join(cat[key] for key in i18n_copyassist.EN)), lang


# ---------------------------------------------------------------- D-435's console part (T-302c)
def test_the_odm_import_form(eb: dict[str, Any]) -> None:  # noqa: F811
    svc = eb["svc"]
    svc.import_dictionary("GZQO", "edc", "crc", "record_id")
    svc.put_map("GZQO", k.MAP, k.TARGET, "crc")
    svc.set_switch("GZQO", True, by="drsato", role="investigator", **k.ACK)
    built = {d["item"]: d for d in svc.build("GZQO", NO, k.PID, "", k.VISIT_DATE, "crc")}
    svc.decide("GZQO", built["weight"]["id"], "confirm", by="crc")
    svc.sign("GZQO", NO, "", signer="crc", printed_name="Chen Mei", role="coordinator", meaning="transcribed",
             meaning_text="I checked each value.", lang="en", seen=k.seen(svc, NO), method="password")  # fmt: skip
    odm = svc.export_odm("GZQO", "crc").encode("utf-8")
    viewer, vcsrf = login(eb["app"], "viewer", VIEWER_PW)
    r = viewer.post("/studies/GZQO/edc/import", data={"csrf": vcsrf}, files={"file": ("x.xml", odm)})
    assert r.status_code in (403, 404)
    crc, _ = login(eb["app"], "crc", PW)
    page = crc.get("/studies/GZQO/edc").text
    assert 'data-testid="edc-import-form"' in page
    r = crc.post("/studies/GZQO/edc/import", data={"csrf": _csrf(page)}, files={"file": ("back.odm.xml", odm)},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text[-500:]
    assert "imp_decided=1" in r.headers["location"]  # the confirmed value is kept, never replaced
    done = crc.get(r.headers["location"]).text
    assert 'data-testid="edc-imported"' in done
    bad = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e "x">]><ODM/>'
    r = crc.post("/studies/GZQO/edc/import", data={"csrf": _csrf(page)}, files={"file": ("bad.xml", bad)})
    assert r.status_code == 409 and 'data-testid="edc-error"' in r.text and "odm.dtd" in r.text
    assert _orch(eb, "edc.odm_import")[-1]["detail"]["refused"] == "odm.dtd"
    # the API twin: the session and the right before the body
    c = TestClient(eb["app"])
    assert c.post("/api/v1/studies/GZQO/edc/import/odm", content=b"").status_code == 401
    tok = c.post("/api/v1/session", json={"username": "crc", "password": PW}).json()["token"]
    hd = {"authorization": f"Bearer {tok}"}
    assert c.post("/api/v1/studies/GZQO/edc/import/odm", json={}, headers=hd).status_code == 422
    r = c.post("/api/v1/studies/GZQO/edc/import/odm", json={"name": "b.xml", "data": base64.b64encode(odm).decode()},
               headers=hd)  # fmt: skip
    assert r.status_code == 200 and len(r.json()["decided"]) == 1
