"""TB-PLAN-04 step 3 (D-123, D-125, D-127): the console's Sources, Conflicts and Forms pages and their ``/api/v1``
routes, on the orchestrator's real data-core API (a real data core in the test's schema and the REDCap simulator).

The path: forms imported from a REDCap data dictionary → a value entered in TrialBox → REDCap attached → Sync now
→ REDCap's different consent date is listed as a conflict → a person resolves it → the trail shows the choice."""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from console.backend import problem_of
from console.data_pages import direction, kind_of
from console.i18n import CATALOGUES
from console.i18n_data import EN as DC_EN
from console.i18n_data import JA as DC_JA
from console.i18n_data import ZH as DC_ZH
from datacore.store import DataCore
from fastapi import FastAPI
from fastapi.testclient import TestClient
from markupsafe import escape
from orchestrator.datacore_api import DataService
from orchestrator.datacore_api import router as datacore_router
from rc_bridge.client import RedcapClient
from rc_sim.app import create_app as create_sim
from rc_sim.app import load_projects
from tb_common.audit import AuditLog

from tests.console.test_console_app import ADMIN_PW, VIEWER_PW, box, login  # noqa: F401 - the fixture is used by name
from tests.rc_kit import TOKEN_A

PW = "data-core-password-0001"
MAPPED = ("consent_date", "enrolled", "subject_no", "tb_status", "tb_screen_date")
OWNED = ("consent_date", "enrolled", "subject_no")
CHART_NO = "MRN-000123"  # the FakeBackend's chart number (reveal): never on these pages


def dictionary() -> bytes:
    """Project A's data dictionary (REDCap API column names) plus an identifier field TrialBox must drop."""
    meta = load_projects()[TOKEN_A]["metadata"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=[*meta[0], "identifier"])
    w.writeheader()
    for m in meta:
        w.writerow({**m, "identifier": ""})
    w.writerow({"field_name": "pt_name", "form_name": "screening", "field_type": "text", "field_label": "Name",
                "identifier": "y"})  # fmt: skip
    return buf.getvalue().encode()


