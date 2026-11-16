"""The EDC's door into TrialBox (D-916): health, signed events, the study map, tool confirmation, optional OIDC.

These routes are absent from the menu. The demo's pages do not call them. Events are refused until
``TB_EDC_EVENT_SECRET`` is set. OIDC is refused until ``TB_EDC_OIDC`` is 1.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from edc_backend import events, linkmap, oidc, tools
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from console.home import Helpers


def register(app: FastAPI, h: Helpers) -> None:
    proposals = tools.Proposals()

    def folder() -> str:
        return events.event_dir()

    def log() -> events.EventLog:
        path = Path(folder() or tempfile.gettempdir()) / "edc-events.json"
        return events.EventLog(path)

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
        book = log()
        try:
            doc, fresh = events.check(secret, body, header, book)
        except events.EventRejected as exc:
            return JSONResponse({"error": exc.message}, status_code=exc.status)
        if fresh:
            raw_data = doc.get("data")
            data = raw_data if isinstance(raw_data, dict) else {}
            kind = str(doc.get("type") or "")
            study = linkmap.study_for_project(folder(), str(doc.get("project_id") or ""))
            if study and kind in events.REREAD:
                from console.study_setup import read_now

                try:
                    read_now(h, study)
                except Exception:
                    return JSONResponse({"error": "the read did not finish"}, status_code=503)
            events.remember(book, doc)
            h.au.append(
                "edc.event",
                actor="edc",
                detail={
                    "id": str(doc.get("id")),
                    "type": kind,
                    "project_id": str(doc.get("project_id") or ""),
                    "record_id": str(doc.get("record_id") or ""),
                    "instrument": str(data.get("instrument") or ""),
                },
            )
        return JSONResponse({"ok": True, "fresh": fresh})

    def admin(request: Request) -> Any:
        sess = h.need(request)
        if sess.user.role != "admin":
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
        sess = admin(request)
        try:
            body = json.loads(await request.body() or b"{}")
        except ValueError:
            return JSONResponse({"error": "not JSON"}, status_code=400)
        tool = str(body.get("tool") or "")
        project_id = str(body.get("project_id") or "")
        record_id = str(body.get("record_id") or "")
        if tool in tools.WRITE_TOOLS:
            proposal = proposals.hold(sess.user.username, tool, project_id, record_id)
            return JSONResponse({"needs_confirm": True, "proposal_id": proposal, "deidentified": True})
        return JSONResponse(_run_tool(tool, project_id, record_id, confirm=False))

    @app.post("/api/edc/tools/{proposal_id}/confirm")
    async def confirm(request: Request, proposal_id: str) -> JSONResponse:
        sess = admin(request)
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
        h.au.append(
            "edc.tool_confirm", actor=h.actor(sess), detail={"tool": row["tool"], "project_id": row["project_id"]}
        )
        return JSONResponse(_run_tool(row["tool"], row["project_id"], row["record_id"], confirm=True))

    def _run_tool(tool: str, project_id: str, record_id: str, *, confirm: bool) -> dict[str, Any]:
        import httpx

        base = tools.tool_base()
        token = tools.tool_token()
        if not base or not token:
            return {"allow": False, "deidentified": True, "reason": "the tool client is not configured"}
        client = tools.ToolClient(base, token, httpx.Client())
        try:
            return client.call(tool, project_id, record_id=record_id, confirm=confirm)
        except tools.ToolError as exc:
            return {"allow": False, "deidentified": True, "reason": exc.message}
        finally:
            client.http.close()

    @app.get("/admin/edc")
    def page(request: Request) -> Response:
        sess = admin(request)
        return h.page(
            request,
            "edc_link.html",
            sess,
            saved=linkmap.load(folder()),
            pending=proposals.ids(),
        )

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
        if request.query_params.get("client_id") != oidc.client_id():
            raise h.problem(400, "bad")
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
        username = oidc.take_code(str(form.get("code") or ""))
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
