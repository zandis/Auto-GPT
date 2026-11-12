"""T-102b (D-380): the roles of the permission matrix in the console.

* the administrator (IT operator) sees no patient row on any page it may open (CR-023, ROLE-010, FIT-022);
* ROLE-005: the opt-out register and the staff directory are kept by the steward and the privacy office only; an SMO
  or hospital coordinator is refused on the page and the API; a lift needs a written reason;
* ROLE-008: the delegation bootstrap is closed: with no PI on a study's log nobody acts as PI; the steward writes the
  PI entry from the signed log;
* ROLE-011: an SMO or CRO account names its studies; one stored without sees no study;
* ROLE-015: an SMO account and the administrator cannot set IRB dates; an approval date needs its number, a change a
  reason, and the audit event holds the old and new values;
* ROLE-018: the role descriptions on ``/ops/users`` and the menu come from the matrix;
* FIT-002 (grant half): a monitor grant opens an enrolled subject, read-only, and refuses a non-enrolled one;
* the clinical item catalogue (``/data/items``) is the steward's page, not the administrator's (T-102a finding)."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from console import i18n_roles
from console.app import role_description
from console.auth import ROLES, AuthError, User
from console.backend import Problem
from fastapi.testclient import TestClient
from tb_common.authz import MATRIX

from tests.console.test_console_app import (  # noqa: F401 - the fixture is used by name
    ADMIN_PW,
    _done_feas,
    _done_screen,
    _ulid,
    box,
    login,
    name_pi,
)
from tests.console.test_role_pages import PW, _csrf, _user
from tests.console.test_role_route_matrix import _fill, _routes

A, B, C = "a" * 32, "b" * 32, "c" * 32


def _events(b: dict[str, Any], name: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted((b["dir"] / "audit").glob("*.jsonl")):
        for line in f.read_text().splitlines():
            if line and json.loads(line).get("event") == name:
                out.append(json.loads(line))
    return out


def _api(b: dict[str, Any], name: str) -> TestClient:
    tok, _ = b["users"].new_session(b["users"].get(name), via="api")
    return TestClient(b["app"], headers={"Authorization": f"Bearer {tok}"})


# ---------------------------------------------------------------------------------------------- the administrator
def test_the_administrator_sees_no_patient_row(box: dict[str, Any]) -> None:  # noqa: F811
    """Every page and API the administrator may open, after a coordinator viewed a candidate (an audit event naming
    the pseudonym), an Approach under an IRB warning and an opt-out: no pseudonym anywhere."""
    _done_feas(box["backend"])
    jid = _ulid(990)
    _done_screen(box["backend"], jid)
    crc = _user(box, "crc1", "coordinator")
    assert crc.get(f"/studies/GZQO/candidates/{A}?purpose=eligibility").status_code == 200
    from console.teamstore import TeamStore

    TeamStore().add_override("GZQO", B, ["irb_missing"], "crc1", "2026-10-01T00:00:00+00:00")
    stw = _user(box, "stw", "steward")
    r = stw.post("/site/opt-outs", data={"csrf": _csrf(stw.get("/site/opt-outs").text), "pid": C, "source": "paper"},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    admin, _ = login(box["app"])
    assert admin.get(f"/studies/GZQO/candidates/{A}").status_code == 403  # its refusal is audited with the path
    assert A in stw.get("/audit").text  # the steward's audit browser (D-451) shows it: the probe below is not empty
    api = _api(box, "admin")
    opened = 0
    for method, path in _routes(box["app"]):
        if method != "GET":
            continue
        url = _fill(path, jid)
        r = (api if path.startswith("/api/v1/") else admin).get(url, follow_redirects=False)
        if r.status_code != 200 or url.endswith((".xlsx", ".zip", ".pdf")):
            continue
        opened += 1
        for pid in (A, B, C):
            assert pid[:8] not in r.text, (url, pid[:8])
    assert opened > 30


def test_the_item_catalogue_is_the_stewards_page(box: dict[str, Any]) -> None:  # noqa: F811
    admin, _ = login(box["app"])
    assert admin.get("/data/items").status_code == 403
    stw = _user(box, "stw", "steward")
    assert stw.get("/data/items").status_code == 200
    assert 'href="/data/items"' in stw.get("/site/staff").text  # the steward's menu names it


# ---------------------------------------------------------------------------------------------- ROLE-005
def test_role_005_opt_outs_are_kept_by_the_steward_and_the_privacy_office_only(box: dict[str, Any]) -> None:  # noqa: F811
    smo = _user(box, "smo1", "coordinator", affiliation="smo", studies="GZQO")
    crc = _user(box, "crc1", "coordinator")
    admin, _ = login(box["app"])
    for c in (smo, crc, admin):
        assert c.get("/site/opt-outs").status_code == 403
        r = c.post("/site/opt-outs", data={"csrf": _csrf(c.get("/account").text), "pid": A, "source": "paper"})
        assert r.status_code == 403
        assert c.post("/site/staff", data={"csrf": _csrf(c.get("/account").text), "name": "Dr X"}).status_code == 403
    for name in ("smo1", "crc1", "admin"):
        api = _api(box, name)
        assert api.get("/api/v1/site/opt-outs").status_code == 403
        assert api.post("/api/v1/site/opt-outs", json={"pid": A}).status_code == 403
    assert admin.get("/site/staff").status_code == 403  # D-380: the administrator no longer keeps the directory
    for name, role in (("stw", "steward"), ("dpo", "privacy")):
        c = _user(box, name, role)
        page = c.get("/site/opt-outs")
        assert page.status_code == 200
        assert c.get("/site/staff").status_code == 200
    dpo, csrf = login(box["app"], "dpo", PW)
    r = dpo.post("/site/opt-outs", data={"csrf": csrf, "pid": A, "source": "paper"}, follow_redirects=False)
    assert r.status_code == 303
    # a lift needs a written reason, on the page and the API
    r = dpo.post("/site/opt-outs", data={"csrf": csrf, "pid": A, "lift": "1"})
    assert r.status_code == 400
    assert (
        _api(box, "dpo").post("/api/v1/site/opt-outs", json={"pid": A, "lift": True, "note": "short"}).status_code
        == 400
    )
    r = dpo.post("/site/opt-outs", data={"csrf": csrf, "pid": A, "lift": "1", "note": "patient asked again by phone"},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and "done=lifted" in r.headers["location"]
    lift = [e for e in _events(box, "console.opt_out") if e["detail"]["action"] == "lift"]
    assert lift and lift[-1]["detail"]["reason"] == "patient asked again by phone"
    assert _user(box, "dpo2", "privacy").get("/home", follow_redirects=False).headers["location"] == "/site/opt-outs"


# ---------------------------------------------------------------------------------------------- ROLE-008
def test_role_008_no_pi_named_means_nobody_acts_as_pi(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(961))
    doc = _user(box, "drsato", "investigator")
    other = _user(box, "drito", "investigator")
    page = doc.get("/studies/GZQO/team").text
    assert 'data-testid="no-pi"' in page and 'data-testid="add-form"' not in page
    assert doc.get("/studies/GZQO/candidates").status_code == 403
    r = doc.post("/studies/GZQO/team", data={"csrf": _csrf(page), "username": "drsato", "role": "pi",
                                             "start": "2026-01-01"})  # fmt: skip
    assert r.status_code == 403  # an investigator cannot claim a study
    tok = _api(box, "drsato")
    assert tok.get("/api/v1/studies/GZQO/candidates").status_code == 403
    assert (
        doc.post(f"/studies/GZQO/patients/{A}/mark", data={"csrf": _csrf(page), "mark": "need_info"}).status_code == 403
    )
    # the steward writes the PI's entry from the signed log; only that PI acts as PI
    stw = _user(box, "stw", "steward")
    spage = stw.get("/studies/GZQO/team").text
    assert 'value="pi"' in spage and 'value="sub_pi"' not in spage  # the steward writes the PI entry, not the team
    r = stw.post("/studies/GZQO/team", data={"csrf": _csrf(spage), "username": "drsato", "role": "sub_pi",
                                             "start": "2026-01-01"})  # fmt: skip
    assert r.status_code == 403
    name_pi(box, "drsato")
    assert doc.get("/studies/GZQO/candidates").status_code == 200
    assert other.get("/studies/GZQO/candidates").status_code == 403
    assert tok.get("/api/v1/studies/GZQO/candidates").status_code == 200
    page = doc.get("/studies/GZQO/team").text
    r = doc.post("/studies/GZQO/team", data={"csrf": _csrf(page), "username": "drito", "role": "sub_pi",
                                             "tasks": ["screen"], "start": "2026-01-01"}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303  # the logged PI keeps the log
    assert other.get("/studies/GZQO/candidates").status_code == 200


# ---------------------------------------------------------------------------------------------- ROLE-011
def test_role_011_smo_and_cro_accounts_name_their_studies(box: dict[str, Any]) -> None:  # noqa: F811
    _done_feas(box["backend"])
    admin, csrf = login(box["app"])
    for role, aff in (("cro", "cro"), ("cro", "hospital"), ("coordinator", "smo")):
        r = admin.post("/ops/users", data={"csrf": csrf, "action": "add", "username": f"x{role}{aff}", "role": role,
                                           "affiliation": aff, "studies": ""})  # fmt: skip
        assert r.status_code == 400, (role, aff)
        assert box["users"].get(f"x{role}{aff}") is None  # refused before the account exists
    r = admin.post("/ops/users", data={"csrf": csrf, "action": "add", "username": "cra1", "role": "cro",
                                       "affiliation": "cro", "studies": "GZQO"}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    r = admin.post("/ops/users", data={"csrf": csrf, "action": "scope", "username": "cra1", "affiliation": "cro",
                                       "studies": ""})  # fmt: skip
    assert r.status_code == 400 and box["users"].get("cra1").studies == ("GZQO",)
    with pytest.raises(AuthError):
        box["users"].set_scope("cra1", "cro", "", None)
    # an account stored without a study (made before D-380) sees none
    box["users"].create("oldcra", "cro", PW)
    old = box["users"].get("oldcra")
    assert old is not None and not old.sees_study("GZQO") and old.studies == ("-",)
    c, _ = login(box["app"], "oldcra", PW)
    assert c.get("/studies/GZQO/feasibility").status_code in (403, 404)
    assert "GZQO" not in c.get("/reports").text
    assert not User("s", "coordinator", None, "smo").sees_study("GZQO")
    assert User("h", "coordinator", None, "hospital").sees_study("GZQO")


# ---------------------------------------------------------------------------------------------- ROLE-015
def test_role_015_irb_dates_are_not_set_silently(box: dict[str, Any]) -> None:  # noqa: F811
    _user(box, "smo1", "coordinator", affiliation="smo", studies="GZQO")
    _user(box, "crc1", "coordinator")
    body = {"approval_no": "IRB-2026-01", "approved_on": "2026-01-01", "expires_on": "2027-01-01",
            "icf_version": "v2.0", "icf_date": "2026-01-01"}  # fmt: skip
    for name in ("smo1", "admin"):
        assert _api(box, name).post("/api/v1/studies/GZQO/irb", json={"approved_on": "2026-01-01"}).status_code == 403
    smo, csrf = login(box["app"], "smo1", PW)
    assert smo.post("/studies/GZQO/irb", data={"csrf": csrf, **body}).status_code == 403
    assert 'data-testid="irb-form"' not in smo.get("/studies/GZQO/irb").text
    crc = _api(box, "crc1")
    r = crc.post("/api/v1/studies/GZQO/irb", json={"approved_on": "2026-01-01"})
    assert r.status_code == 400  # an approval date without its number
    r = crc.post("/api/v1/studies/GZQO/irb", json=body)
    assert r.status_code == 200 and r.json()["warnings"] == []
    r = crc.post("/api/v1/studies/GZQO/irb", json={**body, "expires_on": "2028-01-01"})
    assert r.status_code == 400  # a change needs a reason
    r = crc.post("/api/v1/studies/GZQO/irb", json={**body, "expires_on": "2028-01-01", "reason": "renewal letter 2027"})
    assert r.status_code == 200
    ev = _events(box, "console.irb")[-1]["detail"]
    assert ev["before"]["expires_on"] == "2027-01-01" and ev["expires_on"] == "2028-01-01"
    assert ev["changed"] == "expires_on" and ev["reason"] == "renewal letter 2027"


# ---------------------------------------------------------------------------------------------- ROLE-018
def test_role_018_descriptions_and_menus_come_from_the_matrix(box: dict[str, Any]) -> None:  # noqa: F811
    for lang in ("en", "ja", "zh-TW"):
        cat = {"en": i18n_roles.EN, "ja": i18n_roles.JA, "zh-TW": i18n_roles.ZH}[lang]
        for action in MATRIX:
            assert i18n_roles.right_key(action) in cat, (lang, action)  # a new row needs its label
        assert set(cat) == set(i18n_roles.EN), lang
    admin, _ = login(box["app"])
    page = admin.get("/ops/users").text
    for role in ROLES:
        m = re.search(rf'<li data-role="{role}"><strong>[^<]+</strong>: ([^<]+)</li>', page)
        assert m, role
        assert m.group(1).replace("&#39;", "'") == role_description(role, "en"), role
    viewer = role_description("viewer", "en")
    assert "audit" not in viewer and "runs" not in viewer  # ROLE-018: the viewer opens neither
    assert "patient" not in role_description("admin", "en").replace("one patient", "")
    smo = _user(box, "smo1", "coordinator", affiliation="smo", studies="GZQO")
    nav = smo.get("/home").text
    for href in ('href="/jobs"', 'href="/audit"', 'href="/pilot/cascade"', 'href="/site/opt-outs"'):
        assert href not in nav, href
    for href in ("/jobs", "/audit", "/pilot/cascade"):
        assert smo.get(href).status_code == 403, href
    stw = _user(box, "stw", "steward")
    nav = stw.get("/site/staff").text
    assert 'href="/site/opt-outs"' in nav and 'href="/ops/users"' not in nav


# ---------------------------------------------------------------------------------------------- FIT-002 grant half
SUBJECTS = {
    "S-001": {"record": "S-001", "state": "enrolled", "pid": A, "enrolment": "2026-05-01"},
    "S-002": {"record": "S-002", "state": "candidate", "pid": B},
    "S-003": {"record": "S-003", "state": "screen_fail", "pid": C},
}


def _fake_core(monkeypatch: pytest.MonkeyPatch) -> None:
    from console import s28

    real = s28.call

    def call(bk: Any, method: str, path: str, body: Any = None, headers: Any = None) -> Any:
        if method == "GET" and path.startswith("/studies/GZQO/edc/"):  # no EDC value yet (the SDV page reads them)
            return [] if "/edc/drafts" in path else {"drafts": [], "decisions": [], "signatures": []}
        m = re.match(r"^/studies/GZQO/subjects/([^?/]+)\?", path)
        if method == "GET" and m:
            if m.group(1) not in SUBJECTS:
                raise Problem(404, "notfound", "no such subject")
            # the data core's real reply shape (orchestrator.lifecycle_api.get_subject): the subject is nested (D-436)
            return {"study": "GZQO", "today": "2026-11-11", "subject": dict(SUBJECTS[m.group(1)]), "steps": [],
                    "visits": [], "aes": [], "deviations": []}  # fmt: skip
        return real(bk, method, path, body, headers)

    monkeypatch.setattr(s28, "call", call)


def test_fit_002_the_monitor_grant_refuses_a_non_enrolled_subject(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_core(monkeypatch)
    mon = _user(box, "mon1", "cro", affiliation="cro", studies="GZQO")
    _user(box, "drsato", "investigator")
    assert mon.get("/studies/GZQO/monitor/S-001").status_code == 403  # no grant yet
    name_pi(box, "drsato")
    pi, csrf = login(box["app"], "drsato", PW)
    grant = {"csrf": csrf, "username": "mon1", "role": "monitor", "start": "2026-01-01"}
    assert pi.post("/studies/GZQO/team", data={**grant, "training_ref": "MV-7"}).status_code == 400  # no end date
    assert pi.post("/studies/GZQO/team", data={**grant, "end": "2099-12-31"}).status_code == 400  # no visit id
    r = pi.post("/studies/GZQO/team", data={**grant, "end": "2099-12-31", "training_ref": "MV-7"},
                follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    page = mon.get("/studies/GZQO/monitor/S-001")
    assert page.status_code == 200 and "enrolled" in page.text and A[:8] not in page.text and "MV-7" in page.text
    for rec in ("S-002", "S-003"):  # a candidate, a screen failure: refused
        assert mon.get(f"/studies/GZQO/monitor/{rec}").status_code == 403, rec
    assert mon.get("/studies/OTHER/monitor/S-001").status_code == 404
    assert mon.get(f"/studies/GZQO/candidates/{A}?purpose=eligibility").status_code == 403
    api = _api(box, "mon1")
    r = api.get("/api/v1/studies/GZQO/monitor/S-001")
    assert r.status_code == 200 and r.json()["visit"] == "MV-7" and "pid" not in r.json()["subject"]
    assert api.get("/api/v1/studies/GZQO/monitor/S-002").status_code == 403
    views = _events(box, "console.monitor_view")
    assert [v["detail"]["visit"] for v in views] == ["MV-7", "MV-7"]
    denied = [e for e in _events(box, "console.denied") if e["detail"].get("why") == "not_enrolled"]
    assert len(denied) == 3
    # a grant names a CRO account; a coordinator, an investigator or the CRO itself cannot read through it
    assert pi.get("/studies/GZQO/monitor/S-001").status_code == 403
    r = pi.post("/studies/GZQO/team", data={**grant, "username": "drsato", "end": "2099-12-31", "training_ref": "x"})
    assert r.status_code == 400
