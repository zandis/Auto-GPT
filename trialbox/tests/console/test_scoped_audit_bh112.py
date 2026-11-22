"""BH1-12 (D-380): a study-scoped account sees no audit. The scope check (``console.app._scope_check``) refused the
cross-study audit list by its exact path, ``/audit``, while every page under it (the verify page, a patient's
report and its CSV, the provenance page, the patient search) and the ``/api/v1`` twins showed the same cross-study
lines. The check now refuses ``/audit`` and ``/api/v1/audit`` and everything under them for a scoped account; the same
account without a scope still reads them. Synthetic data only."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.console import test_console_app
from tests.console.test_audit_browser import _events
from tests.console.test_console_app import login
from tests.console.test_role_pages import PW

box = test_console_app.box  # the box fixture, used by name

MARK = "/bh112-other-study-marker"
PID = "aaaaaaaa"
OTHER = "ZZQX"  # a study of the test box the scoped accounts are not given
GETS = (
    "/audit",
    "/audit/patients",
    f"/audit/patients?pid={PID}",
    f"/audit/patients/{PID}",
    f"/audit/patients/{PID}/report.csv",
    "/audit/provenance",
)
POSTS = ("/audit/verify", "/audit/patients/by-chart")
API_POSTS = ("/api/v1/audit/verify", "/api/v1/audit/patients/by-chart")


def _account(b: dict[str, Any], name: str, role: str, scoped: bool) -> Any:
    b["users"].create(name, role, PW, f"{name}@hospa.test")
    if scoped:
        b["users"].set_scope(name, studies="GZQO", expires="2099-12-31")
    b["audit"].append("console.denied", ruleset="OTHER1", actor="console:someone", detail={"action": MARK})
    return login(b["app"], name, PW)


@pytest.mark.parametrize("role", ["steward", "privacy"])
def test_a_scoped_account_is_refused_every_audit_page_and_its_api_twin(box: dict[str, Any], role: str) -> None:
    c, csrf = _account(box, f"s{role[:3]}1", role, scoped=True)
    token, _ = box["users"].new_session(box["users"].get(f"s{role[:3]}1"), via="api")
    api = TestClient(box["app"], headers={"Authorization": f"Bearer {token}"})
    answers = {path: c.get(path) for path in GETS}
    answers |= {path: c.post(path, data={"csrf": csrf, "chart": "123"}) for path in POSTS}
    answers |= {path: api.post(path, json={"chart": "123"}) for path in API_POSTS}
    wrong = {path: r.status_code for path, r in answers.items() if r.status_code != 403 or MARK in r.text}
    assert wrong == {}, (role, wrong)  # every path that answers or shows the other study's line, at once
    seen = _events(box, "console.denied")
    assert any((e.get("detail") or {}).get("action") == "/audit/verify" for e in seen)  # the refusal is recorded


@pytest.mark.parametrize("role", ["steward", "privacy"])
def test_the_same_account_without_a_scope_still_reads_the_audit(box: dict[str, Any], role: str) -> None:
    c, csrf = _account(box, f"u{role[:3]}1", role, scoped=False)
    assert c.get("/audit").status_code == 200
    r = c.post("/audit/verify", data={"csrf": csrf})
    assert r.status_code == 200 and MARK in r.text, r.status_code


def test_a_scoped_steward_sees_only_its_own_studies_break_glass_grants(box: dict[str, Any]) -> None:
    """``/breakglass`` in steward mode listed every grant (its study, the patient id's prefix, the user, the note)."""
    from tests.console.test_d280_breakglass import _open

    admin, _ = login(box["app"])
    assert _open(admin, kind="patient", ruleset="GZQO", pid="a" * 32).status_code == 303
    assert (
        _open(admin, kind="patient", ruleset=OTHER, pid="b" * 32, note="support call about another study").status_code
        == 303
    )
    scoped, _csrf = _account(box, "sbg1", "steward", scoped=True)
    page = scoped.get("/breakglass")
    assert page.status_code == 200 and "aaaaaaaa" in page.text, page.status_code
    assert "bbbbbbbb" not in page.text and OTHER not in page.text and "another study" not in page.text
    whole, _csrf = _account(box, "ubg1", "steward", scoped=False)  # the same role without a scope: every grant
    page = whole.get("/breakglass").text
    assert "aaaaaaaa" in page and "bbbbbbbb" in page
