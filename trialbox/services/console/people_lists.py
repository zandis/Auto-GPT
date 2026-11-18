"""J-5 (D-1223; the journey review's R16 and D-2): two lists of people, Candidates and Participants, in place of seven.

* **The flag** ``layout.people_lists`` (``tb_common.flags``, audited, off by default). Off, every page renders as
  before and the new addresses are no page (404). On:

  - **Candidates** is ``/studies/{rs}/people/candidates`` and **Participants** ``/studies/{rs}/people/participants``,
    each with its views (:data:`VIEWS`). The **default view** of each divides the study's people at consent by J-2's
    one state (:func:`side`): each person is in exactly one, nobody opted out or erased in either. It is built on an
    old page's route, guard and reads (the study registry page, the participants page), which only leaves rows out.
    The other views are **working views**: the old page as it was, which can show people from both sides of consent.
  - **An old address redirects** (a GET, 303) to its working view (the page as it was) with its query kept, for a
    reader its route lets in. Any
    other request (no session, an ended one, a role the route refuses) reaches the old route and gets its answer and
    its audit event there: the gate peeks at the session (no activity, no sign-in, no audit) and asks the strip's
    questions. A form posts to the address it posted to before.
  - **One strip** on a 200 above each view (``templates/_people_tabs.html``) names the two lists and the views of the
    list shown, each only where the role may open it (the same questions the routes ask, from the delegation log,
    without an audit event and without a patient read), says what the view holds, and links the weekly page across
    studies from Candidates.
  - **The menu** shows Candidates and Participants where it showed "This week's patients" and "Candidate registry"
    (``/people/candidates`` and ``/people/participants``, plain routes, open the study's list or a picker).

* **What is not here.** The person's state is J-2's (``console.person_state``); no list reads it another way. The
  site set-up's patient check (``/site/patients``) and the registry index (``/pilot/registry``, all studies' counts)
  keep their addresses. The EDC's state is shown as before (lane E).
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send
from tb_common.flags import Flags

from console import i18n_lists
from console import person_state as ps
from console.i18n import CATALOGUES

FLAG = "layout.people_lists"
LISTS = ("candidates", "participants")
#: as ``console.phone.FLAG_SECONDS``: how old the value a page gets may be before one background read refreshes it
FLAG_SECONDS = 5.0
_RS = r"[A-Za-z0-9][A-Za-z0-9_-]{0,15}"
#: not pages: the flag is not read for them (as ``console.phone.NOT_PAGES``)
NOT_PAGES = ("/static/", "/api/", "/healthz", "/metrics", "/manifest.webmanifest", "/favicon.ico")

for _lang, _cat in (("en", i18n_lists.EN), ("ja", i18n_lists.JA), ("zh-TW", i18n_lists.ZH)):
    CATALOGUES[_lang].update(_cat)


@dataclass(frozen=True)
class View:
    """One view of one of the two lists: the old list page that serves it."""

    list: str  # candidates or participants
    name: str  # "" for the list's first view
    old: str  # the old address, with {rs}
    key: str  # its tab's words: people.view.<key>
    is_old_page: bool = True  # the old page as it was: its old address goes here (a default is not)

    def path(self, rs: str) -> str:
        return f"/studies/{quote(rs, safe='')}/people/{self.list}" + (f"/{self.name}" if self.name else "")

    def old_path(self, rs: str) -> str:
        return self.old.format(rs=quote(rs, safe=""))


#: the views, in the order of their tabs. The first view of each list is its **default** and divides the study's
#: people at consent by J-2's one state (``person_state.CANDIDATE`` / ``PARTICIPANT``): each of J-2's people who is on
#: no opt-out or erasure is in exactly one of the two defaults. A default is built on an old page's route and only
#: leaves rows out. The other views are **working views**: the old page as it was, which can show people from both
#: sides of consent (the strip says so); an old address goes to its working view. The weekly page and the cohort list
#: are one view each for a trial and a registry study.
VIEWS: tuple[View, ...] = (
    View("candidates", "", "/pilot/registry/{rs}", "before", is_old_page=False),
    View("candidates", "week", "/studies/{rs}/week", "week"),
    View("candidates", "cohort", "/studies/{rs}/cohort", "cohort"),
    View("candidates", "referrals", "/studies/{rs}/candidates", "referrals"),
    View("candidates", "log", "/studies/{rs}/screening-log", "log"),
    View("candidates", "everyone", "/pilot/registry/{rs}", "everyone"),
    View("participants", "", "/studies/{rs}/subjects", "from", is_old_page=False),
    View("participants", "records", "/studies/{rs}/subjects", "records"),
    View("participants", "enrolment", "/studies/{rs}/enrolment", "enrolment"),
)
#: which side of consent each default view keeps (J-2's one state)
SIDE: dict[str, tuple[str, ...]] = {"candidates": ps.CANDIDATE, "participants": ps.PARTICIPANT}


def default_of(request: Any) -> str:
    """``candidates`` or ``participants`` when the request is served as that list's default view, else ""."""
    state = getattr(getattr(request, "state", None), "people", None) or {}
    return str(state.get("list") or "") if state and not state.get("view") else ""


