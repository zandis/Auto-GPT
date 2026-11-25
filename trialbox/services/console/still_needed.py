"""The page "Information still needed" (M1, U5-5; D-1280): every open item of ``tb_common.site_needs``, grouped by the
step it is needed before, with why, who knows it, how the box runs meanwhile, and a field to fill it in; and the table
of every install question with its default and the gate it holds (``tb_common.install_questions``).

The console writes nothing on the host: an answer is a request in the operations folder (``tools/trialbox/ops.py``,
``site_needs``), which the host's runner checks and applies (``tools/box/needs_apply.py``). The item leaves the list
once the box reads it as given. Who may: the administrator (``authz.admin_allowed``), as for the operations pages.
Audit: ``console.site_needs`` (the item's key and the request id, never a value).
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from tb_common import install_questions, site_needs
from tb_common.authz import admin_allowed

from console.auth import Session
from console.home import Helpers
from console.i18n import CATALOGUES
from console.i18n_stillneeded import EN, JA, ZH

for _lang, _cat in (("en", EN), ("ja", JA), ("zh-TW", ZH)):
    CATALOGUES[_lang].update(_cat)

PATH = "/admin/still-needed"
ACTION = "site_needs"  # tools/trialbox/ops.py
ROOT = Path(__file__).resolve().parents[2]
PROPOSALS = "needs-proposals.json"  # tools/box/detect.py writes it into the operations folder


def _env_file(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    return dict(ln.split("=", 1) for ln in lines if "=" in ln and not ln.startswith("#"))


def _settings(path: Path) -> dict[str, Any]:
    import yaml

    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return doc if isinstance(doc, dict) else {}


def register(app: FastAPI, h: Helpers, env: Mapping[str, str]) -> None:
    from tools.box import needs_apply
    from tools.trialbox import ops as tb_ops

    ops = tb_ops.OpsDir(Path(env.get("TB_OPS_DIR") or "/data/ops"))
    inline = (env.get("TB_OPS_RUNNER") or "host").strip().lower() == "inline"
    deploy = Path(env.get("TB_OPS_DEPLOY") or ROOT / "deploy")
    runner = tb_ops.OpsRunner(tb_ops.Box.local(deploy, env), ops) if inline else None

    def need_admin(request: Request, action: str) -> Session:
        sess = h.need(request)
        if not admin_allowed(sess.user.role, action):
            h.au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        return sess

    def still_open() -> list[tuple[site_needs.Need, str]]:
        if inline:  # the in-process box: the host's own files
            return site_needs.still_needed(
                env=_env_file(deploy / ".env"),
                settings=_settings(deploy / "settings.yaml"),
                files=["secrets/backup.pub"] if (deploy / "secrets/backup.pub").is_file() else [],
                stand_ins=site_needs.read_stand_ins(deploy)[0],
            )
        return site_needs.still_needed(
            env={**os.environ, **env},
            settings=_settings(Path(env.get("TB_SETTINGS") or "/etc/trialbox/settings.yaml")),
            files=site_needs.mounted_files(),
            stand_ins=site_needs.read_mounted_stand_ins(),
        )

    def proposals() -> dict[str, str]:
        try:
            doc = json.loads((ops.root / PROPOSALS).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {str(k): str(v)[:255] for k, v in doc.items()} if isinstance(doc, dict) else {}

    def requests_of(item: str) -> dict[str, Any] | None:
        """The newest request for ``item``, with its result when there is one."""
        return next(
            (
                r
                for r in ops.history(200)
                if r.get("action") == ACTION and (r.get("args") or {}).get("item") == item
            ),
            None,
        )

    def page(
        request: Request, sess: Session, status: int = 200, *, item: str = "", err: str = "", values: Any = None
    ) -> Response:
        found, rows = proposals(), []
        for n, state in still_open():
            last = requests_of(n.key)
            result = (last or {}).get("result")
            if last and not result:
                state = "waiting"
            elif result and not result.get("ok") and state == "missing":
                state = "unusable"
            rows.append({
                "need": n, "state": state, "fields": needs_apply.FIELDS.get(n.key, ()),
                "failed": result.get("summary", "") if result and not result.get("ok") else "",
            })  # fmt: skip
        steps = [
            {"step": s, "title": site_needs.STEPS[s], "rows": [r for r in rows if r["need"].before[0] == s]}
            for s in site_needs.STEPS
        ]
        keys = {r["need"].key for r in rows}
        return h.page(
            request, "still_needed.html", sess, status, steps=[s for s in steps if s["rows"]], item=item, err=err,
            values=values or {}, found=found, who=site_needs.WHO, kinds=needs_apply.SOURCE_KINDS,
            step_names=site_needs.STEPS, mail_off="mail_relay" in keys,
            table=install_questions.table(sess.lang, open_keys=keys), sent=request.query_params.get("sent", ""),
            can=admin_allowed(sess.user.role, "ops.update_apply"),
        )  # fmt: skip

    @app.get(PATH)
    def still_needed_page(request: Request) -> Response:
        return page(request, need_admin(request, "ops.view"))

    @app.post(PATH + "/{item}")
    async def still_needed_save(request: Request, item: str) -> Response:
        sess = need_admin(request, "ops.update_apply")
        form = {k: str(v)[:255] for k, v in (await request.form()).items() if isinstance(v, str)}
        if not h.csrf_ok(sess, form.get("csrf", "")):
            raise h.problem(400, "csrf")
        if item not in needs_apply.FIELDS:
            raise h.problem(404, "notfound")
        values = {k: form.get(k, "").strip() for k in needs_apply.FIELDS[item]}
        last = requests_of(item)
        if last and not last.get("result"):
            return page(request, sess, 409, item=item, err="busy", values=values)
        try:
            needs_apply.clean(item, values)
        except needs_apply.NeedsError as exc:
            return page(request, sess, 422, item=item, err=exc.code, values=values)
        args = {"item": item, **values}
        if values.get("chartno_example"):  # its form only: no chart number, not even an example, is written down
            args["chartno_rule"] = values["chartno_rule"] or needs_apply.rule_of(values["chartno_example"])
            args["chartno_example"] = ""
        try:
            rid = ops.submit(ACTION, h.actor(sess), args)
        except OSError as exc:
            raise h.problem(503, "ops.unavailable") from exc
        h.au.append("console.site_needs", actor=h.actor(sess), detail={"item": item, "request": rid})
        if runner is not None:
            runner.run_one({"id": rid, "action": ACTION, "by": h.actor(sess), "args": args})
        return RedirectResponse(f"{PATH}?sent={item}", status_code=303)
