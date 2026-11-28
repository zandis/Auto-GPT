"""M5 (10K-15, SO-15; decision 99, SO-D4): the support session (``/admin/support``).

Decision 99 ruled: no standing remote access. When the hospital wants the supplier's help, its administrator turns
the support session on here. While it is on:

* **every patient page is closed to every role.** The console then serves only what rc1's guard serves on a refused
  box (``console.rc1_guard.ALLOWED``: signing in, health, the operations and admin pages, aggregate counts, static
  files); every other route, and every download, is refused with this page's message and a ``console.denied`` line
  (``refusal: support_session``). The same rules, by the same code: :class:`SupportGuard` is rc1's guard with its
  question changed from "is this box refused" to "is a support session on";
* **it ends by itself** :data:`AUTO_END` after it started, the first time anything asks after that time;
* **start and end are audited**: ``console.support_session`` with ``action`` started or ended, the session's id, who,
  and for an end ``how`` (by hand or auto).

The state is one file in the console's folder (``TB_CONSOLE_DIR``), written to a new file, fsynced and moved into
place, so a reader sees the old state or the new one. A start is written with its event still owed, then the event,
then the state again: a stop between the two leaves the event owed, and the next read sends it. At worst an event is
sent twice (same id), never dropped. The session is closed until the end is written.

Who may turn it on or off: the administrator (``authz.admin_allowed(role, "ops.update_apply")``), with a tick that
says so, by one form (``POST /admin/support``) or its twin (``POST /api/v1/admin/support``); reading the page is
``ops.view``.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import secrets
import threading
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.requests import HTTPConnection
from tb_common.authz import admin_allowed

from console.api_first import before_body
from console.form_errors import FAILED, FieldError, FormErrors
from console.home import Helpers
from console.i18n import CATALOGUES
from console.i18n_support import EN, JA, ZH
from console.rc1_guard import Rc1Guard, Rc1Layer

for _lang, _cat in (("en", EN), ("ja", JA), ("zh-TW", ZH)):
    CATALOGUES[_lang].update(_cat)

log = logging.getLogger("console.support")

PATH = "/admin/support"
EVENT = "console.support_session"
REFUSAL = "support_session"
ACTION = "support.refused"  # what the audit and the log say of a refused request: never its path
AUTO_END = timedelta(hours=2)
STATE = "support-session.json"


def _aware(v: Any) -> datetime | None:
    try:
        d = v if isinstance(v, datetime) else datetime.fromisoformat(str(v))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


class SupportSession:
    """The switch: one state file, the audit, and the clock."""

    def __init__(self, folder: Path, au: Any, clock: Any) -> None:
        self.path = folder / STATE
        self.au = au
        self.clock = clock
        self._lock = threading.Lock()

    def _now(self) -> datetime:
        return _aware(self.clock()) or datetime.now(UTC)

    def _read(self) -> dict[str, Any]:
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            # a state that cannot be read keeps the patient pages closed: a session may be on
            return {"on": True, "id": "unreadable", "started_at": self._now().isoformat(), "owed": False}
        return doc if isinstance(doc, dict) else {}

    def _write(self, doc: Mapping[str, Any]) -> None:
        if self.path.is_symlink():
            raise OSError(f"{self.path} is a link: not written")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        try:
            try:
                os.write(fd, (json.dumps(doc, sort_keys=True) + "\n").encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(tmp, self.path)
        except OSError:
            with contextlib.suppress(OSError):
                tmp.unlink()
            raise
        with contextlib.suppress(OSError):  # the rename itself, kept across a power loss
            dfd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)

    def _said(self, doc: Mapping[str, Any], action: str, actor: str, **more: Any) -> None:
        self.au.append(EVENT, actor=actor, detail={"action": action, "session": doc.get("id"), **more})

    def state(self) -> dict[str, Any]:
        """The state now, with an owed event sent and a session past :data:`AUTO_END` ended (and audited)."""
        with self._lock:
            doc = self._read()
            if doc.get("on") and doc.get("owed"):
                self._said(doc, "started", str(doc.get("by") or "console:-"), until=doc.get("until"))
                doc = {**doc, "owed": False}
                self._write(doc)
            if doc.get("on") and doc.get("id") != "unreadable":
                until = _aware(doc.get("until"))
                if until is None or self._now() >= until:
                    doc = self._end(doc, "console:support-auto-end", "auto")
            return doc

    def on(self) -> bool:
        try:
            return bool(self.state().get("on"))
        except Exception:  # the state cannot be settled: closed, never open unchecked
            log.exception("support session: state not read; patient pages stay closed")
            return True

    def start(self, actor: str) -> dict[str, Any]:
        with self._lock:
            doc = self._read()
            if doc.get("on"):
                return doc
            now = self._now()
            doc = {"on": True, "id": secrets.token_hex(6), "by": actor, "started_at": now.isoformat(),
                   "until": (now + AUTO_END).isoformat(), "owed": True}  # fmt: skip
            self._write(doc)  # closed first: the event is owed until it is sent
            self._said(doc, "started", actor, until=doc["until"])
            doc = {**doc, "owed": False}
            self._write(doc)
            return doc

    def end(self, actor: str) -> dict[str, Any]:
        with self._lock:
            doc = self._read()
            return self._end(doc, actor, "hand") if doc.get("on") else doc

    def _end(self, doc: Mapping[str, Any], actor: str, how: str) -> dict[str, Any]:
        if doc.get("owed"):  # its start was never sent: sent before its end
            self._said(doc, "started", str(doc.get("by") or "console:-"), until=doc.get("until"))
        out = {**doc, "on": False, "owed": False, "ended_at": self._now().isoformat(), "ended_by": actor, "how": how}
        self._said(out, "ended", actor, how=how)  # the event first: the pages stay closed until the end is written
        self._write(out)
        return out


class SupportGuard(Rc1Guard):
    """rc1's guard, asking whether a support session is on instead of whether the box is refused."""

    def __init__(self, h: Helpers, switch: SupportSession) -> None:
        super().__init__(h, "")
        self.switch = switch

    def lists_refused(self) -> bool:
        return self.switch.on()

    def downloads_refused(self) -> bool:
        return self.switch.on()

    def refusal_of(self, method: str, path: str, query: str = "") -> str | None:
        return REFUSAL if super().refusal_of(method, path, query) is not None else None

    def refuse(self, request: HTTPConnection, name: str, path: str) -> Response:
        sess = self.session(request)
        who = f"console:{sess.user.username}" if sess is not None else "console:-"
        try:  # a fixed action name: a path can carry a patient identifier, and the supplier is shown this log
            self.h.au.append("console.denied", actor=who, detail={"refusal": REFUSAL, "action": ACTION})
        except Exception:
            log.exception("support session: a refusal was not audited")
        if request.scope["type"] == "websocket":
            return Response(status_code=403)
        if path.startswith("/api/"):
            return JSONResponse({"error": "support.refused"}, status_code=403)
        return self.h.page(request, "problem.html", sess, status=403, key="support.refused", values={})


