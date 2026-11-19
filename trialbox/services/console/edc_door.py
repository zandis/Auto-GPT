"""The EDC's door into TrialBox (D-1042): health, signed events, the study map, tool confirmation, optional OIDC.

These routes are absent from the menu. The demo's pages do not call them. Events are refused until
``TB_EDC_EVENT_SECRET`` is set. OIDC is refused until ``TB_EDC_OIDC`` is 1.

The door's state (event ids, held writes, OIDC codes) is in the trial database (``edc_backend.store``, D-1044). With
no database configured a route that needs it answers 503; nothing is written to the system's temp folder.
"""

from __future__ import annotations

import json
from typing import Any

from edc_backend import events, linkmap, oidc, tools
from edc_backend import store as door
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from tb_common.authz import in_support_session

from console.home import Helpers


def register(app: FastAPI, h: Helpers) -> None:
    proposals = tools.Proposals()

    def folder() -> str:
        return events.event_dir()

    def no_storage() -> JSONResponse:
        return JSONResponse({"error": "the EDC door's storage is not configured"}, status_code=503)

    @app.get("/api/edc/health")
    def health() -> dict[str, str]:
        return {"version": "1"}

    @app.post("/api/edc/events/v1")
    async def receive(request: Request) -> JSONResponse:
        secret = events.event_secret()
        if not secret:
            return JSONResponse({"error": "events are not configured"}, status_code=404)
        body = await request.body()
        header = request.headers.get("x-trialbox-signature") or ""
        try:
            doc = events.check(secret, body, header)
        except events.EventRejected as exc:
            return JSONResponse({"error": exc.message}, status_code=exc.status)
        try:
            book = door.default_store()
        except door.NoStorage:
            return no_storage()
        row = events.row_of(doc)
        study = linkmap.study_for_project(folder(), row["project_id"])
        reread = None
        if study and row["type"] in events.REREAD:
            from console.study_setup import read_now

            def reread() -> None:
                read_now(h, study)

        # D-1044: the id and the re-read in one transaction; 2xx only once it is committed. A read that fails rolls
        # the id back, so the EDC's next delivery of it is taken in
        try:
            fresh = book.take_event(row, reread)
        except Exception:
            return JSONResponse({"error": "the read did not finish"}, status_code=503)
        if fresh:
            h.au.append("edc.event", actor="edc", detail={k: row[k] for k in
                        ("id", "type", "project_id", "record_id", "instrument")})  # fmt: skip
        return JSONResponse({"ok": True, "fresh": fresh})

    def admin(request: Request, *, closed_in_session: bool = False) -> Any:
        sess = h.need(request)
        # 10K-15 (D-1364): a tool call (find_patient, draft_form, quality_check, and its confirmation) answers about
        # one EDC record, so it is refused during a support session, before its CSRF and body are read. The map and
        # the connection page stay open (``redcap.connection``). A check that only narrows: no matrix row of its own
        if not h.permit(sess.user, "redcap.connection").allowed or (closed_in_session and in_support_session()):
            h.au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        return sess

    @app.get("/api/edc/map")
    def get_map(request: Request) -> dict[str, Any]:
        admin(request)
        return linkmap.load(folder())

    @app.put("/api/edc/map")
    async def put_map(request: Request) -> dict[str, Any]:
        sess = admin(request)
        if not h.csrf_ok(sess, request.headers.get("x-csrf") or ""):
            raise h.problem(400, "csrf")
        try:
            doc = json.loads(await request.body() or b"{}")
        except ValueError as exc:
            raise h.problem(400, "bad") from exc
        try:
            linkmap.save(folder(), doc if isinstance(doc, dict) else {})
        except ValueError as exc:
            raise h.problem(400, "bad") from exc
        h.au.append("edc.map", actor=h.actor(sess), detail={"studies": len(linkmap.load(folder())["studies"])})
        return linkmap.load(folder())

    @app.post("/api/edc/tools")
    async def propose(request: Request) -> JSONResponse:
        sess = admin(request, closed_in_session=True)
        if not h.csrf_ok(sess, request.headers.get("x-csrf") or ""):  # D-1045: a tool call is a change
            raise h.problem(400, "csrf")
        try:
            body = json.loads(await request.body() or b"{}")
        except ValueError:
            return JSONResponse({"error": "not JSON"}, status_code=400)
        tool = str(body.get("tool") or "")
        project_id = str(body.get("project_id") or "")
        record_id = str(body.get("record_id") or "")
        if tool in tools.WRITE_TOOLS:
            try:
                proposal = proposals.hold(sess.user.username, tool, project_id, record_id)
            except door.NoStorage:
                return no_storage()
            return JSONResponse({"needs_confirm": True, "proposal_id": proposal, "deidentified": True})
        return JSONResponse(_run_tool(tool, project_id, record_id, confirm=False))

    @app.post("/api/edc/tools/{proposal_id}/confirm")
    async def confirm(request: Request, proposal_id: str) -> JSONResponse:
        sess = admin(request, closed_in_session=True)
        csrf = request.headers.get("x-csrf") or ""
        if not csrf and (request.headers.get("content-type") or "").startswith("application/x-www-form-urlencoded"):
            form = await request.form()
            csrf = str(form.get("csrf") or "")
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        try:
            row = proposals.take(sess.user.username, proposal_id)
        except tools.ToolError as exc:
            return JSONResponse({"error": exc.message}, status_code=404)
        except door.NoStorage:
            return no_storage()
        h.au.append(
            "edc.tool_confirm", actor=h.actor(sess), detail={"tool": row["tool"], "project_id": row["project_id"]}
        )
        return JSONResponse(_run_tool(row["tool"], row["project_id"], row["record_id"], confirm=True))

    def _run_tool(tool: str, project_id: str, record_id: str, *, confirm: bool) -> dict[str, Any]:
        base = tools.tool_base()
        token = tools.tool_token()
        if not base or not token:
            return {"allow": False, "deidentified": True, "reason": "the tool client is not configured"}
        client = tools.ToolClient(base, token, tools.http_client())
        try:
            return client.call(tool, project_id, record_id=record_id, confirm=confirm)
        except tools.ToolError as exc:
            return {"allow": False, "deidentified": True, "reason": exc.message}
        finally:
            client.http.close()

    @app.get("/admin/edc")
    def page(request: Request) -> Response:
        sess = admin(request)
        try:
            pending = proposals.ids()
        except door.NoStorage:
            return no_storage()
        return h.page(request, "edc_link.html", sess, saved=linkmap.load(folder()), pending=pending,
                      conn=connection())  # fmt: skip

    def connection() -> dict[str, Any]:
        """D-1046: the EDC connection's state for the page; one capabilities read, closed at once."""
        base, token = tools.tool_base(), tools.tool_token()
        http = tools.http_client()
        try:
            return tools.connection_status(base, token, http)
        finally:
            http.close()

    @app.get("/api/edc/oidc/.well-known/openid-configuration")
    def well_known() -> JSONResponse:
        if not oidc.enabled():
            return JSONResponse({"error": "oidc is off"}, status_code=404)
        return JSONResponse(oidc.discovery())

    @app.get("/api/edc/oidc/authorize")
    def authorize(request: Request) -> Response:
        if not oidc.enabled():
            return JSONResponse({"error": "oidc is off"}, status_code=404)
        sess = h.need(request)
        # 10K-15 (D-1364): no EDC sign-in starts during a support session, whatever the role (the EDC's pages hold
        # patient records); refused before the request's parameters are read
        if in_support_session():
            h.au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        if request.query_params.get("client_id") != oidc.client_id():
            raise h.problem(400, "bad")
        try:
            door.default_store()
        except door.NoStorage:
            return no_storage()
        try:
            target = oidc.authorize_redirect(
                sess.user.username,
                request.query_params.get("redirect_uri") or "",
                request.query_params.get("state") or "",
            )
        except ValueError as exc:
            raise h.problem(400, "bad") from exc
        return RedirectResponse(target, status_code=302)

    @app.post("/api/edc/oidc/token")
    async def token(request: Request) -> JSONResponse:
        if not oidc.enabled():
            return JSONResponse({"error": "oidc is off"}, status_code=404)
        form = await request.form()
        if (
            not oidc.secret_ok(str(form.get("client_secret") or ""))
            or str(form.get("client_id") or "") != oidc.client_id()
        ):
            return JSONResponse({"error": "invalid_client"}, status_code=401)
        # D-1045: the redirect and the client the code was issued for are required, and must be the code's own
        try:
            username = oidc.redeem(str(form.get("code") or ""), str(form.get("client_id") or ""),
                                   str(form.get("redirect_uri") or ""))  # fmt: skip
        except door.NoStorage:
            return no_storage()
        if username is None:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        issued = oidc.sign_id_token(username)
        return JSONResponse({"access_token": issued, "id_token": issued, "token_type": "Bearer"})

    @app.get("/api/edc/oidc/userinfo")
    def userinfo(request: Request) -> JSONResponse:
        if not oidc.enabled():
            return JSONResponse({"error": "oidc is off"}, status_code=404)
        header = request.headers.get("authorization") or ""
        raw = header[7:] if header.lower().startswith("bearer ") else ""
        sub = oidc.subject_of(raw)
        if not sub:
            return JSONResponse({"error": "invalid_token"}, status_code=401)
        return JSONResponse({"sub": sub})
