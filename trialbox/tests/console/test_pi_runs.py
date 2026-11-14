"""T-512 (D-349, owner answer Q-04, findings FIT-003 and FIT-U01): the PI starts FEAS, SCREEN and CASE on the PI's own
study and is refused elsewhere; a sub-investigator needs the ``run`` tick; the daily limits hold; the patient lists
say how old their data is."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from console.home import data_as_of
from orchestrator.core import Rejected
from tb_common import authz
from tb_contracts import Job, JobCreate

from tests.console.test_console_app import (  # noqa: F401 - the fixture is used by name
    PILOT_ENV,
    _done_feas,
    _done_screen,
    _ulid,
    box,
    name_pi,
)
from tests.console.test_role_pages import _csrf, _user
from tests.console.test_team_pages import A, _log_pi_and_sub
from tests.unit.test_orchestrator_unit import make  # noqa: F401 - the fixture is used by name


# ---------------------------------------------------------------------------------------------- the rule in authz
def test_the_q04_rule_is_one_table_in_authz() -> None:
    pi = dict(is_pi=True, tasks=frozenset())
    for cmd in ("FEAS", "SCREEN", "CASE", "APPROVE", "STATUS"):
        assert authz.can_request("investigator", cmd, **pi)  # type: ignore[arg-type]
    for cmd in ("COHORT", "NAV", "CONSENT", "RELEASE"):
        assert not authz.can_request("investigator", cmd, **pi)  # type: ignore[arg-type]
    # a sub-investigator: nothing without the tick, the "run" row with it
    assert not authz.can_request("investigator", "SCREEN", tasks=frozenset({"screen", "approach"}))
    assert authz.can_request("investigator", "SCREEN", tasks=frozenset({"run"}))
    assert authz.can_request("investigator", "APPROVE")  # unchanged: the console still asks may_approve on top
    # coordinators and admins keep the role table; viewer and CRO start nothing
    assert authz.can_request("coordinator", "SCREEN") and authz.can_request("admin", "FEAS")
    assert not authz.can_request("viewer", "FEAS") and not authz.can_request("cro", "CASE")
    # the orchestrator's job table is the ceiling of the same rule
    assert authz.ROLE_COMMANDS["investigator"] >= authz.INVESTIGATOR_RUNS["pi"] | authz.INVESTIGATOR_RUNS["run"]
    assert "run" in authz.STUDY_TASKS


def test_a_different_q04_answer_is_a_one_line_change(monkeypatch: pytest.MonkeyPatch) -> None:
    # T-102a (D-366): the table is the matrix's ``command.*`` rows; the PI's runs gone is one cell per command
    for cmd in authz.INVESTIGATOR_RUNS["pi"]:
        monkeypatch.setitem(authz.MATRIX[f"command.{cmd}"], "investigator", ("task:run",))
    assert not authz.can_request("investigator", "FEAS", is_pi=True)
    assert authz.can_request("investigator", "APPROVE", is_pi=True)


def test_the_orchestrator_lets_the_investigator_run_and_the_daily_limit_holds(make: Any) -> None:  # noqa: F811
    orch, _ = make({})
    for _ in range(20):
        orch.create(JobCreate(type="SCREEN", ruleset="GZQO", requested_by="pi@hospa.test"), role="investigator",
                    by="console:drsato")  # fmt: skip
    with pytest.raises(Rejected, match=r"rate limit reached \(20 SCREEN jobs per sender per day\)"):
        orch.create(JobCreate(type="SCREEN", ruleset="GZQO", requested_by="pi@hospa.test"), role="investigator")
    with pytest.raises(Rejected, match="the investigator role may not run COHORT"):
        orch.create(JobCreate(type="COHORT", ruleset="GZQO", requested_by="pi@hospa.test"), role="investigator")


# ---------------------------------------------------------------------------------------------- console
def test_pi_starts_feas_and_screen_on_own_study_and_is_refused_elsewhere(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(961))
    pi = _user(box, "drsato", "investigator", studies="GZQO")
    name_pi(box, "drsato")  # D-380 (ROLE-008): the steward names the PI
    page = pi.get("/pilot/request").text
    r = pi.post("/pilot/request", data={"csrf": _csrf(page), "kind": "FEAS", "ruleset": "GZQO"}, follow_redirects=False)
    assert r.status_code == 303, r.text[-400:]
    r = pi.post("/pilot/request", data={"csrf": _csrf(page), "kind": "SCREEN", "ruleset": "GZQO"},
                follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text[-400:]
    made = [(q.type, q.ruleset) for q in box["backend"].created]
    assert ("FEAS", "GZQO") in made and ("SCREEN", "GZQO") in made
    assert box["backend"].created_by[-1] == ("console:drsato", "investigator")  # the orchestrator checks the role
    # another study: not the PI's
    r = pi.post("/pilot/request", data={"csrf": _csrf(page), "kind": "FEAS", "ruleset": "RA-BIO"},
                follow_redirects=False)  # fmt: skip
    assert r.status_code == 403
    assert all(q.ruleset != "RA-BIO" for q in box["backend"].created)


def test_sub_investigator_needs_the_run_tick(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(961))
    pi = _user(box, "drsato", "investigator")
    sub = _user(box, "drkato", "investigator")
    other = _user(box, "drito", "investigator")
    _log_pi_and_sub(box, pi, ("screen", "refer"))
    page = sub.get("/pilot/request").text
    r = sub.post("/pilot/request", data={"csrf": _csrf(page), "kind": "SCREEN", "ruleset": "GZQO"},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code == 403
    op = other.get("/pilot/request").text  # an investigator not on the log that names a PI: no run
    r = other.post("/pilot/request", data={"csrf": _csrf(op), "kind": "FEAS", "ruleset": "GZQO"},
                   follow_redirects=False)  # fmt: skip
    assert r.status_code == 403
    # the PI ticks "run": the sub-investigator may start it now
    log = pi.get("/studies/GZQO/team").text
    assert 'data-testid="add-run"' in log
    eid = next(e.id for e in box["app"].state.helpers.team.entries("GZQO") if e.username == "drkato")
    r = pi.post(f"/studies/GZQO/team/{eid}", data={"csrf": _csrf(log), "tasks": ["screen", "refer", "run"]},
                follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text[-400:]
    r = sub.post("/pilot/request", data={"csrf": _csrf(page), "kind": "SCREEN", "ruleset": "GZQO"},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text[-400:]


def test_pi_refreshes_feasibility_and_a_viewer_does_not(box: dict[str, Any]) -> None:  # noqa: F811
    _done_feas(box["backend"])
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")  # D-380 (ROLE-008): the steward names the PI
    page = pi.get("/studies/GZQO/feasibility").text
    assert 'data-testid="refresh"' in page
    r = pi.post("/studies/GZQO/feasibility/refresh", data={"csrf": _csrf(page)}, follow_redirects=False)
    assert r.status_code == 303
    assert box["backend"].created[-1].type == "FEAS"
    viewer = _user(box, "vw2", "viewer")
    vp = viewer.get("/studies/GZQO/feasibility").text
    assert 'data-testid="refresh"' not in vp


# ---------------------------------------------------------------------------------------------- data as of
def test_data_as_of_turns_amber_after_two_days() -> None:
    job = Job.model_validate({"job_id": _ulid(1), "type": "SCREEN", "ruleset": "GZQO", "requested_by": "a@b.test",
                              "received_at": "2026-10-05T00:00:00+00:00", "updated_at": "2026-10-05T00:00:00+00:00",
                              "state": "done", "snapshot_date": "2026-10-04"})  # fmt: skip
    assert data_as_of(job, date(2026, 10, 6)) == {"day": "2026-10-04", "stale": False}
    assert data_as_of(job, date(2026, 10, 7))["stale"] is True


def test_four_patient_pages_show_data_as_of(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(961))
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")  # D-380 (ROLE-008): the steward names the PI
    pages = {
        "week": pi.get("/studies/GZQO/week?list=all").text,
        "candidates": pi.get("/studies/GZQO/candidates").text,
        "patient": pi.get(f"/studies/GZQO/patients/{A}").text,
        "candidate": pi.get(f"/studies/GZQO/candidates/{A}?purpose=eligibility").text,
    }
    for name, html in pages.items():
        assert 'data-testid="data-asof"' in html, name


# ---------------------------------------------------------------------------------------------- NEW-JRN-3 (D-767)
def test_the_pi_finds_the_run_controls_on_the_request_and_case_pages(box: dict[str, Any]) -> None:  # noqa: F811
    """JRN-003: the PI had the right (T-512) but no control: "New request" said "you are signed in as a viewer" and
    the CASE button was disabled. The forms now show for each study the account may run, and only those."""
    _done_screen(box["backend"], _ulid(962))
    pi = _user(box, "drsato", "investigator", studies="GZQO")
    name_pi(box, "drsato")
    page = pi.get("/pilot/request").text
    assert 'data-testid="viewer-card"' not in page
    assert 'data-testid="start-feas"' in page and 'data-testid="start-screen"' in page
    assert 'value="GZQO"' in page
    case = pi.get("/pilot/case").text
    assert 'data-testid="case-submit"' in case
    button = case[case.index('data-testid="case-submit"') - 80 : case.index('data-testid="case-submit"')]
    assert "disabled" not in button


def test_an_investigator_who_may_run_nothing_keeps_the_reading_card(box: dict[str, Any]) -> None:  # noqa: F811
    """No PI entry on the study's log: nothing to start, the page says what to read instead."""
    _done_screen(box["backend"], _ulid(963))
    sub = _user(box, "drkato", "investigator", studies="GZQO")
    page = sub.get("/pilot/request").text
    assert 'data-testid="viewer-card"' in page and 'data-testid="start-feas"' not in page
    case = sub.get("/pilot/case").text
    button = case[case.index('data-testid="case-submit"') - 80 : case.index('data-testid="case-submit"')]
    assert "disabled" in button


def test_the_free_text_request_stays_the_coordinators_and_the_coordinator_page_is_unchanged(
    box: dict[str, Any],  # noqa: F811
) -> None:
    """The review of D-767: the PI gets the forms, not the free-text card (it proposes any command); a coordinator's
    page keeps the free-text card and its forms."""
    _done_screen(box["backend"], _ulid(964))
    pi = _user(box, "drsato", "investigator", studies="GZQO")
    name_pi(box, "drsato")
    assert 'data-testid="propose"' not in pi.get("/pilot/request").text
    crc = _user(box, "crc9", "coordinator")
    page = crc.get("/pilot/request").text
    assert 'data-testid="propose"' in page and 'data-testid="start-feas"' in page
    case = crc.get("/pilot/case").text
    assert "disabled" not in case[case.index('data-testid="case-submit"') - 80 : case.index('data-testid="case-submit"')]