class SupportLayer(Rc1Layer):
    """The support session's refusals as a plain ASGI layer, inside rc1's (``console.app`` adds rc1's last)."""


def register(app: FastAPI, h: Helpers, env: Mapping[str, str] | None = None) -> SupportSession:
    folder = Path((env or {}).get("TB_CONSOLE_DIR") or "/data/console")

    def clock() -> datetime:  # read at each call: the console's clock may be replaced after start (tests)
        return h.clock()

    switch = SupportSession(folder, h.au, clock)
    app.state.support_session = switch
    app.add_middleware(SupportLayer, guard=SupportGuard(h, switch))

    def need(request: Request, action: str) -> Any:
        sess = h.need(request)
        if not admin_allowed(sess.user.role, action):
            h.au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        return sess

    def render(request: Request, sess: Any, status: int = 200, fe: FormErrors | None = None) -> Response:
        return h.page(request, "support_page.html", sess, status, st=switch.state(), fe=fe,
                      hours=int(AUTO_END.total_seconds() // 3600),
                      can=admin_allowed(sess.user.role, "ops.update_apply"))  # fmt: skip

    @app.get(PATH)
    def support_page(request: Request) -> Response:
        return render(request, need(request, "ops.view"))

    @app.post(PATH)
    def support_turn(request: Request, csrf: str = Form(""), was: str = Form(""), confirm: str = Form("")) -> Response:
        """One form turns the session on or off: ``was`` is the state the page showed, so a second press of the same
        page does nothing (a page with no ``was`` turns the state it finds). The box asks for a tick first."""
        sess = need(request, "ops.update_apply")
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if confirm != "1":
            fe = FormErrors("support", "sp", (FieldError("confirm", "supportpage.confirm.missing"),))
            return render(request, sess, FAILED, fe=fe)
        try:
            on = bool(switch.state().get("on"))
            if not on and was in ("", "off"):
                switch.start(h.actor(sess))
            elif on and was in ("", "on"):
                switch.end(h.actor(sess))
        except OSError as exc:
            raise h.problem(503, "ops.unavailable") from exc
        return RedirectResponse(PATH, status_code=303)

    def first(sess: Any, request: Request) -> None:
        """The permit check before the body is read (console.api_first)."""
        if not admin_allowed(sess.user.role, "ops.update_apply"):
            h.au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")

    @app.post("/api/v1" + PATH, response_model=None)
    @before_body(first)
    def api_support_turn(request: Request, body: dict[str, str]) -> Any:
        """The form's twin (FIT-019): ``{"turn": "on"}`` or ``{"turn": "off"}``; answers the state. Calling it is the
        administrator's saying so (the form's tick)."""
        assert h.api_session is not None  # set by register() before any request
        sess = h.api_session(request)
        turn = str(body.get("turn") or "").strip().lower()
        try:
            if turn in ("on", "off"):
                st = switch.start(h.actor(sess)) if turn == "on" else switch.end(h.actor(sess))
            else:  # clinical tolerance: the state stays as it is, and the answer says so
                log.warning("support session: an unrecognised turn was ignored")
                st = switch.state()
        except OSError as exc:
            raise h.problem(503, "ops.unavailable") from exc
        out = {"on": bool(st.get("on")), "session": st.get("id"), "until": st.get("until") if st.get("on") else None}
        return out if turn in ("on", "off") else {**out, "warning": "turn"}

    return switch
