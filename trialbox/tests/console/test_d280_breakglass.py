"""D-280, fix group "data steward and break-glass" (TB-REG-01 CR-023, CR-029; owner decision OD-5; PX-6).

The administrator holds no patient-level right on the routine pages: no candidate row, no patient page, no reveal,
no registry, no SAE row, no opt-out register. One patient or one job opens only through a break-glass grant: a reason
from a fixed list plus a written note, 60 minutes, then it ends by itself. Every opening and use is audited, the
steward and the study's PI are told at once, and the steward reviews each grant. A steward role keeps the opt-out
register. Synthetic pseudonyms and chart numbers only."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from console.auth import ROLES, User
from fastapi.testclient import TestClient
from tb_common import authz
from tb_common import service_auth as sa

from tests.console.test_console_app import _done_screen, _ulid, box, login  # noqa: F401 - the fixture by name
from tests.console.test_role_pages import _csrf, _user

A, B = "a" * 32, "b" * 32


def _events(b: dict[str, Any], name: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted((b["dir"] / "audit").glob("*")):
        for line in f.read_text().splitlines():
            if line and json.loads(line).get("event") == name:
                out.append(json.loads(line))
    return out


def _open(c: TestClient, **form: str) -> Any:
    data = {"csrf": _csrf(c.get("/breakglass").text), "reason": "support", "note": "support call about one patient"}
    data.update(form)
    return c.post("/breakglass", data=data, follow_redirects=False)


def _shift(b: dict[str, Any], minutes: int) -> None:
    """Move the console's clock (the grants' clock) forward."""
    h = b["app"].state.helpers
    base = h.clock()
    h.clock = lambda: base + timedelta(minutes=minutes)


# ---------------------------------------------------------------------------------------------- CR-023 (PX-6)
def test_the_administrator_holds_no_patient_level_right() -> None:
    admin = User("it1", "admin", None)
    assert not admin.can_view_phi and not admin.can_reveal and not admin.sees_ids("GZQO") and not admin.sees_ids(None)
    assert authz.study_tasks("admin", log_names_pi=False, is_pi=False, ticked=frozenset()) == frozenset()
    assert not authz.sae_allowed("admin", "view")
    assert "steward" in ROLES
    stw = User("stw1", "steward", None)
    assert not stw.can_view_phi and not stw.can_reveal  # the steward's own patient pages are T-102b's
    for role in ("coordinator", "investigator"):
        assert User("x", role, None).can_view_phi and User("x", role, None).can_reveal  # type: ignore[arg-type]


def test_the_administrators_pages_show_no_patient_row(box: dict[str, Any]) -> None:  # noqa: F811
    jid = _ulid(990)
    _done_screen(box["backend"], jid)
    admin, csrf = login(box["app"])
    page = admin.get(f"/pilot/jobs/{jid}").text
    assert 'data-testid="screen-rows"' not in page and 'data-testid="reveal"' not in page
    for path in (f"/studies/GZQO/patients/{A}", "/pilot/registry/GZQO", "/pilot/registry/GZQO/export.xlsx", "/sae",
                 "/site/opt-outs", "/studies/GZQO/excluded", "/site/patients"):  # fmt: skip
        assert admin.get(path).status_code == 403, path
    r = admin.post(f"/pilot/jobs/{jid}/reveal", data={"csrf": csrf, "pid": A, "reason": "contact"})
    assert r.status_code == 403
    r = admin.post(f"/studies/GZQO/patients/{A}/reveal", data={"csrf": csrf, "reason": "contact"})
    assert r.status_code == 403 and box["backend"].revealed == []
    # the set-up pages without a patient row stay the administrator's (D-131, D-179)
    assert admin.get("/site/help").status_code == 200 and admin.get("/site/staff").status_code == 200
    home = admin.get("/home?view=studies").text
    assert A[:8] not in home


def test_the_steward_keeps_the_opt_out_register(box: dict[str, Any]) -> None:  # noqa: F811
    stw = _user(box, "stw1", "steward")
    assert stw.get("/home", follow_redirects=False).headers["location"] == "/breakglass"
    page = stw.get("/site/opt-outs").text
    r = stw.post("/site/opt-outs", data={"csrf": _csrf(page), "pid": A}, follow_redirects=False)
    assert r.status_code == 303
    assert stw.get("/site/staff").status_code == 200
    assert stw.get(f"/studies/GZQO/patients/{A}").status_code == 403  # no study page from this card
    assert 'data-testid="more-breakglass"' in stw.get("/breakglass").text


# ---------------------------------------------------------------------------------------------- CR-029 (OD-5)
def test_a_grant_needs_a_listed_reason_a_note_and_one_target(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(991))
    admin, _ = login(box["app"])
    bad = (
        {"reason": "", "kind": "patient", "ruleset": "GZQO", "pid": A},
        {"reason": "curious", "kind": "patient", "ruleset": "GZQO", "pid": A},
        {"note": "short", "kind": "patient", "ruleset": "GZQO", "pid": A},
        {"kind": "patient", "ruleset": "GZQO", "pid": ""},
        {"kind": "everything"},
        {"kind": "job", "job_id": ""},
    )
    for form in bad:
        r = _open(admin, **form)
        assert r.status_code == 303 and "err=bg.err." in r.headers["location"], form
    assert _events(box, "console.breakglass_open") == []
    # a coordinator or a viewer opens no grant
    crc = _user(box, "crc1", "coordinator")
    assert _open(crc, kind="patient", ruleset="GZQO", pid=A).status_code == 403
    assert crc.get("/breakglass").status_code == 403


def test_a_patient_grant_opens_one_patient_for_60_minutes(box: dict[str, Any]) -> None:  # noqa: F811
    jid = _ulid(992)
    _done_screen(box["backend"], jid)
    stw = _user(box, "stw1", "steward")
    admin, _ = login(box["app"])
    r = _open(admin, kind="patient", ruleset="GZQO", pid=A)
    assert r.status_code == 303 and r.headers["location"] == "/breakglass?done=open"
    page = admin.get("/breakglass").text
    assert 'data-testid="bg-active"' in page and f'href="/studies/GZQO/patients/{A}"' in page
    # that patient, and nobody else
    p = admin.get(f"/studies/GZQO/patients/{A}")
    assert p.status_code == 200 and 'data-testid="reveal"' in p.text
    assert admin.get(f"/studies/GZQO/patients/{B}").status_code == 403
    assert 'data-testid="screen-rows"' not in admin.get(f"/pilot/jobs/{jid}").text  # not the job's list
    r = admin.post(f"/studies/GZQO/patients/{A}/reveal", data={"csrf": _csrf(p.text), "reason": "other",
                                                             "note": "support call, chart check"})  # fmt: skip
    assert r.status_code == 200 and "MRN-000123" in r.text
    assert box["backend"].signed == [("reveal", authz.BREAK_GLASS_ROLE, "*")]  # never "admin"
    opened = _events(box, "console.breakglass_open")
    assert len(opened) == 1 and opened[0]["detail"]["pid"] == A and opened[0]["detail"]["reason"] == "support"
    gid = opened[0]["detail"]["grant"]
    assert {e["detail"]["grant"] for e in _events(box, "console.breakglass_use")} == {gid}
    assert _events(box, "console.reveal_patient")[-1]["detail"]["breakglass"] == gid
    # the steward is told at once: on the list, and by mail
    assert any(n[0] == "BG" and "stw1@hospa.test" in n[1] and A not in n[3] for n in box["backend"].notices)
    row = stw.get("/breakglass").text
    assert f'data-grant="{gid}"' in row and 'data-testid="bg-waiting"' not in row  # open: not yet to review
    # 60 minutes later the grant has ended by itself
    _shift(box, 61)
    assert admin.get(f"/studies/GZQO/patients/{A}").status_code == 403
    r = admin.post(f"/studies/GZQO/patients/{A}/reveal", data={"csrf": _csrf(admin.get("/breakglass").text),
                                                             "reason": "contact"})  # fmt: skip
    assert r.status_code == 403 and len(box["backend"].revealed) == 1


def test_a_job_grant_opens_that_jobs_list_only(box: dict[str, Any]) -> None:  # noqa: F811
    jid, other = _ulid(994), _ulid(993)  # the newer id is the study's latest list
    _done_screen(box["backend"], other)
    _done_screen(box["backend"], jid)
    admin, _ = login(box["app"])
    assert _open(admin, kind="job", job_id=jid, reason="incident", note="incident 42: list check").status_code == 303
    page = admin.get(f"/pilot/jobs/{jid}").text
    assert 'data-testid="screen-rows"' in page and 'data-testid="reveal"' in page
    assert 'data-testid="screen-rows"' not in admin.get(f"/pilot/jobs/{other}").text
    r = admin.post(f"/pilot/jobs/{jid}/reveal", data={"csrf": _csrf(page), "pid": A, "reason": "contact"})
    assert r.status_code == 200 and "MRN-000123" in r.text
    assert box["backend"].signed == [("reveal", authz.BREAK_GLASS_ROLE, "*")]
    r = admin.post(f"/pilot/jobs/{other}/reveal", data={"csrf": _csrf(page), "pid": A, "reason": "contact"})
    assert r.status_code == 403
    # a new grant ends the one before: one patient or one job at a time
    assert _open(admin, kind="patient", ruleset="GZQO", pid=B).status_code == 303
    assert 'data-testid="screen-rows"' not in admin.get(f"/pilot/jobs/{jid}").text
    assert [e["detail"]["why"] for e in _events(box, "console.breakglass_end")] == ["replaced"]


def test_the_steward_reviews_each_grant_and_the_pi_sees_their_studys(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(995))
    stw = _user(box, "stw1", "steward")
    pi = _user(box, "drsato", "investigator")
    page = pi.get("/studies/GZQO/team").text
    r = pi.post("/studies/GZQO/team", data={"csrf": _csrf(page), "username": "drsato", "role": "pi",
                                            "start": "2026-01-01", "training_day": "2025-06-01"},
                follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    admin, _ = login(box["app"])
    _open(admin, kind="patient", ruleset="GZQO", pid=A)
    gid = _events(box, "console.breakglass_open")[0]["detail"]["grant"]
    assert any(n[0] == "BG" and "drsato@hospa.test" in n[1] for n in box["backend"].notices)  # the PI is told
    assert f'data-grant="{gid}"' in pi.get("/breakglass").text
    assert 'data-testid="bg-review"' not in pi.get("/breakglass").text  # the PI reads; the steward reviews
    # not while it is open; the administrator never reviews
    r = stw.post(f"/breakglass/{gid}/review", data={"csrf": _csrf(stw.get("/breakglass").text)},
                 follow_redirects=False)  # fmt: skip
    assert r.headers["location"] == "/breakglass?err=bg.err.open"
    assert admin.post(f"/breakglass/{gid}/end", data={"csrf": _csrf(admin.get("/breakglass").text)},
                      follow_redirects=False).status_code == 303  # fmt: skip
    r = admin.post(f"/breakglass/{gid}/review", data={"csrf": _csrf(admin.get("/breakglass").text)})
    assert r.status_code == 403
    page = stw.get("/breakglass").text
    assert 'data-testid="bg-waiting"' in page and 'data-testid="bg-review"' in page
    _shift(box, 8 * 24 * 60)  # unreviewed after 7 days: overdue on the steward's list
    page = stw.get("/breakglass").text
    assert 'data-testid="bg-overdue"' in page
    r = stw.post(f"/breakglass/{gid}/review", data={"csrf": _csrf(page), "note": "matches the ticket"},
                 follow_redirects=False)  # fmt: skip
    assert r.headers["location"] == "/breakglass?done=review"
    page = stw.get("/breakglass").text
    assert 'data-reviewed="yes"' in page and "matches the ticket" in page
    assert _events(box, "console.breakglass_review")[0]["detail"]["grant"] == gid


def test_the_orchestrator_gives_no_chart_number_to_the_admin_role(monkeypatch: pytest.MonkeyPatch) -> None:
    """D-280: the box's own check. ``admin`` is refused; the console's break-glass role is accepted."""
    from orchestrator import app as oapp
    from orchestrator.scenarios import screen

    from tests.unit.test_service_auth import TOKEN, _fake_box

    monkeypatch.setenv("TB_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    monkeypatch.setattr(oapp, "REVEALS", oapp.RevealLimit())
    events: list[dict[str, Any]] = []
    monkeypatch.setattr(oapp, "orch", lambda: _fake_box(events))
    monkeypatch.setattr(screen, "resolve_mrns", lambda _d, pids, _url=None: {p: "MRN-1" for p in pids})
    client = TestClient(oapp.app)
    assert "admin" not in oapp.ID_ROLES
    h = {sa.TOKEN_HEADER: TOKEN, **sa.actor_header("console:it1", role="admin", scope="*")}
    r = client.post("/jobs/J1/reveal", json={"pid": "PID-00000001"}, headers=h)
    assert r.status_code == 403 and events[-1]["detail"]["reason"] == "role"
    h = {sa.TOKEN_HEADER: TOKEN, **sa.actor_header("console:it1", role=authz.BREAK_GLASS_ROLE, scope="*")}
    assert client.post("/jobs/J1/reveal", json={"pid": "PID-00000001"}, headers=h).status_code == 200
