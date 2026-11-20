"""9k-7 (D-1388; review 09 §3.5, DS-7): every POST act of the console is confirm-first, act-at-once with Undo, or
plain, in exactly one list (``console.act_classes``); a confirm-first act writes nothing before its confirming POST;
the Undo of a mark keeps the owner's rules.

The two tests D-1388 names:

* ``test_every_post_form_and_route_is_in_exactly_one_list``: the app's POST routes (outside the machine APIs under
  ``/api/``) and every POST form of the templates (``tools.form_fields.scan``, the form guard's own reading), each
  form taken to the routes its ``action`` can reach; a route or a form in no list or in two fails, and so does a list
  entry that names no route.
* ``test_nothing_is_written_before_the_confirming_post``: every confirm-first act with a confirmation page
  (``SHEETS``) is walked by the test that already reaches its page, run here under a guard (``acts_9k7.run_guarded``)
  that compares the database and the folder (the audit trail is files there) before and after each POST that answers
  with the page; ``tests/console/test_acts_9k7_life.py`` walks the participant's final steps and the study's close the
  same way. ``test_opening_a_page_records_no_act`` walks the GET of every page of the console (where every one-step
  confirm-first act's form is), as five roles.
"""

from __future__ import annotations

import importlib
import json
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from console import act_classes as ac
from console.home import UNDO_MINUTES
from console.sitestore import SiteStore
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from tests.console.acts_9k7 import changed, run_guarded, snapshot
from tests.console.test_console_app import (  # noqa: F401 - the fixture is used by name
    ADMIN_PW,
    VIEWER_PW,
    _done_feas,
    _done_screen,
    _ulid,
    box,
    login,
    name_pi,
    sub_investigator,
)
from tests.console.test_data_pages import dcb  # noqa: F401 - the fixture is used by name
from tests.console.test_flags_page import _fresh_cache  # noqa: F401 - autouse there, so here too
from tests.console.test_ops_pages import ob  # noqa: F401 - the fixture is used by name
from tests.console.test_site_setup_pages import sb  # noqa: F401 - the fixture is used by name
from tests.console.test_step4 import b4  # noqa: F401 - the fixture is used by name
from tools.form_fields import ACTION_ATTR, scan

PW = "acts-9k7-password-0001"
A, B = "a" * 32, "b" * 32
# a form whose whole action is the act it confirms (the one confirm page): its class is that act's
CONFIRM_PAGES = {"confirm.html"}
# POST routes the test box does not register (a profile or a flag decides), each with the text that registers it
CONDITIONAL: dict[str, tuple[str, str]] = {
    "/studies/{rs}/committee": ("committee_pages.py", '@app.post("/studies/{rs}/committee")'),  # the Japan profile
    "/login/first-run/answers/keep": ("firstrun.py", 'app.post(f"{PATH}/answers/keep")'),  # the country flag
}


# ---------------------------------------------------------------------------------------------- the three lists
def _post_routes(app: Any) -> set[str]:
    return {r.path for r in app.routes if isinstance(r, APIRoute) and "POST" in (r.methods or ())}


def _segments_match(route: str, action: str) -> bool:
    rs, fs = route.strip("/").split("/"), action.strip("/").split("/")
    if len(rs) != len(fs):
        return False
    return all(r == f or (r.startswith("{") and r.endswith("}")) or "{{" in f for r, f in zip(rs, fs, strict=True))


