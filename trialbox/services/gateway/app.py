"""tb-gateway HTTP app (spec v4 §8.2; S1-06): OpenAI-compatible ``POST /v1/chat/completions`` and ``GET /v1/models``.

``create_app(gateway)`` wraps a configured :class:`gateway.core.Gateway`; ``create_app()`` builds one from the
environment (``TB_TOPOLOGY``, ``TB_ENV``, ``TB_PROFILE``, ``TB_CLOUD_OPT_IN``, ``TB_ROUTING_PATH``,
``TB_REGISTRY_PATH``, ``TB_AUDIT_DIR``, ``TB_TRACESTORE_PATH``). Refusals are HTTP 403 with
``{"error": {"type": "tb_refusal", "code": <reason>}}``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from registry.registry import DEFAULT_PATH as REGISTRY_PATH
from registry.registry import Registry
from tb_common.audit import AuditLog
from tb_common.http import make_app
from tracestore.store import TraceStore

from gateway.core import Gateway, GatewayConfig
from gateway.policy import DEFAULT_PATH as ROUTING_PATH
from gateway.policy import RoutingPolicy


def from_env() -> Gateway:
    e = os.environ
    traces = TraceStore(Path(e["TB_TRACESTORE_PATH"])) if e.get("TB_TRACESTORE_PATH") else None
    return Gateway(
        RoutingPolicy.load(Path(e.get("TB_ROUTING_PATH") or ROUTING_PATH)),
        Registry.load(Path(e.get("TB_REGISTRY_PATH") or REGISTRY_PATH)),
        AuditLog(Path(e.get("TB_AUDIT_DIR") or "/data/audit"), e.get("TZ_SITE", "Asia/Taipei")),
        GatewayConfig.from_env(),
        traces=traces,
    )


def create_app(gateway: Gateway | None = None) -> FastAPI:
    gw = gateway or from_env()
    app = make_app(
        "gateway",
        checks=[lambda: {"policy_version": gw.policy.version, "registry_version": gw.registry.version}],
    )

    @app.get("/readyz")
    def readyz() -> dict[str, Any]:
        return {"status": "ready", "policy_version": gw.policy.version, "registry_version": gw.registry.version}

    @app.get("/v1/models")
    def models() -> dict[str, Any]:
        return {"object": "list", "data": [{"id": a, "object": "model", "owned_by": "tb-gateway"} for a in gw.models()]}

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return JSONResponse({"error": {"type": "invalid_request", "message": "JSON object body required"}}, 400)
        res = gw.chat(dict(request.headers), body)
        return JSONResponse(res.body, status_code=res.status, headers=res.headers)

    return app
