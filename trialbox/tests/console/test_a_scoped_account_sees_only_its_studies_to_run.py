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


# ---------------------------------------------------------------------------------------------- the review's cases
def _other_job(b: dict[str, Any]) -> str:
    """A FEAS of OTHER1, asked by a hospital coordinator (no scope)."""
    _two_trials(b)
    crc = _user(b, "crc9", "coordinator")
    page = crc.get("/pilot/request").text
    r = crc.post("/pilot/request", data={"csrf": _csrf(page), "kind": "FEAS", "ruleset": "OTHER1"},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text[-300:]
    return str(r.headers["location"].rsplit("/", 1)[1])


def _propose(client: Any, text: str) -> Any:
    import re

    page = client.get("/pilot/request").text
    r = client.post("/pilot/propose", data={"csrf": _csrf(page), "text": text})
    m = re.search(r'/pilot/propose/([^/"]+)/confirm', r.text)
    assert m, r.text[-500:]
    return client.post(f"/pilot/propose/{m.group(1)}/confirm", data={"csrf": _csrf(r.text)}, follow_redirects=False)


def test_a_scoped_coordinator_cannot_ask_status_or_cancel_of_another_studys_job(box: dict[str, Any]) -> None:  # noqa: F811
    """The review of D-769 (F1): STATUS mails the named job's record; the job-id commands named no study, so the
    scope check never ran. Now the named job's study is checked."""
    jid = _other_job(box)
    before = len(box["backend"].created)
    smo = _user(box, "smo1", "coordinator", affiliation="smo", studies="GZQO", expires="2099-12-31")
    for cmd in ("STATUS", "CANCEL"):
        r = _propose(smo, f"{cmd} {jid}")
        assert r.status_code == 403, (cmd, r.status_code)
    assert len(box["backend"].created) == before
    crc = _user(box, "crc8", "coordinator")  # a hospital coordinator (no scope) may
    assert _propose(crc, f"STATUS {jid}").status_code == 303


def test_the_registry_home_of_an_unscoped_coordinator_is_unchanged(box: dict[str, Any]) -> None:  # noqa: F811
    """The review of D-769 (F2, F3): the registry's home keeps its own list (it was scoped already)."""
    _two_trials(box)
    crc = _user(box, "crc9", "coordinator")
    page = crc.get("/pilot/registry").text
    assert "GZQO" in page and "OTHER1" in page