def test_every_post_form_and_route_is_in_exactly_one_list(box: dict[str, Any]) -> None:  # noqa: F811
    """The owner's ruling of 2026-11-20 (D-1388): every POST form of the console is in exactly one of the three
    lists. Read from the app's routes and the templates' forms, so a new route or form is caught without a hand-kept
    list of either."""
    console = Path(__file__).resolve().parents[2] / "services" / "console"
    for route, (module, text) in CONDITIONAL.items():
        assert text in (console / module).read_text(encoding="utf-8"), f"{route} is no longer registered by {module}"
    every = _post_routes(box["app"]) | set(CONDITIONAL)
    pages = {r for r in every if not r.startswith("/api/")}
    problems: list[str] = []
    forms = 0
    reached: set[str] = set()
    for template, found in scan().items():
        for f in found:
            forms += 1
            m = ACTION_ATTR.search(f.attrs)
            action = ((m.group(1) or m.group(2) or "") if m else "").split("?", 1)[0].strip()
            if template in CONFIRM_PAGES and action.startswith("{{"):
                continue  # posts back to the act it confirms
            routes = {r for r in every if _segments_match(r, action)}
            if not routes:
                problems.append(f"{template}: a POST form to {action!r} reaches no POST route")
                continue
            reached |= routes
            classes = {c for r in routes for c in ac.class_of(r)}
            if len(classes) != 1:
                problems.append(f"{template}: the POST form to {action!r} ({sorted(routes)}) is in "
                                f"{len(classes)} lists: {sorted(classes)}")  # fmt: skip
    walked = pages | {r for r in reached if r.startswith("/api/")}
    for r in sorted(walked):
        lists = ac.class_of(r)
        if len(lists) != 1:
            problems.append(f"POST {r} is in {len(lists)} lists of console/act_classes.py: {lists or 'none'}")
    named = {r for acts in ac.LISTS.values() for r in acts}
    problems += [f"console/act_classes.py names {r}, which is no POST route of the console" for r in named - walked]
    problems += [f"UNSURE names {r}, which is not confirm-first" for r in set(ac.UNSURE) - set(ac.CONFIRM_FIRST)]
    problems += [f"SHEETS names {r}, which is not confirm-first" for r in set(ac.SHEETS) - set(ac.CONFIRM_FIRST)]
    assert not problems, "\n".join(problems)
    assert forms > 100 and len(walked) == len(named)  # the walk read the templates and the routes


# ---------------------------------------------------------------------------------------------- nothing before Yes
# each confirm-first act with a confirmation page, walked by the test that reaches its page (module, test, values
# the test is given that are not fixtures, the SHEETS routes it reaches)
WALKS: list[tuple[str, str, dict[str, Any], set[str]]] = [
    ("test_step4", "test_admin_tabs_cancel_and_retry", {}, {"/admin/jobs/{job_id}/cancel"}),
    ("test_step4", "test_admin_retry_of_a_scheduler_job", {"jtype": "INGEST"}, {"/admin/jobs/{job_id}/retry"}),
    ("test_ops_pages", "test_backup_asks_first_then_runs_is_audited_and_checked", {}, {"/admin/ops/{action}"}),
    ("test_ops_pages", "test_reset_asks_first_and_disable_has_an_undo", {}, {"/ops/users"}),
    ("test_ops_pages", "test_reject_asks_first_and_every_fact_decision_can_be_undone", {}, {"/site/facts/{fid}"}),
    ("test_ops_pages", "test_a_closing_outcome_asks_first_and_an_outcome_can_be_undone", {},
     {"/studies/{rs}/patients/{pid}/outcome"}),
    ("test_data_pages", "test_forms_sources_sync_conflict_resolve_detach", {},
     {"/studies/{rs}/conflicts/{cid}", "/studies/{rs}/sources/redcap/detach"}),
    ("test_flags_page", "test_a_change_needs_a_reason_and_a_confirmation_and_is_audited", {}, {"/ops/flags"}),
    ("test_identity", "test_admin_resets_an_authenticator_and_only_an_admin_may", {}, {"/ops/identity"}),
    ("test_criterion_labels", "test_approve_all_waits_for_a_label_in_the_page_language", {},
     {"/pilot/jobs/{job_id}/approve"}),
    ("test_poc_workflow", "test_a_referral_after_approach_pauses_the_approach", {},
     {"/studies/{rs}/candidates/{pid}/referral"}),
]  # fmt: skip
# walked in test_acts_9k7_life.py (their fixtures share a name with this module's)
LIFE_WALKS = {"/studies/{rs}/subjects/{record}/step", "/studies/{rs}/state"}


