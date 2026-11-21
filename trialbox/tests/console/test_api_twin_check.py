"""T-657 (D-444): the API twin check, as a walk over the console's route table (FIT-019, ROLE-019, ROLE-020).

1. Every state-changing ``/api/v1`` route depends first on the session guard of ``console.api_first`` (so the
   session is checked before the body), and every one that takes a body declares the permit check it runs before
   the body (``@before_body``). An anonymous call answers 401, with an empty body and with a body that is not JSON.
2. Every state-changing page route has an ``/api/v1`` twin (the same path under ``/api/v1``, any changing method, or
   an API route that names it with ``@page_twin``), or is on one of the two lists below with its reason.
3. A study-scoped account naming a study outside its scope on ``/api/v1/site/*`` gets 404 (ROLE-020).

New routes are caught without a hand-kept list of routes: the walk reads the app."""

from __future__ import annotations

import re
from typing import Any

from console import api_first
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from tests.console.test_console_app import box  # noqa: F401 - the fixture is used by name
from tests.console.test_site_setup_pages import PW as SB_PW
from tests.console.test_site_setup_pages import sb  # noqa: F401 - the fixture is used by name

CHANGING = ("POST", "PUT", "PATCH", "DELETE")
JSON = {"content-type": "application/json"}
# page routes outside the twin rule: the browser's own session, not an action on the site's data
NOT_ACTIONS = re.compile(r"^/(login|logout|lang|static)(/|$)")

# Page-only by design, one reason each. Keep this short: a new entry needs a reason a reviewer accepts.
EXEMPT: dict[str, str] = {
    "/account/password": "the account's own password, changed in the browser; D-279: the API refuses an account "
    "whose password someone else set and sends it to this page",
    "/enrol": "the holder's first sign-in with an enrolment code (D-719): a browser sign-in like /login, which has "
    "no page twin either; the API signs in only accounts that already chose their password",
    "/ops/accounts/requests": "a second person confirms an account request in the browser, where the code or password "
    "is shown once to them (D-719); the API holds no account's factors",
    "/demo/ack": "demo mode's acknowledgement of the page banner (D-328); the API shows no banner",
    "/feedback": "the feedback control about the page on screen (D-331); its comment names that page",
    "/role": "the session's acting role on a test box (D-877), switched in the browser's top bar like /lang; an API "
    "token starts in the account's own role",
    "/account/prefs": "the look of the person's own pages and the language of their next page sessions (10F-1, "
    "D-1387), like /lang: the API draws no page and an API token keeps its own language",
}

# FIT-019 as found on 2026-11-11: page actions that have no /api/v1 twin yet. Follow-up cards close it; the list
# may only shrink (an entry that gains a twin or disappears fails below, and its length has a ceiling).
NO_TWIN_YET: tuple[str, ...] = (
    # operations (administrator)
    "/admin/jobs/{job_id}/cancel", "/admin/jobs/{job_id}/retry", "/admin/models/canary", "/admin/ops/{action}",
    "/admin/redcap", "/admin/redcap/{ref}/test", "/ops/flags", "/ops/identity", "/ops/ingest", "/ops/notices",
    "/ops/users", "/settings/notices",
    # break-glass (D-430) and the steward's pages
    "/breakglass", "/breakglass/{gid}/end", "/breakglass/{gid}/review", "/data/conflicts/{cid}/resolve",
    "/data/instruments/{iid}",
    # the pilot workspace: requests, approvals, the registry, the job page's reveal (T-103: one reveal path)
    "/pilot/cascade", "/pilot/case", "/pilot/consent", "/pilot/jobs/{job_id}/approval/label",
    "/pilot/jobs/{job_id}/approval/tick", "/pilot/jobs/{job_id}/approve", "/pilot/jobs/{job_id}/release",
    "/pilot/jobs/{job_id}/reveal", "/pilot/mailbox", "/pilot/propose", "/pilot/propose/{pid}/confirm",
    "/pilot/protocol", "/pilot/registry/{ruleset}", "/pilot/registry/{ruleset}/promote", "/pilot/request",
    # site set-up (FIT-019: staff directory, sheets)
    "/site/people/resolve", "/site/practice", "/site/remote", "/site/sheets", "/site/staff",
    # a study's set-up and its team (FIT-019: delegation log and its monthly check)
    "/studies/{rs}/setup", "/studies/{rs}/setup/contact", "/studies/{rs}/setup/log", "/studies/{rs}/setup/redcap",
    "/studies/{rs}/setup/redcap/test", "/studies/{rs}/setup/sae", "/studies/{rs}/setup/scope",
    "/studies/{rs}/setup/study", "/studies/{rs}/identity", "/studies/{rs}/irb-text", "/studies/{rs}/profile",
    "/studies/{rs}/redcap-read", "/studies/{rs}/state", "/studies/{rs}/feasibility/refresh", "/studies/{rs}/team",
    "/studies/{rs}/team/check", "/studies/{rs}/team/{eid}",
    # a study's work (FIT-019: the not-matched review, the SAE register, schedule undo)
    "/studies/{rs}/deviations",
    "/studies/{rs}/sae/sync", "/studies/{rs}/sae/{record}/{event}/ack", "/studies/{rs}/sae/{record}/{event}/{what}",
    "/studies/{rs}/sources/redcap/undo", "/studies/{rs}/subjects/{record}/undo",
)  # fmt: skip
# page actions that answer the walk's empty form before their role check, so their matrix row says nothing about
# the role (the matrix test's ROUTE_ACTIONS note): left out of the page-and-twin comparison
PAGE_BODY_FIRST: dict[str, str] = {
    "/studies/{rs}/candidates/{pid}/reveal": "an empty reveal form is refused 400 before the one reveal path's check",
}
NO_TWIN_CEILING = 60  # lower it with every twin added; never raise it


