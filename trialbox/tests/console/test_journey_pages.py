"""User-journey review of 2026-11-09, wave 1c (D-146), on the console: the request refusals in the page's language
(J-01, J-02), one role rule for pages and ``/api/v1`` (J-03, J-04, J-05), the codes template (J-08), the account
names on the site pages (J-17), the screening scope on the study's set-up page (J-26), who ticks and approves the
criteria (J-27), the site label over the protocol's words, the username pattern and the readiness API's study."""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

import pytest
from console import studies as st
from console.i18n import CATALOGUES
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sitesetup import help as site_help

from tests.console.test_console_app import (  # noqa: F401 - the fixture is used by name
    ADMIN_PW,
    VIEWER_PW,
    _done_case,
    _done_feas,
    _done_screen,
    box,
    login,
)
from tests.console.test_site_setup_pages import PW as SB_PW
from tests.console.test_site_setup_pages import _csrf, sb  # noqa: F401 - the fixture is used by name
from tests.console.test_step3 import PW as B3_PW
from tests.console.test_step3 import b3  # noqa: F401 - the fixture is used by name

ROOT = Path(__file__).resolve().parents[2]
PW = "journey-review-password-1"


# ---------------------------------------------------------------------------------------------- J-01 / J-02
def test_a_console_request_names_the_person_and_role(box: dict[str, Any]) -> None:  # noqa: F811
    """The console sends the signed-in person and role, so the orchestrator authorises by role (D-146)."""
    box["users"].create("crc7", "coordinator", PW)  # made on the console: no mailbox (the admin's mail is used)
    c, csrf = login(box["app"], "crc7", PW)
    r = c.post("/pilot/request", data={"csrf": csrf, "kind": "FEAS", "ruleset": "GZQO"}, follow_redirects=False)
    assert r.status_code == 303
    assert box["backend"].created_by[-1] == ("console:crc7", "coordinator")


@pytest.mark.parametrize(
    ("refusal", "status", "key"),
    [
        ("rate limit reached (20 SCREEN jobs per sender per day)", 429, "request.limit"),
        ("the coordinator role may not run SCREEN", 403, "request.role"),
        ("admin@hospa.test is not permitted to run SCREEN", 403, "request.mailbox"),
    ],
)
@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_a_refused_request_says_why_in_the_page_language(
    box: dict[str, Any],  # noqa: F811
    refusal: str,
    status: int,
    key: str,
    lang: str,
) -> None:
    box["backend"].refuse = refusal
    c, csrf = login(box["app"])
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
    r = c.post("/pilot/request", data={"csrf": csrf, "kind": "SCREEN", "ruleset": "GZQO", "version": "1.0.0"})
    want = CATALOGUES[lang][key].format(n=20, kind="SCREEN", mailbox="admin@hospa.test")
    assert r.status_code == status and want in r.text.replace("&#39;", "'")
    assert "{&#34;detail&#34;" not in r.text and '{"detail"' not in r.text and refusal not in r.text


# ---------------------------------------------------------------------------------------------- J-03 / J-04 / J-05
def _api(app: Any, user: str, pw: str) -> TestClient:
    c = TestClient(app)
    tok = c.post("/api/v1/session", json={"username": user, "password": pw}).json()["token"]
    c.headers["Authorization"] = f"Bearer {tok}"
    return c


def _paths(app: Any, values: dict[str, str]) -> list[str]:
    out = []
    for r in app.routes:
        if not isinstance(r, APIRoute) or "GET" not in (r.methods or set()):
            continue
        names = re.findall(r"{(\w+)(?::\w+)?}", r.path)
        if all(n in values for n in names):
            out.append(re.sub(r"{(\w+)(?::\w+)?}", lambda m: values[m.group(1)], r.path))
    return out