def test_every_confirmation_page_is_walked() -> None:
    walked = set().union(*(w[3] for w in WALKS)) | LIFE_WALKS
    assert walked == set(ac.SHEETS), (sorted(set(ac.SHEETS) - walked), sorted(walked - set(ac.SHEETS)))


@pytest.mark.parametrize(("module", "name", "given", "routes"), WALKS, ids=[w[1] for w in WALKS])
def test_nothing_is_written_before_the_confirming_post(
    module: str,
    name: str,
    given: dict[str, Any],
    routes: set[str],
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-1388: for every confirm-first act, nothing is written to the database or the audit trail before the
    confirming POST: each POST that answers with the confirmation page leaves both as they were."""
    fn = getattr(importlib.import_module(f"tests.console.{module}"), name)
    reached = run_guarded(fn, request, monkeypatch, given)
    assert routes <= set(reached), f"the confirmation page of {sorted(routes - set(reached))} was not reached"
    written = {r: w for r, w in reached.items() if w}
    assert not written, f"written before the confirming POST: {written}"


# what opening a page records by design: none is an act (D-1388 names each)
READ_RECORDS = re.compile(r"^(db:[a-z0-9_]+\.(weekly_seen)|file:audit/.*)$")
SKIP_PAGES = re.compile(r"^/(login|logout|lang|role|static|healthz|metrics|favicon|auth/oidc|enrol)(/|$|\.)")


def _audit_events(b: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for f in sorted((b["dir"] / "audit").glob("*.jsonl")):
        out += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x]
    return out


# audit events a page writes when it is opened: reads, downloads, searches and refusals, never an act
READ_EVENTS = re.compile(
    r"^(console\.(view|export|denied|refused|command|site_patients|audit_search|audit_report)|feedback\.export|"
    r"console\.[a-z_]+_refused)$"
)


def test_opening_a_page_records_no_act(box: dict[str, Any]) -> None:  # noqa: F811
    """D-1388: the page that holds a one-step confirm-first act's form (its confirmation page) records no act when it
    is opened: every GET page of the console, as the administrator, a coordinator, the named PI, the steward and the
    viewer, on the test box with a finished FEAS and SCREEN run; between the GET and the answer nothing in the
    database changes but the records of reads, and the audit trail gains only read and refusal events."""
    _done_feas(box["backend"])
    job = _done_screen(box["backend"], _ulid(961))
    for name, role in (("crc", "coordinator"), ("drsato", "investigator"), ("stw", "steward")):
        box["users"].create(name, role, PW, f"{name}@hospa.test")
    name_pi(box, "drsato")
    gets = sorted({r.path for r in box["app"].routes if isinstance(r, APIRoute) and "GET" in (r.methods or ())
                   and not r.path.startswith("/api/") and not SKIP_PAGES.match(r.path)})  # fmt: skip

    def fill(path: str) -> str:
        values = {"rs": "GZQO", "ruleset": "GZQO", "pid": B, "job_id": job.job_id, "fmt": "xlsx"}
        return re.sub(r"\{(\w+)(?::\w+)?\}", lambda m: values.get(m.group(1), "1"), path)

    problems: list[str] = []
    for user, pw in (("admin", ADMIN_PW), ("crc", PW), ("drsato", PW), ("stw", PW), ("viewer", VIEWER_PW)):
        c, _ = login(box["app"], user, pw)
        for path in gets:
            before, n = snapshot(box["dir"]), len(_audit_events(box))
            c.get(fill(path), follow_redirects=False)
            diff = [k for k in changed(before, snapshot(box["dir"])) if not READ_RECORDS.match(k)]
            acts = [e.get("event") for e in _audit_events(box)[n:] if not READ_EVENTS.match(str(e.get("event")))]
            if diff or acts:
                problems.append(f"{user} GET {path}: {diff} {acts}")
    assert not problems, "\n".join(problems)


# ---------------------------------------------------------------------------------------------- the confirm page
def test_the_confirmation_page_is_one_pattern(box: dict[str, Any]) -> None:  # noqa: F811
    """The one confirm pattern (D-1388): the page header (its heading is the page's title), the consequence, the line
    that nothing has been recorded yet, one primary act and the way back; in the person's language."""
    box["users"].create("nurse.lin", "coordinator", PW, "lin@hospa.test")
    c, csrf = login(box["app"])
    for lang, nothing in (("en", "Nothing has been recorded yet."), ("ja", "まだ何も記録していません。"),
                          ("zh-TW", "尚未記錄任何內容。")):  # fmt: skip
        c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/ops/users"})
        r = c.post("/ops/users", data={"csrf": csrf, "action": "disable", "username": "nurse.lin"})
        assert r.status_code == 200 and 'data-testid="confirm"' in r.text
        page = r.text.split("<main", 1)[-1]
        assert page.count("<h1") == 1 and '<header class="ph">' in page
        h1 = re.search(r"<h1>([^<]+)</h1>", page)
        title = re.search(r"<title>([^<]+) · TrialBox</title>", r.text)
        assert h1 and title and h1.group(1) == title.group(1)
        assert f'data-testid="confirm-nothing-yet">{nothing}<' in page
        form = page.split('<form method="post" action="/ops/users"', 1)[1].split("</form>", 1)[0]
        primaries = [b for b in re.findall(r"<button\b[^>]*>|<a\b[^>]*\bclass=\"[^\"]*\bbutton\b[^\"]*\"[^>]*>", form)
                     if not re.search(r'class="[^"]*\b(secondary|quiet|danger)\b', b)]  # fmt: skip
        assert len(primaries) == 1 and 'data-testid="confirm-yes"' in primaries[0]
    login(box["app"], "nurse.lin", PW)  # nothing was recorded: the account still signs in


# ---------------------------------------------------------------------------------------------- the Undo of a mark
def _csrf(page: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', page)
    assert m
    return m.group(1)


def _pi_marks(b: dict[str, Any]) -> list[dict[str, Any]]:
    return [e["detail"] for e in _audit_events(b) if e.get("event") == "console.pi_mark"]


def _offer(page: str) -> str | None:
    m = re.search(r'name="undo" value="(\d+)"><button type="submit" name="mark" value="undo"', page)
    return m.group(1) if m else None


@pytest.fixture
def mb(box: dict[str, Any]) -> dict[str, Any]:  # noqa: F811
    """The weekly list of GZQO with drsato as its named PI and drkato a sub-investigator who marks too."""
    _done_screen(box["backend"], _ulid(961))
    for name, role in (("drsato", "investigator"), ("drkato", "investigator")):
        box["users"].create(name, role, PW, f"{name}@hospa.test")
    name_pi(box, "drsato")
    sub_investigator(box, "drkato", tasks=("screen",))
    sato, _ = login(box["app"], "drsato", PW)
    kato, _ = login(box["app"], "drkato", PW)
    return {**box, "sato": sato, "kato": kato}


def _mark(c: TestClient, pid: str, mark: str, **extra: str) -> Any:
    page = c.get(f"/studies/GZQO/patients/{pid}").text
    return c.post(f"/studies/GZQO/patients/{pid}/mark",
                  data={"csrf": _csrf(page), "mark": mark, "back": "patient", **extra}, follow_redirects=True)  # fmt: skip


def _undo(c: TestClient, pid: str, row: str | None) -> Any:
    page = c.get(f"/studies/GZQO/patients/{pid}").text
    data = {"csrf": _csrf(page), "mark": "undo", "back": "patient", **({"undo": row} if row else {})}
    return c.post(f"/studies/GZQO/patients/{pid}/mark", data=data, follow_redirects=True)


def test_a_mark_is_undone_once_and_the_state_before_comes_back_with_both_events(mb: dict[str, Any]) -> None:
    """Undo is offered on the toast with its time, takes back exactly the row it names, puts back the mark before
    with its reason and note, and is done once: a second click (or the back button, or a second tab) answers the
    same page and writes nothing. The done event stays; the undone event names it."""
    sato = mb["sato"]
    _mark(sato, B, "not_suitable", reason="comorbidity", note="seen in clinic")
    r = _mark(sato, B, "need_info")
    row = _offer(r.text)
    assert row and 'data-testid="undo-until"' in r.text and "You can undo this until " in r.text
    r = _undo(sato, B, row)
    assert r.status_code == 200 and "Undone" in r.text
    marks = SiteStore().mark_history("GZQO", B)
    assert [(m.mark, m.reason, m.note) for m in marks][-1] == ("not_suitable", "comorbidity", "seen in clinic")
    assert marks[-1].undoes == int(row)
    events = _pi_marks(mb)
    assert [e["action"] for e in events] == ["not_suitable", "need_info", "not_suitable"]
    assert events[-1]["undo"] == "need_info" and events[-1]["undoes"] == int(row)
    for _ in range(2):  # a double click, then the back button's re-post
        again = _undo(sato, B, row)
        assert again.status_code == 200 and "Undone" in again.text
    assert len(SiteStore().mark_history("GZQO", B)) == len(marks) and len(_pi_marks(mb)) == len(events)
    assert _offer(sato.get(f"/studies/GZQO/patients/{B}?done=undo").text) is None  # an Undo is not undone


def test_only_the_person_who_marked_may_undo_and_only_while_nothing_changed(mb: dict[str, Any]) -> None:
    """Someone else's mark is not offered and is refused; a mark changed since by someone else is refused with who
    and when; an account without the right to mark is refused. Each refusal writes nothing."""
    sato, kato = mb["sato"], mb["kato"]
    row = _offer(_mark(sato, B, "need_info").text)
    assert row and _offer(kato.get(f"/studies/GZQO/patients/{B}?done=need_info").text) is None
    n = len(_pi_marks(mb))
    r = _undo(kato, B, row)
    assert r.status_code == 409 and "Only drsato, who made this mark, can undo it." in r.text
    _mark(kato, B, "not_now")
    r = _undo(sato, B, row)
    assert r.status_code == 409 and "has changed since: drkato recorded a newer one" in r.text
    assert len(_pi_marks(mb)) == n + 1  # kato's mark, nothing else
    viewer, _ = login(mb["app"], "viewer", VIEWER_PW)
    r = viewer.post(f"/studies/GZQO/patients/{B}/mark", data={"csrf": _csrf(viewer.get("/").text), "mark": "undo"})
    assert r.status_code == 403 and len(_pi_marks(mb)) == n + 1


def test_the_undo_ends_at_the_time_it_states(mb: dict[str, Any]) -> None:
    """After UNDO_MINUTES the toast offers no Undo, and a POST of the old form is refused with the time it ended."""
    sato = mb["sato"]
    r = _mark(sato, A, "need_info")
    row = _offer(r.text)
    until = re.search(r"You can undo this until (\d\d:\d\d)\.", r.text)
    assert row and until
    h = mb["app"].state.helpers
    real = h.clock
    h.clock = lambda: real() + timedelta(minutes=UNDO_MINUTES, seconds=5)
    assert _offer(sato.get(f"/studies/GZQO/patients/{A}?done=need_info").text) is None
    n = len(_pi_marks(mb))
    r = _undo(sato, A, row)
    assert r.status_code == 409 and f"The time to undo this mark ended at {until.group(1)}." in r.text
    assert len(_pi_marks(mb)) == n and SiteStore().mark_history("GZQO", A)[-1].mark == "need_info"
