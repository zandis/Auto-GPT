"""SEC-SCOPE (D-769; found by the review of NEW-JRN-3): a scoped account is offered only its own studies to run.

The CASE page listed every approved trial, also to an account scoped to some studies (an SMO coordinator, D-104):
the names of other studies were shown to someone whose refusals are worded to tell nothing about them (D-540). The
request page already listed only the studies the account sees. The server refused the run all along (``submit``,
D-104); this test holds that too. Synthetic data only."""

from __future__ import annotations

from typing import Any

from console.backend import RulesetInfo

from tests.console.test_console_app import box  # noqa: F401 - the fixture is used by name
from tests.console.test_role_pages import _csrf, _user


def _two_trials(b: dict[str, Any]) -> None:
    bk = b["backend"]
    bk.rulesets = lambda: [RulesetInfo("GZQO", "1.0.0", "approved", "trial"),
                           RulesetInfo("OTHER1", "1.0.0", "approved", "trial")]  # fmt: skip


def test_the_case_page_lists_only_the_studies_a_scoped_coordinator_sees(box: dict[str, Any]) -> None:  # noqa: F811
    _two_trials(box)
    smo = _user(box, "smo1", "coordinator", affiliation="smo", studies="GZQO", expires="2099-12-31")
    page = smo.get("/pilot/case").text
    assert 'value="GZQO"' in page and "OTHER1" not in page
    request = smo.get("/pilot/request").text
    assert 'value="GZQO"' in request and "OTHER1" not in request


def test_a_scoped_coordinator_cannot_run_another_study(box: dict[str, Any]) -> None:  # noqa: F811
    _two_trials(box)
    smo = _user(box, "smo1", "coordinator", affiliation="smo", studies="GZQO", expires="2099-12-31")
    page = smo.get("/pilot/request").text
    r = smo.post("/pilot/request", data={"csrf": _csrf(page), "kind": "FEAS", "ruleset": "OTHER1"},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code == 403 and not [q for q in box["backend"].created if q.ruleset == "OTHER1"]
