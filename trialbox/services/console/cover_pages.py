"""9f-3 and 9f-5 (D-1383): the PI's cover and a task's owner, each limited to the study's delegation log.

**The cover (9f-3).** While the PI is away, the PI the study's log names (by their own entry, never a covering person)
names a sub-investigator of the same study's log to hold the PI's rights in that study from a first to a last day
(at most ``teamstore.COVER_MAX_DAYS``, both required). The rights come from one place: ``teamstore.log_rights``, the
reading of the log that ``console.team.standing`` and ``orchestrator.grants.log_standing`` both ask; the matrix is not
changed. A cover carries only the PI rights of ``teamstore.COVER_RIGHTS`` (the clinical ones; default deny), never the
study's administration (``teamstore.COVER_WITHHELD``): the delegation log, its monthly check, the study's state, the
IRB records, prefill on and off stay the PI's. A cover that lapses (the PI covered no longer the PI the log names, or
the covering person's own entry not active) is ended for good when first observed (``console.cover`` ``lapsed``). Every audit event the covering person's acts write in that study while
the cover is in effect carries ``covering_for`` with both names (:class:`CoverAudit`); the actor stays the covering
person, never the PI. The entry, an early end, the start and the end of a cover are ``console.cover`` events; the start
and the end once each (:func:`record_edges`: when a cover is entered for today, when a page first reads it in effect,
and in the daily notice round). The study's team pages show a banner while a cover is in effect, and the opening page
a task "tell the IRB of the cover" until someone marks it done. The covering person's morning mail (N1) carries the
study, as the PI's does, only while the cover is in effect (``console.notify``: the study is in it because the
standing is the PI's that day), with one line saying whom they cover.

**A task's owner (9f-5).** A task of the opening page (call, find information, prepare, ask a treating doctor, the
monthly log check, tell the IRB of a cover) may name an owner: a person with an active entry on that study's log (not
a monitor grant). Who may set or change it: the study's PI (or the PI's cover) and a person whose own active entry on
that log is the coordinator's (``crc``). Each change is a ``console.task_owner`` event with the owner before and
after. Who sees a task does not change: the owner is shown on the task line to whoever sees the line.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from tb_common.authz import permit

from console.api_first import before_body
from console.auth import Session, User
from console.home import Helpers
from console.studies import known_study
from console.teamstore import COVER_MAX_DAYS, COVER_ROLE, OWNER_ROLES, Cover, TeamError, TeamStore, cover_state

_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
EDGE_ACTOR = "system:cover"  # the actor of a cover's start and end events (no person starts or ends a day)


class ApiCover(BaseModel):
    username: str = Field(default="", max_length=120)
    start: str = Field(default="", max_length=10)
    end: str = Field(default="", max_length=10)


class ApiTaskOwner(BaseModel):
    kind: str = Field(default="", max_length=20)
    ref: str = Field(default="", max_length=64)
    owner: str = Field(default="", max_length=120)


def cover_detail(c: Cover) -> dict[str, Any]:
    """Both names of a cover, as every ``console.cover`` event and ``covering_for`` note carry them."""
    return {"id": c.id, "pi": c.pi, "pi_name": c.pi_name, "username": c.username, "name": c.name, "start": c.start,
            "end": c.end}  # fmt: skip


def task_key(o: Any) -> dict[str, str]:
    """A task as its ``console.task_owner`` event names it, by the audit trail's convention for a patient (the
    ``console.referral`` events'): the pseudonym as ``pid`` (call, find information, prepare), a referral's ``id``, a
    cover's ``cover``; the monthly log check has none."""
    if not o.ref:
        return {}
    names = {"call": "pid", "info": "pid", "prepare": "pid", "refer": "id", "cover_irb": "cover"}
    return {names.get(o.kind, "task"): o.ref}


