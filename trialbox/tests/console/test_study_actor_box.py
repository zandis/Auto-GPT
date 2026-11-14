"""T-715d (D-554): the study router's changing routes refuse a call without a verified person.

On the real orchestrator in the production trust configuration. Before this card the group was in stage `report`:
any admitted token could save a study's settings, its screening scope or its REDCap link, or keep the box's REDCap
connections, under a name typed in the body (``"by": "dr_tanaka"``), and the audit trail showed that name. The
study's own routes are signed for ``study.setup``; the two connection routes are the box's, not one study's, so
their claim names no study and asks ``site.setup``; the REDCap read keeps ``request.prepare`` (the nightly timer
calls it too, as a service principal).

Synthetic data only.
"""

from __future__ import annotations

from typing import Any

from tests.actor3 import signed
from tests.console.test_orch_box import site  # noqa: F401  (the console of the box)
from tests.orch_box import STUDY, OrchBox

SETUP = "study.setup"
SITE = "redcap.connection"  # T-715e (D-701): the administrator's alone, as the console's page is
READ = "request.prepare"
SETTINGS: dict[str, Any] = {"study_type": "trial", "cohort_kind": "enrolled",
                            "not_suitable_reasons": ["stage", "other"], "screening_no_format": "GZ-"}  # fmt: skip
SCOPE: dict[str, Any] = {"mode": "hospital", "practitioners": []}
CONN: dict[str, Any] = {"url": "https://redcap.example.org/api", "token": "0123456789ABCDEF0123456789ABCDEF"}


def _settings(ob: OrchBox) -> dict[str, Any] | None:
    r = ob.client("console").get(f"/studies/{STUDY}/settings")
    return dict(r.json()) if r.status_code == 200 else None


def test_a_name_in_the_body_saves_no_settings_scope_or_link(orch_box: OrchBox) -> None:
    c = orch_box.client("console")
    calls = [
        ("PUT", f"/studies/{STUDY}/settings", {**SETTINGS, "by": "console:dr_tanaka"}),
        ("PUT", f"/studies/{STUDY}/screen-scope", {**SCOPE, "by": "console:dr_tanaka"}),
        ("PUT", f"/studies/{STUDY}/redcap-link", {"link": {"project": "1"}, "by": "console:dr_tanaka"}),
        ("POST", f"/studies/{STUDY}/redcap-link/test", {"screening": {}, "by": "console:dr_tanaka"}),
        ("PUT", "/redcap/connections/rc1", {**CONN, "by": "console:dr_tanaka"}),
        ("POST", "/redcap/connections/rc1/test", None),
    ]
    for method, path, body in calls:
        r = c.request(method, path, json=body)
        assert r.status_code == 403, (path, r.status_code, r.text[:300])
    assert _settings(orch_box) is None
    assert [e["detail"]["action"] for e in orch_box.events("actor.refused")] == [SETUP, SETUP, SETUP, SETUP,
                                                                                SITE, SITE]  # fmt: skip
    assert orch_box.events("study.settings") == [] and orch_box.events("redcap.connection") == []


def test_a_signed_call_is_recorded_under_the_verified_person(orch_box: OrchBox) -> None:
    c = orch_box.client("console")
    path = f"/studies/{STUDY}/settings"
    r = c.put(path, json=SETTINGS, headers=signed(SETUP, STUDY, "PUT", path, SETTINGS, sub="console:crc"))
    assert r.status_code == 200, r.text[:300]
    assert _settings(orch_box) is not None
    assert [e["actor"] for e in orch_box.events("study.settings")] == ["console:crc"]
    path = f"/studies/{STUDY}/screen-scope"
    r = c.put(path, json=SCOPE, headers=signed(SETUP, STUDY, "PUT", path, SCOPE, sub="console:crc"))
    assert r.status_code == 200, r.text[:300]
    assert [e["actor"] for e in orch_box.events("study.screen_scope")] == ["console:crc"]
    # the connection is the box's: the claim names no study, and asks the site's own row of the matrix
    path = "/redcap/connections/rc1"
    r = c.put(path, json=CONN, headers=signed(SITE, "", "PUT", path, CONN, sub="console:admin", role="admin"))
    assert r.status_code == 200, r.text[:300]
    assert [e["actor"] for e in orch_box.events("redcap.connection")] == ["console:admin"]
    # a `by` in the body is not a field of the request any more: it is refused, not ignored (the body is signed)
    typed = {**SETTINGS, "by": "console:dr_tanaka"}
    path = f"/studies/{STUDY}/settings"
    r = c.put(path, json=typed, headers=signed(SETUP, STUDY, "PUT", path, typed, sub="console:crc"))
    assert r.status_code == 422, r.text[:300]