@pytest.fixture
def dcb(box: dict[str, Any], tmp_path: Path) -> Iterator[dict[str, Any]]:  # noqa: F811
    """The console box on the orchestrator's data-core router; every study_api call is recorded."""
    sim = create_sim()

    def client(_ref: str) -> RedcapClient:
        rc = RedcapClient("https://rc.example/", TOKEN_A, http=TestClient(sim, base_url="http://rc"))
        rc.url = "/api/"
        return rc

    dc = DataCore()  # TB_DB_URL: the test's own schemas (tests/conftest.py)
    svc = DataService(dc, AuditLog(tmp_path / "orch-audit"), lambda: datetime(2026, 11, 8, 1, 0, tzinfo=UTC), client)
    api = FastAPI()
    api.include_router(datacore_router(lambda: svc))
    oc = TestClient(api)
    calls: list[tuple[str, str, Any]] = []

    def study_api(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        calls.append((method, path, body))
        if path == "/redcap/connections":  # S36's token list (the study store; not under test here)
            return {"connections": [{"token_ref": "main"}]}
        r = oc.request(method, path, json=body) if body is not None else oc.request(method, path)
        if r.status_code >= 400:
            raise problem_of(r.status_code, r.text)
        return r.json()

    box["backend"].study_api = study_api
    for name, role, studies in (("crc", "coordinator", ""), ("pi", "investigator", ""),
                                ("smo", "coordinator", "OTHR")):  # fmt: skip
        box["users"].create(name, role, PW, f"{name}@hospa.test")
        if studies:
            box["users"].set_scope(name, "smo", studies, None)
    yield {**box, "dc": dc, "oc": oc, "sim": sim, "calls": calls}
    dc.close()


def _writes(calls: list[tuple[str, str, Any]]) -> list[tuple[str, str, Any]]:
    return [c for c in calls if c[0] != "GET"]


def _import(c: TestClient, csrf: str) -> Any:
    files = {"dictionary": ("GZQO_DataDictionary.csv", dictionary(), "text/csv")}
    return c.post("/studies/GZQO/forms/dictionary", data={"csrf": csrf, "record_field": "record_id"}, files=files)


def _attach(c: TestClient, csrf: str) -> Any:
    return c.post("/studies/GZQO/sources/redcap", data={
        "csrf": csrf, "token_ref": "main", "key_field": "tb_screening_no", "create": "1",
        "field_map": "\n".join(f"{f}={f}" for f in MAPPED), "owned": list(OWNED)})  # fmt: skip


def _with_conflict(b: dict[str, Any]) -> tuple[TestClient, str, int]:
    """Forms imported, TrialBox's own consent date entered, REDCap attached and synced: one open conflict."""
    c, csrf = login(b["app"], "crc", PW)
    assert 'data-testid="dc-imported"' in _import(c, csrf).text
    r = b["oc"].put("/studies/GZQO/data/GZQO-0901", json={"values": {"consent_date": "2026-10-19", "tb_status": "3"},
                                                          "by": "console:crc"})  # fmt: skip
    assert r.status_code == 200, r.text
    assert 'data-testid="dc-done"' in _attach(c, csrf).text
    r = c.post("/studies/GZQO/sources/redcap/sync", data={"csrf": csrf})
    assert 'data-testid="dc-done"' in r.text and 'data-testid="dc-open"' in r.text
    cs = b["dc"].conflicts("GZQO")
    assert [(x["record"], x["field"], x["trialbox"], x["theirs"]) for x in cs] == [
        ("GZQO-0901", "consent_date", "2026-10-19", "2026-10-20")
    ]
    return c, csrf, int(cs[0]["id"])


def _api(b: dict[str, Any], user: str, pw: str = PW) -> TestClient:
    c = TestClient(b["app"])
    r = c.post("/api/v1/session", json={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return c


# ---------------------------------------------------------------------------------------------- the path
def test_forms_sources_sync_conflict_resolve_detach(dcb: dict[str, Any]) -> None:
    c, csrf = login(dcb["app"], "crc", PW)
    assert 'data-testid="dc-no-forms"' in c.get("/studies/GZQO/forms").text
    page = c.get("/studies/GZQO/sources").text
    assert 'data-testid="dc-no-source"' in page and 'data-testid="dc-attach-noforms"' in page
    r = _import(c, csrf)
    assert re.search(
        r'data-testid="dc-imported">2 forms with \d+ fields imported. Identifier fields dropped: 1', r.text
    )
    assert 'data-testid="form-screening"' in r.text and 'data-testid="form-trialbox_screening"' in r.text
    assert 'data-testid="field-consent_date"' in r.text and "pt_name" not in r.text
    assert re.search(r'data-testid="field-enrolled">.*?One choice.*?<span class="mono">1</span>', r.text, re.S)
    _, _, cid = _with_conflict(dcb)  # imports again (same forms) and attaches
    page = c.get("/studies/GZQO/sources").text
    assert 'data-testid="source-redcap"' in page and re.search(r'data-testid="dir-redcap">Two-way<', page)
    assert re.search(r'data-testid="owned-by-consent_date">REDCap<', page)
    assert re.search(r'data-testid="owned-by-tb_status">TrialBox<', page)
    assert "1 open conflicts" in page and 'data-testid="attach-redcap"' not in page  # attached: no second form
    forms = c.get("/studies/GZQO/forms").text
    assert re.search(r'data-testid="form-owner-enrolled">REDCap<', forms)
    page = c.get("/studies/GZQO/conflicts").text
    row = re.search(rf'data-testid="conflict-{cid}">(.*?)</tr>', page, re.S)
    assert row and "GZQO-0901" in row.group(1) and "2026-10-19" in row.group(1) and "2026-10-20" in row.group(1)
    assert "REDCap" in row.group(1) and f'data-testid="keep-theirs-{cid}"' in row.group(1)
    dcb["calls"].clear()
    r = c.post(f"/studies/GZQO/conflicts/{cid}", data={"csrf": csrf, "keep": "theirs"})
    assert 'data-testid="confirm-text"' in r.text and "Take the value from" in r.text  # P-10: nothing changed yet
    assert not [x for x in _writes(dcb["calls"]) if x[1].endswith(f"/conflicts/{cid}")]
    r = c.post(f"/studies/GZQO/conflicts/{cid}", data={"csrf": csrf, "keep": "theirs", "confirm": "yes"})
    assert r.status_code == 200 and 'data-testid="dc-done"' in r.text and f"conflict-{cid}" not in r.text
    assert _writes(dcb["calls"]) == [
        ("POST", f"/studies/GZQO/conflicts/{cid}", {"keep": "theirs", "by": "console:crc"})
    ]
    assert dcb["dc"].record("GZQO", "GZQO-0901")["consent_date"] == "2026-10-20"
    trail = c.get("/studies/GZQO/conflicts?all=1").text
    assert f'data-testid="resolved-{cid}"' in trail and "value taken by crc on " in trail
    assert "Hide resolved" in trail
    # resolved twice: refused by the data core, shown in the reader's words
    r = c.post(f"/studies/GZQO/conflicts/{cid}", data={"csrf": csrf, "keep": "trialbox", "confirm": "yes"})
    assert 'data-testid="dc-error"' in r.text and "DATA-CONFLICT" in r.text
    r = c.post("/studies/GZQO/sources/redcap/detach", data={"csrf": csrf})
    assert 'data-testid="confirm-text"' in r.text and "Detach REDCap from this study?" in r.text  # P-10
    r = c.post("/studies/GZQO/sources/redcap/detach", data={"csrf": csrf, "confirm": "yes"})
    assert 'data-testid="dc-no-source"' in r.text and dcb["dc"].owners("GZQO")["consent_date"] == "trialbox"
    assert [c[:2] for c in _writes(dcb["calls"])][-1] == ("DELETE", "/studies/GZQO/sources/redcap?by=console%3Acrc")
    events = [e.event for e in dcb["backend"].audit(None, 500)]
    assert {"console.data_forms", "console.data_source", "console.data_sync", "console.data_resolve"} <= set(events)


def test_a_sync_of_an_unknown_source_and_a_bad_dictionary_are_shown_not_raised(dcb: dict[str, Any]) -> None:
    c, csrf = login(dcb["app"], "crc", PW)
    r = c.post("/studies/GZQO/sources/redcap/sync", data={"csrf": csrf})
    assert 'data-testid="dc-error"' in r.text and "DATA-SOURCE" in r.text
    bad = {"dictionary": ("x.csv", b"a,b\n1,2\n", "text/csv")}
    r = c.post("/studies/GZQO/forms/dictionary", data={"csrf": csrf}, files=bad)
    assert 'data-testid="dc-error"' in r.text and "FORM-COLUMNS" in r.text
    r = c.post("/studies/GZQO/forms/dictionary", data={"csrf": csrf})
    assert "FORM-EMPTY" in r.text


# ---------------------------------------------------------------------------------------------- roles
def test_roles_that_may_not_change_setup_read_only_and_get_403(dcb: dict[str, Any]) -> None:
    _, _, cid = _with_conflict(dcb)
    dcb["calls"].clear()
    files = {"dictionary": ("d.csv", dictionary(), "text/csv")}
    for user, pw in (("pi", PW), ("admin", ADMIN_PW)):  # setup changes are the coordinator's (study_setup)
        c, csrf = login(dcb["app"], user, pw)
        for path in ("/studies/GZQO/sources", "/studies/GZQO/conflicts", "/studies/GZQO/forms"):
            page = c.get(path).text
            assert 'data-testid="dc-readonly"' in page, (user, path)
            assert not re.search(r'data-testid="(sync-|detach-|attach-|keep-|import-)', page), (user, path)
        assert c.post("/studies/GZQO/sources/redcap/sync", data={"csrf": csrf}).status_code == 403
        assert c.post("/studies/GZQO/sources/redcap/detach", data={"csrf": csrf}).status_code == 403
        assert c.post("/studies/GZQO/sources/redcap", data={"csrf": csrf, "field_map": "a=a"}).status_code == 403
        assert c.post(f"/studies/GZQO/conflicts/{cid}", data={"csrf": csrf, "keep": "theirs"}).status_code == 403
        assert c.post("/studies/GZQO/forms/dictionary", data={"csrf": csrf}, files=files).status_code == 403
    viewer, _ = login(dcb["app"], "viewer", VIEWER_PW)
    for path in ("/studies/GZQO/sources", "/studies/GZQO/forms", "/studies/GZQO/setup"):  # D-144 (J-05)
        assert viewer.get(path).status_code == 403, path
    assert viewer.get("/studies/GZQO/conflicts").status_code == 403  # trial values: patient-level rows
    smo, csrf = login(dcb["app"], "smo", PW)  # a coordinator scoped to another study
    assert smo.get("/studies/GZQO/sources").status_code == 404
    assert smo.post(f"/studies/GZQO/conflicts/{cid}", data={"csrf": csrf, "keep": "theirs"}).status_code == 404
    crc, _ = login(dcb["app"], "crc", PW)
    assert crc.post(f"/studies/GZQO/conflicts/{cid}", data={"csrf": "wrong", "keep": "theirs"}).status_code == 400
    assert _writes(dcb["calls"]) == [] and len(dcb["dc"].conflicts("GZQO")) == 1  # nothing reached the data core


# ---------------------------------------------------------------------------------------------- /api/v1
def test_api_needs_a_bearer_token_and_answers_as_the_pages(dcb: dict[str, Any]) -> None:
    _, _, cid = _with_conflict(dcb)
    anon = TestClient(dcb["app"])
    for method, path in (("GET", "/api/v1/studies/GZQO/sources"), ("POST", "/api/v1/studies/GZQO/sources/redcap/sync"),
                         ("GET", "/api/v1/studies/GZQO/conflicts"), ("GET", "/api/v1/studies/GZQO/forms")):  # fmt: skip
        r = anon.request(method, path)
        assert r.status_code == 401 and r.json()["error"] == "login", path
    r = anon.post(f"/api/v1/studies/GZQO/conflicts/{cid}", json={"keep": "theirs"},
                  headers={"Authorization": "Bearer not-a-token"})  # fmt: skip
    assert r.status_code == 401
    api = _api(dcb, "crc")
    src = api.get("/api/v1/studies/GZQO/sources").json()
    assert src["study"] == "GZQO" and src["may_change"] is True
    red = src["sources"][0]
    assert (red["name"], red["direction"], sorted(red["owned"])) == ("redcap", "two", sorted(OWNED))
    assert red["result"]["conflicts"] == 1 and red["last_sync"]
    owners = {f["name"]: f["owner"] for f in src["fields"]}
    assert owners["consent_date"] == "redcap" and owners["tb_status"] == "trialbox"
    forms = api.get("/api/v1/studies/GZQO/forms").json()["forms"]
    assert [f["name"] for f in forms] == ["screening", "trialbox_screening"]
    enrolled = next(x for f in forms for x in f["fields"] if x["name"] == "enrolled")
    assert enrolled["kind"] == "choice" and enrolled["owner"] == "redcap" and enrolled["choices"][0]["code"] == "1"
    open_ = api.get("/api/v1/studies/GZQO/conflicts").json()["conflicts"]
    assert [(x["id"], x["record"], x["field"]) for x in open_] == [(cid, "GZQO-0901", "consent_date")]
    r = api.post(f"/api/v1/studies/GZQO/conflicts/{cid}", json={"keep": "source"})
    assert r.status_code == 400 and r.json()["error"] == "request.refused"
    dcb["calls"].clear()
    r = api.post(f"/api/v1/studies/GZQO/conflicts/{cid}", json={"keep": "trialbox"})
    assert r.status_code == 200 and r.json()["resolved"] == "trialbox" and r.json()["resolved_by"] == "console:crc"
    assert _writes(dcb["calls"]) == [("POST", f"/studies/GZQO/conflicts/{cid}",
                                      {"keep": "trialbox", "by": "console:crc"})]  # fmt: skip
    assert api.get("/api/v1/studies/GZQO/conflicts").json()["conflicts"] == []
    trail = api.get("/api/v1/studies/GZQO/conflicts", params={"all": "true"}).json()["conflicts"]
    assert [x["resolved"] for x in trail] == ["trialbox"]
    r = api.post(f"/api/v1/studies/GZQO/conflicts/{cid}", json={"keep": "trialbox"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "DATA-CONFLICT"
    r = api.post("/api/v1/studies/GZQO/sources/redcap/sync")
    assert r.status_code == 200 and r.json()["source"] == "redcap" and r.json()["conflicts"] == []  # not listed again
    assert dcb["dc"].record("GZQO", "GZQO-0901")["consent_date"] == "2026-10-19"
    assert api.post("/api/v1/studies/GZQO/sources/sheet/sync").status_code == 404
    # the same refusals as the pages
    pi = _api(dcb, "pi")
    assert pi.get("/api/v1/studies/GZQO/sources").json()["may_change"] is False
    assert pi.post("/api/v1/studies/GZQO/sources/redcap/sync").json()["error"] == "forbidden"
    assert pi.post(f"/api/v1/studies/GZQO/conflicts/{cid}", json={"keep": "theirs"}).status_code == 403
    assert pi.delete("/api/v1/studies/GZQO/sources/redcap").status_code == 403
    assert _api(dcb, "viewer", VIEWER_PW).get("/api/v1/studies/GZQO/conflicts").status_code == 403
    assert _api(dcb, "smo").get("/api/v1/studies/GZQO/forms").status_code == 404
    # detach and import through the API too (D-125: every screen action)
    assert api.delete("/api/v1/studies/GZQO/sources/redcap").json()["detached"] is True
    r = api.post("/api/v1/studies/GZQO/forms/dictionary", json={"csv": dictionary().decode(),
                                                                "record_field": "record_id"})  # fmt: skip
    assert r.status_code == 200 and r.json()["dropped"] == ["pt_name"]
    r = api.put("/api/v1/studies/GZQO/sources/redcap", json={"token_ref": "main", "field_map": {"enrolled": "enrolled"},
                                                             "owned": ["enrolled"]})  # fmt: skip
    assert r.status_code == 200 and r.json()["owned"] == ["enrolled"]


# ---------------------------------------------------------------------------------------------- languages
@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_each_page_in_each_language_without_a_chart_number(dcb: dict[str, Any], lang: str) -> None:
    c, csrf, cid = _with_conflict(dcb)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})
    cat = CATALOGUES[lang]
    pages = {
        "/studies/GZQO/sources": ("dc.sources.title", "dc.sources.help", "dc.dir.two", "dc.sync"),
        "/studies/GZQO/conflicts": ("dc.conflicts.title", "dc.keep.trialbox", "dc.keep.theirs", "dc.show_resolved"),
        "/studies/GZQO/forms": ("dc.forms.title", "dc.forms.help", "dc.kind.choice", "dc.import.title"),
        "/studies/GZQO/setup": ("setup.title", "dc.sources.title", "dc.forms.title"),
    }
    pages["/studies/GZQO/conflicts?all=1"] = ("dc.resolved.title", "dc.kept.theirs", "dc.hide_resolved")
    for path, keys in pages.items():
        if path.endswith("?all=1"):  # the trail, once the conflict is resolved
            c.post(f"/studies/GZQO/conflicts/{cid}", data={"csrf": csrf, "keep": "theirs", "confirm": "yes"})
        r = c.get(path)
        assert r.status_code == 200, (lang, path)
        for k in keys:
            assert str(escape(cat[k])) in r.text, (lang, path, k)
        assert not re.search(r"\bdc\.[a-z]", r.text), (lang, path)  # no key left untranslated
        assert CHART_NO not in r.text and not re.search(r"\b[0-9a-f]{32}\b", r.text), (lang, path)
        if lang != "en":
            for k in ("dc.sources.help", "dc.conflicts.help", "dc.forms.help", "dc.readonly", "dc.keep.theirs"):
                assert str(escape(DC_EN[k])) not in r.text, (lang, path, k)
        nav = re.search(r'<nav aria-label="main".*?</nav>', r.text, re.S)
        assert nav and 'data-testid="more-sources"' in nav.group(0)
        top = re.sub(r"<details.*?</details>", "", nav.group(0), flags=re.S)
        assert len(re.findall(r"<a ", top)) <= 4


def test_data_strings_in_three_languages() -> None:
    assert set(DC_EN) == set(DC_JA) == set(DC_ZH)
    same = [k for k, v in DC_EN.items() if (DC_JA[k] == v or DC_ZH[k] == v) and v not in ("REDCap", "TrialBox")]
    assert same == []
    for cat in CATALOGUES.values():
        assert "dc.conflicts.title" in cat and "dc.err.DATA-CONFLICT" in cat


def test_direction_and_kinds() -> None:
    assert (direction("redcap"), direction("sheet"), direction("fhir"), direction("ssmix2")) == (
        "two",
        "two",
        "in",
        "in",
    )
    assert kind_of({"type": "choice", "repeats": True}) == "multi" and kind_of({"type": "choice"}) == "choice"
    assert kind_of({"type": "string", "readOnly": True}) == "calc" and kind_of({"type": "text"}) == "notes"
    assert kind_of({"type": "date"}) == "date" and kind_of({"type": "string"}) == "text"