def side(people: ps.People, lst: str) -> dict[str, ps.PersonState]:
    """The people of one default view: every person of the study (``People.states``: no one opted out or erased)
    whose one state is on that side of consent. A state that could not be read is on neither side."""
    keep = set(SIDE[lst])
    return {pid: st for pid, st in people.states().items() if st.name in keep}


_NEW = re.compile(rf"^/studies/(?P<rs>{_RS})/people/(?P<list>candidates|participants)(?:/(?P<view>[a-z]+))?$")
_OLD = tuple(
    (re.compile("^" + re.escape(v.old).replace(re.escape("{rs}"), f"(?P<rs>{_RS})") + "$"), v)
    for v in VIEWS
    if v.is_old_page
)


def view_of(lst: str, name: str) -> View | None:
    return next((v for v in VIEWS if v.list == lst and v.name == name), None)


def new_of(path: str) -> tuple[View, str] | None:
    """``(view, study)`` for a new address, None for any other path (an unknown view too: the router answers 404)."""
    m = _NEW.match(path)
    if m is None:
        return None
    v = view_of(m["list"], m["view"] or "")
    return (v, m["rs"]) if v is not None else None


def old_of(path: str) -> tuple[View, str] | None:
    """``(view, study)`` for an old list's address (exactly: not its files or its actions)."""
    for pattern, v in _OLD:
        m = pattern.match(path)
        if m is not None:
            return v, m["rs"]
    return None


# ------------------------------------------------------------------------------------------------- the flag's read
class _Kept:
    """The flag's value as a page gets it: the value last read at once (off before the first read and after a failed
    one); a value older than 5 s starts one background read, so a store that hangs delays no page (as J-3's)."""

    def __init__(self) -> None:
        self.kept: tuple[bool, float] | None = None
        self.reading = False
        self.guard = threading.Lock()
        self.clock: Callable[[], float] = time.monotonic

    def read(self) -> bool:
        return Flags().row(FLAG) == "on"

    def refresh(self) -> None:
        try:
            value = bool(self.read())
        except Exception:  # the store is down, not installed, no URL: off until the next read
            value = False
        with self.guard:
            self.kept = (value, self.clock())
            self.reading = False

    def now(self) -> bool:
        with self.guard:
            kept = self.kept
            start = (kept is None or self.clock() - kept[1] >= FLAG_SECONDS) and not self.reading
            if start:
                self.reading = True
        if start:
            threading.Thread(target=self.refresh, name="people-lists-flag", daemon=True).start()
        return kept[0] if kept is not None else False


