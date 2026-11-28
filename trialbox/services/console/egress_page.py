"""M3: the console's door of the egress edge, and the page "What left this box" (``/admin/egress``).

Every answer of the console that is a file passes :class:`EgressLayer`: a listed download (``egress_edge.DOWNLOADS``)
goes through ``egress_edge.leave`` by its route's rule; an attachment no rule lists is refused. The layer is the
innermost of the console's middleware (as ``console.phone``'s), so a refusal carries the console's headers. A job's
file is an aggregate (masked) or a patient file (an exception: to its named recipients' own mailbox, D-369). The
study's log with every chart number is an exception to the person the reveal right let through (D-438).
"""

from __future__ import annotations

import json
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
from tb_common.authz import permit

from console import audit_page
from console.home import Helpers
from console.i18n import CATALOGUES
from console.rc1_guard import Rc1Guard, _path

DAYS = 30
PACKS = 1000  # the newest feasibility packs the published page lists
PATHSEND = "http.response.pathsend"
#: a handler that serves a file the box recorded when it built it names the record's sha256 here (1523 ruling); the
#: layer takes it off the answer and hands it to the edge
MADE_HEADER = b"x-tb-made-sha256"
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
        made: tuple[str, ...] = getattr(request.state, "tb_made", ())  # the handler's record (MADE_HEADER)
        sess = self.session(request)
        who = self.h.actor(sess) if sess is not None else ""
        where, refused = "download", ""
        named: tuple[str, ...] = ()
        if listed and route is None:
            m = _JOB.match(path)
            job = self.h.bk.get_job(m["job"]) if m else None
            out = next((o for o in (job.outputs or []) if m and o.filename == m["name"]), None) if job else None
            made = (
                (*made, str(out.sha256)) if out is not None and getattr(out, "sha256", None) else made
            )  # the job's record of the file it built
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
            made=made,
            rebuild=request.query_params.get("rebuild") == "1",  # a plain PDF of its text, asked for by name
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
                if message["status"] in (200, 206) and (attached or listed) and scope["method"] != "HEAD":
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
        if listed:  # a listed download is always whole: a range would answer 206 with the file's own bytes (OCR 1523-5)
            scope["headers"] = [(k, v) for k, v in scope.get("headers", []) if k.lower() not in (b"range", b"if-range")]
        scope["extensions"] = {k: v for k, v in (scope.get("extensions") or {}).items() if k != PATHSEND}
        await self.app(scope, receive, held)

    async def release(self, scope: Scope, receive: Receive, send: Send, path: str, start: Message, data: bytes) -> None:
        request = Request(scope, receive)
        made = tuple(v.decode("latin-1") for k, v in start["headers"] if k.lower() == MADE_HEADER)
        headers = [(k, v) for k, v in start["headers"] if k.lower() not in (b"content-length", MADE_HEADER)]
        head = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in headers}
        disposition = head.get("content-disposition", "")
        media = head.get("content-type", "").partition(";")[0].strip().lower()
        name = filename_of(disposition) or "answer" + _SUFFIX.get(media, "")
        try:
            request.state.tb_made = made
            got = await run_in_threadpool(self.door.leave, request, path, name, data)
        except egress_edge.Refused as exc:
            resp = await run_in_threadpool(self.door.refusal, request, path, exc.reason)
            await resp(scope, receive, send)
            return
        if disposition and got.name != name:
            headers = [(k, v) for k, v in headers if k.lower() != b"content-disposition"]
            headers.append((b"content-disposition", f"attachment; filename*=UTF-8''{quote(got.name)}".encode()))
        if got.name.lower().endswith(".pdf") and not name.lower().endswith(".pdf"):  # rebuilt: a plain PDF
            headers = [(k, v) for k, v in headers if k.lower() != b"content-type"]
            headers.append((b"content-type", b"application/pdf"))
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

    @app.get("/audit/published")
    def published(request: Request) -> Response:
        """Lane K (H3-PROD §2 row 7): what was published, for the steward. Every trial-opportunity feed the box
        built in the last year (period, studies published, its rounding threshold), every feasibility pack on the box
        (study, version, snapshot, the small-cell threshold of its counts), and the departure record by day and
        route. Counts only. The roles of ``audit.provenance`` (steward, privacy office, administrator)."""
        sess = h.need(request)
        if not permit(sess.user.role, audit_page.PROVENANCE):
            h.au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        since = (h.today() - timedelta(days=365)).isoformat()
        feeds = [
            {"day": r.ts[:10], **r.detail}
            for r in audit_page.iter_events(
                h.au.directory, audit_page.Filter(event="opportunity.feed", since=since), shown=False
            )
        ]
        packs = []
        # the orchestrator filters by type and state, so an old pack behind many newer jobs is still found; past
        # PACKS the page says it shows the newest PACKS only (ponytail: no paging; add it if a site ever gets there)
        done = h.bk.list_jobs(limit=PACKS, state="done", type_="FEAS")
        for job in done:
            prof = next((o for o in job.outputs or [] if o.filename.startswith("feasprofile_")), None)
            try:
                got = json.loads(h.bk.get_object(prof.minio_key)) if prof else {}
            except (KeyError, ValueError, OSError):
                got = {}  # unread: the page says so, never a default
            got = got if isinstance(got, dict) else {}
            packs.append({"job": job, "small_cell": got.get("small_cell"), "snapshot": got.get("snapshot")})
        rows = egress_record.by_day(events(h))
        for r in rows:
            got = "refusal" if r["result"] == "refused" else str(r["result"])
            r["result_text"] = _word(sess, f"egress.{got}", got)
        return h.page(
            request, "published.html", sess, feeds=feeds, packs=packs, rows=rows, days=DAYS,
            capped=len(done) >= PACKS, cap=PACKS,
        )  # fmt: skip
