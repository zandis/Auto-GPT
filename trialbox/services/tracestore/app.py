"""Trace store HTTP surface v0 (admin listener only, §8.14): write, read with purpose, prune.

Reads need ``X-TB-User``, ``X-TB-Purpose`` and ``X-TB-Roles`` containing ``trace:read``; every attempt is logged.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, HTTPException
from tb_common.http import make_app

from tracestore.store import TraceAccessDenied, TraceStore


def create_app(store: TraceStore | None = None) -> FastAPI:
    ts = store or TraceStore()  # schema "trace" of the trial database (TB_DB_URL, D-126)
    app = make_app("tracestore", checks=[lambda: {"traces": ts.count()}], protect_reads=True)  # D-130

    @app.post("/v1/traces")
    def write(trace: dict[str, Any]) -> dict[str, Any]:
        try:
            return {"call_id": ts.write(trace)}
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

    @app.get("/v1/traces/{call_id}")
    def read(
        call_id: str,
        x_tb_user: str = Header(default=""),
        x_tb_purpose: str = Header(default=""),
        x_tb_roles: str = Header(default=""),
    ) -> dict[str, Any]:
        roles = frozenset(r.strip() for r in x_tb_roles.split(",") if r.strip())
        try:
            return {"traces": ts.read(call_id, user=x_tb_user, purpose=x_tb_purpose, roles=roles)}
        except TraceAccessDenied as e:
            raise HTTPException(status_code=403, detail=str(e)) from e

    @app.post("/v1/prune")
    def prune() -> dict[str, Any]:
        return {"deleted": ts.prune()}

    return app