_flag = _Kept()
#: set by :func:`register`: whether the reader of a request would be let into the old list (then it redirects)
_gate: Callable[[Scope, View, str], bool] | None = None


def flag_now() -> bool:
    return _flag.now()


def flag_on() -> bool:
    """The flag read now, waiting for the store (a command line, a test); never raises."""
    with _flag.guard:
        _flag.reading = True
    _flag.refresh()
    return _flag.now()


def clear_cache() -> None:
    with _flag.guard:
        _flag.kept = None


# ------------------------------------------------------------------------------------------------- the addresses
def _query(scope: Scope) -> str:
    q = scope.get("query_string", b"").decode("latin-1")
    return f"?{q}" if q else ""


def _see_other(to: str) -> RedirectResponse:
    resp = RedirectResponse(to, status_code=303)
    resp.headers["Cache-Control"] = "no-store"
    return resp


class PeopleLists:
    """For each page: the flag's value into ``request.state.people_lists`` (the menu reads it). For each GET: with the
    flag on, an old list's address goes to its view, and a view is served by its old route (``request.state.people``
    names the view, for the strip and the menu); with the flag off, a view's address goes to the old list. Installed
    after J-3's middleware, so its answers carry the security headers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = str(scope.get("path", ""))
        if scope["type"] == "http" and not path.startswith(NOT_PAGES):
            on = flag_now()
            state = scope.setdefault("state", {})  # the same dict: an outer middleware reads what a route writes there
            state["people_lists"] = on
            new = new_of(path) if scope.get("method") == "GET" else None
            old = old_of(path) if scope.get("method") == "GET" and new is None else None
            if old is not None and on and _gate is not None and await run_in_threadpool(_gate, scope, *old):
                await _see_other(old[0].path(old[1]) + _query(scope))(scope, receive, send)
                return
            if new is not None and on:  # served by the old route, which asks its own questions (off: no such page)
                view, rs = new
                target = view.old_path(rs)
                state["people"] = {"list": view.list, "view": view.name, "rs": rs}
                scope = {**scope, "path": target, "raw_path": target.encode("latin-1")}
        await self.app(scope, receive, send)


# ------------------------------------------------------------------------------------------------- who may open what
def register(app: FastAPI, h: Any, env: Any) -> None:
    """The middleware, the strip's question (a template global) and the two pickers."""
    app.user_middleware.append(Middleware(PeopleLists))

    def registry_study(rid: str) -> bool:
        try:
            return h.settings_of is not None and h.settings_of(rid).study_type == "registry"
        except Exception:  # no settings read: a trial study, as the weekly page assumes
            return False

    def rows_for(user: Any, rid: str, tasks: tuple[str, ...]) -> bool:
        return bool(user.can_view_phi) and bool(h.delegated_ok(user, rid, tasks))

    def may(user: Any, rid: str, view: View, registry: bool) -> bool:
        """The question the view's own route asks, as a yes or no: no audit event, no patient read (the delegation
        log only). A view the route refuses is not offered; its route still decides."""
        if not user.sees_study(rid):
            return False
        rows = rows_for(user, rid, ("screen",))  # Helpers.reads and need_rows: the phi.view row, then the log
        if view.list == "participants":  # lifecycle_pages.study_or_404: phi.view, the log for screen or enter_data
            return not user.sponsor_form and rows_for(user, rid, ("screen", "enter_data"))
        if view.key == "week":
            return rows and not registry
        if view.key == "cohort":
            return rows and registry
        if view.key == "log":
            return rows
        if view.key == "referrals":  # team.need_task(screen)
            return h.stand is not None and "screen" in h.stand(user, rid).tasks
        if view.key in ("before", "everyone"):  # the study registry's route; route_actions: phi.view and the
            # screen task (D-280, D-273); never an aggregate-only account (D-146)
            return rows and not user.is_admin and not user.aggregate_only
        return False

    def gate(scope: Scope, view: View, rs: str) -> bool:
        """Would the old list's route let this request's reader in? Only then does its address redirect. A session is
        read without counting as activity; no sign-in is made and nothing is audited (the route does that)."""
        from console.app import COOKIE

        try:
            request = Request(scope)
            sess = h.users.session(request.cookies.get(COOKIE), touch=False)
            if sess is None or h.users.must_change(sess.user.username):
                return False
            rid = rs.strip().upper()
            # the weekly page and the cohort list are each the route of its own study type; either redirects
            return may(sess.user, rid, view, view.key == "cohort")
        except Exception:  # any doubt: the old route answers, as before
            return False

    global _gate
    _gate = gate

    def offered(user: Any, rid: str) -> dict[str, list[View]]:
        registry = registry_study(rid)
        return {lst: [v for v in VIEWS if v.list == lst and may(user, rid, v, registry)] for lst in LISTS}

    def people_tabs(request: Any, user: Any, status: int = 200) -> dict[str, Any] | None:
        """The strip above a view: None when the page is not a view, the flag is off, or the page is not a 200 (a
        refusal or a missing page offers no view)."""
        state = getattr(getattr(request, "state", None), "people", None)
        if not state or user is None or status != 200:
            return None
        rid = str(state["rs"]).upper()
        shown = offered(user, rid)
        here = view_of(state["list"], state["view"])
        if here is not None and here not in shown[here.list]:  # the route let the reader in: the strip says where
            shown[here.list].append(here)
        return {
            "rs": rid,
            "list": state["list"],
            "lists": [(lst, shown[lst][0].path(rid)) for lst in LISTS if shown[lst]],
            "views": [(v.key, v.path(rid), v == here) for v in shown[state["list"]]],
            "working": bool(state["view"]),  # a working view: people from both sides of consent
            # /week across studies (its approvals, safety banners and registry lists): one step from Candidates
            "week_all": state["list"] == "candidates" and bool(user.can_view_phi) and not user.aggregate_only,
        }

    def studies_for(user: Any, lst: str, name: str = "") -> list[tuple[str, str]]:
        """The studies with this list for the reader, each with the address of the view asked for (``name``) where
        the reader may open it, else of the list's first view."""
        out: list[tuple[str, str]] = []
        for r in h.bk.rulesets():
            if r.status != "approved" or not user.sees_study(r.id) or any(r.id == s for s, _ in out):
                continue
            views = offered(user, r.id)[lst]
            if views:
                pick = next((v for v in views if v.name == name), views[0])
                out.append((r.id, pick.path(r.id)))
        return out

    env.globals["people_tabs"] = people_tabs
    app.state.people_lists_env = env  # the console's templates, for the test that the flag off adds no byte

    def people_pick(request: Request, which: str) -> Response:
        """The menu's Candidates and Participants: the study's list, or a choice of study when there are several
        (``?view=`` keeps the view asked for through the choice). With the flag off this page does not exist."""
        if not flag_now():
            raise h.problem(404, "notfound")
        sess = h.need(request)
        name = request.query_params.get("view", "")
        studies = studies_for(sess.user, which, name if re.fullmatch(r"[a-z]{1,20}", name) else "")
        if len(studies) == 1:
            return _see_other(studies[0][1])
        page: Response = h.page(request, "people_pick.html", sess, which=which, studies=studies)
        return page

    async def people_candidates(request: Request) -> Response:
        return await run_in_threadpool(people_pick, request, "candidates")

    async def people_participants(request: Request) -> Response:
        return await run_in_threadpool(people_pick, request, "participants")

    # plain routes, not API routes: with the flag off the route table the walks read is master's (and these answer
    # 404); with it on they open the study's list after the session check
    app.add_route("/people/candidates", people_candidates, methods=["GET"], include_in_schema=False)
    app.add_route("/people/participants", people_participants, methods=["GET"], include_in_schema=False)
