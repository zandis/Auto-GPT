"""tb-gateway HTTP app (spec v4 §8.2; S1-06): OpenAI-compatible ``POST /v1/chat/completions`` and ``GET /v1/models``
(each alias with its context, T-603);
``POST /v1/serving/activate``, ``POST /v1/serving/release`` and ``GET /v1/serving/status`` drive the one-GPU model
swap (:mod:`gateway.swap`).

``create_app(gateway)`` wraps a configured :class:`gateway.core.Gateway`; ``create_app()`` builds one from the
environment (``TB_TOPOLOGY``, ``TB_ENV``, ``TB_PROFILE``, ``TB_CLOUD_OPT_IN``, ``TB_ROUTING_PATH``,
``TB_REGISTRY_PATH``, ``TB_REGISTRY_OVERRIDE`` (site pins), ``TB_AUDIT_DIR``, ``TB_TRACESTORE``). Refusals are
HTTP 403 with ``{"error": {"type": "tb_refusal", "code": <reason>}}``.

In the compose stack the model registry, the PHI guard and the trace store run inside this process (they are on the
request path of every model call; a network hop each would add failure modes to a fail-closed path). The read-only
registry view (builds, statuses, pins; no endpoint addresses) is mounted at ``/registry/v1/builds``. Reads need the
service token too (``protect_reads``, review LLM-043).

The perimeter is checked (T-604, D-388; review LLM-036): in PRODUCTION on topology A, ``phi_on_box`` lets D3 go to
the perimeter endpoints without a study step because they are the box itself. So every perimeter endpoint's host must
resolve to box addresses only (:func:`gateway.policy.perimeter_addresses`). When one does not, the gateway does not
start (``SystemExit``). The names are resolved again while it runs (``TB_PERIMETER_RECHECK_S``, default 60 s): a name
that now points off the box makes every chat call a ``perimeter_unverified`` refusal (audited) and ``/healthz`` red.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Mapping
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
from gateway.policy import Resolver, RoutingPolicy, perimeter_checked, perimeter_problems, resolve_host
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


PERIMETER_RECHECK_S = 60.0


class PerimeterWatch:
    """The perimeter check of a running gateway (T-604): the endpoint names resolved again at most every
    ``ttl_s`` seconds, since a container restart or a changed DNS record can move a name off the box."""

    def __init__(
        self,
        policy: RoutingPolicy,
        env: Mapping[str, str],
        environment: str,
        resolver: Resolver = resolve_host,
        ttl_s: float = PERIMETER_RECHECK_S,
    ) -> None:
        self.policy, self.env, self.environment, self.resolver, self.ttl_s = policy, env, environment, resolver, ttl_s
        self._lock = threading.Lock()
        self._at = -1.0
        self._problems: list[str] = []

    def problems(self) -> list[str]:
        with self._lock:
            now = time.monotonic()
            if self._at < 0 or now - self._at >= self.ttl_s:
                self._problems = perimeter_problems(self.policy, self.env, self.environment, self.resolver)
                self._at = now
            return list(self._problems)


def perimeter_watch(gw: Gateway, resolver: Resolver = resolve_host) -> PerimeterWatch | None:
    """The watch for a gateway whose perimeter must be the box (PRODUCTION, topology A), checked once now: a
    perimeter endpoint off the box stops the start (``SystemExit``). None where the check does not apply."""
    cfg = gw.config
    if not perimeter_checked(cfg.topology, cfg.environment):
        return None
    ttl = float(gw.env.get("TB_PERIMETER_RECHECK_S") or PERIMETER_RECHECK_S)
    watch = PerimeterWatch(gw.policy, gw.env, cfg.environment.value, resolver, ttl)
    problems = watch.problems()
    if problems:
        gw.audit.append("llm.gateway.perimeter_refused", detail={"phase": "start", "problems": problems})
        raise SystemExit("tb-gateway: a perimeter endpoint is not on the box (T-604): " + "; ".join(problems))
    return watch


def create_app(gateway: Gateway | None = None, *, resolver: Resolver = resolve_host) -> FastAPI:
    gw = gateway or from_env()
    perimeter = perimeter_watch(gw, resolver)
    checks: list[Any] = [lambda: {"policy_version": gw.policy.version, "registry_version": gw.registry.version}]
    if gw.traces is not None and getattr(gw.traces, "db", None) is not None:
        checks.append(gw.traces.db.ping)  # the trace store's schema answers (D-142, review A-02)
    if perimeter is not None:

        def perimeter_on_box() -> dict[str, Any]:
            problems = perimeter.problems()
            if problems:
                raise RuntimeError("; ".join(problems))
            return {"perimeter": "on_box"}

        checks.append(perimeter_on_box)
    app = make_app("gateway", checks=checks, protect_reads=True)  # review LLM-043: reads need the token too

    @app.get("/readyz")
    def readyz() -> dict[str, Any]:
        return {"status": "ready", "policy_version": gw.policy.version, "registry_version": gw.registry.version}

    @app.get("/v1/models")
    def models() -> dict[str, Any]:
        """Aliases, each with its context in tokens (T-603): ``context_length`` and, as vLLM names it,
        ``max_model_len``; null where no routable build records one. Callers size their prompts from it."""
        ctx = gw.contexts()
        data = [
            {
                "id": a,
                "object": "model",
                "owned_by": "tb-gateway",
                "context_length": ctx.get(a),
                "max_model_len": ctx.get(a),
            }
            for a in gw.models()
        ]
        return {"object": "list", "data": data}

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return JSONResponse({"error": {"type": "invalid_request", "message": "JSON object body required"}}, 400)
        problems = await run_in_threadpool(perimeter.problems) if perimeter is not None else []
        if problems:
            # T-604: a perimeter name now points off the box; no call goes anywhere until it is back
            caller = request.headers.get("x-tb-caller", "")
            gw.audit.append(
                "llm.gateway.perimeter_refused", detail={"phase": "call", "caller": caller, "problems": problems}
            )
            msg = "a perimeter endpoint is not on the box"
            err = {"type": "tb_refusal", "code": "perimeter_unverified", "message": msg}
            return JSONResponse({"error": err}, 403, headers={"X-TB-Refusal": "perimeter_unverified"})
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
