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

**Start check (T-677, D-393; deep review LLM-008, LLM-009).** The served-model echo cannot see wrong weights (vLLM
copies the request's ``model`` into its answer), so a gateway built from the environment checks two things before it
lets a model call through, at start and then every hour (:class:`StartCheck`):

* the weights flag: ``trialbox doctor --verify-all`` writes ``weights_changed.json`` next to the site pins (the
  folder of ``TB_REGISTRY_OVERRIDE``, or ``TB_WEIGHTS_FLAG``) when a pinned build's weights no longer hash to their
  pin, and removes it when they do again. While it exists every call is refused ``weights_changed``;
* ``GET <endpoint>/models`` of each on-box endpoint a pinned build is served on: the row of the build's served name
  must report the pinned folder as ``root`` (vLLM's ``--model`` path, ``/models/<weights.model_dir>``) and a
  ``max_model_len`` not below the build's ``context_length`` (the gateway sizes prompts from it). A mismatch refuses
  every call ``model_mismatch`` until a later check passes. A server that does not answer yet (vLLM loads for
  minutes) is not a mismatch: it is asked again every 30 seconds until it answers.

Either refusal is HTTP 403 ``tb_refusal``, audited, and makes ``/healthz`` unhealthy, so ``docker compose up --wait``
(install, update) fails and an update rolls back. A gateway given to :func:`create_app` (tests) runs the check only
when a :class:`StartCheck` is given too.

**The verified caller (T-212b, D-437; CR-040).** Each call's ``X-TB-Caller`` is bound to the service its
``X-TB-Service-Token`` identifies (``request.state.tb_caller``): ``service_callers`` in ``models/routing.yaml`` says
which names each service may claim, and ``serving_control`` which services may drive the swap. See
:meth:`gateway.policy.RoutingPolicy.check_claim`.

The perimeter is checked (T-604, D-388; review LLM-036): in PRODUCTION on topology A, ``phi_on_box`` lets D3 go to
the perimeter endpoints without a study step because they are the box itself. So every perimeter endpoint's host must
resolve to box addresses only (:func:`gateway.policy.perimeter_addresses`). When one does not, the gateway does not
start (``SystemExit``). The names are resolved again while it runs (``TB_PERIMETER_RECHECK_S``, default 60 s): a name
that now points off the box makes every chat call a ``perimeter_unverified`` refusal (audited) and ``/healthz`` red.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
import time
from collections.abc import AsyncIterator, Callable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from registry.app import create_app as registry_app
from registry.registry import Registry
from starlette.concurrency import run_in_threadpool
from tb_common.audit_writer import open_audit
from tb_common.config import site_tz
from tb_common.http import make_app
from tracestore.store import TraceStore

from gateway.core import Gateway, GatewayConfig
from gateway.policy import DEFAULT_PATH as ROUTING_PATH
from gateway.policy import Resolver, RoutingPolicy, endpoint_key, perimeter_checked, perimeter_problems, resolve_host
from gateway.swap import SWAPPABLE, ModelSwap

log = logging.getLogger("gateway.start_check")
WEIGHTS_FLAG = "weights_changed.json"  # written by `trialbox doctor --verify-all` on a mismatch, removed on a pass
RECHECK_S = 3600.0  # a passed check is repeated every hour (LLM-009)
PENDING_S = 30.0  # a model server that did not answer yet is asked again this often


def weights_flag_path(env: Mapping[str, str]) -> Path | None:
    """Where ``doctor --verify-all`` puts the weights flag: ``TB_WEIGHTS_FLAG``, else beside the site pins
    (``TB_REGISTRY_OVERRIDE``); None when neither is set (no site pins, nothing to flag)."""
    raw = (env.get("TB_WEIGHTS_FLAG") or "").strip()
    if raw:
        return Path(raw)
    override = (env.get("TB_REGISTRY_OVERRIDE") or "").strip()
    return Path(override).parent / WEIGHTS_FLAG if override else None


def served_problems(
    gw: Gateway, env: Mapping[str, str], get: Callable[[str, str], tuple[int | None, Any]] | None = None
) -> tuple[list[str], list[str]]:
    """(mismatches, unchecked): each pinned on-box build's row in its server's ``GET /models`` against the pin.

    A mismatch is a ``root`` (vLLM's ``--model`` path; only an absolute path is compared, as vLLM reports it) whose
    folder is not the pin's ``weights.model_dir``, or a ``max_model_len`` below the build's ``context_length``.
    Unchecked: the server did not answer, answered other than 200, or does not list the served name (``doctor
    --serving`` reports that one; a call would be answered 404)."""
    fetch = get or (lambda url, key: _get_models(gw, url, key))
    mismatches: list[str] = []
    unchecked: list[str] = []
    answers: dict[str, tuple[int | None, Any]] = {}
    for b in gw.registry.builds:
        if not b.pinned or b.serving in ("stub", "hosted") or b.status.value in ("retired", "suspended"):
            continue
        for ep_name, name in sorted(b.served.items()):
            ep = gw.policy.endpoints.get(ep_name)
            if not name or ep is None or ep.zone != "perimeter":
                continue
            url = ep.url(dict(env)).rstrip("/")
            key = endpoint_key(ep.api_key_env, env) if ep.api_key_env else ""
            if url not in answers:
                answers[url] = fetch(url, key)
            status, doc = answers[url]
            if status != 200 or not isinstance(doc, dict):
                unchecked.append(f"{ep_name}: GET {url}/models answered {status if status else doc}")
                continue
            rows = {str(r.get("id")): r for r in doc.get("data") or [] if isinstance(r, dict)}
            row = rows.get(name)
            if row is None:
                unchecked.append(f"{ep_name}: the server does not list {name!r} (doctor --serving)")
                continue
            want_dir = str((b.weights or {}).get("model_dir") or "")
            root = row.get("root")
            on_disk = isinstance(root, str) and root.startswith("/")
            if want_dir and on_disk and PurePosixPath(str(root)).name != PurePosixPath(want_dir).name:
                mismatches.append(
                    f"{b.build_id}: {ep_name} serves {name!r} from {root}, but the pin is the folder {want_dir}"
                )
            mml = row.get("max_model_len")
            if b.context_length and isinstance(mml, int) and not isinstance(mml, bool) and mml < b.context_length:
                mismatches.append(
                    f"{b.build_id}: {ep_name} serves {name!r} with max_model_len {mml}, below the pinned "
                    f"context_length {b.context_length}"
                )
    return mismatches, unchecked


def _get_models(gw: Gateway, url: str, key: str) -> tuple[int | None, Any]:
    try:
        r = gw.http.get(f"{url}/models", headers={"Authorization": f"Bearer {key}"} if key else {}, timeout=10.0)
    except Exception as e:  # unreachable is "not yet", never a mismatch
        return None, f"{type(e).__name__}: {e}"
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, None


class StartCheck:
    """The gateway's start check (module docstring): the weights flag and ``/v1/models`` against the pins."""

    def __init__(
        self,
        gw: Gateway,
        env: Mapping[str, str] | None = None,
        get: Callable[[str, str], tuple[int | None, Any]] | None = None,
    ) -> None:
        self.gw = gw
        self.env: Mapping[str, str] = os.environ if env is None else env
        self.flag = weights_flag_path(self.env)
        self.get = get
        self.mismatches: list[str] = []
        self.unchecked: list[str] = []
        self.checked = False
        self._lock = threading.Lock()

    def run(self) -> list[str]:
        """Ask every on-box model server once; returns the mismatches (also kept for :meth:`refusal`)."""
        mismatches, unchecked = served_problems(self.gw, self.env, self.get)
        with self._lock:
            changed = mismatches != self.mismatches
            self.mismatches, self.unchecked, self.checked = mismatches, unchecked, True
        if changed:
            event = "llm.gateway.model_mismatch" if mismatches else "llm.gateway.model_match"
            self.gw.audit.append(event, detail={"mismatches": mismatches})
        return mismatches

    def flagged(self) -> str | None:
        """The weights flag's findings, or None when there is no flag."""
        if self.flag is None or not self.flag.is_file():
            return None
        try:
            doc = json.loads(self.flag.read_text(encoding="utf-8"))
            lines = [str(x) for x in doc.get("lines") or []] if isinstance(doc, dict) else []
        except (OSError, ValueError):
            lines = []
        return "; ".join(lines) or "the weights flag is set"

    def refusal(self) -> tuple[str, str] | None:
        """(code, message) while the box must not call a model, else None."""
        flagged = self.flagged()
        if flagged is not None:
            fix = "restore the pinned files or re-pin (RUNBOOK §8), then run `trialbox doctor --verify-all`"
            return "weights_changed", f"model weights differ from their pins ({flagged[:400]}): {fix}"
        with self._lock:
            if self.mismatches:
                why = "; ".join(self.mismatches)[:400]
                return "model_mismatch", f"a model server does not serve the pinned model ({why}): fix deploy/.env"
        return None

    def health(self) -> dict[str, Any]:
        """A /healthz check: raises while a refusal holds, so compose marks the gateway unhealthy."""
        r = self.refusal()
        if r is not None:
            raise RuntimeError(r[0])
        with self._lock:
            state = "pending" if not self.checked or self.unchecked else "ok"
        return {"model_check": state}

    def run_safe(self) -> None:
        try:
            self.run()
        except Exception:  # a check that cannot run is retried; it never stops the gateway
            log.exception("start check failed")

    def loop(self, stop: threading.Event) -> None:
        """The checks after the first (which the app runs before it serves): every 30 s while a server has not
        answered, then every hour."""
        while not stop.is_set():
            with self._lock:
                wait = PENDING_S if (self.unchecked or not self.checked) else RECHECK_S
            if stop.wait(wait):
                return
            self.run_safe()


def _service(request: Request) -> str | None:
    """The service the request's ``X-TB-Service-Token`` identifies (``make_app`` sets it from
    ``service_auth.authorize``); None when the box has no token (DEV and TEST only) (T-212b, D-437)."""
    got = getattr(request.state, "tb_caller", None)
    return str(got) if got else None


def _refused(gw: Gateway, code: str, message: str) -> JSONResponse:
    gw.audit.append("llm.gateway.refuse", detail={"reason": code, "message": message})
    return JSONResponse(
        {"error": {"type": "tb_refusal", "code": code, "message": message}}, 403, headers={"X-TB-Refusal": code}
    )


def from_env() -> Gateway:
    e = os.environ
    # TB_TRACESTORE=on: traces go to schema "trace" of the trial database (TB_DB_URL, D-126); off by default
    traces = TraceStore(e.get("TB_DB_URL")) if e.get("TB_TRACESTORE", "").strip().lower() == "on" else None
    policy = RoutingPolicy.load(Path(e.get("TB_ROUTING_PATH") or ROUTING_PATH))
    swap = ModelSwap.from_env({k: ep.url(dict(e)) for k, ep in policy.endpoints.items() if k in SWAPPABLE}, e)
    return Gateway(
        policy,
        Registry.from_env(e),
        open_audit(Path(e.get("TB_AUDIT_DIR") or "/data/audit"), site_tz(None, e), env=e),
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


def create_app(
    gateway: Gateway | None = None, start_check: StartCheck | None = None, *, resolver: Resolver = resolve_host
) -> FastAPI:
    gw = gateway or from_env()
    perimeter = perimeter_watch(gw, resolver)  # T-604: off the box, the gateway does not start
    sc = start_check if start_check is not None or gateway is not None else StartCheck(gw)
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
    lifespan = None
    if sc is not None:
        checks.append(sc.health)

        @contextlib.asynccontextmanager
        async def lifespan(_: FastAPI) -> AsyncIterator[None]:
            await run_in_threadpool(sc.run_safe)  # before the first call is served
            stop = threading.Event()
            threading.Thread(target=sc.loop, args=(stop,), name="gateway-start-check", daemon=True).start()
            yield
            stop.set()

    # review LLM-043: reads need the token too
    app = make_app("gateway", checks=checks, lifespan=lifespan, protect_reads=True)

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
            detail = {"phase": "call", "caller": caller, "service": _service(request) or "", "problems": problems}
            gw.audit.append("llm.gateway.perimeter_refused", detail=detail)
            msg = "a perimeter endpoint is not on the box"
            err = {"type": "tb_refusal", "code": "perimeter_unverified", "message": msg}
            return JSONResponse({"error": err}, 403, headers={"X-TB-Refusal": "perimeter_unverified"})
        refused = sc.refusal() if sc is not None else None
        if refused is not None:  # T-677: weights or served model not the pin's; no model is called
            return _refused(gw, *refused)
        # upstream calls block; keep the loop free. The verified service binds X-TB-Caller (T-212b, D-437)
        res = await run_in_threadpool(lambda: gw.chat(dict(request.headers), body, service=_service(request)))
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
        caller, service = request.headers.get("x-tb-caller", ""), _service(request)
        res = await run_in_threadpool(lambda: gw.activate(caller, endpoint, hold, service=service))
        return JSONResponse(res.body, status_code=res.status)

    @app.post("/v1/serving/release")
    def serving_release(request: Request) -> JSONResponse:
        """A screening run lets go of the card (D-116): nothing swaps back now; the next call wakes what it needs."""
        res = gw.release(request.headers.get("x-tb-caller", ""), service=_service(request))
        return JSONResponse(res.body, status_code=res.status)

    app.mount("/registry", registry_app(gw.registry))
    return app
