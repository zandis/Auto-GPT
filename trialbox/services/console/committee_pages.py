"""The Japan profile's committee record and the head of the institution's permission (plan 10 card 10C-4, JP-3, D-1227).

``/studies/{rs}/committee`` (and ``/api/v1/studies/{rs}/committee``) exists only under the Japan profile (the site's
country is Japan, ``site.tz``); elsewhere it is 404 and no other page changes. On it:

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

The record's findings feed the one gate a study passes to screen: the move to open (``console.study_setup``,
screening runs only for an open study, ``orchestrator.scheduler.require_open``)."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from tb_common import committees as cm

from console.api_first import before_body
from console.auth import Session
from console.home import Helpers
from console.i18n import translate
from console.studies import known_study
from console.study_setup import site_country

_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
REASON_MIN = 10  # as the IRB record (D-380, ROLE-015): the written reason for a change to a saved record
FIELDS = ("kind", "external", "establisher", "contract_on", "current_version", "approved_version", "approved_on",
          "central", "documents")  # fmt: skip


class ApiCommittee(BaseModel):
    """The body of ``POST /api/v1/studies/{rs}/committee``: the whole record (a field left out is cleared)."""

    kind: str = Field(default="", max_length=16)
    external: bool = False
    establisher: str = Field(default="", max_length=200)
    contract_on: str = Field(default="", max_length=10)
    current_version: str = Field(default="", max_length=40)
    approved_version: str = Field(default="", max_length=40)
    approved_on: str = Field(default="", max_length=10)
    central: bool = False
    documents: str = Field(default="", max_length=300)
    permission_version: str = Field(default="", max_length=40)
    permitted_on: str = Field(default="", max_length=10)
    reason: str = Field(default="", max_length=300)


def site_id(bk: object) -> str:
    """The box's site id (``TB_SITE_ID``): the key of this site's permission."""
    env = getattr(getattr(bk, "cfg", None), "env", None)
    return str(getattr(env, "site_id", "") or os.environ.get("TB_SITE_ID", "")).strip()


def register(app: FastAPI, h: Helpers) -> None:
    bk, au = h.bk, h.au

    def team() -> Any:
        return h.team  # console.team registers it first (TB_DB_URL, schema team)

    def country() -> str:
        return site_country(bk)

    def findings(rid: str) -> list[tuple[str, str]] | None:
        """The record's findings at this site, or None outside the Japan profile; read by the gate on open and the
        study's IRB page."""
        if not cm.on(country()) or getattr(h, "team", None) is None:
            return None
        return cm.findings(country(), team().committee(rid), team().permission(rid, site_id(bk)))

    h.committee_findings = findings

    def deny(sess: Session, path: str) -> Exception:
        au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80]})
        return h.problem(403, "forbidden")

    def study_or_404(sess: Session, rs: str) -> str:
        """As the IRB page (``console.team``), and 404 outside the Japan profile."""
        rid = rs.strip().upper()
        if not cm.on(country()):
            raise h.problem(404, "notfound")
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

    def save(sess: Session, path: str, rs: str, body: ApiCommittee) -> str:
        rid = study_or_404(sess, rs)
        if not may_record(sess, rid):
            raise deny(sess, path)
        today = h.today()
        new = cm.Committee(body.kind.strip(), body.external, " ".join(body.establisher.split()),
                           body.contract_on.strip() if body.external else "", body.current_version.strip(),
                           body.approved_version.strip(), body.approved_on.strip(), body.central,
                           " ".join(body.documents.split()))  # fmt: skip
        perm = cm.Permission(site_id(bk), body.permission_version.strip(), body.permitted_on.strip())
        bad = new.problems(today) + [f"permission_{b}" for b in perm.problems(today)]
        if bad:
            raise h.problem(
                400,
                "request.refused",
                reason=translate(
                    sess.lang, "cmt.err.bad", fields=", ".join(translate(sess.lang, f"cmt.bad.{b}") for b in bad)
                ),
            )
        before, before_perm = team().committee(rid), team().permission(rid, site_id(bk))
        changed = [k for k in FIELDS if getattr(before, k) != getattr(new, k)]
        perm_changed = (before_perm.version, before_perm.permitted_on) != (perm.version, perm.permitted_on) if (
            before_perm is not None) else bool(perm.permitted_on)  # fmt: skip
        reason = " ".join(body.reason.split())
        if ((before.at and changed) or (before_perm is not None and perm_changed)) and len(reason) < REASON_MIN:
            raise h.problem(400, "request.refused", reason=translate(sess.lang, "cmt.err.reason", n=REASON_MIN))
        now = h.clock().isoformat()
        if changed or not before.at:
            team().save_committee(rid, new, sess.user.username, now)
        if perm_changed:
            team().save_permission(rid, perm, sess.user.username, now)
        au.append("console.irb", ruleset=rid, actor=h.actor(sess),
                  detail={"action": "committee", "site": perm.site, "changed": ",".join(changed),
                          "permission": f"{perm.version} {perm.permitted_on}".strip() if perm_changed else "",
                          "reason": reason[:300], "after": {k: str(getattr(new, k)) for k in FIELDS},
                          "before": {k: str(getattr(before, k)) for k in FIELDS},
                          "before_permission": "" if before_perm is None else
                          f"{before_perm.version} {before_perm.permitted_on}".strip()})  # fmt: skip
        return rid

    def as_json(rid: str) -> dict[str, Any]:
        rec, perm = team().committee(rid), team().permission(rid, site_id(bk))
        return {"study": rid, **{k: getattr(rec, k) for k in FIELDS}, "committee": rec.committee or None,
                "site": site_id(bk), "permission": None if perm is None else
                {"version": perm.version, "permitted_on": perm.permitted_on, "by": perm.by, "at": perm.at},
                "findings": [{"code": c, "level": lv} for c, lv in findings(rid) or []]}  # fmt: skip

    @app.get("/studies/{rs}/committee")
    def committee_page(request: Request, rs: str) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        readable(sess, rid, request.url.path)
        rec = team().committee(rid)
        return h.page(request, "committee.html", sess, rs=rid, rec=rec, kinds=cm.KINDS, site=site_id(bk),
                      perm=team().permission(rid, site_id(bk)), findings=findings(rid), can_edit=may_record(sess, rid),
                      history=list(reversed(team().committee_history(rid)))[:20])  # fmt: skip

    @app.post("/studies/{rs}/committee")
    async def committee_save(request: Request, rs: str) -> Response:
        sess = h.need(request)
        form: Mapping[str, Any] = await request.form()
        if not h.csrf_ok(sess, str(form.get("csrf") or "")):
            raise h.problem(400, "csrf")
        text = {k: str(form.get(k) or "")[:300] for k in ApiCommittee.model_fields if k not in ("external", "central")}
        body = ApiCommittee(**text, external=form.get("external") == "1", central=form.get("central") == "1")
        rid = save(sess, request.url.path, rs, body)
        return RedirectResponse(f"/studies/{rid}/committee?done=1", status_code=303)

    def api(request: Request) -> Session:
        assert h.api_session is not None
        return h.api_session(request)

    def first(sess: Session, request: Request) -> None:
        rid = study_or_404(sess, request.path_params["rs"])
        if not may_record(sess, rid):
            raise deny(sess, request.url.path)

    @app.get("/api/v1/studies/{rs}/committee")
    def api_committee(request: Request, rs: str) -> dict[str, Any]:
        sess = api(request)
        rid = study_or_404(sess, rs)
        readable(sess, rid, request.url.path)
        return as_json(rid)

    @app.post("/api/v1/studies/{rs}/committee")
    @before_body(first)
    def api_committee_save(request: Request, rs: str, body: ApiCommittee) -> dict[str, Any]:
        return as_json(save(api(request), request.url.path, rs, body))
