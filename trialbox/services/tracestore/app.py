"""Trace store HTTP surface v0 (admin listener only, §8.14): write, read with purpose, prune.

Reads need ``X-TB-User``, ``X-TB-Purpose`` and ``X-TB-Roles`` containing ``trace:read``; every attempt is logged.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from tb_common.http import make_app

from tracestore.store import TraceAccessDenied, TraceStore

log = logging.getLogger("tracestore")

#: D-634: a refusal is a code and a fixed sentence (the gateway's shape), never an exception's own text: the write
#: path takes a whole trace, and what an exception below it says is not ours to send back. code -> (status, sentence)
REFUSALS = {
    "trace_invalid": (422, "the trace cannot be stored as it was sent"),
    "trace_read_denied": (403, "a trace read needs a user, a purpose and the read role"),
}


def refusal(code: str, exc: BaseException) -> JSONResponse:
    status, message = REFUSALS[code]
    log.warning("refused: %s (%s)", code, type(exc).__name__)  # the type, never the text
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def create_app(store: TraceStore | None = None) -> FastAPI:
    ts = store or TraceStore()  # schema "trace" of the trial database (TB_DB_URL, D-126)
    app = make_app("tracestore", checks=[lambda: {"traces": ts.count()}], protect_reads=True)  # D-130

    @app.post("/v1/traces", response_model=None)
    def write(trace: dict[str, Any]) -> dict[str, Any] | JSONResponse:
        try:
            return {"call_id": ts.write(trace)}
        except ValueError as e:
            return refusal("trace_invalid", e)

    @app.get("/v1/traces/{call_id}", response_model=None)
    def read(
        call_id: str,
        x_tb_user: str = Header(default=""),
        x_tb_purpose: str = Header(default=""),
        x_tb_roles: str = Header(default=""),
    ) -> dict[str, Any] | JSONResponse:
        roles = frozenset(r.strip() for r in x_tb_roles.split(",") if r.strip())
        try:
            return {"traces": ts.read(call_id, user=x_tb_user, purpose=x_tb_purpose, roles=roles)}
        except TraceAccessDenied as e:
            return refusal("trace_read_denied", e)

    @app.post("/v1/prune")
    def prune() -> dict[str, Any]:
        return {"deleted": ts.prune()}

    return app