@pytest.mark.parametrize("role", ["viewer", "cro"])
def test_aggregate_only_accounts_get_no_patient_level_page_or_api(box: dict[str, Any], role: str) -> None:  # noqa: F811
    """Every GET route, page and ``/api/v1``, walked as a viewer and as a CRO account: a study's pages other than
    its feasibility report, every job page but a feasibility run's, the registry, the audit trail, the runs list,
    the site set-up and the REDCap connections answer 403 (or 404), never 200."""
    bk = box["backend"]
    case, screen, feas = _done_case(bk), _done_screen(bk, "01JTEST0000000000000000777"), _done_feas(bk)
    box["users"].create("acct", role, PW)
    page = login(box["app"], "acct", PW)[0]
    api = _api(box["app"], "acct", PW)
    values = {"rs": "GZQO", "ruleset": "GZQO", "pid": "a" * 32, "record": "1", "event": "1", "fmt": "csv",
              "form": "f", "cid": "1", "fid": "1", "name": "codes", "kind": "x"}  # fmt: skip
    leaks = []
    for job in (case.job_id, screen.job_id):
        for path in _paths(box["app"], {**values, "job_id": job}):
            if not path.startswith("/pilot/jobs/"):
                continue
            if page.get(path, follow_redirects=False).status_code == 200:
                leaks.append(path)
    for path in _paths(box["app"], values):
        is_api = path.startswith("/api/v1/")
        study_level = re.match(r"^/(?:api/v1/)?studies/GZQO/", path) and not path.endswith("/feasibility")
        listed = re.match(r"^/(?:jobs|audit|admin/redcap|pilot/registry|site|api/v1/site)(?:/|$)", path)
        if not (study_level or listed):
            continue
        r = (api if is_api else page).get(path, follow_redirects=False)
        if r.status_code not in (403, 404):
            leaks.append(f"{path} {r.status_code}")
    assert leaks == []
    for path in ("/api/v1/studies/GZQO/patients", "/api/v1/studies/GZQO/screening-log"):
        assert api.get(path).status_code == 403
    for path in (f"/pilot/jobs/{case.job_id}", "/pilot/registry/GZQO", "/audit", "/jobs", "/admin/redcap"):
        assert page.get(path).status_code == 403, path
    if role == "viewer":  # what an aggregate-only account is for
        assert page.get(f"/pilot/jobs/{feas.job_id}").status_code == 200
        assert page.get("/studies/GZQO/feasibility").status_code == 200
    assert api.get("/api/v1/studies").status_code == 200
    nav = page.get("/reports").text
    assert not re.search(r'href="/(?:jobs|audit|pilot/registry|admin/redcap)"', nav)


def test_the_study_team_keeps_its_pages_and_api(box: dict[str, Any]) -> None:  # noqa: F811
    box["users"].create("crc", "coordinator", PW, "crc1@hospa.test")
    api = _api(box["app"], "crc", PW)
    assert api.get("/api/v1/studies/GZQO/patients").status_code == 200
    assert api.get("/api/v1/studies/GZQO/screening-log").status_code == 200
    page = login(box["app"], "crc", PW)[0]
    for path in ("/jobs", "/audit", "/pilot/registry/GZQO", f"/pilot/jobs/{_done_case(box['backend']).job_id}"):
        assert page.get(path).status_code == 200, path
    assert page.get("/admin/redcap").status_code == 403  # S36 is the administrator's


# ---------------------------------------------------------------------------------------------- J-08 / J-17 / J-16
def test_codes_template_downloads_and_pages_name_the_person(sb: dict[str, Any]) -> None:  # noqa: F811
    from openpyxl import load_workbook

    c, csrf = login(sb["app"], "crc", SB_PW)
    c.post("/lang", data={"csrf": csrf, "lang": "ja", "back": "/site/codes"})
    page = c.get("/site?study=GZQO").text
    dump_name, dump = site_help.practice_inputs()["dump"]
    c.post("/site/sheets", data={"csrf": _csrf(page), "ws": "main", "study": "GZQO", "kind": "dump"},
           files={"file": (dump_name, dump, "text/csv")})  # fmt: skip
    x = c.get("/site/templates/codes.xlsx")
    assert x.status_code == 200 and load_workbook(io.BytesIO(x.content)).worksheets[0].max_row >= 2
    page = c.get("/site/codes?study=GZQO").text
    code = re.findall(r'data-testid="map-([^"]+)"', page)[0]
    form = re.search(rf'data-testid="map-{re.escape(code)}">(.*?)</form>', page, re.S)
    assert form
    hidden = dict(re.findall(r'name="(domain|system|code)" value="([^"]*)"', form.group(1)))
    c.post("/site/codes", data={"csrf": _csrf(page), "ws": "main", "study": "GZQO", **hidden, "target": "I10"})
    page = c.get("/site/codes?study=GZQO").text
    assert "console:crc" not in page and re.search(r'class="nowrap">crc</td>', page)


def test_readiness_api_needs_the_study_when_the_account_has_several(sb: dict[str, Any]) -> None:  # noqa: F811
    api = _api(sb["app"], "crc", SB_PW)
    r = api.get("/api/v1/site/readiness")
    assert r.status_code == 400 and r.json()["detail"]["code"] == "study-required"
    assert set(r.json()["detail"]["studies"]) == {"GZQO", "RA-BIO"}
    assert api.get("/api/v1/site/readiness?study=GZQO").status_code == 200


