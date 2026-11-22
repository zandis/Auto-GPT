"""BH1-12 (D-380): a study-scoped account sees no audit. The scope check (``console.app._scope_check``) refused the
cross-study audit list by its exact path, ``/audit``, while every page under it (the verify page, a patient's
report and its CSV, the provenance page, the patient search) and the ``/api/v1`` twins showed the same cross-study
lines. The check now refuses ``/audit`` and ``/api/v1/audit`` and everything under them for a scoped account; the same
account without a scope still reads them. Synthetic data only."""

from __future__ import annotations

from typing import Any

import pytest

from fastapi.testclient import TestClient

from tests.console.test_audit_browser import _events
from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_role_pages import PW

MARK = "/bh112-other-study-marker"
PID = "aaaaaaaa"
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


def _account(box: dict[str, Any], name: str, role: str, scoped: bool) -> Any:
    box["users"].create(name, role, PW, f"{name}@hospa.test")
    if scoped:
        box["users"].set_scope(name, studies="GZQO", expires="2099-12-31")
    box["audit"].append("console.denied", ruleset="OTHER1", actor="console:someone", detail={"action": MARK})
    return login(box["app"], name, PW)


@pytest.mark.parametrize("role", ["steward", "privacy"])
def test_a_scoped_account_is_refused_every_audit_page_and_its_api_twin(box: dict[str, Any], role: str) -> None:  # noqa: F811
    c, csrf = _account(box, f"s{role[:3]}1", role, scoped=True)
    for path in GETS:
        r = c.get(path)
        assert r.status_code == 403 and MARK not in r.text, (role, path, r.status_code)
    for path in POSTS:
        r = c.post(path, data={"csrf": csrf, "chart": "123"})
        assert r.status_code == 403 and MARK not in r.text, (role, path, r.status_code)
    token, _ = box["users"].new_session(box["users"].get(f"s{role[:3]}1"), via="api")
    api = TestClient(box["app"], headers={"Authorization": f"Bearer {token}"})
    for path in API_POSTS:
        r = api.post(path, json={"chart": "123"})
        assert r.status_code == 403 and MARK not in r.text, (role, path, r.status_code)
    seen = _events(box, "console.denied")
    assert any((e.get("detail") or {}).get("action") == "/audit/verify" for e in seen)  # the refusal is recorded


@pytest.mark.parametrize("role", ["steward", "privacy"])
def test_the_same_account_without_a_scope_still_reads_the_audit(box: dict[str, Any], role: str) -> None:  # noqa: F811
    c, csrf = _account(box, f"u{role[:3]}1", role, scoped=False)
    assert c.get("/audit").status_code == 200
    r = c.post("/audit/verify", data={"csrf": csrf})
    assert r.status_code == 200 and MARK in r.text, r.status_code


def test_a_path_that_only_starts_with_the_word_is_not_caught(box: dict[str, Any]) -> None:  # noqa: F811
    """The prefix is a path segment: ``/auditx`` is no audit page (it is simply not found), so the check stays exact."""
    c, _csrf = _account(box, "sste2", "steward", scoped=True)
    assert c.get("/auditx").status_code == 404
