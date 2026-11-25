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
from fastapi.responses import JSONResponse, RedirectResponse
from tb_common import install_questions, site_needs
from tb_common.authz import admin_allowed

from console.api_first import before_body
from console.auth import Session
from console.form_errors import FAILED, FieldError, FormErrors, kept_values
from console.home import Helpers
from console.i18n import CATALOGUES, translate
from console.i18n_stillneeded import EN, JA, ZH

for _lang, _cat in (("en", EN), ("ja", JA), ("zh-TW", ZH)):
    CATALOGUES[_lang].update(_cat)

PATH = "/admin/still-needed"
ACTION = "site_needs"  # tools/trialbox/ops.py
ROOT = Path(__file__).resolve().parents[2]
PROPOSALS = "needs-proposals.json"  # tools/box/detect.py writes it into the operations folder


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
    from tools.trialbox.finish_check import read_env

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
                env=read_env(deploy / ".env"),
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
            (r for r in ops.history(200) if r.get("action") == ACTION and (r.get("args") or {}).get("item") == item),
            None,
        )

    def page(
        request: Request, sess: Session, status: int = 200, *, item: str = "", fe: FormErrors | None = None
    ) -> Response:
        found = proposals()
        rows: list[dict[str, Any]] = []
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
            request, "still_needed.html", sess, status, steps=[s for s in steps if s["rows"]], item=item, fe=fe,
            found=found, who=site_needs.WHO, choices=choices(sess.lang, found),
            step_names=site_needs.STEPS, mail_off="mail_relay" in keys,
            table=install_questions.table(sess.lang, open_keys=keys), sent=request.query_params.get("sent", ""),
            can=admin_allowed(sess.user.role, "ops.update_apply"),
        )  # fmt: skip

    def choices(lang: str, found: Mapping[str, str]) -> dict[str, list[tuple[str, str]]]:
        rule = found.get("chartno_rule", "")
        kinds = [(k, translate(lang, f"stillneeded.kind.{k}")) for k in needs_apply.SOURCE_KINDS]
        rules = [("", translate(lang, "stillneeded.rule.unset"))]
        rules += [(rule, rule)] if rule else []
        return {"source_kind": kinds, "chartno_rule": [*rules, ("asis", translate(lang, "stillneeded.rule.asis"))]}

    @app.get(PATH)
    def still_needed_page(request: Request) -> Response:
        return page(request, need_admin(request, "ops.view"))

    def send(sess: Session, item: str, values: dict[str, str]) -> tuple[int, str]:
        """One answer to the host: (200, the request id), else the status and the error's code. Answers
        are applied in order: the last one stands."""
        try:
            needs_apply.clean(item, values)
        except needs_apply.NeedsError as exc:
            return 422, exc.code
        args = {"item": item, **values}
        if values.get("chartno_example"):  # its form only: no chart number, not even an example, is written down
            args["chartno_rule"] = values.get("chartno_rule") or needs_apply.rule_of(values["chartno_example"])
            args["chartno_example"] = ""
        try:
            rid = ops.submit(ACTION, h.actor(sess), args)
        except OSError as exc:
            raise h.problem(503, "ops.unavailable") from exc
        h.au.append("console.site_needs", actor=h.actor(sess), detail={"item": item, "request": rid})
        if runner is not None:
            runner.run_one({"id": rid, "action": ACTION, "by": h.actor(sess), "args": args})
        return 200, rid

    def fields_of(item: str) -> tuple[str, ...]:
        if item not in needs_apply.FIELDS:
            raise h.problem(404, "notfound")
        return needs_apply.FIELDS[item]

    @app.post(PATH + "/{item}")
    async def still_needed_save(request: Request, item: str) -> Response:
        sess = need_admin(request, "ops.update_apply")
        form = {k: str(v)[:255] for k, v in (await request.form()).items() if isinstance(v, str)}
        if not h.csrf_ok(sess, form.get("csrf", "")):
            raise h.problem(400, "csrf")
        values = {k: form.get(k, "").strip() for k in fields_of(item)}
        status, said = send(sess, item, values)
        if status != 200:
            at = "smtp_port" if said == "port" else next(iter(values))
            error = FieldError(at, f"stillneeded.err.{said}")
            fe = FormErrors("still-needed", f"sn-{item}", (error,), kept_values(values))
            return page(request, sess, FAILED, item=item, fe=fe)
        return RedirectResponse(f"{PATH}?sent={item}", status_code=303)

    def first(sess: Session, request: Request) -> None:
        """The permit check before the body is read (console.api_first)."""
        if not admin_allowed(sess.user.role, "ops.update_apply"):
            h.au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")

    @app.post("/api/v1" + PATH + "/{item}", response_model=None)
    @before_body(first)
    def api_still_needed(request: Request, item: str, body: dict[str, str]) -> Any:
        """The page's twin (FIT-019): the item's fields; answers the request's id."""
        assert h.api_session is not None  # set by register() before any request
        sess = h.api_session(request)
        status, said = send(sess, item, {k: str(body.get(k, ""))[:255].strip() for k in fields_of(item)})
        if status != 200:
            return JSONResponse({"error": "request.refused", "detail": {"code": said}}, status_code=status)
        return {"item": item, "request": said}
