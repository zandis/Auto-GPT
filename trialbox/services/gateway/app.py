"""tb-gateway HTTP app (spec v4 §8.2; S1-06): OpenAI-compatible ``POST /v1/chat/completions`` and ``GET /v1/models``;
``POST /v1/serving/activate``, ``POST /v1/serving/release`` and ``GET /v1/serving/status`` drive the one-GPU model
swap (:mod:`gateway.swap`).

``create_app(gateway)`` wraps a configured :class:`gateway.core.Gateway`; ``create_app()`` builds one from the
environment (``TB_TOPOLOGY``, ``TB_ENV``, ``TB_PROFILE``, ``TB_CLOUD_OPT_IN``, ``TB_ROUTING_PATH``,
``TB_REGISTRY_PATH``, ``TB_REGISTRY_OVERRIDE`` (site pins), ``TB_AUDIT_DIR``, ``TB_TRACESTORE``). Refusals are
HTTP 403 with ``{"error": {"type": "tb_refusal", "code": <reason>}}``.

In the compose stack the model registry, the PHI guard and the trace store run inside this process (they are on the
request path of every model call; a network hop each would add failure modes to a fail-closed path). The read-only
registry view (builds, statuses, pins; no endpoint addresses) is mounted at ``/registry/v1/builds``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from registry.app import create_app as registry_app
from registry.registry import Registry
from starlette.concurrency import run_in_threadpool
from tb_common.audit import AuditLog
from tb_common.config import site_tz
from tb_common.http import make_app
from tracestore.store import TraceStore

from gateway.core import Gateway, GatewayConfig
from gateway.policy import DEFAULT_PATH as ROUTING_PATH
from gateway.policy import RoutingPolicy
from gateway.swap import SWAPPABLE, ModelSwap


def from_env() -> Gateway:
    e = os.environ
    # TB_TRACESTORE=on: traces go to schema "trace" of the trial database (TB_DB_URL, D-126); off by default
    traces = TraceStore(e.get("TB_DB_URL")) if e.get("TB_TRACESTORE", "").strip().lower() == "on" else None
    policy = RoutingPolicy.load(Path(e.get("TB_ROUTING_PATH") or ROUTING_PATH))
    swap = ModelSwap.from_env({k: ep.url(dict(e)) for k, ep in policy.endpoints.items() if k in SWAPPABLE}, e)
    return Gateway(
        policy,
        Registry.from_env(e),
        AuditLog(Path(e.get("TB_AUDIT_DIR") or "/data/audit"), site_tz(None, e)),
        GatewayConfig.from_env(),
        traces=traces,
        swap=swap,
    )


def create_app(gateway: Gateway | None = None) -> FastAPI:
    gw = gateway or from_env()
    checks: list[Any] = [lambda: {"policy_version": gw.policy.version, "registry_version": gw.registry.version}]
    if gw.traces is not None and getattr(gw.traces, "db", None) is not None:
        checks.append(gw.traces.db.ping)  # the trace store's schema answers (D-142, review A-02)
    app = make_app("gateway", checks=checks)

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
        res = await run_in_threadpool(gw.chat, dict(request.headers), body)  # upstream calls block; keep the loop free
        return JSONResponse(res.body, status_code=res.status, headers=res.headers)

    @app.get("/v1/serving/status")
    def serving_status() -> dict[str, Any]:
        return gw.swap.status() if gw.swap is not None else {"swap": "off", "active": None}

    @app.post("/v1/serving/activate")
    async def serving_activate(request: Request) -> JSONResponse:
        """Wake one model and sleep the other (TB_MODEL_SWAP=sleep); body ``{"endpoint": "serving" | "verifier",
        "hold": true}`` (hold: a screening run keeps the card until ``/v1/serving/release``)."""
        try:
            body = await request.json()
        except ValueError:
            body = None
        endpoint = body.get("endpoint") if isinstance(body, dict) else None
        if not isinstance(endpoint, str):
            return JSONResponse({"error": {"type": "invalid_request", "message": "endpoint required"}}, 400)
        hold = bool(body.get("hold")) if isinstance(body, dict) else False
        res = await run_in_threadpool(gw.activate, request.headers.get("x-tb-caller", ""), endpoint, hold)
        return JSONResponse(res.body, status_code=res.status)

    @app.post("/v1/serving/release")
    def serving_release(request: Request) -> JSONResponse:
        """A screening run lets go of the card (D-116): nothing swaps back now; the next call wakes what it needs."""
        res = gw.release(request.headers.get("x-tb-caller", ""))
        return JSONResponse(res.body, status_code=res.status)

    app.mount("/registry", registry_app(gw.registry))
    return app
