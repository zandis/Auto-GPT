"""9f-3 (D-1383): the role x route matrix, walked as a sub-investigator who covers the PI.

One investigator account (``cov``), on the GZQO log as a sub-investigator with no task ticked, walks every route of
the router table as ``test_role_route_matrix`` does (the page with its CSRF token, ``/api/v1`` with its bearer token):

* with no cover, then with a cover of another study in effect, a cover of GZQO still to come, a cover ended before it
  began, and a cover ended early: the same answers every time (outside the dates and the study, nothing changes);
* with a cover of GZQO in effect: exactly the design table's column of the PI the log names (``lpi``), except the
  delegation log's own rows (add or change an entry, enter a cover), every export of the study's patients
  (``EXPORT_ROUTES``: a cover gives no export) and every route whose declared row is a PI right the cover does not
  carry (``teamstore.COVER_WITHHELD``: the log's monthly check, the study's state and reopening,
  the IRB records and the IRB-text answer, prefill on and off, ...), which a cover never gives: the log and the
  study's administration stay the PI's. The cover adds no right that the PI's column does not have, and the matrix
  is not changed.
* the allow-list itself: every PI row of the matrix is in ``COVER_RIGHTS`` or in ``COVER_WITHHELD``, never both, so a
  PI row added later fails here until it is listed on purpose (default deny holds meanwhile)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from console.teamstore import COVER_RIGHTS, COVER_WITHHELD
from fastapi.testclient import TestClient
from tb_common.authz import MATRIX, Standing, permit

from tests.console.test_console_app import _done_feas, _done_screen, _ulid, box, login  # noqa: F401 - fixture by name
from tests.console.test_role_route_matrix import TABLE, _clients, _orchestrator_routes, parse
from tests.console.test_role_route_matrix_acting import _walk
from tools.role_walk import load_declared

PW = "cover-matrix-password-01"
#: the delegation log's own rows: refused to a covering person (the log stays the PI's and the steward's)
LOG_ROWS = {
    ("POST", "/studies/{rs}/team"),
    ("POST", "/studies/{rs}/team/{eid}"),
    ("POST", "/studies/{rs}/cover"),
    ("POST", "/api/v1/studies/{rs}/cover"),
}


#: the PI rights a cover carries or withholds that are not PI rows of the matrix (console.team.Standing.pi_for: the
#: criteria's approval is a role row the console adds the PI to; a task's owner is no row)
NOT_MATRIX = {"criteria.approve", "team.task_owner"}


def _pi_rows() -> set[str]:
    """Every matrix row some role holds only as the PI (a ``pi`` or ``logged_pi`` condition)."""
    return {a for a, row in MATRIX.items() for cell in row.values()
            if isinstance(cell, tuple) and ({"pi", "logged_pi"} & set(cell))}  # fmt: skip


def test_every_pi_right_is_carried_or_withheld_by_a_cover_on_purpose() -> None:
    assert not COVER_RIGHTS & COVER_WITHHELD
    listed = (COVER_RIGHTS | COVER_WITHHELD) - NOT_MATRIX
    assert listed <= set(MATRIX), sorted(listed - set(MATRIX))
    missing = _pi_rows() - listed
    assert not missing, f"a PI row neither carried nor withheld by a cover (teamstore.COVER_*): {sorted(missing)}"
    assert listed == _pi_rows(), sorted(listed - _pi_rows())  # no stale name
    assert {"delegation.check", "study.state", "study.reopen", "irb.edit", "study.irb_text",
            "edc.switch_off"} <= COVER_WITHHELD  # fmt: skip
    pi = Standing(is_pi=True, tasks=frozenset(), log_names_pi=True)
    cover = Standing(is_pi=True, tasks=frozenset(), log_names_pi=True, pi_rights=COVER_RIGHTS)
    for a in _pi_rows():
        assert bool(permit("investigator", a, cover)) is (a in COVER_RIGHTS and bool(permit("investigator", a, pi))), a
    assert not permit("investigator", "a.row.added.later", cover)


def withheld_routes() -> set[tuple[str, str]]:
    """The routes whose declared row the PI holds and a cover does not (``COVER_WITHHELD``)."""
    pi = Standing(is_pi=True, tasks=frozenset({"screen", "approach", "refer", "enter_data", "run"}), log_names_pi=True)
    cover = Standing(is_pi=True, tasks=pi.tasks, log_names_pi=True, pi_rights=COVER_RIGHTS)
    out = set()
    for key, d in load_declared().items():
        if d.kind != "actions":
            continue

        def ok(st: Standing, actions: tuple[str, ...] = d.actions, mode: str = d.mode) -> bool:
            got = [bool(permit("investigator", a.lstrip("!"), st)) != a.startswith("!") for a in actions]
            return any(got) if mode == "any" else all(got)

        if ok(pi) and not ok(cover):
            out.add(key)
    return out


#: a task's owner and the cover's IRB task: the route declares delegation.keep (the PI's own entry) and
#: ``cover_pages.keeps_tasks`` adds a coordinator entry of the log, never a cover (``team.task_owner`` is withheld)
BY_TASK_OWNER = {
    ("POST", "/studies/{rs}/tasks/owner"),
    ("POST", "/api/v1/studies/{rs}/tasks/owner"),
    ("POST", "/studies/{rs}/cover/{cid}/irb"),
    ("POST", "/api/v1/studies/{rs}/cover/{cid}/irb"),
}
#: the files of a study's patients that leave TrialBox: never by a cover (the owner's ruling, 2026-11-20), though
#: their declared rows (``task.screen``, ``task.enter_data``, ``edc.export``, ``edc.copy``) are clinical rows the PI's
#: column holds (``Helpers.export_ok``, ``teamstore.COVER_NO_EXPORT``)
EXPORT_ROUTES = {
    ("GET", "/studies/{rs}/export.{fmt}"),
    ("GET", "/api/v1/studies/{rs}/export/{fmt}"),
    ("GET", "/studies/{rs}/screening-log.xlsx"),
    ("GET", "/pilot/registry/{ruleset}/export.xlsx"),
    ("GET", "/studies/{rs}/edc/export.odm.xml"),
    ("GET", "/api/v1/studies/{rs}/edc/export/odm"),
    ("GET", "/studies/{rs}/edc/copy.csv"),
    ("GET", "/api/v1/studies/{rs}/edc/copy"),
    ("GET", "/studies/{rs}/edc/copy/{record}"),
    ("GET", "/studies/{rs}/enrolment.{fmt}"),
    ("GET", "/api/v1/studies/{rs}/enrolment/{fmt}"),
}
END_ROWS = {("POST", "/studies/{rs}/cover/{cid}/end"), ("POST", "/api/v1/studies/{rs}/cover/{cid}/end")}


@pytest.fixture
def walked_box(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:  # noqa: F811
    monkeypatch.setenv("TB_ENV", "TEST")
    _orchestrator_routes(box)
    _done_feas(box["backend"])
    _done_screen(box["backend"], _ulid(990))
    return box


def test_a_cover_opens_the_pis_column_inside_its_dates_and_nothing_else(walked_box: dict[str, Any]) -> None:
    b = walked_box
    h = b["app"].state.helpers
    design = parse(TABLE.read_text(encoding="utf-8"))
    _clients(b)  # the columns' accounts; the GZQO log names ``lpi`` as its PI
    b["users"].create("cov", "investigator", PW, "cov@hospa.test")
    team = h.team
    team.add_entry("GZQO", username="cov", name="Dr C", role="sub_pi", tasks=(), start="2026-01-01", end=None,
                   training_day="2026-01-01", training_ref=None, by="lpi", at="2026-01-01T00:00:00+00:00")  # fmt: skip
    page, csrf = login(b["app"], "cov", PW)
    token, _ = b["users"].new_session(b["users"].get("cov"), via="api")
    api = TestClient(b["app"], headers={"Authorization": f"Bearer {token}"})
    job_id = _ulid(990)
    day: date = h.today()

    def iso(n: int) -> str:
        return (day + timedelta(days=n)).isoformat()

    at = "2026-01-01T00:00:00+00:00"

    base = _walk(b, page, csrf, api, job_id)
    assert len(base) > 150  # the walk reached the router table
    # another study's cover in effect (cover 1): nothing changes in GZQO
    for who, role in (("lpi", "pi"), ("cov", "sub_pi")):
        team.add_entry("ZZQO", username=who, name=who, role=role, tasks=(), start="2026-01-01", end=None,
                       training_day="2026-01-01", training_ref=None, by="stw", at=at)  # fmt: skip
    team.add_cover("ZZQO", username="cov", start=iso(0), end=iso(6), today=day, by="lpi", at=at)
    walks = {"another study": _walk(b, page, csrf, api, job_id)}
    coming = team.add_cover("GZQO", username="cov", start=iso(2), end=iso(4), today=day, by="lpi", at=at)
    walks["to come"] = _walk(b, page, csrf, api, job_id)
    team.end_cover("GZQO", coming.id, today=day, by="lpi", at=at)
    walks["ended before it began"] = _walk(b, page, csrf, api, job_id)
    live = team.add_cover("GZQO", username="cov", start=iso(0), end=iso(6), today=day, by="lpi", at=at)
    inside = _walk(b, page, csrf, api, job_id)
    team.end_cover("GZQO", live.id, today=day, by="cov", at=at)
    walks["ended early"] = _walk(b, page, csrf, api, job_id)

    for name, walked in walks.items():
        # an early end asks first whether the account is named in a cover of the study, then finds the cover by its
        # id: the walk's id 1 is another study's cover, so a person named in a GZQO cover meets 404 where others 403
        changed = [f"{m} {p}: {base[(m, p)]} -> {c}" for (m, p), c in sorted(walked.items())
                   if base.get((m, p)) != c and not ((m, p) in END_ROWS and (base[(m, p)], c) == ("-", "n"))]  # fmt: skip
        assert not changed, f"{name}: a cover outside its dates or study changed an answer:\n" + "\n".join(changed)
    # a task's owner and the cover's IRB task (declared delegation.keep) and every export: never by a cover
    withheld = withheld_routes() | EXPORT_ROUTES
    assert withheld_routes() >= BY_TASK_OWNER, sorted(BY_TASK_OWNER - withheld_routes())
    assert ("POST", "/studies/{rs}/team/check") in withheld and ("POST", "/studies/{rs}/state") in withheld, withheld
    # a route the PI meets as "n" (allowed, then nothing of that id) is refused to the cover before any look-up
    # when the cover never holds its right (an export, a task's owner, the cover's IRB task)
    first = EXPORT_ROUTES | BY_TASK_OWNER
    want = {k: ("-" if k in LOG_ROWS or (k in withheld and design[k]["lpi"] in ("Y", "U"))
                or (k in first and design[k]["lpi"] == "n") else design[k]["lpi"])
            for k in inside if k in design}  # fmt: skip
    assert set(want) == set(inside), "a route of the walk is not in the design table: regenerate it"
    diff = [f"{m} {p}: the PI's column {want[(m, p)]}, under the cover {c}"
            for (m, p), c in sorted(inside.items()) if want[(m, p)] != c]  # fmt: skip
    assert not diff, "under a cover the PI's column, less the log's own rows:\n" + "\n".join(diff)
    assert all(base[k] in ("-", "n") for k in LOG_ROWS), "without a cover the log rows are refused too"
    opened = sorted(k for k in inside if base[k] != "Y" and inside[k] == "Y")
    assert ("POST", "/studies/{rs}/team/check") not in opened and len(opened) >= 10, opened  # the walk saw the cover
    assert all(inside[k] != "Y" for k in withheld if k in inside), "a cover carried a withheld PI right"
