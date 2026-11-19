"""The Japan profile's committee record and the head of the institution's permission (plan 10 card 10C-4, JP-3, D-1227).

``/studies/{rs}/committee`` (and ``/api/v1/studies/{rs}/committee``) exists only under the Japan profile (the site's
country is Japan, ``site.tz``); elsewhere it answers exactly as a route the console does not have (the framework's
404, before any sign-in check) and no other page changes. On it:

* the study kind (治験, 特定臨床研究, a 指針 study, or none: the other-country default), which names the committee
  (IRB, CRB, ethics committee) from the profile's data (``tb_common.committees``);
* the committee: internal or external, its establishing body (設置者), the contract date when external, the protocol
  version the site runs now, the version the committee approved and the date, central review (一括審査) or not, and
  the documents by title and date only (nothing is uploaded);
* this site's head-of-institution permission (実施許可日) and the version it covers (each site of a multi-site study
  records its own: the row is keyed by the box's site id).

Who records and who reads follow the study's IRB record exactly (``console.team``): recording is the matrix's
``irb.edit`` for hospital staff (a hospital coordinator, the logged PI; never an SMO or CRO account nor the
administrator), with a written reason for a change to a saved record, audited as ``console.irb`` (action
``committee``) with the old and the new values; reading is every account that reads the IRB page (not an
aggregate-only account). No patient data is on this record.

The record's findings feed the one rule of ``tb_common.committees``: the console's moves into open
(``console.study_setup``: start-up or paused to open, a close taken back) and the orchestrator's open check before
every list (``orchestrator.scheduler.require_open`` and the timer's hold) read the same record."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any, cast

from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from tb_common import committees as cm

from console.api_first import before_body
from console.auth import Session
from console.home import Helpers
from console.i18n import translate
from console.studies import known_study
from console.study_setup import site_country

_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
_PATH = re.compile(r"^(/api/v1)?/studies/[^/]+/committee$")
REASON_MIN = 10  # as the IRB record (D-380, ROLE-015): the written reason for a change to a saved record
FIELDS = ("kind", "external", "establisher", "contract_on", "current_version", "approved_version", "approved_on",
          "central", "documents", "due_on")  # fmt: skip


class ApiCommittee(BaseModel):
    """The body of ``POST /api/v1/studies/{rs}/committee``: the whole study record (a field left out is cleared).
    This site's permission is changed only when ``permission_version`` and ``permitted_on`` are given, and cleared
    only with ``clear_permission`` and a reason; left out, the permission stays as it is."""

    kind: str = Field(default="", max_length=16)
    external: bool = False
    establisher: str = Field(default="", max_length=200)
    contract_on: str = Field(default="", max_length=10)
    current_version: str = Field(default="", max_length=40)
    approved_version: str = Field(default="", max_length=40)
    approved_on: str = Field(default="", max_length=10)
    central: bool = False
    documents: str = Field(default="", max_length=300)
    due_on: str = Field(default="", max_length=10)
    permission_version: str | None = Field(default=None, max_length=40)
    permitted_on: str | None = Field(default=None, max_length=10)
    clear_permission: bool = False
    reason: str = Field(default="", max_length=300)


def site_id(bk: object) -> str:
    """The box's site id (``TB_SITE_ID``): the key of this site's permission. Empty: no permission is recorded."""
    env = getattr(getattr(bk, "cfg", None), "env", None)
    return str(getattr(env, "site_id", "") or os.environ.get("TB_SITE_ID", "")).strip()


def register(app: FastAPI, h: Helpers) -> None:
    bk, au = h.bk, h.au

    def team() -> Any:
        return h.team  # console.team registers it first (TB_DB_URL, schema team)

    def country() -> str:
        return site_country(bk)

    def absent() -> None:
        """Outside the Japan profile the routes answer as a route the console does not have."""
        if not cm.on(country()):
            raise StarletteHTTPException(status_code=404)

    @app.middleware("http")
    async def absent_outside_japan(request: Request, call_next: Any) -> Response:
        """Outside the Japan profile a committee path gets the answer of a path the console has no route for (the
        app's own 404 handler, as the router gives it), before any route's sign-in check. One exception, D-444: an
        ``/api/v1`` POST first meets the session guard every state-changing API route has (anonymous: 401), then
        :func:`absent` (signed in: the absent route's 404)."""
        path = request.scope.get("path", "")
        guarded = path.startswith("/api/v1/") and request.method in ("POST", "PUT", "PATCH", "DELETE")
        if path.endswith("/committee") and _PATH.match(path) and not guarded and not cm.on(country()):
            handler: Any = app.exception_handlers[StarletteHTTPException]  # the one an unmatched path meets
            return cast(Response, await handler(request, StarletteHTTPException(status_code=404)))
        return cast(Response, await call_next(request))

    def status(rid: str) -> dict[str, Any] | None:
        """The record's findings at this site and what they do, or None outside the Japan profile: ``open`` what
        refuses a move into open, ``held`` what holds the lists now (the orchestrator's same rule), ``waiting`` what
        an open study shows without being held, ``due_on`` the date the site set to record it by. Read by the moves
        into open, the state page and the IRB page."""
        if not cm.on(country()) or getattr(h, "team", None) is None:
            return None
        rec = team().committee(rid)
        found = cm.findings(country(), rec, team().permission(rid, site_id(bk)), h.today())
        cur = h.store.study_state(rid)
        recorded = bool(cur.at)
        is_open = cur.state == "open"
        return {"findings": found, "open": cm.at_open(found),
                "held": cm.at_lists(found, recorded) if is_open else [],
                "waiting": cm.in_waiting(found) if is_open and recorded else [], "due_on": rec.due_on}  # fmt: skip

    h.committee_status = status

    def deny(sess: Session, path: str) -> Exception:
        au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80]})
        return h.problem(403, "forbidden")

    def refused(sess: Session, key: str, **values: Any) -> Exception:
        return h.problem(400, "request.refused", reason=translate(sess.lang, key, **values))

    def study_or_404(sess: Session, rs: str) -> str:
        """As the IRB page (``console.team``)."""
        rid = rs.strip().upper()
        if not _RS.match(rid) or not sess.user.sees_study(rid) or not known_study(bk, rid):
            if _RS.match(rid):
                au.append("console.denied", actor=h.actor(sess), detail={"action": f"study {rid}"})
            raise h.problem(404, "notfound")
        return rid

    def readable(sess: Session, rid: str, path: str) -> None:
        if sess.user.aggregate_only:  # as GET /studies/{rs}/irb
            raise deny(sess, path)

    def may_record(sess: Session, rid: str) -> bool:
        """The IRB record's rule (``console.team.may_edit_irb``): hospital staff with the matrix's ``irb.edit``."""
        return sess.user.affiliation == "hospital" and h.permit(sess.user, "irb.edit", rid).allowed

    def recordable(sess: Session, rs: str, path: str) -> str:
        """The right first (before any field is read): the study, then ``irb.edit``."""
        rid = study_or_404(sess, rs)
        if not may_record(sess, rid):
            raise deny(sess, path)
        return rid

    def save(sess: Session, rid: str, body: ApiCommittee) -> str:
        today, site = h.today(), site_id(bk)
        new = cm.Committee(body.kind.strip(), body.external, " ".join(body.establisher.split()),
                           body.contract_on.strip() if body.external else "", body.current_version.strip(),
                           body.approved_version.strip(), body.approved_on.strip(), body.central,
                           " ".join(body.documents.split()), due_on=body.due_on.strip())  # fmt: skip
        before, before_perm = team().committee(rid), team().permission(rid, site)
        perm: cm.Permission | None = None  # None: the permission is left as it is
        if body.clear_permission:
            perm = cm.Permission(site)
        elif body.permission_version is not None or body.permitted_on is not None:
            perm = cm.Permission(site, (body.permission_version or "").strip(), (body.permitted_on or "").strip())
        bad = new.problems(today)
        if perm is not None and not body.clear_permission:
            bad += [f"permission_{b}" for b in perm.problems(today)]
        elif perm is not None and not site:
            bad.append("permission_site")
        if bad:
            raise refused(sess, "cmt.err.bad", fields=", ".join(translate(sess.lang, f"cmt.bad.{b}") for b in bad))
        changed = [k for k in FIELDS if getattr(before, k) != getattr(new, k)]
        was = ("", "") if before_perm is None else (before_perm.version, before_perm.permitted_on)
        perm_changed = perm is not None and was != (perm.version, perm.permitted_on)
        reason = " ".join(body.reason.split())
        if ((before.at and changed) or (before_perm is not None and perm_changed)) and len(reason) < REASON_MIN:
            raise refused(sess, "cmt.err.reason", n=REASON_MIN)
        now = h.clock().isoformat()
        if changed or not before.at:
            team().save_committee(rid, new, sess.user.username, now)
        if perm is not None and perm_changed:
            team().save_permission(rid, perm, sess.user.username, now)
        au.append("console.irb", ruleset=rid, actor=h.actor(sess),
                  detail={"action": "committee", "site": site, "changed": ",".join(changed),
                          "permission": ("cleared" if body.clear_permission else
                                         f"{perm.version} {perm.permitted_on}") if perm and perm_changed else "",
                          "reason": reason[:300], "after": {k: str(getattr(new, k)) for k in FIELDS},
                          "before": {k: str(getattr(before, k)) for k in FIELDS},
                          "before_permission": " ".join(was).strip()})  # fmt: skip
        return rid

    def as_json(rid: str) -> dict[str, Any]:
        """As the IRB record's API: the fields and the findings, not who recorded them."""
        rec, perm, st = team().committee(rid), team().permission(rid, site_id(bk)), status(rid) or {}
        return {"study": rid, **{k: getattr(rec, k) for k in FIELDS}, "committee": rec.committee or None,
                "site": site_id(bk) or None, "permission": None if perm is None else
                {"version": perm.version, "permitted_on": perm.permitted_on},
                "findings": [{"code": c, "level": lv} for c, lv in st.get("findings") or []],
                "refuses_open": st.get("open") or [], "holds_lists": st.get("held") or []}  # fmt: skip

    @app.get("/studies/{rs}/committee")
    def committee_page(request: Request, rs: str) -> Response:
        absent()
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        readable(sess, rid, request.url.path)
        rec = team().committee(rid)
        return h.page(request, "committee.html", sess, rs=rid, rec=rec, kinds=cm.KINDS, site=site_id(bk),
                      perm=team().permission(rid, site_id(bk)), st=status(rid), can_edit=may_record(sess, rid),
                      history=list(reversed(team().committee_history(rid)))[:20])  # fmt: skip

    @app.post("/studies/{rs}/committee")
    async def committee_save(request: Request, rs: str) -> Response:
        absent()
        sess = h.need(request)
        form: Mapping[str, Any] = await request.form()
        if not h.csrf_ok(sess, str(form.get("csrf") or "")):
            raise h.problem(400, "csrf")
        rid = recordable(sess, rs, request.url.path)
        text = {
            k: str(form.get(k) or "")
            for k in ApiCommittee.model_fields
            if k not in ("external", "central", "clear_permission", "permission_version", "permitted_on")
        }
        given = {k: str(form.get(k) or "").strip() for k in ("permission_version", "permitted_on")}
        try:  # a blank permission on the page leaves it as it is; clearing it is its own tick, with a reason
            body = ApiCommittee(**text, external=form.get("external") == "1", central=form.get("central") == "1",
                                clear_permission=form.get("clear_permission") == "1",
                                **{k: v for k, v in given.items() if any(given.values())})  # fmt: skip
        except ValidationError as exc:
            fields = sorted({str(e["loc"][0]) for e in exc.errors() if e.get("loc")})
            raise refused(sess, "cmt.err.long", fields=", ".join(fields)) from exc
        save(sess, rid, body)
        return RedirectResponse(f"/studies/{rid}/committee?done=1", status_code=303)

    def api(request: Request) -> Session:
        assert h.api_session is not None
        return h.api_session(request)

    def first(sess: Session, request: Request) -> None:
        absent()
        recordable(sess, request.path_params["rs"], request.url.path)

    @app.get("/api/v1/studies/{rs}/committee")
    def api_committee(request: Request, rs: str) -> dict[str, Any]:
        absent()
        sess = api(request)
        rid = study_or_404(sess, rs)
        readable(sess, rid, request.url.path)
        return as_json(rid)

    @app.post("/api/v1/studies/{rs}/committee")
    @before_body(first)
    def api_committee_save(request: Request, rs: str, body: ApiCommittee) -> dict[str, Any]:
        sess = api(request)
        return as_json(save(sess, recordable(sess, rs, request.url.path), body))
