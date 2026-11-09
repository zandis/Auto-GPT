"""The administrator's operations screens (D-178; review J-09, master plan WS-08.5 / WS-14.7).

``/admin/ops`` shows, on six tabs: the version (TrialBox and the bundle last applied), **backups** (every target's
files, the newest backup's age, red after 36 hours, the last check), **update and rollback** (the bundles staged on
the box, the history of each update, ended applied or rolled back, the rollback points kept), **logs** (the days
collected), **secrets** (names, present or not, age; never a value) and the **network sheet** (en, ja, zh-TW, to
download). Its actions: back up now, check the newest backups, verify a staged bundle, apply it, collect the logs,
write the network sheet again. Each asks first, in a sentence that names its consequence, and each is an audit event
(``console.ops``).

The console never runs an operation itself: it writes a request into the operations folder (``TB_OPS_DIR``,
``/data/ops`` in the container) and the host's runner (``python3 -m tools.trialbox ops run``, every minute) runs the
command the runbook names and writes the result and the status back (``tools/trialbox/ops.py``). With
``TB_OPS_RUNNER=inline`` (the in-process box, the demo, the tests) the same runner runs at once in this process.

Who may: :func:`tb_common.authz.admin_allowed` (the administrator only); everyone else gets 403 on every page, action
and ``/api/v1/admin/ops``, audited as ``console.denied``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from tb_common.authz import admin_allowed

from console.auth import Session
from console.home import Helpers
from console.i18n import translate

ROOT = Path(__file__).resolve().parents[2]
TABS = ("overview", "backups", "update", "logs", "secrets", "network")
# action -> (authz action, the tab it belongs to)
ACTIONS: dict[str, tuple[str, str]] = {
    "backup": ("ops.backup", "backups"),
    "backup_check": ("ops.backup_check", "backups"),
    "update_check": ("ops.update_check", "update"),
    "update_apply": ("ops.update_apply", "update"),
    "logs_collect": ("ops.logs", "logs"),
    "network_sheet": ("ops.network", "network"),
}
SECRET_KEYS = ("name", "present", "age_days", "registered")  # what a secrets row may show; never a value
_SHEET = re.compile(r"^network-sheet\.(en|ja|zh-TW)\.(html|md)$")
_BUNDLE = re.compile(r"^[A-Za-z0-9][\w.\-]{0,120}\.tar$")
_REQ = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{6}$")


def _hours_since(iso: str, now: datetime) -> float | None:
    try:
        t = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return round((now - t).total_seconds() / 3600, 1)


def register(app: FastAPI, h: Helpers, env: Mapping[str, str]) -> None:
    from tools.trialbox import ops as tb_ops

    au = h.au
    ops = tb_ops.OpsDir(Path(env.get("TB_OPS_DIR") or "/data/ops"))
    inline = (env.get("TB_OPS_RUNNER") or "host").strip().lower() == "inline"
    deploy = Path(env.get("TB_OPS_DEPLOY") or ROOT / "deploy")
    runner = tb_ops.OpsRunner(tb_ops.Box.local(deploy, env), ops) if inline else None

    def need_ops(request: Request, action: str = "ops.view") -> Session:
        sess = h.need(request)
        if not admin_allowed(sess.user.role, action):
            au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        return sess

    def status() -> dict[str, Any]:
        st = ops.status()
        if st is None and runner is not None:
            st = runner.write_status()
        return st or {}

    def summary() -> dict[str, Any]:
        """The health tab's Operations tile and the overview: version, last backup and its age, the agent."""
        st = status()
        now = h.clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        newest = str((st.get("backups") or {}).get("newest") or "")
        age = _hours_since(newest, now) if newest else None
        seen = _hours_since(str(st.get("at") or ""), now) if st else None
        check = ops.last("backup_check")
        from tb_common import __version__

        return {
            "console_version": __version__,
            "version": st.get("version") or {},
            "box": st.get("box") or "",
            "newest_backup": newest,
            "backup_age_h": age,
            "backup_red": age is None or age > tb_ops.STALE_HOURS,
            "backup_key": bool((st.get("backups") or {}).get("key")),
            "last_check": check,
            "agent_seen_h": seen,
            "agent_late": not inline and (seen is None or seen > 0.25),
            "inline": inline,
        }

    h.ops_summary = summary  # the health tab's tile (console.step4)

    @app.get("/admin/ops")
    def ops_page(request: Request, tab: str = "overview", req: str = "") -> Response:
        sess = need_ops(request)
        tab = tab if tab in TABS else "overview"
        st = status()
        mine = None
        if _REQ.match(req):
            mine = next((r for r in ops.history(200) if r.get("id") == req), None)
        secrets_rows = [{k: r.get(k) for k in SECRET_KEYS} for r in st.get("secrets") or []]
        sheets = sorted(p.name for p in ops.network.glob("network-sheet.*") if _SHEET.match(p.name))
        return h.page(
            request,
            "admin_ops.html",
            sess,
            tab=tab,
            tabs=TABS,
            st=st,
            sm=summary(),
            history=ops.history(30),
            pending=[r.get("action") for r in ops.pending()],
            mine=mine,
            secrets_rows=secrets_rows,
            sheets=sheets,
            allowed={a: admin_allowed(sess.user.role, z) for a, (z, _) in ACTIONS.items()},
        )

    @app.post("/admin/ops/{action}")
    def ops_action(
        request: Request,
        action: str,
        csrf: str = Form(""),
        confirm: str = Form(""),
        bundle: str = Form(""),
    ) -> Response:
        if action not in ACTIONS:
            raise h.problem(404, "notfound")
        perm, tab = ACTIONS[action]
        sess = need_ops(request, perm)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        args: dict[str, str] = {}
        if action in ("update_check", "update_apply"):
            if not _BUNDLE.match(bundle):
                raise h.problem(400, "request.refused", reason="choose a staged bundle")
            args["bundle"] = bundle
        if action in [r.get("action") for r in ops.pending()]:
            raise h.problem(409, "ops.busy")
        if confirm != "yes" and h.confirm is not None:  # WS-14.7: each action names its consequence first
            text = translate(sess.lang, f"ops.confirm.{action}", bundle=bundle)
            return h.confirm(request, sess, text, request.url.path, args, f"/admin/ops?tab={tab}")
        try:
            rid = ops.submit(action, h.actor(sess), args)
        except OSError as exc:  # the folder is not there or not writable: the host runner has never prepared it
            raise h.problem(503, "ops.unavailable") from exc
        au.append("console.ops", actor=h.actor(sess), detail={"action": action, "request": rid, **args})
        if runner is not None:
            res = runner.run_one({"id": rid, "action": action, "by": h.actor(sess), "args": args})
            runner.write_status()
            au.append("console.ops", actor=h.actor(sess),
                      detail={"action": f"{action}.done", "request": rid, "ok": bool(res.get("ok"))})  # fmt: skip
        return RedirectResponse(f"/admin/ops?tab={tab}&req={rid}", status_code=303)

    @app.get("/admin/ops/network/{name}")
    def network_file(request: Request, name: str) -> Response:
        sess = need_ops(request)
        if not _SHEET.match(name) or not (ops.network / name).is_file():
            raise h.problem(404, "notfound")
        au.append("console.ops", actor=h.actor(sess), detail={"action": "network_download", "file": name})
        media = "text/html" if name.endswith(".html") else "text/markdown"
        return FileResponse(ops.network / name, media_type=f"{media}; charset=utf-8", filename=name,
                            content_disposition_type="attachment")  # fmt: skip

    @app.get("/api/v1/admin/ops", response_model=None)
    def api_ops(request: Request) -> dict[str, Any]:
        """The same status for hospital IT's own tools: version, backups, updates, logs, secrets by name only."""
        assert h.api_session is not None
        sess = h.api_session(request)
        if not admin_allowed(sess.user.role, "ops.view"):
            au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        st = dict(status())
        st["secrets"] = [{k: r.get(k) for k in SECRET_KEYS} for r in st.get("secrets") or []]
        return {"status": st, "summary": summary(), "history": ops.history(30)}
