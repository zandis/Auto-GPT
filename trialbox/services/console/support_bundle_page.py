"""10K-5 (D-1381, plan 10 row 10K-5, review 18 SO-5): the support bundle as a button on the operations pages.

The button is the operations action ``support_bundle`` (``POST /admin/ops/support_bundle``: CSRF, the confirmation
that names what goes in and what never does, ``console.ops`` audit events, one request at a time; ``ops_pages``).
The host's runner makes the bundle from allow-listed fields only (``tools/trialbox/ops_support.py``,
``tools/trialbox/support_fields.py``) and has the SAME builder as ``trialbox support-bundle`` scan and write it
(``tools/support_bundle.py``) into ``<ops>/support/``. This module adds the tab's texts and the one download route:

``POST /admin/ops/support/{rid}``
    a form with the session's CSRF token and nothing typed (the review of 48b3210c, L8: not a link another site could
    have a signed-in browser follow). It hands out the bundle request ``rid`` made, only when the runner's result for
    it is a success that names the file, its size and its sha256, and only when the file on disk still has that size
    and sha256; otherwise it answers 303 back to the tab, which says the bundle is not on the box as it was made (a
    changed file is also the event ``support_bundle_download.refused``). The same open file is hashed and then sent.
    Each download is the audit event ``console.ops`` with ``support_bundle_download.started``, the request, the file
    name, its size and its sha256, written when the response starts: it records that the file was handed to the
    response, not that every byte arrived (as the console's other files, the feedback and audit CSVs, record theirs);
    when it cannot be written, the file is closed and the answer is 503 with no byte of it. The bundle's contents are
    never read into an event or a log. GET and HEAD answer 405.

Who may: the right that opens the operations pages, ``ops.view`` (:func:`tb_common.authz.admin_allowed`: the
administrator only). No new matrix row; every other role gets 403, audited as ``console.denied``.

Not here: the refusal while a support session is on (10K-15, pull request #1170, not on master when this was built).
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import RedirectResponse, StreamingResponse
from tb_common.authz import admin_allowed

from console import i18n_support_bundle
from console.auth import Session
from console.home import Helpers
from console.i18n import CATALOGUES

for _lang, _cat in (("en", i18n_support_bundle.EN), ("ja", i18n_support_bundle.JA), ("zh-TW", i18n_support_bundle.ZH)):
    CATALOGUES[_lang].update(_cat)

RIGHT = "ops.view"  # the administrator's row that opens the operations pages; no new row (D-1381)
_REQ = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{6}", re.ASCII)
CHUNK = 1 << 20


def _chunks(fh: Any) -> Iterator[bytes]:
    try:
        while chunk := fh.read(CHUNK):
            yield chunk
    finally:
        fh.close()


def register(app: FastAPI, h: Helpers, env: Mapping[str, str]) -> None:
    from tools.trialbox import ops as tb_ops
    from tools.trialbox import ops_support

    au = h.au
    ops = tb_ops.OpsDir(Path(env.get("TB_OPS_DIR") or "/data/ops"))

    def need(request: Request) -> Session:
        sess = h.need(request)
        if not admin_allowed(sess.user.role, RIGHT):
            au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        return sess

    def gone(rid: str) -> Response:
        """Back to the tab, which says the bundle is not on the box (any more) or not as it was made."""
        where = f"&req={rid}" if _REQ.fullmatch(rid) else ""
        return RedirectResponse(f"/admin/ops?tab=support{where}&gone=1", status_code=303)

    @app.post("/admin/ops/support/{rid}")
    def support_bundle_download(request: Request, rid: str, csrf: str = Form("")) -> Response:
        sess = need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        rec = ops_support.record(ops.result(rid)) if _REQ.fullmatch(rid) else None
        if rec is None:
            return gone(rid)
        path = ops_support.support_dir(ops.root) / rec["file"]
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except OSError:  # removed (only the newest bundles are kept, none past its age) or never readable here
            return gone(rid)
        fh = os.fdopen(fd, "rb")
        try:
            sha, size = ops_support.sha256_of(fh)
            if sha != rec["sha256"] or size != rec["bytes"]:
                au.append("console.ops", actor=h.actor(sess),
                          detail={"action": "support_bundle_download.refused", "request": rid, "file": rec["file"],
                                  "why": "the file on disk is not the one the runner made"})  # fmt: skip
                fh.close()
                return gone(rid)
            fh.seek(0)
        except BaseException:
            fh.close()
            raise
        try:
            au.append("console.ops", actor=h.actor(sess),
                      detail={"action": "support_bundle_download.started", "request": rid, **rec})  # fmt: skip
        except Exception as exc:  # the start could not be recorded: no byte is sent, and the file is closed
            fh.close()
            raise h.problem(503, "sbundle.err.audit") from exc
        except BaseException:
            fh.close()
            raise
        return StreamingResponse(
            _chunks(fh),
            media_type="application/gzip",
            headers={
                "Content-Disposition": f'attachment; filename="{rec["file"]}"',
                "Content-Length": str(size),
                "Cache-Control": "no-store",
            },
        )
