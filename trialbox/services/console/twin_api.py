"""The patient twin's read route (T-204, D-440): ``GET /api/v1/studies/{rs}/patients/{pid}/twin``.

The one stable read of ``tb_patient_profile`` for the cards that build on it (the cited profile page T-311a, the
annotations T-312, the setpoints T-313, the de-identified export T-316c read the store itself). Who reads:

* matrix row ``profile.read`` and ``Helpers.reads`` (``phi.view``, then the study's delegation log), as the patient
  page; outside one's own rights only an open break-glass grant for that patient (D-430), and each such read is a use
  of the grant;
* the patient is one of the study's: on its current list or in its candidate registry;
* never a patient on the opt-out register (404, like a patient the study does not have);
* the ``setpoint`` and ``gap`` layers only with ``profile.research_layers`` (the study's PI); absent for every other
  reader.

Every read is one audit event ``console.twin_view`` with the role, the layers returned and the basis (snapshot,
version); a refusal is one ``console.denied``. No inline role check: the matrix decides (D-425).
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import FastAPI, Request
from tb_common.authz import BREAK_GLASS_ROLE

from console.home import Helpers
from console.studies import known_study

_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
_PID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def register(app: FastAPI, h: Helpers, store: Any = None) -> None:
    holder: dict[str, Any] = {"store": store}

    def twins() -> Any:
        if holder["store"] is None:  # opened at the first read: a console without the store still starts
            from patient_profile.twin import ProfileStore

            holder["store"] = ProfileStore()
        return holder["store"]

    def in_study(sess: Any, rid: str, pid: str) -> bool:
        """The patient is one of the study's: on its current list, or in its candidate registry."""
        wk = h.week_bundle(sess, rid) if h.week_bundle is not None else None
        rows = (wk or {}).get("cl", {}).get("rows") or [] if wk else []
        if any(str(r.get("pid")) == pid for r in rows):
            return True
        return h.registry_map is not None and pid in h.registry_map(rid)

    @app.get("/api/v1/studies/{rs}/patients/{pid}/twin")
    def api_twin(request: Request, rs: str, pid: str) -> dict[str, Any]:
        """The patient's twin (``schemas/profile.schema.json``) with ``as_of``: the version, the snapshot it was built
        from and the newest snapshot that gave the same content."""
        if h.api_session is None:  # set by console.home.register, which runs first
            raise h.problem(401, "login")
        sess = h.api_session(request)
        user = sess.user
        rid = rs.strip().upper()
        if not _RS.match(rid) or not user.sees_study(rid) or not known_study(h.bk, rid):
            if _RS.match(rid):
                h.au.append("console.denied", actor=h.actor(sess), detail={"action": f"study {rid}"})
            raise h.problem(404, "notfound")
        grant = None
        if not (h.permit(user, "profile.read", rid).allowed and h.reads(user, rid)):
            # T-309 (D-430): outside one's own rights, one patient under one's own open grant, or nothing
            grant = h.breakglass(sess, ruleset=rid, pid=pid, what="twin") if h.breakglass and _PID.match(pid) else None
            if grant is None:
                h.au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
                raise h.problem(403, "forbidden")
        if not _PID.match(pid) or pid in h.gone() or not in_study(sess, rid, pid):
            raise h.problem(404, "notfound")
        twin = twins().current(pid)
        if twin is None:
            raise h.problem(404, "notfound")
        from patient_profile.twin import for_role

        research = grant is None and h.permit(user, "profile.research_layers", rid).allowed
        doc = for_role(twin.doc, research)
        detail: dict[str, Any] = {
            "pid": pid,
            "role": BREAK_GLASS_ROLE if grant is not None else user.role,
            "layers": sorted(k for k, v in doc["layers"].items() if v is not None),
            "basis": twin.snapshot,
            "version": twin.version,
        }
        if grant is not None:
            detail["grant"] = grant.id
        h.au.append("console.twin_view", ruleset=rid, actor=h.actor(sess), detail=detail)
        return {**doc, "as_of": {"version": twin.version, "snapshot": twin.snapshot,
                                 "checked_snapshot": twin.checked_snapshot, "built_at": twin.built_at}}  # fmt: skip