class CoverAudit:
    """The console's audit writer with one step added (9f-3, D-1383): an event a person writes in a study (``actor``
    ``console:<name>`` and ``ruleset``) while that person holds the study's PI cover gets ``covering_for`` in its
    detail: the PI's account and name and the covering person's name. Everything else is the writer's own."""

    def __init__(self, inner: Any, find: Callable[[str, str], Cover | None]) -> None:
        self._inner = inner
        self._find = find

    def append(self, event: str, *, ts: Any = None, **fields: Any) -> dict[str, Any]:
        actor = str(fields.get("actor") or "")
        rs = fields.get("ruleset")
        if actor.startswith("console:") and rs:
            try:
                c = self._find(actor.removeprefix("console:"), str(rs))
            except Exception:  # no store, a store that cannot answer: the standing then gives no cover either
                c = None
            if c is not None:
                detail = dict(fields.get("detail") or {})
                detail.setdefault("covering_for", {"pi": c.pi, "pi_name": c.pi_name, "name": c.name, "cover": c.id})
                fields["detail"] = detail
        out: dict[str, Any] = self._inner.append(event, ts=ts, **fields)
        return out

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def record_edges(team: TeamStore, au: Any, day: date, at: str, rulesets: list[str] | None = None) -> list[str]:
    """Write each cover's edges to the audit trail, once each, as :func:`teamstore.cover_state` reads it on ``day``:
    ``start`` only once the cover takes effect; ``end`` once a cover that never broke is over (its last day; an early
    end's day before); ``lapsed`` when a lapse is first observed (its reason and its true last day in effect, None when
    it never took effect), which also stores the lapse for good (``TeamStore.lapse_cover``: never revived, a new cover
    must be entered) and stands for its end. Returns the edges written, as ``<study>:<id>:<edge>``."""
    done: list[str] = []
    for rs in rulesets if rulesets is not None else team.cover_rulesets():
        entries = team.entries(rs)
        for c in team.covers(rs):
            if c.lapse_reason or c.end_logged:
                continue
            state, reason, last = cover_state(entries, c, day)
            took_effect = (state in ("effective", "over") and bool(c.last_day())) or (state == "lapsed" and bool(last))
            if took_effect and not c.start_logged:

                def start(c: Cover = c, rs: str = rs) -> None:
                    au.append(
                        "console.cover", ruleset=rs, actor=EDGE_ACTOR, detail={"action": "start", **cover_detail(c)}
                    )

                if team.mark_cover_edge(rs, c.id, "start", at, start):
                    done.append(f"{rs}:{c.id}:start")
            if state == "lapsed" and reason:

                def lapsed(c: Cover = c, rs: str = rs, reason: str = reason, last: str | None = last) -> None:
                    au.append("console.cover", ruleset=rs, actor=EDGE_ACTOR,
                              detail={"action": "lapsed", "reason": reason, "last_day": last,
                                      "took_effect": last is not None, **cover_detail(c)})  # fmt: skip

                if team.lapse_cover(rs, c.id, reason=reason, last=last, at=at, before_commit=lapsed):
                    done.append(f"{rs}:{c.id}:lapsed")
            elif state == "over":
                last_day = c.last_day()

                def end(c: Cover = c, rs: str = rs, last: str = last_day) -> None:
                    au.append("console.cover", ruleset=rs, actor=EDGE_ACTOR,
                              detail={"action": "end", "last_day": last or None, "early": c.ended_on is not None,
                                      **cover_detail(c)})  # fmt: skip

                if team.mark_cover_edge(rs, c.id, "end", at, end):
                    done.append(f"{rs}:{c.id}:end")
    return done


