"""PoC demonstration mode (T-502, D-328; REG-014, OPS-004, PLAN-019, REG-015): the hosted demo takes no real data.

The mode is the audited feature flag ``demo.mode`` (``tb_common.flags``: seeded once from ``TB_DEMO_MODE``, changed on
``/ops/flags`` with a reason, every change a ``flag.set`` audit event). It is read per request through the flag cache,
so a change reaches the console within five seconds. With the flag ``on``:

* **Uploads and pasted chart text are refused**, with a page in the reader's language (403, ``demo.refused``): every
  ``multipart/form-data`` post (every upload form of the console is one) and every route in :data:`GUARDED` (the chart
  paste box, the chart, case, protocol, consent and mail uploads and their JSON twins), before the body is read. Each
  refusal is an audit event ``demo.refused`` with the account and the path, never the content. The upload routes also
  call :func:`guard` themselves, so a route stays closed if it is ever reached another way.
* **A banner on every page** (``templates/_demo_banner.html``, included by ``base.html``): synthetic data only, not
  for clinical use, not a medical device, do not enter patient information; and a footer line saying the same.
* **The acknowledgement** of ``docs/plan/27-poc-plan.md`` §9.3 at the first sign-in: a signed-in account reaches no
  other page (and no ``/api/v1`` call) until it has ticked the five statements on ``/demo/ack``. Accepting writes one
  audit event ``demo.ack`` with the account, the role, the language, the statement's version and the two optional
  answers; a second visit writes nothing. The sign-in, the second factor, the password change, the language and
  sign-out stay open, so the first sign-in runs as 27-poc-plan task A0 says.

**The scan of stored input** (27-poc-plan §10, RSK-55): ``python -m console.demo_guard scan --db PATH ...`` runs the
data-handling scan (``tools/data_scan``, its patterns and allowlist) over the given folders (the console's and the
box's data) and over every text column of the trial database (``TB_DB_URL``, all its schemas). A hit names the place
and the pattern and shows the value masked, as the repository scan does. ``--write-baseline FILE`` after seeding the
demo records what the synthetic seed itself holds; ``--baseline FILE`` after a session reports only what is new.
Exit 0 clean, 2 on a hit. The columns of :data:`MUST_SCAN` (the free-text fields testers type into, such as the
feedback comment of T-510) must be among those read: when one is missing the scan says so and exits 1. So does
it when the database holds a store its role may not read (D-711): it names them; the box's admin role reads all.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import threading
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from tb_common.flags import Flags

from console import i18n_demo
from console.home import Helpers
from console.i18n import CATALOGUES

log = logging.getLogger("console.demo")

for _lang, _cat in (("en", i18n_demo.EN), ("ja", i18n_demo.JA), ("zh-TW", i18n_demo.ZH)):
    CATALOGUES[_lang].update(_cat)

FLAG = "demo.mode"
ACK_EVENT = "demo.ack"
REFUSED_EVENT = "demo.refused"
REFUSED = "demo.refused"  # the problem key: the refusal page in the reader's language
ACK_NEED = "demo.ack.need"
#: the version of the data-handling statement the acknowledgement refers to (27-poc-plan §9.2)
STATEMENT_VERSION = "PoC data-handling statement v1, 2026-11-10"
REQUIRED = ("i1", "i2", "i3", "i4", "i5")
OPTIONAL = ("o1", "o2")

#: routes that take a file or pasted chart text: refused whatever their encoding (a multipart post is refused anyway)
GUARDED: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        r"^/pilot/(?:protocol|consent|case|mailbox)$",  # protocol, consent form, chart files (CASE), test mail
        r"^(?:/api/v1)?/site/charts$",  # the chart paste box and chart upload of the site set-up, and its API
        r"^(?:/api/v1)?/studies/[^/]+/forms/dictionary$",  # a data dictionary file, and its API (CSV text)
        r"^/api/v1/studies/[^/]+/edc/import/odm$",  # an ODM file's JSON twin (T-302c; the page is multipart)
    )
)

#: what a signed-in account may open before it has accepted the acknowledgement
ACK_OPEN = frozenset({"/demo/ack", "/login", "/login/totp", "/logout", "/lang", "/account", "/account/password",
                      "/healthz", "/api/v1/session"})  # fmt: skip
ACK_OPEN_PREFIX = ("/static/", "/auth/oidc/")

#: free-text columns of the trial database (``schema.table.column``, without ``tb_prefix``) the ``--db`` scan must read:
#: the scan fails (exit 1) when one is missing, so a renamed field cannot drop out of it unnoticed
MUST_SCAN = ("feedback.entry.comment",)  # T-510 (D-331): the comment of the feedback control on every page


def flag_on() -> bool:
    """The flag says ``on``. Off when it is unset, unreadable or there is no flag store (never raises)."""
    return Flags().get(FLAG, "off") == "on"


def guarded(method: str, path: str, content_type: str) -> bool:
    """A request demo mode refuses: a post with a file part or to a chart paste or upload route."""
    if method.upper() not in ("POST", "PUT", "PATCH"):
        return False
    return content_type.lower().startswith("multipart/form-data") or any(p.match(path) for p in GUARDED)


def guard(request: Request, problem: Callable[..., Exception]) -> None:
    """The guard call of an upload or paste route: with demo mode on, audit the refusal and raise
    ``problem(403, "demo.refused")`` (the console's refusal page, or JSON on ``/api/``)."""
    g = getattr(request.app.state, "demo_guard", None)
    if not (g.on() if g is not None else flag_on()):
        return
    if g is not None:
        g.audit_refused(request, g.session(request))
    raise problem(403, REFUSED)


class DemoGuard:
    """The guard of one console app: the flag, the acknowledgement store (the audit chain) and the refusals."""

    def __init__(self, h: Helpers, read_flag: Callable[[], bool] = flag_on) -> None:
        self.h = h
        self.read_flag = read_flag
        self._acked: set[str] = set()  # accounts seen with a demo.ack: an acknowledgement is never taken back
        self._lock = threading.Lock()

    def on(self) -> bool:
        return self.read_flag()

    # ------------------------------------------------------------------ who asks
    def session(self, request: Request) -> Any:
        """The live session of the request (a page's cookie, or a bearer token on ``/api/``), None without one.
        Reads only: the request is not counted as activity."""
        from console.app import COOKIE  # console.app imports this module

        try:
            if request.url.path.startswith("/api/"):
                auth = request.headers.get("authorization") or ""
                token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
                return self.h.users.session(token, touch=False, api=True) if token else None
            return self.h.users.session(request.cookies.get(COOKIE), touch=False)
        except Exception as e:  # the store is down: the page itself will say so
            log.warning("demo guard: session not read (%s)", type(e).__name__)
            return None

    # ------------------------------------------------------------------ the acknowledgement
    def _events(self) -> Iterator[dict[str, Any]]:
        directory = Path(getattr(self.h.au, "directory", "") or "")
        if not directory.is_dir():
            return
        for f in sorted(directory.glob("*.jsonl")):
            with f.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if f'"{ACK_EVENT}"' not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if rec.get("event") == ACK_EVENT:
                        yield rec

    def acked(self, username: str) -> bool:
        """The account has a ``demo.ack`` event in the audit chain (the one store of the acknowledgement)."""
        if username in self._acked:
            return True
        actor = f"console:{username}"
        if any(rec.get("actor") == actor for rec in self._events()):
            self._acked.add(username)
            return True
        return False

    def record_ack(self, sess: Any, lang: str, optional: dict[str, bool]) -> bool:
        """Write the account's one ``demo.ack`` event; False (nothing written) when it already has one."""
        u = sess.user
        with self._lock:
            if self.acked(u.username):
                return False
            detail = {"role": u.role, "lang": lang, "version": STATEMENT_VERSION, "accepted": list(REQUIRED),
                      "recording": optional.get("o1", False), "quote": optional.get("o2", False)}  # fmt: skip
            self.h.au.append(ACK_EVENT, actor=f"console:{u.username}", detail=detail)
            self._acked.add(u.username)
        return True

    # ------------------------------------------------------------------ refusals
    def audit_refused(self, request: Request, sess: Any) -> None:
        who = f"console:{sess.user.username}" if sess is not None else "console:-"
        try:  # the path only: never the content
            detail = {"path": request.url.path[:120], "method": request.method}
            self.h.au.append(REFUSED_EVENT, actor=who, detail=detail)
        except Exception:
            log.exception("demo guard: the refusal of %s was not audited", request.url.path[:120])

    def refusal(self, request: Request, sess: Any) -> Response:
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": REFUSED, "detail": {}}, status_code=403)
        return self.h.page(request, "problem.html", sess, status=403, key=REFUSED, values={})

    # ------------------------------------------------------------------ every request
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if not self.on():
            return await call_next(request)
        request.state.demo_on = True  # the banner (templates/_demo_banner.html)
        path = request.url.path
        if guarded(request.method, path, request.headers.get("content-type") or ""):
            sess = self.session(request)
            self.audit_refused(request, sess)
            return self.refusal(request, sess)  # before the body is read: nothing is parsed, nothing stored
        if path in ACK_OPEN or path.startswith(ACK_OPEN_PREFIX):
            return await call_next(request)
        sess = self.session(request)
        if sess is not None and not self.acked(sess.user.username):
            if path.startswith("/api/"):
                return JSONResponse({"error": ACK_NEED, "detail": {}}, status_code=403)
            back = path if request.method == "GET" else "/"
            return RedirectResponse(f"/demo/ack?back={quote(back, safe='/')}", status_code=303)
        return await call_next(request)


def _back(value: str) -> str:
    """A local path to return to after the acknowledgement; anything else is the home page."""
    v = value or "/"
    return v if v.startswith("/") and not v.startswith("//") and "\\" not in v and v != "/demo/ack" else "/"


def register(app: FastAPI, h: Helpers, read_flag: Callable[[], bool] = flag_on) -> DemoGuard:
    """Install the guard on the console app: the middleware (innermost, so the console's security headers wrap its
    answers too) and the acknowledgement page."""
    g = DemoGuard(h, read_flag)
    app.state.demo_guard = g
    # appended, not inserted at the front as app.middleware() does: inside the headers middleware of console.app
    app.user_middleware.append(Middleware(BaseHTTPMiddleware, dispatch=g.dispatch))

    def signed_in(request: Request) -> Any:
        """The account on the page. Not ``h.need`` alone: its role scope (a CRO account opens the reports only)
        would shut that account out of the one page it must accept first."""
        if not g.on():
            raise h.problem(404, "notfound")
        sess = g.session(request)
        if sess is None or h.users.must_change(sess.user.username):
            return h.need(request)  # the sign-in page, or D-279's password page first
        return sess

    @app.get("/demo/ack", response_class=HTMLResponse)
    def ack_page(request: Request, back: str = "/") -> Response:
        sess = signed_in(request)
        if g.acked(sess.user.username):
            return RedirectResponse(_back(back), status_code=303)
        return h.page(request, "demo_ack.html", sess, back=_back(back), version=STATEMENT_VERSION,
                      required=REQUIRED, optional=OPTIONAL, ticked=set(), missing=False)  # fmt: skip

    @app.post("/demo/ack")
    async def ack_post(request: Request, csrf: str = Form(""), back: str = Form("/")) -> Response:
        sess = signed_in(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        form = await request.form()
        ticked = {k for k in (*REQUIRED, *OPTIONAL) if form.get(k) == "yes"}
        if not set(REQUIRED) <= ticked:
            return h.page(request, "demo_ack.html", sess, status=400, back=_back(back), version=STATEMENT_VERSION,
                          required=REQUIRED, optional=OPTIONAL, ticked=ticked, missing=True)  # fmt: skip
        g.record_ack(sess, sess.lang, {k: k in ticked for k in OPTIONAL})
        return RedirectResponse(_back(back), status_code=303)

    return g


# ---------------------------------------------------------------------------------------------- the scan
def _db_texts(url: str, seen: set[str] | None = None, unread: set[str] | None = None) -> Iterator[tuple[str, str]]:
    """``(place, text)`` for every non-empty text, varchar and JSON value in every schema of the database that this
    database role may read. ``seen`` collects every column read, as ``schema.table.column`` without the
    ``tb_prefix``.

    NEW-FR-2 (D-711): ``unread`` collects the stores (schemas, without the prefix) that hold a table this role may
    not read. ``information_schema`` lists only what the role has a right on, so on a box with service roles a
    scan as the console's role read the console's own stores and passed over the rest without a word."""
    import psycopg
    from tb_common.db import split_url

    dsn, prefix = split_url(url)
    with psycopg.connect(dsn, autocommit=True, connect_timeout=10) as con:
        if unread is not None:  # the catalogue itself is readable by every role
            rows = con.execute(
                "SELECT DISTINCT n.nspname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relkind IN ('r', 'p') AND n.nspname LIKE %s AND n.nspname NOT LIKE 'pg\\_%%' "
                "AND n.nspname <> 'information_schema' AND NOT (has_schema_privilege(n.oid, 'USAGE') "
                "AND has_table_privilege(c.oid, 'SELECT'))",
                (prefix.replace("_", "\\_") + "%",),
            ).fetchall()
            unread.update(str(r[0])[len(prefix) :] for r in rows)
        cols = con.execute(
            "SELECT c.table_schema, c.table_name, c.column_name FROM information_schema.columns c "
            "JOIN information_schema.tables t ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
            "WHERE t.table_type = 'BASE TABLE' AND c.table_schema NOT IN ('pg_catalog', 'information_schema') "
            "AND c.table_schema NOT LIKE 'pg\\_%%' AND c.table_schema LIKE %s "
            "AND c.data_type IN ('text', 'character varying', 'character', 'json', 'jsonb') "
            "ORDER BY 1, 2, 3",
            (prefix.replace("_", "\\_") + "%",),
        ).fetchall()
        for schema, table, column in cols:
            if seen is not None:
                seen.add(f"{schema[len(prefix) :]}.{table}.{column}")
            q = f'SELECT "{column}"::text FROM "{schema}"."{table}" WHERE "{column}" IS NOT NULL'
            try:
                rows = con.execute(q).fetchall()  # the names come from the catalogue
            except psycopg.errors.InsufficientPrivilege:  # listed for another right (INSERT) and not readable
                if unread is None:
                    raise
                unread.add(schema[len(prefix) :])
                continue
            for (value,) in rows:
                if value:
                    yield f"db:{schema}.{table}.{column}", str(value)


def scan_stored(
    paths: list[Path], db_url: str | None = None, seen: set[str] | None = None, unread: set[str] | None = None
) -> list[Any]:
    """The data-handling scan over stored demo input: the files under ``paths`` and, with ``db_url``, every text
    value of the trial database that its role may read. A database value is placed by its column and a short hash
    of the value. ``seen`` collects the database columns read (:data:`MUST_SCAN`); ``unread`` the stores the role
    may not read (D-711)."""
    from tools import data_scan as ds

    patterns, allow = ds.load_patterns(), ds.load_allow()
    files = ds._expand(paths)
    hits = list(ds.run(files, ds.ROOT, patterns, allow, in_repo=False))
    if db_url:
        for place, text in _db_texts(db_url, seen, unread):
            tag = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
            hits += ds.scan_text(text, f"{place}#{tag}", patterns, allow)
    return sorted(set(hits))


def main(argv: list[str] | None = None) -> int:
    import os

    ap = argparse.ArgumentParser(prog="python -m console.demo_guard", description="the scan of stored demo input")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scan", help="scan the demo's stored input (files and the trial database)")
    sc.add_argument("paths", nargs="*", type=Path, help="data folders or files (the console's and the box's)")
    sc.add_argument("--db", action="store_true", help="also every text column of the trial database (TB_DB_URL)")
    sc.add_argument("--baseline", type=Path, help="report only hits not in this file (written after the seed)")
    sc.add_argument("--write-baseline", type=Path, help="write the hits found now to this file and exit 0")
    a = ap.parse_args(argv)
    url = os.environ.get("TB_DB_URL") if a.db else None
    if a.db and not url:
        print("demo_guard scan: --db needs TB_DB_URL", file=sys.stderr)
        return 1
    seen: set[str] = set()
    unread: set[str] = set()
    hits = [str(x) for x in scan_stored(a.paths, url, seen, unread)]
    if unread:  # D-711: never "clean" for stores that were not read
        print(f"demo_guard scan: not read, this database role may not: {', '.join(sorted(unread))}. "
              "Run the scan with the box's admin role (trialbox) in TB_DB_URL.", file=sys.stderr)  # fmt: skip
        return 1
    missing = [c for c in MUST_SCAN if c not in seen] if url else []
    if missing:
        print(f"demo_guard scan: not scanned: {', '.join(missing)} (has the console started on this database?)",
              file=sys.stderr)  # fmt: skip
        return 1
    if a.write_baseline:
        a.write_baseline.write_text("".join(f"{x}\n" for x in hits), encoding="utf-8")
        print(f"demo_guard scan: baseline of {len(hits)} hit(s) written")
        return 0
    if a.baseline:
        known = set(a.baseline.read_text(encoding="utf-8").splitlines())
        hits = [x for x in hits if x not in known]
    for x in hits:
        print(x)
    print(f"demo_guard scan: {'clean' if not hits else f'{len(hits)} new hit(s)'}")
    return 2 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
