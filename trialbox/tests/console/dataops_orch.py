"""NEW-ARCH-3 (D-761): the console's data-operations page over the orchestrator's real ``dataops`` routes, for the
console tests: the fake backend's ``orch`` (and ``orch_once``) call a test client of those routes, over the same
``dataops`` store the tests fill and the box's audit. ``adapter`` is the adapter client the routes publish through
(None: this box cannot publish)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from tb_common.http import ServiceError


class OrchShim:
    def __init__(self, client: TestClient) -> None:
        self.client = client

    def _answer(self, r: Any) -> Any:
        if r.status_code >= 400:
            raise ServiceError("orchestrator", r.status_code, r.text)
        return r

    def get_json(self, path: str) -> Any:
        return self._answer(self.client.get(path)).json()

    def post_raw(self, path: str, body: Any, headers: dict[str, str] | None = None) -> Any:
        return self._answer(self.client.post(path, json=body, headers=headers or {}))


def attach(backend: Any, audit: Any, adapter: Any = None) -> dict[str, Any]:
    """Point ``backend.orch`` at the routes; returns the holder whose ``adapter`` a test may set."""
    from datacore.dataops import DataOps
    from orchestrator.dataops_api import router

    held: dict[str, Any] = {"adapter": adapter}
    ops = DataOps()
    app = FastAPI()
    app.include_router(router(lambda: ops, lambda: held["adapter"], lambda: audit))
    backend.orch = backend.orch_once = OrchShim(TestClient(app, raise_server_exceptions=False))
    return held