def register(app: FastAPI, h: Helpers) -> None:
    team: TeamStore = h.team
    au = h.au

    def today() -> date:
        return h.today()

    def now() -> str:
        return h.clock().isoformat()

    def api(request: Request) -> Session:
        assert h.api_session is not None
        return h.api_session(request)

    def deny(sess: Session, path: str) -> Exception:
        au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80]})
        return h.problem(403, "forbidden")

    def refused(exc: Exception) -> Exception:
        return h.problem(400, "request.refused", reason=str(exc))

    def study(sess: Session, rs: str) -> str:
        rid = rs.strip().upper()
        if not _RS.match(rid) or not sess.user.sees_study(rid) or not known_study(h.bk, rid):
            if _RS.match(rid):
                au.append("console.denied", actor=h.actor(sess), detail={"action": f"study {rid}"})
            raise h.problem(404, "notfound")
        return rid

    def stand(user: User, rid: str) -> Any:
        assert h.stand is not None
        return h.stand(user, rid)

    def pi_by_entry(user: User, rid: str) -> bool:
        """The PI the study's log names by their own entry (a cover never enters or changes a cover)."""
        if user.aggregate_only:
            return False
        s = stand(user, rid)
        return bool(s.pi and s.cover is None and permit(user.role, "delegation.keep", s.own_grant()).allowed)

    def keeps_tasks(user: User, rid: str) -> bool:
        """9f-5: may set a task's owner and mark the cover's IRB task done: the study's PI (or the PI's cover), or a
        person whose own active entry on the study's log is the coordinator's."""
        if user.aggregate_only:
            return False
        if pi_by_entry(user, rid):  # the matrix row the route declares (route_actions.yaml): delegation.keep
            return True
        s = stand(user, rid)
        if s.cover is not None and s.pi_for("team.task_owner"):  # the PI's cover: teamstore.COVER_RIGHTS
            return True
        return any(e.role == "crc" for e in team.rights(rid, user.username, today()).mine)

    def cover_or_404(rid: str, cid: int) -> Cover:
        c = team.cover(rid, cid)
        if c is None:
            raise h.problem(404, "notfound")
        return c

    # ------------------------------------------------------------------ the actions (page and /api/v1)
    def add_cover(sess: Session, path: str, rs: str, body: ApiCover) -> Cover:
        rid = study(sess, rs)
        if not pi_by_entry(sess.user, rid):
            raise deny(sess, path)
        who = body.username.strip().lower()
        acct = h.users.get(who) if who else None
        if who and (acct is None or acct.role != "investigator" or not acct.sees_study(rid)):
            raise refused(TeamError("the person who covers signs in with an investigator account of this study"))
        try:
            c = team.add_cover(rid, username=who, start=body.start, end=body.end, today=today(), by=sess.user.username,
                               at=now())  # fmt: skip
        except TeamError as exc:
            raise refused(exc) from exc
        au.append("console.cover", ruleset=rid, actor=h.actor(sess),
                  detail={"action": "add", "max_days": COVER_MAX_DAYS, **cover_detail(c)})  # fmt: skip
        record_edges(team, au, today(), now(), [rid])  # a cover from today starts now
        return c

    def end_cover(sess: Session, path: str, rs: str, cid: int) -> Cover:
        rid = study(sess, rs)
        me = sess.user.username
        named = not sess.user.aggregate_only and any(x.username == me for x in team.covers(rid))
        if not (pi_by_entry(sess.user, rid) or named):  # asked before the cover is looked up
            raise deny(sess, path)
        c = cover_or_404(rid, cid)
        if not (pi_by_entry(sess.user, rid) or c.username == me):  # the PI by their own entry, or the covering person
            raise deny(sess, path)
        try:
            out = team.end_cover(rid, cid, today=today(), by=sess.user.username, at=now())
        except TeamError as exc:
            raise refused(exc) from exc
        au.append("console.cover", ruleset=rid, actor=h.actor(sess),
                  detail={"action": "end_early", "ended_on": out.ended_on, **cover_detail(out)})  # fmt: skip
        record_edges(team, au, today(), now(), [rid])  # its end, at once
        return out

    def irb_told(sess: Session, path: str, rs: str, cid: int) -> Cover:
        rid = study(sess, rs)
        if not keeps_tasks(sess.user, rid):
            raise deny(sess, path)
        cover_or_404(rid, cid)
        try:
            out = team.irb_told(rid, cid, today=today(), by=sess.user.username)
        except TeamError as exc:
            raise refused(exc) from exc
        au.append("console.cover", ruleset=rid, actor=h.actor(sess),
                  detail={"action": "irb_told", "on": out.irb_told_on, **cover_detail(out)})  # fmt: skip
        return out

    def set_owner(sess: Session, path: str, rs: str, body: ApiTaskOwner) -> dict[str, Any]:
        rid = study(sess, rs)
        if not keeps_tasks(sess.user, rid):
            raise deny(sess, path)
        current = h.task_keys(sess, rid) if h.task_keys is not None else None
        try:
            before, after = team.set_task_owner(rid, kind=body.kind, ref=body.ref, owner=body.owner, day=today(),
                                                by=sess.user.username, at=now(), current=current)  # fmt: skip
        except TeamError as exc:
            raise refused(exc) from exc
        au.append("console.task_owner", ruleset=rid, actor=h.actor(sess),
                  detail={"action": "set" if after.owner else "clear", "kind": after.kind, **task_key(after),
                          "owner": after.owner, "owner_name": after.owner_name,
                          "before": before.owner if before else ""})  # fmt: skip
        return {"study": rid, "kind": after.kind, "ref": after.ref, "owner": after.owner or None,
                "owner_name": after.owner_name or None}  # fmt: skip

    # ------------------------------------------------------------------ pages
    async def form_of(request: Request, sess: Session) -> Any:
        form = await request.form()
        if not h.csrf_ok(sess, str(form.get("csrf") or "")):
            raise h.problem(400, "csrf")
        return form

    @app.post("/studies/{rs}/cover")
    async def cover_add_page(request: Request, rs: str) -> Response:
        sess = h.need(request)
        form = await form_of(request, sess)
        body = ApiCover(username=str(form.get("username") or "")[:120], start=str(form.get("start") or "")[:10],
                        end=str(form.get("end") or "")[:10])  # fmt: skip
        c = add_cover(sess, request.url.path, rs, body)
        return RedirectResponse(f"/studies/{c.ruleset}/team?done=cover#cover", status_code=303)

    @app.post("/studies/{rs}/cover/{cid}/end")
    async def cover_end_page(request: Request, rs: str, cid: int) -> Response:
        sess = h.need(request)
        await form_of(request, sess)
        c = end_cover(sess, request.url.path, rs, cid)
        return RedirectResponse(f"/studies/{c.ruleset}/team?done=cover_end#cover", status_code=303)

    @app.post("/studies/{rs}/cover/{cid}/irb")
    async def cover_irb_page(request: Request, rs: str, cid: int) -> Response:
        sess = h.need(request)
        await form_of(request, sess)
        c = irb_told(sess, request.url.path, rs, cid)
        back = str(request.headers.get("referer") or "")
        to = "/home" if back.endswith("/home") else f"/studies/{c.ruleset}/team?done=cover_irb#cover"
        return RedirectResponse(to, status_code=303)

    @app.post("/studies/{rs}/tasks/owner")
    async def task_owner_page(request: Request, rs: str) -> Response:
        sess = h.need(request)
        form = await form_of(request, sess)
        body = ApiTaskOwner(kind=str(form.get("kind") or "")[:20], ref=str(form.get("ref") or "")[:64],
                            owner=str(form.get("owner") or "")[:120])  # fmt: skip
        set_owner(sess, request.url.path, rs, body)
        return RedirectResponse("/home#tasks", status_code=303)

    # ------------------------------------------------------------------ /api/v1 (D-125: the same rules)
    def first_pi(sess: Session, request: Request) -> None:
        rid = study(sess, request.path_params["rs"])
        if not pi_by_entry(sess.user, rid):
            raise deny(sess, request.url.path)

    def first_tasks(sess: Session, request: Request) -> None:
        rid = study(sess, request.path_params["rs"])
        if not keeps_tasks(sess.user, rid):
            raise deny(sess, request.url.path)

    @app.get("/api/v1/studies/{rs}/cover")
    def api_covers(request: Request, rs: str) -> dict[str, Any]:
        sess = api(request)
        rid = study(sess, rs)
        if sess.user.aggregate_only:
            raise deny(sess, request.url.path)
        day = today()
        return {"study": rid, "max_days": COVER_MAX_DAYS,
                "covers": [{**c.as_dict(), "in_effect": c.in_effect_on(day)} for c in team.covers(rid)]}  # fmt: skip

    @app.post("/api/v1/studies/{rs}/cover")
    @before_body(first_pi)
    def api_cover_add(request: Request, rs: str, body: ApiCover) -> dict[str, Any]:
        sess = api(request)
        return {"study": rs.strip().upper(), "cover": add_cover(sess, request.url.path, rs, body).as_dict()}

    @app.post("/api/v1/studies/{rs}/cover/{cid}/end")
    def api_cover_end(request: Request, rs: str, cid: int) -> dict[str, Any]:
        sess = api(request)
        return {"study": rs.strip().upper(), "cover": end_cover(sess, request.url.path, rs, cid).as_dict()}

    @app.post("/api/v1/studies/{rs}/cover/{cid}/irb")
    def api_cover_irb(request: Request, rs: str, cid: int) -> dict[str, Any]:
        sess = api(request)
        return {"study": rs.strip().upper(), "cover": irb_told(sess, request.url.path, rs, cid).as_dict()}

    @app.post("/api/v1/studies/{rs}/tasks/owner")
    @before_body(first_tasks)
    def api_task_owner(request: Request, rs: str, body: ApiTaskOwner) -> dict[str, Any]:
        sess = api(request)
        return set_owner(sess, request.url.path, rs, body)

    # ------------------------------------------------------------------ what other pages and the mail read
    def cover_view(what: str, sess: Session, rs: str) -> Any:
        """``banner``: the cover in effect today in study ``rs`` (None without one); ``card``: the log page's cover
        card (the covers, who may be named, what this account may do)."""
        rid = str(rs or "").strip().upper()
        if not _RS.match(rid) or not sess.user.sees_study(rid) or sess.user.aggregate_only:
            return None
        day = today()
        entries = team.entries(rid)
        covers = team.covers(rid)
        subs = sorted({(e.username, e.name) for e in entries
                       if e.role == COVER_ROLE and e.username and e.active_on(day)})  # fmt: skip
        states = {c.id: cover_state(entries, c, day)[0] for c in covers}
        if any((states[c.id] == "effective" and not c.start_logged) or (states[c.id] == "lapsed" and not c.lapse_reason)
               for c in covers):  # fmt: skip
            record_edges(team, au, day, now(), [rid])  # the first page that finds it in effect or lapsed writes it
            covers = team.covers(rid)
        # the cover log_rights gives today (the same state: in effect, unbroken since it was entered)
        live = next((c for c in reversed(covers) if c.in_effect_on(day) and states[c.id] == "effective"), None)
        if what == "banner":
            return live
        mine_pi = pi_by_entry(sess.user, rid)
        return {"covers": list(reversed(covers)), "live": live, "may_add": mine_pi, "subs": subs, "today": day,
                "max_days": COVER_MAX_DAYS, "me": sess.user.username,
                "may_irb": keeps_tasks(sess.user, rid)}  # fmt: skip

    def cover_lines(user: User, day: date) -> list[tuple[str, str, str]]:
        """N1: (study, PI's name, last day) of each cover this account holds on ``day`` (its standing is the PI's)."""
        out: list[tuple[str, str, str]] = []
        for rs in team.cover_rulesets():
            r = team.rights(rs, user.username, day)
            if r.cover is not None and user.sees_study(rs):
                out.append((rs, r.cover.pi_name, r.cover.last_day()))
        return out

    def task_owners(rid: str) -> tuple[dict[tuple[str, str], Any], list[tuple[str, str]]]:
        """9f-5: the study's task owners and who on its log may own one (account, name) today."""
        day = today()
        people = sorted({(e.username, e.name) for e in team.entries(rid)
                         if e.username and e.role in OWNER_ROLES and e.active_on(day)})  # fmt: skip
        return team.task_owners(rid), people

    def cover_tasks(rid: str) -> list[Cover]:
        """The covers of the study whose IRB task is open: entered, not ended before it began, IRB not told."""
        return [c for c in team.covers(rid) if not c.irb_told_on and c.last_day()]

    h.cover_view = cover_view
    h.cover_lines = cover_lines
    h.task_owners = task_owners
    h.keeps_tasks = keeps_tasks
    h.cover_tasks = cover_tasks
    h.cover_edges = lambda day: record_edges(team, au, day, now())
