"""TB-PLAN-04 step 4 (D-129, D-125, D-127): the console's Entry and History pages, the exports and the built-in
forms, and their ``/api/v1`` routes, on the orchestrator's real data-core API (a real data core in the test's
schema).

The path: the coordinator adds the built-in forms → opens a screening number → saves a consent → saves a visit →
edits the consent → the history shows who, when, old and new; a required-field and a range refusal come back per
field in the reader's language; the exports download; a chart number is never a record."""

from __future__ import annotations

import csv
import io
import re
from typing import Any
from xml.etree import ElementTree as ET

import pytest
from console.backend import read_audit
from console.entry_pages import can_enter, record_key, why
from console.i18n import CATALOGUES
from console.i18n_entry import EN as DE_EN
from console.i18n_entry import JA as DE_JA
from console.i18n_entry import ZH as DE_ZH
from fastapi.testclient import TestClient
from markupsafe import escape

from tests.console.test_console_app import ADMIN_PW, VIEWER_PW, box, login, sub_investigator  # noqa: F401 - the fixture is used by name
from tests.console.test_data_pages import PW, _api, _writes, dcb  # noqa: F401 - the fixture is used by name

CHART_NO = "MRN-000123"


def _numbers(b: dict[str, Any], n: int = 2) -> list[str]:
    """Screening numbers the console's site store issues for GZQO (the records the coordinator may open)."""
    h = b["app"].state.helpers
    assert h.settings_of is not None
    return [h.store.assign_screening_no("GZQO", f"{i:032x}", h.settings_of("GZQO"), "2026-11-08T09:00:00+09:00")
            for i in range(1, n + 1)]  # fmt: skip


def _builtin(c: TestClient, csrf: str) -> Any:
    return c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})


def _save(c: TestClient, csrf: str, record: str, form: str, values: dict[str, Any], event: str = "",
          reason: str = "") -> Any:  # fmt: skip
    data: dict[str, Any] = {"csrf": csrf, "record": record, "event": event, "form": form, "reason": reason}
    data.update({f"f_{k}": v for k, v in values.items()})
    return c.post("/studies/GZQO/entry", data=data)