def _api_routes(app: Any) -> list[APIRoute]:
    return [r for r in app.routes if isinstance(r, APIRoute)]


def _changing(r: APIRoute) -> list[str]:
    return sorted(m for m in r.methods or () if m in CHANGING)


def _guarded(app: Any) -> list[tuple[str, APIRoute]]:
    return [(m, r) for r in _api_routes(app) for m in _changing(r) if api_first.guarded(r.path, {m})]


def _page_actions(app: Any) -> list[tuple[str, str]]:
    return sorted({(m, r.path) for r in _api_routes(app) for m in _changing(r)
                   if not r.path.startswith("/api/") and not NOT_ACTIONS.match(r.path)})  # fmt: skip


def _twins(app: Any) -> set[str]:
    """Page paths that have an /api/v1 twin: the same path under /api/v1, or named with ``@page_twin``."""
    out: set[str] = set()
    for r in _api_routes(app):
        if r.path.startswith(api_first.API) and _changing(r):
            out.add(r.path.removeprefix("/api/v1"))
            out.update(getattr(r.endpoint, api_first.TWINS, ()))
    return out


def test_every_api_change_checks_the_session_and_permit_before_the_body(box: dict[str, Any]) -> None:  # noqa: F811
    app = box["app"]
    guarded = _guarded(app)
    assert len(guarded) > 20, "the walk reached the router table"
    no_guard, no_check = [], []
    for m, r in guarded:
        if not r.dependant.dependencies or not api_first.is_guard(r.dependant.dependencies[0].call):
            no_guard.append(f"{m} {r.path}")
        if r.body_field is not None and getattr(r.endpoint, api_first.PRE_BODY, None) is None:
            no_check.append(f"{m} {r.path}")
    assert not no_guard, "routes without the session guard first:\n" + "\n".join(no_guard)
    assert not no_check, "routes with a body and no @before_body permit check:\n" + "\n".join(no_check)
    paths = {(m, r.path) for r in _api_routes(app) for m in r.methods or ()}
    assert set(api_first.SESSION_OPEN) <= paths, "a SESSION_OPEN line names a route that is gone"


def test_anonymous_gets_401_before_the_body_is_read(box: dict[str, Any]) -> None:  # noqa: F811
    anon = TestClient(box["app"])
    wrong = []
    for m, r in _guarded(box["app"]):
        url = re.sub(r"\{(\w+)(?::\w+)?\}", lambda g: "GZQO" if g.group(1) in ("rs", "ruleset") else "1", r.path)
        for kind, got in (("empty", anon.request(m, url, json={}).status_code),
                          ("not json", anon.request(m, url, content=b"{x", headers=JSON).status_code)):  # fmt: skip
            if got != 401:
                wrong.append(f"{m} {r.path} {kind}: {got}")
    assert not wrong, "anonymous calls not answered 401:\n" + "\n".join(wrong)


