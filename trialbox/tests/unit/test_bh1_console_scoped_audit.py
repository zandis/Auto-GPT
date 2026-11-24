"""Bug hunt BH1 (console access): a study-scoped account is refused the cross-study audit list at ``GET /audit``
(``console.app._scope_check``, D-104), but ``POST /audit/verify`` renders the same newest-first list of every study.
Synthetic data only."""

from __future__ import annotations

from typing import Any

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_role_pages import PW

MARK = "/bh1-other-study-marker"


def test_a_scoped_steward_gets_no_cross_study_audit_list_from_verify(box: dict[str, Any]) -> None:  # noqa: F811
    """Entry point: ``POST /audit/verify`` (``console.audit_page.audit_verify``)."""
    box["users"].create("stw1", "steward", PW, "stw1@hospa.test")
    box["users"].set_scope("stw1", studies="GZQO", expires="2099-12-31")
    box["audit"].append("console.denied", ruleset="OTHER1", actor="console:someone", detail={"action": MARK})
    c, csrf = login(box["app"], "stw1", PW)
    assert c.get("/audit").status_code == 403  # the list is refused to a scoped account
    r = c.post("/audit/verify", data={"csrf": csrf})
    assert r.status_code == 403 and MARK not in r.text, r.status_code
