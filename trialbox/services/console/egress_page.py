"""M3: the console's door of the egress edge, and the page "What left this box" (``/admin/egress``).

Every answer of the console that is a file passes :class:`EgressLayer`: a listed download (``egress_edge.DOWNLOADS``)
goes through ``egress_edge.leave`` by its route's rule; an attachment no rule lists is refused. The layer is the
innermost of the console's middleware (as ``console.phone``'s), so a refusal carries the console's headers. A job's
file is an aggregate (masked) or a patient file (an exception: to its named recipients' own mailbox, D-369). The
study's log with every chart number is an exception to the person the reveal right let through (D-438).
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from datetime import timedelta
from email.message import Message as Headers
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from tb_common import egress_edge, egress_record

from console import audit_page
from console.home import Helpers
from console.i18n import CATALOGUES
from console.rc1_guard import Rc1Guard, _path

DAYS = 30
PATHSEND = "http.response.pathsend"
_JOB = re.compile(r"^/pilot/jobs/(?P<job>[^/]+)/files/(?P<name>[^/]+)$")
#: a JSON answer that carries a file's text
_SUFFIX = {"application/json": ".json", "text/csv": ".csv", "application/xml": ".xml", "text/html": ".html"}


def filename_of(disposition: str) -> str:
    m = Headers()
    m["content-disposition"] = disposition
    return m.get_filename() or ""


def _word(sess: Any, key: str, other: str) -> str:
    """The catalogue's word for a code of the record, the code itself when there is none."""
    lang = sess.lang if sess is not None and sess.lang in CATALOGUES else "en"
    return CATALOGUES[lang].get(key, other)


class Door:
    """What the layer needs of the console: the session, the job and the audit log."""

    def __init__(self, h: Helpers) -> None:
        self.h = h
        self.session = Rc1Guard(h, "").session

    def leave(self, request: Request, path: str, name: str, data: bytes) -> egress_edge.File:
        listed, route = egress_edge.download_route(path)
        sess = self.session(request)
        who = self.h.actor(sess) if sess is not None else ""
        where, refused = "download", ""
        named: tuple[str, ...] = ()
        if listed and route is None:
            m = _JOB.match(path)
            job = self.h.bk.get_job(m["job"]) if m else None
            out = next((o for o in (job.outputs or []) if m and o.filename == m["name"]), None) if job else None
            if out is not None and out.tag == "aggregate":
                route = "download.aggregate"
            elif out is not None:  # a patient file: to the mailbox of a named recipient who may read patient data
                route = "patient.download"
                box = (sess.user.mailbox or "").strip().lower() if sess is not None else ""
                if box and box in {r.strip().lower() for r in out.recipients}:
                    named = (where,)
                    user, study = sess.user, getattr(job, "ruleset", None) or ""
                    ok = user.can_view_phi and user.sees_study(study) and self.h.delegated_ok(user, study)
                    refused = egress_edge.may_have(bool(ok), True)
        elif route == "download.registry" and sess is not None:  # the route has asked the reveal right and the role
            named = (where,)
        got: egress_edge.File = egress_edge.leave(
            route or "download.unlisted",
            where,
            egress_edge.File(name, data),
            audit=self.h.au,
            actor=who,
            named=named,
            refused=refused,
            items=egress_edge.chart_numbers(data) if route == "download.registry" else None,
        )
        return got

    def refusal(self, request: Request, path: str, reason: str) -> Response:
        sess = self.session(request)
        if path.startswith("/api/"):
            return JSONResponse({"error": "egress.refused", "detail": {"reason": reason}}, status_code=409)
        why = _word(sess, f"egress.reason.{reason}", reason)
        return self.h.page(request, "problem.html", sess, status=409, key="egress.refused", values={"why": why})


class EgressLayer:
    """A plain ASGI layer: an answer that is a file is held until it is whole, then sent as the edge leaves it."""

    def __init__(self, app: ASGIApp, door: Door) -> None:
        self.app, self.door = app, door

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = _path(scope)
        listed = egress_edge.download_route(path)[0]
        start: Message | None = None
        body: list[bytes] = []

        async def held(message: Message) -> None:
            nonlocal start
            if message["type"] == "http.response.start":
                head = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in message["headers"]}
                attached = head.get("content-disposition", "").lower().startswith("attachment")
                if message["status"] == 200 and (attached or listed) and scope["method"] != "HEAD":
                    start = message
                    return
            if start is None:
                await send(message)
                return
            # ponytail: a download is held in memory whole, as openpyxl and the zips already are; MAX_BYTES bounds it
            body.append(message.get("body", b""))
            if message.get("more_body"):
                return
            await self.release(scope, receive, send, path, start, b"".join(body))

        # no file path may be handed to the server: the bytes must pass here. The scope itself is passed on (a copy
        # would keep the matched route from the middleware outside this one, whose timing header reads it)
        scope["extensions"] = {k: v for k, v in (scope.get("extensions") or {}).items() if k != PATHSEND}
        await self.app(scope, receive, held)

    async def release(self, scope: Scope, receive: Receive, send: Send, path: str, start: Message, data: bytes) -> None:
        request = Request(scope, receive)
        headers = [(k, v) for k, v in start["headers"] if k.lower() != b"content-length"]
        head = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in headers}
        disposition = head.get("content-disposition", "")
        media = head.get("content-type", "").partition(";")[0].strip().lower()
        name = filename_of(disposition) or "answer" + _SUFFIX.get(media, "")
        try:
            got = await run_in_threadpool(self.door.leave, request, path, name, data)
        except egress_edge.Refused as exc:
            resp = await run_in_threadpool(self.door.refusal, request, path, exc.reason)
            await resp(scope, receive, send)
            return
        if disposition and got.name != name:
            headers = [(k, v) for k, v in headers if k.lower() != b"content-disposition"]
            headers.append((b"content-disposition", f"attachment; filename*=UTF-8''{quote(got.name)}".encode()))
        headers.append((b"content-length", str(len(got.data)).encode()))
        await send({**start, "headers": headers})
        await send({"type": "http.response.body", "body": got.data})


def events(h: Helpers, days: int = DAYS) -> Iterator[dict[str, Any]]:
    """The egress lines of the last ``days`` days, from the audit chain."""
    since = (h.today() - timedelta(days=days - 1)).isoformat()
    f = audit_page.Filter(event=egress_record.EVENT, since=since)
    for r in audit_page.iter_events(h.au.directory, f):
        yield {"ts": r.ts, "event": r.event, "detail": r.detail}


def register(app: FastAPI, h: Helpers, _env: Mapping[str, str] | None = None) -> None:
    app.user_middleware.append(Middleware(EgressLayer, door=Door(h)))  # appended: inside the headers middleware

    @app.get("/admin/egress")
    def left_this_box(request: Request) -> Response:
        sess = h.need(request)
        if not sess.user.is_admin:
            h.au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        rows = egress_record.by_day(events(h))
        for r in rows:
            got = "refusal" if r["result"] == "refused" else str(r["result"])
            r["result_text"] = _word(sess, f"egress.{got}", got)
            r["reason_text"] = _word(sess, f"egress.reason.{r['reason']}", str(r["reason"]))
        return h.page(request, "egress.html", sess, rows=rows, days=DAYS, checks=egress_edge.doctor_checks())
