"""FastAPI app factory (``/healthz``, JSON errors, request logs) and a typed inter-service client."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from tb_contracts import dump

from tb_common.logging import setup_logging

M = TypeVar("M", bound=BaseModel)
HealthCheck = Callable[[], dict[str, Any]]
VERSION = "1.0.0"


class ServiceError(RuntimeError):
    def __init__(self, service: str, status: int, detail: str) -> None:
        super().__init__(f"{service} returned {status}: {detail}")
        self.service = service
        self.status = status
        self.detail = detail


def make_app(
    service: str, checks: list[HealthCheck] | None = None, level: str = "INFO", lifespan: Any = None
) -> FastAPI:
    """Create a FastAPI app with ``GET /healthz`` and structured logging (optional ``lifespan`` context)."""
    log = setup_logging(service, level)
    app = FastAPI(title=f"trialbox-{service}", version=VERSION, lifespan=lifespan)
    health_checks = list(checks or [])
    app.state.health_checks = health_checks

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        detail: dict[str, Any] = {}
        ok = True
        for chk in app.state.health_checks:
            try:
                detail.update(chk())
            except Exception as exc:  # health must report, not raise
                ok = False
                detail[getattr(chk, "__name__", "check")] = f"error: {type(exc).__name__}"
        body = {
            "status": "ok" if ok else "degraded",
            "service": service,
            "version": VERSION,
            "checks": detail,
        }
        return JSONResponse(body, status_code=200 if ok else 503)

    @app.middleware("http")
    async def access_log(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled error", extra={"path": request.url.path})
            return JSONResponse({"error": "internal error"}, status_code=500)
        if request.url.path != "/healthz":
            log.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "ms": round((time.perf_counter() - t0) * 1000, 1),
                },
            )
        return response

    return app


class ServiceClient:
    """Small synchronous client that sends/receives contract models."""

    def __init__(
        self, base_url: str, service: str, timeout: float = 300.0, retries: int = 2, idempotent: bool = True
    ) -> None:
        """``idempotent=False`` (e.g. mail-gateway ``POST /send``): retry only when no connection was made, never
        after the request may have reached the service (5xx, read timeout) — a retry would send it twice."""
        self.base_url = base_url.rstrip("/")
        self.service = service
        self.retries = retries
        self.idempotent = idempotent
        self.client = httpx.Client(timeout=timeout)
        self.log = logging.getLogger(f"client.{service}")

    def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                resp = self.client.request(method, f"{self.base_url}{path}", **kw)
            except httpx.TransportError as exc:
                last = exc
                if not self.idempotent and not isinstance(exc, httpx.ConnectError | httpx.ConnectTimeout):
                    break  # it may have arrived
                time.sleep(min(2**attempt, 8))
                continue
            if resp.status_code >= 500 and attempt < self.retries and self.idempotent:
                time.sleep(min(2**attempt, 8))
                continue
            if resp.status_code >= 400:
                raise ServiceError(self.service, resp.status_code, resp.text[:2000])
            return resp
        if last is not None and not isinstance(last, httpx.ConnectError | httpx.ConnectTimeout):
            raise ServiceError(self.service, 0, f"no answer (the request may have been processed): {last}")
        raise ServiceError(self.service, 0, f"unreachable: {last}")

    def post(self, path: str, body: BaseModel | dict[str, Any], response: type[M]) -> M:
        payload = dump(body) if isinstance(body, BaseModel) else body
        resp = self._request("POST", path, json=payload)
        return response.model_validate(resp.json())

    def post_raw(self, path: str, body: BaseModel | dict[str, Any]) -> httpx.Response:
        payload = dump(body) if isinstance(body, BaseModel) else body
        return self._request("POST", path, json=payload)

    def get(self, path: str, response: type[M]) -> M:
        return response.model_validate(self._request("GET", path).json())

    def get_json(self, path: str) -> Any:
        return self._request("GET", path).json()

    def healthy(self) -> bool:
        try:
            return self.client.get(f"{self.base_url}/healthz", timeout=5).status_code == 200
        except httpx.HTTPError:
            return False

    def close(self) -> None:
        self.client.close()