def test_every_page_action_has_an_api_twin_or_a_reason(box: dict[str, Any]) -> None:  # noqa: F811
    app = box["app"]
    twins = _twins(app)
    pages = {p for _, p in _page_actions(app)}
    missing = sorted(p for p in pages if p not in twins and p not in EXEMPT and p not in NO_TWIN_YET)
    assert not missing, "page actions with no /api/v1 twin and no line in EXEMPT or NO_TWIN_YET:\n" + "\n".join(missing)
    stale = sorted(p for p in (*EXEMPT, *NO_TWIN_YET) if p not in pages)
    assert not stale, "lines naming a page action that is gone:\n" + "\n".join(stale)
    closed = sorted(p for p in NO_TWIN_YET if p in twins)
    assert not closed, "these now have a twin: take them off NO_TWIN_YET:\n" + "\n".join(closed)
    both = sorted(set(EXEMPT) & set(NO_TWIN_YET))
    assert not both, both
    assert all(len(why) > 20 for why in EXEMPT.values()), "every exemption gives its reason"
    assert len(NO_TWIN_YET) <= NO_TWIN_CEILING
    named = {t for r in _api_routes(app) for t in getattr(r.endpoint, api_first.TWINS, ())}
    assert named <= pages, f"@page_twin names a page action that is gone: {sorted(named - pages)}"


def test_the_permit_comes_before_the_body(box: dict[str, Any]) -> None:  # noqa: F811
    """ROLE-019: a role the handler refuses is refused with an empty body too (it used to get 422), and a role the
    handler lets in still gets the body's 422."""
    users = box["users"]
    viewer, _ = users.new_session(users.get("viewer"), via="api")
    admin, _ = users.new_session(users.get("admin"), via="api")
    as_viewer = TestClient(box["app"], headers={"Authorization": f"Bearer {viewer}"})
    as_admin = TestClient(box["app"], headers={"Authorization": f"Bearer {admin}"})
    for path in ("/api/v1/studies/GZQO/edc/switch", "/api/v1/studies/GZQO/patients/" + "a" * 32 + "/mark",
                 "/api/v1/site/codes"):  # fmt: skip
        assert as_viewer.post(path, json={}).status_code in (403, 404), path
        assert as_viewer.post(path, content=b"{x", headers=JSON).status_code in (403, 404), path
    assert as_admin.post("/api/v1/site/codes", json={}).status_code == 422  # site.setup: the body decides now


def test_role020_a_study_outside_the_scope_is_not_found(sb: dict[str, Any]) -> None:  # noqa: F811
    sb["users"].create("smo", "coordinator", SB_PW, "smo@hospa.test")
    sb["users"].set_scope("smo", "smo", "GZQO", None)
    tok, _ = sb["users"].new_session(sb["users"].get("smo"), via="api")
    api = TestClient(sb["app"], headers={"Authorization": f"Bearer {tok}"})
    assert api.get("/api/v1/site/readiness?study=GZQO").status_code == 200
    r = api.get("/api/v1/site/readiness?study=RA-BIO")
    assert r.status_code == 404, r.text  # was: GZQO's readiness, silently
    assert api.get("/api/v1/site/readiness").status_code == 200  # no study named: its own, as before


def test_a_page_and_its_api_twin_refuse_the_same_roles(box: dict[str, Any]) -> None:  # noqa: F811
    """D-146 / D-425 on the generated matrix: no column is refused (403) by a page action and let in by its /api/v1
    twin, or the other way round (a page's 503 ``U`` and the API's ``Y`` both mean the guard let the role in; ``n``,
    the walk's made-up row not found, says nothing about the role)."""
    from tests.console.test_role_route_matrix import TABLE, parse

    have = parse(TABLE.read_text(encoding="utf-8"))
    app = box["app"]
    pairs = []
    for r in _api_routes(app):
        if not (r.path.startswith(api_first.API) and _changing(r)):
            continue
        for page in (r.path.removeprefix("/api/v1"), *getattr(r.endpoint, api_first.TWINS, ())):
            for pm in ("POST", "PUT", "DELETE"):
                for am in _changing(r):
                    if (pm, page) in have and (am, r.path) in have:
                        pairs.append(((pm, page), (am, r.path)))
    assert len(pairs) > 15, pairs
    let_in = {"Y", "U"}

    def clash(x: str, y: str) -> bool:  # one side refused the role (403), the other let it in; ``n`` is no row
        return (x == "-" and y in let_in) or (y == "-" and x in let_in)

    differ = [f"{p} {have[p]} / {a} {have[a]}" for p, a in pairs if p[1] not in PAGE_BODY_FIRST
              and any(clash(have[p][k], have[a][k]) for k in have[p])]  # fmt: skip
    assert not differ, "page and API twin disagree:\n" + "\n".join(differ)