# ---------------------------------------------------------------------------------------------- the path
def test_builtin_forms_entry_history_and_refusals(dcb: dict[str, Any]) -> None:
    no, other = _numbers(dcb)
    c, csrf = login(dcb["app"], "crc", PW)
    page = c.get("/studies/GZQO/entry").text
    assert 'data-testid="entry-noforms"' in page
    r = _builtin(c, csrf)
    assert 'data-testid="dc-builtin-added">7 built-in forms added.' in r.text
    assert 'data-testid="form-tb_consent"' in r.text and "Date of consent" in r.text and "Shown only if" in r.text
    page = c.get("/studies/GZQO/entry").text
    assert f'<option value="{no}">' in page and "Screening log" in page and "Adverse event" in page
    page = c.get("/studies/GZQO/entry", params={"record": no.lower(), "form": "tb_consent"}).text
    assert 'data-testid="entry-form"' in page and f'<span class="mono">{no}</span>' in page
    assert 'href="/studies/GZQO/entry/tb_consent.css"' in page and 'data-testid="entry-save"' in page
    css = c.get("/studies/GZQO/entry/tb_consent.css")
    assert css.headers["content-type"].startswith("text/css")
    assert css.text == ('#entry:not(:has(input[name="f_ic_reconsent"][value="1"]:checked)) .q-ic_reconsent_date '
                        "{ display: none; }\n"
                        '#entry:not(:has(input[name="f_ic_reconsent"][value="1"]:checked)) .q-ic_reconsent_version '
                        "{ display: none; }\n"  # D-399: the consent record's added fields (FIT-009)
                        '#entry:not(:has(input[name="f_ic_lar"][value="1"]:checked)) .q-ic_lar_relation '
                        "{ display: none; }\n"
                        '#entry:not(:has(input[name="f_ic_witness"][value="1"]:checked)) .q-ic_witness_by '
                        "{ display: none; }\n")  # fmt: skip
    # a required field missing and a bad date: refused whole, per field, nothing written
    dcb["calls"].clear()
    r = _save(c, csrf, no, "tb_consent", {"ic_date": "2026-02-30", "ic_copy": "1"})
    assert 'data-testid="entry-refused"' in r.text and "Correct the 2 marked fields" in r.text, re.findall(
        r'class="error"[^>]*>.*?</p>', r.text
    )
    assert re.search(r'data-testid="why-ic_version">Consent form version: required\.<', r.text)
    assert re.search(r'data-testid="why-ic_date">Date of consent: enter a date as YYYY-MM-DD\.<', r.text)
    assert 'value="2026-02-30"' in r.text  # what was typed stays on the page
    assert dcb["dc"].history("GZQO") == []
    r = _save(c, csrf, no, "tb_consent", {"ic_date": "2026-11-02", "ic_version": "v2.1", "ic_copy": "1",
                                          "ic_reconsent": "0", "ic_reconsent_date": "2026-11-03"})  # fmt: skip
    assert r.status_code == 200 and 'data-testid="entry-saved"' in r.text, r.text[-800:]
    assert str(r.url).endswith(f"/studies/GZQO/history?record={no}&saved=tb_consent&event=")
    assert dcb["dc"].record("GZQO", no) == {
        "ic_date": "2026-11-02",
        "ic_version": "v2.1",
        "ic_copy": "1",
        "ic_reconsent": "0",
    }  # fmt: skip  (the hidden date is not written)
    posted = [x for x in _writes(dcb["calls"]) if x[1].startswith("/studies/GZQO/entry/")]
    assert posted[-1][2]["values"]["ic_reconsent_date"] == "2026-11-03" and posted[-1][2]["by"] == "console:crc"
    # a visit on event v1: the range refusal, then saved
    r = _save(c, csrf, no, "tb_visit", {"vs_status": "1", "vs_date": "2026-11-05", "vs_weight": "999"}, "V1")
    assert re.search(r'data-testid="why-vs_weight">Body weight \(kg\): must be 400 or less\.<', r.text)
    r = _save(c, csrf, no, "tb_visit", {"vs_status": "1", "vs_date": "2026-11-05", "vs_weight": "61.5",
                                        "vs_window": "1"}, "v1")  # fmt: skip
    assert 'data-testid="entry-saved"' in r.text
    assert dcb["dc"].record("GZQO", no, "v1")["vs_weight"] == "61.5"
    # an edit of the consent shows in the history: who, when, old, new, source (and, D-778, it needs a reason)
    r = _save(c, csrf, no, "tb_consent", {"ic_date": "2026-11-02", "ic_version": "v2.2", "ic_copy": "1"},
              reason="version misread")  # fmt: skip
    hist = dcb["dc"].history("GZQO", no)
    edit = next(x for x in hist if x["field"] == "ic_version" and x["old"] == "v2.1")
    row = re.search(rf'data-testid="hist-{edit["id"]}">(.*?)</tr>', r.text, re.S)
    assert row and "crc" in row.group(1) and "v2.1" in row.group(1) and "v2.2" in row.group(1)
    assert "Consent form version" in row.group(1) and "TrialBox" in row.group(1)
    assert r.text.index(f'"hist-{edit["id"]}"') < r.text.index(f'"hist-{hist[0]["id"]}"')  # newest first
    assert 'data-testid="hist-' in c.get("/studies/GZQO/history", params={"record": no}).text
    page = c.get("/studies/GZQO/entry", params={"record": no, "form": "tb_visit", "event": "v1"}).text
    assert 'value="61.5"' in page and re.search(r'value="1" checked[^>]*data-testid="f-vs_status-1"', page)
    # a chart number or another study's key is never a record
    for bad in (CHART_NO, "XX-0001"):
        r = _save(c, csrf, bad, "tb_consent", {"ic_date": "2026-11-02", "ic_version": "v1", "ic_copy": "1"})
        assert 'data-testid="dc-error"' in r.text and "DATA-RECORD" in r.text and bad not in dcb["dc"].records("GZQO")
        assert 'data-testid="dc-error"' in c.get("/studies/GZQO/history", params={"record": bad}).text
    assert other not in dcb["dc"].records("GZQO")
    events = [e.event for e in dcb["backend"].audit(None, 500)]
    assert {"console.data_forms", "console.data_entry"} <= set(events)