def test_another_study_another_body_or_a_role_without_the_right_is_refused(orch_box: OrchBox) -> None:
    c = orch_box.client("console")
    path = f"/studies/{STUDY}/settings"
    cases = {
        "study": signed(SETUP, "OTHER1", "PUT", path, SETTINGS),
        "body": signed(SETUP, STUDY, "PUT", path, {**SETTINGS, "screening_no_next": 7}),
        "request": signed(SETUP, STUDY, "PUT", f"/studies/{STUDY}/screen-scope", SETTINGS),
        "right": signed(SETUP, STUDY, "PUT", path, SETTINGS, sub="console:viewer1", role="viewer"),
        "action": signed(SITE, STUDY, "PUT", path, SETTINGS),
    }
    for why, headers in cases.items():
        r = c.put(path, json=SETTINGS, headers=headers)
        assert r.status_code == 403 and why in r.text, (why, r.status_code, r.text[:200])
    assert _settings(orch_box) is None
    # the box's connection route refuses a claim that names a study, and a study route refuses one that names none
    path = "/redcap/connections/rc1"
    r = c.put(path, json=CONN, headers=signed(SITE, STUDY, "PUT", path, CONN))
    assert r.status_code == 403 and "study" in r.text, r.text[:200]
    path = f"/studies/{STUDY}/settings"
    r = c.put(path, json=SETTINGS, headers=signed(SETUP, "", "PUT", path, SETTINGS))
    assert r.status_code == 403 and "study" in r.text, r.text[:200]


def test_the_consoles_own_pages_still_save_the_study(site: Any, orch_box: OrchBox) -> None:  # noqa: F811
    """The console's call site signs: its set-up page saves the screening scope on the real route. (The settings,
    the link, its test, the read and the connection pages are held by test_step3 and test_step4b, whose client
    signs nothing for the console.)"""
    from tests.console.test_console_app import CRC_PW, login

    c, csrf = login(site["app"], "crc", CRC_PW)
    r = c.post(f"/studies/{STUDY}/setup/scope", data={"csrf": csrf, "mode": "hospital"})
    assert r.status_code in (200, 303), r.text[:300]
    assert [e["actor"] for e in orch_box.events("study.screen_scope")] == ["console:crc"]


def test_only_the_administrator_writes_or_tests_the_boxs_redcap_connection(orch_box: OrchBox) -> None:
    """T-715e (D-701, the owner's decision of 2026-11-13): the console's page for the box's REDCap connection and
    its token is the administrator's alone; the routes asked ``site.setup``, which a coordinator holds too, so the
    orchestrator was wider than the page. They ask a row of their own now."""
    from tb_common.authz import permit

    assert {r for r in ("admin", "coordinator", "investigator", "viewer", "cro", "steward", "privacy")
            if permit(r, SITE).allowed} == {"admin"}  # fmt: skip
    c = orch_box.client("console")
    for method, path, body in (
        ("PUT", "/redcap/connections/rc1", CONN),
        ("POST", "/redcap/connections/rc1/test", None),
    ):
        kw: dict[str, Any] = {} if body is None else {"json": body}
        # a coordinator, signed for this very request: the matrix refuses the role
        crc = signed(SITE, "", method, path, body, sub="console:crc", role="coordinator")
        r = c.request(method, path, headers=crc, **kw)
        assert r.status_code == 403 and "right" in r.text, (path, r.text[:200])
        # the row the routes asked before is not this route's action any more
        old = signed("site.setup", "", method, path, body, sub="console:crc", role="coordinator")
        r = c.request(method, path, headers=old, **kw)
        assert r.status_code == 403 and "action" in r.text, (path, r.text[:200])
    assert orch_box.events("redcap.connection") == []
    r = c.put("/redcap/connections/rc1", json=CONN,
              headers=signed(SITE, "", "PUT", "/redcap/connections/rc1", CONN, sub="console:admin", role="admin"))  # fmt: skip
    assert r.status_code == 200, r.text[:300]
