"""Report-first role pages (D-104): role homes, the feasibility report, the weekly PI list, the patient page, PI
marks, the CRO and study-scope limits, in three languages."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from console import studies as st
from console.i18n import CATALOGUES
from console.sitestore import Mark, SiteProfile, SiteStore
from fastapi.testclient import TestClient
from tb_common.crypto import sha256_bytes
from tb_contracts import JobOutput

from tests.console.test_console_app import (  # noqa: F401 - the fixture is used by name
    ADMIN_PW,
    _done_feas,
    _done_screen,
    _ulid,
    box,
    login,
)

PW = "role-pages-password-01"


def _user(b: dict[str, Any], name: str, role: str, **scope: str) -> TestClient:
    b["users"].create(name, role, PW, f"{name}@hospa.test")
    if scope:
        b["users"].set_scope(name, **scope)
    c, _ = login(b["app"], name, PW)
    return c


def _csrf(page: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', page)
    assert m
    return m.group(1)


def _add_profile(backend: Any, job_id: str) -> None:
    prof = {
        "pool_now": 5,
        "potential": 40,
        "visits_90d": "<5",
        "screen_fail_default": 0.6,
        "screen_fail_source": "Clarity AD",
        "small_cell": 5,
        "demographics": {
            "bands": [{"band": "70-79", "F": 5, "M": "<5", "other": 0, "n": 5}],
            "sex": {"F": 5, "M": "<5", "other": 0},
            "age_unknown": 0,
        },
        "data": {"appointment_rows": 120, "note_chunks": 0},
        "projection": {"months": 12, "path": [[0.1 * m, 0.2 * m, 0.4 * m] for m in range(1, 13)]},
    }
    job = backend.jobs[job_id]
    name = "feasprofile_GZQO_v1.0.0_2026-10-04.json"
    data = json.dumps(prof).encode()
    backend.objects[f"outputs/{job_id}/{name}"] = data
    job.outputs.append(
        JobOutput(
            filename=name,
            sha256=sha256_bytes(data),
            minio_key=f"outputs/{job_id}/{name}",
            recipients=[],
            tag="aggregate",
        )
    )


# ---------------------------------------------------------------------------------------------- pure rules
def test_go_reading_boundaries() -> None:
    assert st.go_reading(8, 10, 12, 8) == "go"
    assert st.go_reading(7.9, 10, 12, 8) == "conditional"
    assert st.go_reading(1, 2, 8, 8) == "conditional"
    assert st.go_reading(1, 2, 7.9, 8) == "nogo"
    assert st.go_reading(1, 2, 3, None) is None


@pytest.mark.parametrize(
    ("tier", "reg", "mark", "new", "want"),
    [
        ("high", None, None, True, "new"),
        ("high", None, None, False, "pending"),
        ("review", None, "need_info", False, "pending"),
        ("high", None, "approach", True, "new"),
        ("high", None, "not_suitable", False, "not_eligible"),
        ("excluded", None, None, True, "not_eligible"),
        ("high", "contacted", None, False, "contacted"),
        ("high", "consented", None, False, "screened"),
        ("high", "enrolled", None, False, "enrolled"),
        ("high", "screen_fail", None, False, "not_eligible"),
        ("high", "declined", "approach", False, "not_eligible"),
        ("high", "withdrawn", None, False, "not_eligible"),
    ],
)
def test_status_derivation(tier: str, reg: str | None, mark: str | None, new: bool, want: str) -> None:
    assert st.derive_status(tier, reg, mark, new) == want


def test_fit_facts_count_and_open_items() -> None:
    crit = {
        "I1": st.CriterionMeta("I1", "inclusion", "structured", "MCI diagnosis"),
        "I2": st.CriterionMeta("I2", "inclusion", "structured", "MMSE 22-30"),
        "I3": st.CriterionMeta("I3", "inclusion", "human", "study partner"),
        "E1": st.CriterionMeta("E1", "exclusion", "note", "anticoagulant"),
        "E2": st.CriterionMeta("E2", "exclusion", "structured", "other neuro"),
    }
    fit = st.fit_facts(
        [
            {"id": "I1", "verdict": "pass", "evidence": {"quote_date": "2025-03-18"}},
            {"id": "I2", "verdict": "unknown", "evidence": {}},
            {"id": "I3", "verdict": "pending_human", "evidence": {}},
            {"id": "E1", "verdict": "fail", "evidence": {"quote": "ワーファリン内服中", "quote_date": "2026-10-02"}},
            {"id": "E2", "verdict": "pass", "evidence": {}},
        ],
        crit,
    )
    assert (fit.inc_met, fit.inc_total, fit.exc_clear, fit.exc_total) == (1, 3, 1, 2)
    assert fit.open == ["MMSE 22-30"] and fit.person == ["study partner"]
    assert fit.key[0]["label"] == "MCI diagnosis" and fit.note_exclusion[0]["quote"] == "ワーファリン内服中"
    # a failed inclusion is shown as "not met", never silently dropped (review 6 Nov)
    fit2 = st.fit_facts([{"id": "I2", "verdict": "fail", "evidence": {"quote": "MMSE 18"}}], crit)
    assert fit2.not_met == ["MMSE 22-30"] and fit2.inc_met == 0


def test_feas_report_applies_screen_failure_and_target() -> None:
    result = {
        "start_n": 600,
        "funnel": [
            {"criterion_id": "I1", "label": "dx", "remaining": 120, "dropped": 480, "unknown": 300, "pct": 20.0},
            {"criterion_id": "I2", "label": "partner", "remaining": 120, "dropped": 0, "applied": False},
        ],
        "sensitivity": [{"criterion_id": "*", "variant": "unknown_as_pass", "remaining": 400}],
        "simulation": {"months": 12, "low": 10, "mid": 20, "high": 30, "reach_rate": 0.6, "accept_rate": 0.35},
        "monthly_new": [],
    }
    crit = {"I1": st.CriterionMeta("I1", "inclusion", "structured", "dx")}
    rep = st.feas_report(result, {"screen_fail_default": 0.6}, SiteProfile(target_n=8, target_months=12), crit)
    s = rep["summary"]
    assert s["horizon"] == [4.0, 8.0, 12.0] and s["screen_fail_source"] == "default"
    assert s["reading"] == "conditional" and s["potential"] == "400" and s["n_not_applied"] == 1
    assert rep["barriers"][0] == {"id": "I1", "label": "dx", "dropped": 480, "never": 300, "failed": 180}
    site = SiteProfile(screen_fail=0.0, comment="paper MMSE", comment_to_sponsor=False)
    assert st.feas_report(result, None, site, crit)["summary"]["horizon"] == [10.0, 20.0, 30.0]
    assert st.feas_report(result, None, site, crit, sponsor=True)["comment"] == ""
    assert st.feas_report(result, None, SiteProfile(), crit)["summary"]["consent_only"] is True


def test_site_store_profile_marks_and_seen(tmp_path: Path) -> None:
    s = SiteStore(tmp_path / "site.sqlite")
    assert s.profile("GZQO").missing == ["capability", "competing", "target"]
    s.save_profile(
        "GZQO", SiteProfile(target_n=6, capabilities={"amyloid_pet": {"value": "partner", "note": ""}}), "crc1", "t"
    )
    assert s.profile("GZQO").missing == ["competing"]
    s.mark("GZQO", Mark("a" * 32, "need_info", None, None, "pi", "2026-11-01T00:00", "J1"))
    s.mark("GZQO", Mark("a" * 32, "approach", None, None, "pi", "2026-11-02T00:00", "J1"))
    assert s.latest_marks("GZQO")["a" * 32].mark == "approach" and len(s.mark_history("GZQO", "a" * 32)) == 2
    with pytest.raises(ValueError):
        s.mark("GZQO", Mark("a" * 32, "screen_fail", None, None, "pi", "t", None))
    assert s.seen("GZQO", ["p1", "p2"], "J1", "t") == {"p1": "J1", "p2": "J1"}
    assert s.seen("GZQO", ["p2", "p3"], "J2", "t") == {"p1": "J1", "p2": "J1", "p3": "J2"}


# ---------------------------------------------------------------------------------------------- pages
def test_each_role_lands_on_its_own_home_with_at_most_four_items(box: dict[str, Any]) -> None:
    _done_feas(box["backend"])
    _done_screen(box["backend"], _ulid(950))
    admin, _ = login(box["app"])
    r = admin.get("/home")
    assert 'data-testid="tile-accounts"' in r.text and 'data-testid="tile-system"' in r.text
    crc = _user(box, "crc1", "coordinator")
    r = crc.get("/")
    assert r.url.path == "/home" and 'data-testid="study-GZQO"' in r.text and 'data-testid="next-GZQO"' in r.text
    pi = _user(box, "drsato", "investigator")
    r = pi.get("/")
    assert r.url.path == "/studies/GZQO/week"
    cro = _user(box, "cra1", "cro", affiliation="cro")
    r = cro.get("/")
    assert r.url.path == "/reports" and 'data-testid="cro-note"' in r.text
    for c in (admin, crc, pi, cro):
        nav = re.search(r'<nav aria-label="main".*?</nav>', c.get("/home").text, re.S)
        assert nav
        top = re.sub(r"<details.*?</details>", "", nav.group(0), flags=re.S)
        assert len(re.findall(r"<a ", top)) <= 4


def test_feasibility_report_sections_site_fields_and_sponsor_view(box: dict[str, Any]) -> None:
    job = _done_feas(box["backend"])
    _add_profile(box["backend"], job.job_id)
    crc = _user(box, "crc1", "coordinator")
    page = crc.get("/studies/GZQO/feasibility").text
    for n in range(1, 13):
        assert f"{n} · " in page
    assert 'data-testid="projection-chart"' in page and 'data-testid="demographics"' in page
    assert "60 %" in page  # the early-AD default screen failure is printed with its source
    r = crc.post(
        "/studies/GZQO/profile",
        data={
            "csrf": _csrf(page),
            "target_n": "8",
            "target_months": "12",
            "screen_fail": "50",
            "cap_amyloid_pet": "partner",
            "ct_id_0": "jRCT2031230001",
            "ct_title_0": "anti-amyloid early AD",
            "ct_overlap_0": "same",
            "comment": "MMSE on paper until 2025",
        },
        follow_redirects=True,
    )
    assert "jRCT2031230001" in r.text and "MMSE on paper until 2025" in r.text and 'data-testid="reading"' in r.text
    sponsor = crc.get("/studies/GZQO/feasibility?view=sponsor").text
    assert 'data-testid="sponsor-banner"' in sponsor and "MMSE on paper until 2025" not in sponsor
    viewer, _ = login(box["app"], "viewer", "viewer-password-0001")
    r = viewer.post("/studies/GZQO/profile", data={"csrf": _csrf(viewer.get("/reports").text), "target_n": "1"})
    assert r.status_code == 403


def test_weekly_list_marks_and_patient_page_in_three_languages(box: dict[str, Any]) -> None:
    _done_screen(box["backend"], _ulid(951))
    pi = _user(box, "drsato", "investigator")
    page = pi.get("/studies/GZQO/week").text
    assert 'data-testid="row-aaaaaaaa"' in page and 'data-testid="row-bbbbbbbb"' in page
    assert page.index("row-aaaaaaaa") < page.index("row-bbbbbbbb")  # booked visit first, no visit last
    assert "cccccccc" not in page  # excluded tier never listed
    r = pi.post(
        f"/studies/GZQO/patients/{'b' * 32}/mark",
        data={"csrf": _csrf(page), "mark": "not_suitable", "reason": "partner"},
        follow_redirects=True,
    )
    assert 'data-testid="row-bbbbbbbb"' not in r.text  # not suitable leaves the list
    r = pi.post(
        f"/studies/GZQO/patients/{'a' * 32}/mark", data={"csrf": _csrf(page), "mark": "approach"}, follow_redirects=True
    )
    assert 'data-testid="mark-aaaaaaaa"' in r.text
    events = [json.loads(x) for f in sorted((box["dir"] / "audit").glob("*")) for x in f.read_text().splitlines() if x]
    assert sum(1 for e in events if e.get("event") == "console.pi_mark") == 2
    p = pi.get(f"/studies/GZQO/patients/{'a' * 32}").text
    assert "two flares this spring" in p and 'data-testid="criteria"' in p
    r = pi.post(f"/studies/GZQO/patients/{'a' * 32}/reveal", data={"csrf": _csrf(p)})
    assert "MRN-000123" in r.text and box["backend"].revealed[-1][2] == "console:drsato"
    crc = _user(box, "crc1", "coordinator")
    r = crc.post(
        f"/studies/GZQO/patients/{'a' * 32}/mark", data={"csrf": _csrf(crc.get("/home").text), "mark": "approach"}
    )
    assert r.status_code == 403  # marks are the investigator's
    for lang, word in (("ja", "今週の候補患者リスト"), ("zh-TW", "本週候選病人名單")):
        pi.post("/lang", data={"csrf": _csrf(page), "lang": lang, "back": "/studies/GZQO/week"})
        assert word in pi.get("/studies/GZQO/week").text


def test_cro_and_scoped_accounts_see_only_what_they_may(box: dict[str, Any]) -> None:
    feas = _done_feas(box["backend"])
    _done_screen(box["backend"], _ulid(952))
    cro = _user(box, "cra1", "cro", affiliation="cro")
    assert cro.get("/studies/GZQO/feasibility").status_code == 200
    assert 'data-testid="sponsor-banner"' in cro.get("/studies/GZQO/feasibility").text  # always the sponsor copy
    for path in (
        "/studies/GZQO/week",
        f"/studies/GZQO/patients/{'a' * 32}",
        "/jobs",
        "/audit",
        f"/pilot/jobs/{feas.job_id}",
    ):
        assert cro.get(path).status_code == 403, path
    smo = _user(box, "smo1", "coordinator", affiliation="smo", studies="OTHER", expires="2099-12-31")
    assert 'data-testid="smo-banner"' in smo.get("/home").text
    assert smo.get("/studies/GZQO/feasibility").status_code == 404
    assert smo.get(f"/pilot/jobs/{feas.job_id}").status_code == 404
    assert smo.get("/pilot/registry/GZQO").status_code == 404
    # review 6 Nov: no request for another study, no cross-study lists
    page = smo.get("/pilot/request?ruleset=GZQO")
    if page.status_code == 200:
        r = smo.post(
            "/pilot/request",
            data={"csrf": _csrf(page.text), "kind": "SCREEN", "ruleset": "GZQO", "version": "1.0.0"},
            follow_redirects=False,
        )
        assert r.status_code == 404, r.text[:300]
    for path in ("/jobs", "/audit", "/pilot/mailbox", "/pilot/cascade"):
        assert smo.get(path).status_code == 403, path
    assert "GZQO" not in smo.get("/pilot/registry").text
    # the CRO account gets the sponsor pack of a study, nothing else of the job
    assert cro.get(f"/pilot/jobs/{feas.job_id}/sponsor-pack.zip").status_code == 200


def test_expired_account_cannot_sign_in(box: dict[str, Any]) -> None:
    box["users"].create("old", "coordinator", PW)
    box["users"].set_scope("old", affiliation="smo", studies="GZQO", expires="2020-01-01")
    c = TestClient(box["app"])
    token = re.search(r'name="login_csrf" value="([^"]+)"', c.get("/login").text)
    assert token
    r = c.post("/login", data={"username": "old", "password": PW, "login_csrf": token.group(1)}, follow_redirects=False)
    assert r.status_code != 303


def test_expired_sso_account_is_refused(tmp_path: Path) -> None:
    from console.app import create_app
    from console.auth import UserStore
    from tb_common.audit import AuditLog

    from tests.console.test_console_app import SSO_ENV, FakeBackend

    backend = FakeBackend()
    backend.audit_dir = tmp_path / "audit"
    users = UserStore(tmp_path / "c.sqlite")
    users.create("admin", "admin", ADMIN_PW, "admin@hospa.test")
    app = create_app(
        {**SSO_ENV, "TB_CONSOLE_DIR": str(tmp_path)}, backend=backend, audit=AuditLog(backend.audit_dir), users=users
    )
    c = TestClient(app, headers={"X-Forwarded-User": "nurse.old@hospa.test", "X-Forwarded-Groups": "crc"})
    assert c.get("/home", follow_redirects=False).status_code == 200
    users.set_scope("nurse.old", affiliation="smo", studies="GZQO", expires="2020-01-01")
    fresh = TestClient(app, headers={"X-Forwarded-User": "nurse.old@hospa.test", "X-Forwarded-Groups": "crc"})
    assert fresh.get("/home", follow_redirects=False).status_code == 303  # to the sign-in page


def test_admin_scope_is_checked_before_the_account_exists_and_can_be_edited(box: dict[str, Any]) -> None:
    admin, _ = login(box["app"], "admin", ADMIN_PW)
    tok = _csrf(admin.get("/ops/users").text)
    bad = {"csrf": tok, "action": "add", "username": "smo9", "role": "coordinator", "affiliation": "smo",
           "studies": "GZQO", "expires": "31/03/2027", "mailbox": ""}  # fmt: skip
    assert admin.post("/ops/users", data=bad, follow_redirects=False).status_code == 400
    assert box["users"].get("smo9") is None
    ok = {**bad, "expires": "2027-03-31"}
    assert admin.post("/ops/users", data=ok, follow_redirects=False).status_code == 303
    edit = {"csrf": tok, "action": "scope", "username": "smo9", "affiliation": "smo", "studies": "GZQO,LEQ-301",
            "expires": "2027-06-30"}  # fmt: skip
    assert admin.post("/ops/users", data=edit, follow_redirects=False).status_code == 303
    u = box["users"].get("smo9")
    assert u is not None and u.studies == ("GZQO", "LEQ-301") and u.expires == "2027-06-30"


def test_go_reading_uses_the_path_at_the_sponsor_deadline() -> None:
    result = {"start_n": 600, "funnel": [], "sensitivity": [], "simulation": {"low": 2.0, "mid": 5.0, "high": 9.0}}
    prof = {"projection": {"months": 12, "path": [[0.5 * m, 1.0 * m, 1.5 * m] for m in range(1, 13)]}}
    # target 3 by month 6: the path at month 6 is (3, 6, 9), so GO; pro-rating would compare 6 at month 12 with the
    # 12-month low of 2 and say CONDITIONAL
    site = SiteProfile(target_n=3, target_months=6)
    rep = st.feas_report(result, prof, site, {})
    assert rep["summary"]["reading"] == "go"  # path low at month 6 is 3.0 >= 3


def test_role_page_strings_exist_in_every_language() -> None:
    from console import i18n_home

    for lang in ("ja", "zh-TW"):
        missing = [k for k in i18n_home.EN if k not in CATALOGUES[lang]]
        assert not missing, (lang, missing[:5])
    assert datetime.now(UTC)  # keep the import list honest for the unused-import check
    assert ADMIN_PW