def test_exports_download_from_the_console(dcb: dict[str, Any]) -> None:
    sub_investigator(dcb, "pi")  # D-380 (ROLE-008): the investigator's old rights, now from the log
    (no,) = _numbers(dcb, 1)
    c, csrf = login(dcb["app"], "crc", PW)
    _builtin(c, csrf)
    _save(c, csrf, no, "tb_consent", {"ic_date": "2026-11-02", "ic_version": "v2.1", "ic_copy": "1"})
    _save(c, csrf, no, "tb_visit", {"vs_status": "2", "vs_missed_reason": "入院中"}, "v1")
    page = c.get("/studies/GZQO/entry").text
    assert all(f'data-testid="export-{f}"' in page for f in ("odm", "csv", "xlsx"))
    r = c.get("/studies/GZQO/export.odm.xml")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    assert 'filename="GZQO_' in r.headers["content-disposition"]
    root = ET.fromstring(r.content)
    keys = [s.get("SubjectKey") for s in root.iter("{http://www.cdisc.org/ns/odm/v1.3}SubjectData")]
    assert keys == [no] and "入院中" in r.text
    r = c.get("/studies/GZQO/export.csv")
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert [(x["record_id"], x["redcap_event_name"]) for x in rows] == [(no, "event_1_arm_1"), (no, "v1")]
    assert rows[1]["vs_missed_reason"] == "入院中" and CHART_NO not in r.text
    r = c.get("/studies/GZQO/export.xlsx")
    assert r.content[:2] == b"PK"
    assert c.get("/studies/GZQO/export.pdf").status_code in (404, 503)
    pi, _ = login(dcb["app"], "pi", PW)
    assert pi.get("/studies/GZQO/export.csv").status_code == 200  # the investigator reads
    viewer, _ = login(dcb["app"], "viewer", VIEWER_PW)
    assert viewer.get("/studies/GZQO/export.csv").status_code == 403


# ---------------------------------------------------------------------------------------------- roles
def test_roles_on_entry_and_history(dcb: dict[str, Any]) -> None:
    sub_investigator(dcb, "pi")  # D-380 (ROLE-008): the investigator's old rights, now from the log
    (no,) = _numbers(dcb, 1)
    c, csrf = login(dcb["app"], "crc", PW)
    _builtin(c, csrf)
    _save(c, csrf, no, "tb_consent", {"ic_date": "2026-11-02", "ic_version": "v2.1", "ic_copy": "1"})
    dcb["calls"].clear()
    a, _ = login(dcb["app"], "admin", ADMIN_PW)  # D-280 (OD-5): the administrator reads no trial data
    assert a.get("/studies/GZQO/entry", params={"record": no, "form": "tb_consent"}).status_code == 403
    for user, pw in (("pi", PW),):  # the investigator reads; only the coordinator enters
        u, ucsrf = login(dcb["app"], user, pw)
        page = u.get("/studies/GZQO/entry", params={"record": no, "form": "tb_consent"}).text
        assert 'data-testid="dc-readonly"' in page and 'data-testid="entry-save"' not in page
        assert re.search(r'value="v2.1"[^>]* disabled', page)
        assert 'data-testid="hist-' in u.get("/studies/GZQO/history", params={"record": no}).text
        assert _save(u, ucsrf, no, "tb_consent", {"ic_version": "v9"}).status_code == 403
        assert _builtin(u, ucsrf).status_code == 403
        assert 'data-testid="add-builtin"' not in u.get("/studies/GZQO/forms").text
    viewer, _ = login(dcb["app"], "viewer", VIEWER_PW)
    for path in ("/studies/GZQO/entry", "/studies/GZQO/history", "/studies/GZQO/entry/tb_consent.css"):
        assert viewer.get(path).status_code == 403, path
    smo, scsrf = login(dcb["app"], "smo", PW)  # a coordinator scoped to another study
    assert smo.get("/studies/GZQO/entry").status_code == 404
    assert _save(smo, scsrf, no, "tb_consent", {"ic_version": "v9"}).status_code == 404
    assert c.post("/studies/GZQO/entry", data={"csrf": "wrong", "record": no, "form": "tb_consent"}).status_code == 400
    assert _writes(dcb["calls"]) == [] and dcb["dc"].record("GZQO", no)["ic_version"] == "v2.1"
    assert can_enter(dcb["users"].get("crc")) and not can_enter(dcb["users"].get("pi"))