# ---------------------------------------------------------------------------------------------- J-26
def test_the_set_up_page_sets_who_to_screen(b3: dict[str, Any]) -> None:  # noqa: F811
    c, csrf = login(b3["app"], "crc", B3_PW)
    c.post("/lang", data={"csrf": csrf, "lang": "ja", "back": "/studies/GZQO/setup"})
    page = c.get("/studies/GZQO/setup").text
    assert 'data-testid="setup-who"' in page and CATALOGUES["ja"]["setup.who.unset"] in page
    r = c.post("/studies/GZQO/setup/scope", data={"csrf": csrf, "mode": "hospital"})
    assert r.status_code == 200 and CATALOGUES["ja"]["setup.who.now.hospital"] in r.text
    assert b3["svc"].store.screen_scope("GZQO")["mode"] == "hospital"
    r = c.post("/studies/GZQO/setup/scope", data={"csrf": csrf, "mode": "practitioners", "practitioners": "P1、 P2"})
    assert b3["svc"].store.screen_scope("GZQO")["practitioners"] == ["P1", "P2"]
    r = c.post("/studies/GZQO/setup/scope", data={"csrf": csrf, "mode": "practitioners", "practitioners": "<x>"})
    assert r.status_code == 400 and "<x>" not in r.text
    pi, pcsrf = login(b3["app"], "pi", B3_PW)  # the coordinator sets it; the investigator reads it
    assert 'data-testid="who-form"' not in pi.get("/studies/GZQO/setup").text
    assert pi.post("/studies/GZQO/setup/scope", data={"csrf": pcsrf, "mode": "hospital"}).status_code == 403


# ---------------------------------------------------------------------------------------------- J-27 and the draft
def test_who_ticks_and_approves_is_said_in_three_languages() -> None:
    from console.i18n_journey import EN as J_EN
    from console.i18n_journey import JA as J_JA
    from console.i18n_journey import ZH as J_ZH

    assert set(J_EN) == set(J_JA) == set(J_ZH)
    for lang, words in (("en", J_EN), ("ja", J_JA), ("zh-TW", J_ZH)):
        assert all(CATALOGUES[lang][k] == v for k, v in words.items()), lang  # merged last: these words win
    assert "investigator ticks" in CATALOGUES["en"]["s20.who"] and "責任医師" in CATALOGUES["ja"]["s20.who"]
    assert "can tick codes" not in CATALOGUES["en"]["s20.only_pi"]


def test_the_site_label_wins_over_the_words_a_run_wrote_down() -> None:
    site = st.CriterionMeta("X-INC-01", "inclusion", "structured", "20歳以上", "", "Age 20 years or older")
    plain = st.CriterionMeta("X-INC-02", "inclusion", "structured", "Diagnosis of gout", "")
    assert st.site_or_written("Age 20 years or older", site, "X-INC-01") == ("20歳以上", True)
    assert st.site_or_written("Diagnosis of gout (M10)", plain, "X-INC-02") == ("Diagnosis of gout (M10)", False)
    assert st.site_or_written(None, None, "X-INC-03") == ("X-INC-03", False)
    html = (ROOT / "services/console/templates/approval.html").read_text(encoding="utf-8")
    assert "<span data-authored>{{ r.text }}</span>" in html and "site-label-" in html


# ---------------------------------------------------------------------------------------------- the username pattern
def _v_flag_ok(pattern: str) -> bool:
    """The HTML ``pattern`` attribute compiles with the ``v`` flag: inside a class a ``-`` that is not a range, and
    the class syntax characters ``( ) [ { } / |``, must be escaped."""
    i, n = 0, len(pattern)
    while i < n:
        if pattern[i] == "\\":
            i += 2
            continue
        if pattern[i] != "[":
            i += 1
            continue
        j, atoms = i + 1, []
        while j < n and pattern[j] != "]":
            if pattern[j] == "\\":
                atoms.append(pattern[j : j + 2])
                j += 2
                continue
            if pattern[j] in "()[{}/|":
                return False
            atoms.append(pattern[j])
            j += 1
        for k, a in enumerate(atoms):
            if a == "-" and (k == 0 or k == len(atoms) - 1 or atoms[k - 2 : k - 1] == ["-"]):
                return False
        i = j + 1
    return True


def test_every_pattern_attribute_is_valid_with_the_v_flag() -> None:
    assert not _v_flag_ok("[a-z0-9._-]+") and _v_flag_ok(r"[a-z0-9._\-]+")
    bad = []
    for f in sorted((ROOT / "services/console/templates").glob("*.html")):
        for p in re.findall(r'pattern="([^"]*)"', f.read_text(encoding="utf-8")):
            if not _v_flag_ok(p):
                bad.append(f"{f.name}: {p}")
    assert bad == []