# ---------------------------------------------------------------------------------------------- /api/v1
def test_api_does_what_the_pages_do(dcb: dict[str, Any]) -> None:
    sub_investigator(dcb, "pi")  # D-380 (ROLE-008): the investigator's old rights, now from the log
    no, _ = _numbers(dcb)
    anon = TestClient(dcb["app"])
    for method, path in (("POST", "/api/v1/studies/GZQO/forms/builtin"), ("GET", "/api/v1/studies/GZQO/records"),
                         ("GET", f"/api/v1/studies/GZQO/records/{no}"), ("GET", "/api/v1/studies/GZQO/export/odm"),
                         ("PUT", f"/api/v1/studies/GZQO/records/{no}/forms/tb_consent")):  # fmt: skip
        assert anon.request(method, path, json={"values": {}}).status_code == 401, path
    api = _api(dcb, "crc")
    r = api.post("/api/v1/studies/GZQO/forms/builtin")
    assert r.status_code == 200 and len(r.json()["forms"]) == 7
    r = api.put(f"/api/v1/studies/GZQO/records/{no}/forms/tb_consent", json={"values": {"ic_date": "2026-11-02"}})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "DATA-FORM"
    assert {(p["field"], p["code"]) for p in r.json()["problems"]} == {("ic_version", "required"),
                                                                       ("ic_copy", "required")}  # fmt: skip
    assert r.json()["problems"][0]["message"].endswith("required.")
    ok = {"ic_date": "2026-11-02", "ic_version": "v2.1", "ic_copy": "1"}
    r = api.put(f"/api/v1/studies/GZQO/records/{no}/forms/tb_consent", json={"values": ok})
    assert r.status_code == 200 and r.json()["changed"] == 3 and r.json()["record"] == no
    r = api.put(
        f"/api/v1/studies/GZQO/records/{no}/forms/tb_visit",
        json={"event": "v1", "values": {"vs_status": "1", "vs_date": "2026-11-05", "vs_weight": "0"}},
    )
    assert [p["code"] for p in r.json()["problems"]] == ["min"]
    api.put(f"/api/v1/studies/GZQO/records/{no}/forms/tb_consent", json={"values": {**ok, "ic_version": "v2.2"},
                                                                            "reason": "version misread"})  # fmt: skip
    rec = api.get(f"/api/v1/studies/GZQO/records/{no}").json()
    assert rec["values"][""]["ic_version"]["value"] == "v2.2"
    assert [(x["field"], x["old"], x["new"], x["by"]) for x in rec["history"]][-1] == (
        "ic_version",
        "v2.1",
        "v2.2",
        "console:crc",
    )
    assert api.get("/api/v1/studies/GZQO/records").json()["records"][0]["record"] == no
    r = api.get("/api/v1/studies/GZQO/export/csv")
    assert r.status_code == 200 and r.text.startswith("record_id,sl_date,")
    assert api.get(f"/api/v1/studies/GZQO/records/{CHART_NO}").json()["detail"]["code"] == "DATA-RECORD"
    ja = TestClient(dcb["app"])
    tok = ja.post("/api/v1/session", json={"username": "crc", "password": PW, "lang": "ja"}).json()["token"]
    ja.headers["Authorization"] = f"Bearer {tok}"
    r = ja.put(f"/api/v1/studies/GZQO/records/{no}/forms/tb_consent", json={"values": {**ok, "ic_copy": ""}})
    assert r.json()["problems"][0]["message"] == "ic_copy: 必須項目です。"
    pi = _api(dcb, "pi")
    assert pi.put(f"/api/v1/studies/GZQO/records/{no}/forms/tb_consent", json={"values": ok}).status_code == 403
    assert pi.get(f"/api/v1/studies/GZQO/records/{no}").status_code == 200
    assert _api(dcb, "viewer", VIEWER_PW).get("/api/v1/studies/GZQO/records").status_code == 403
    assert _api(dcb, "smo").get("/api/v1/studies/GZQO/records").status_code == 404


# ---------------------------------------------------------------------------------------------- languages
@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_entry_and_history_in_each_language(dcb: dict[str, Any], lang: str) -> None:
    (no,) = _numbers(dcb, 1)
    c, csrf = login(dcb["app"], "crc", PW)
    _builtin(c, csrf)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})
    cat = CATALOGUES[lang]
    r = _save(c, csrf, no, "tb_consent", {"ic_date": "2026-11-02", "ic_copy": "1"})
    assert str(escape(cat["dc.why.required"].format(label={"en": "Consent form version", "ja": "同意説明文書の版",
                                                           "zh-TW": "受試者同意書版本"}[lang]))) in r.text  # fmt: skip
    _save(c, csrf, no, "tb_consent", {"ic_date": "2026-11-02", "ic_version": "v1", "ic_copy": "1"})
    pages = {
        f"/studies/GZQO/entry?record={no}&form=tb_consent": ("dc.entry.title", "dc.entry.help", "dc.entry.save",
                                                             "dc.export.odm"),
        f"/studies/GZQO/history?record={no}": ("dc.history.title", "dc.col.old", "dc.col.new", "dc.owner.trialbox"),
        "/studies/GZQO/forms": ("dc.builtin.title", "dc.builtin.go", "dc.export.title"),
        "/studies/GZQO/sources": ("dc.sources.title", "dc.owners.title"),
    }  # fmt: skip
    label = {"en": "Date of consent", "ja": "同意取得日", "zh-TW": "簽署同意日期"}[lang]
    for path, keys in pages.items():
        page = c.get(path).text
        for k in keys:
            assert str(escape(cat[k])) in page, (lang, path, k)
        assert label in page, (lang, path)
        assert not re.search(r"\bdc\.[a-z]", page), (lang, path)
        assert CHART_NO not in page
        if lang != "en":
            for k in ("dc.entry.help", "dc.history.help", "dc.builtin.help", "dc.entry.save"):
                assert str(escape(DE_EN[k])) not in page, (lang, path, k)
            assert "Date of consent" not in page and "Consent form version" not in page
        nav = re.search(r'<nav aria-label="main".*?</nav>', page, re.S)
        assert nav and 'data-testid="more-entry"' in nav.group(0)


def test_entry_strings_in_three_languages() -> None:
    assert set(DE_EN) == set(DE_JA) == set(DE_ZH)
    same = [k for k, v in DE_EN.items() if DE_JA[k] == v or DE_ZH[k] == v]
    assert same == []
    for cat in CATALOGUES.values():
        assert "dc.entry.title" in cat and "dc.why.required" in cat
    for k, v in DE_EN.items():  # the same placeholders in every language
        assert (
            set(re.findall(r"\{\w+\}", v))
            == set(re.findall(r"\{\w+\}", DE_JA[k]))
            == set(re.findall(r"\{\w+\}", DE_ZH[k]))
        ), k


def test_helpers() -> None:
    assert record_key(" gzqo-0001 ") == "GZQO-0001" and record_key("AB" * 16) == "ab" * 16
    assert why("ja", {"field": "x", "code": "max", "max": "400"}, {"x": "体重"}) == "体重: 400 以下にしてください。"
    assert why("en", {"field": "x", "code": "???"}, {}) == "This value was refused."


def test_a_ticked_investigator_saves_a_lifecycle_form(dcb: dict[str, Any]) -> None:
    """T-715 review H1: an investigator the PI ticked "enter data" for saves a form that moves the participant. The
    follow-up refresh of the participants is the coordinator's (``study.setup``); the investigator's save must not
    answer 403 after the data is stored, and no false ``console.denied`` is written."""
    sub_investigator(dcb, "pi", tasks=("screen", "enter_data"))
    (no,) = _numbers(dcb, 1)
    c, csrf = login(dcb["app"], "crc", PW)
    _builtin(c, csrf)
    u, ucsrf = login(dcb["app"], "pi", PW)

    def denied() -> list[Any]:
        return [x for x in read_audit(dcb["dir"] / "audit") if x.event == "console.denied"]

    before = len(denied())
    r = _save(u, ucsrf, no, "tb_consent", {"ic_date": "2026-11-02", "ic_version": "v2.1", "ic_copy": "1"})
    assert r.status_code == 200, r.text[-300:]
    assert dcb["dc"].record("GZQO", no)["ic_version"] == "v2.1"
    assert len(denied()) == before
    # the entry call itself carried the investigator's signed claim for `task.enter_data`
    entry = [c_ for c_ in dcb["calls"] if c_[0] == "POST" and "/entry/" in c_[1]]
    assert entry and all("by" not in (c_[2] or {}) or c_[2]["by"] == "console:pi" for c_ in entry)
