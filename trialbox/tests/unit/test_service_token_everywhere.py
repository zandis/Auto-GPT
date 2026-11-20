"""D-127 (review F-11): every TrialBox service checks the box's service token, not only the orchestrator."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from tb_common.http import make_app
from tb_common.service_auth import TOKEN_HEADER, auth_headers


def _app(token: bool = True):  # type: ignore[no-untyped-def]
    app = make_app("lake", service_token=token)

    @app.post("/query")
    def query() -> dict[str, str]:
        return {"rows": "all of them"}

    @app.get("/snapshots")
    def snaps() -> list[str]:
        return []

    return app


@pytest.fixture
def production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    monkeypatch.setenv("TB_SERVICE_TOKEN", "box-secret-123")


def test_changing_calls_need_the_token(production: None) -> None:
    c = TestClient(_app())
    assert c.post("/query").status_code == 401
    assert c.post("/query", headers={TOKEN_HEADER: "guess"}).status_code == 403
    assert c.post("/query", headers=auth_headers()).json() == {"rows": "all of them"}
    assert c.get("/healthz").status_code == 200 and c.get("/snapshots").status_code == 200


def test_no_token_configured_refuses_in_production_and_opens_in_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_SERVICE_TOKEN", raising=False)
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    assert TestClient(_app()).post("/query").status_code == 503
    monkeypatch.setenv("TB_ENV", "DEV")
    assert TestClient(_app()).post("/query").status_code == 200


def test_the_model_stub_stays_open(production: None) -> None:
    assert TestClient(_app(token=False)).post("/query").status_code == 200


def test_reads_are_protected_where_asked(production: None) -> None:
    """Plan v4 F4 (D-130): ``protect_reads`` puts GET / HEAD behind the token; /healthz stays open."""
    app = make_app("mail-gateway", protect_reads=True)

    @app.get("/threads/{job_id}")
    def threads(job_id: str) -> dict[str, str]:
        return {"job": job_id}

    c = TestClient(app)
    assert c.get("/threads/J1").status_code == 401 and c.head("/threads/J1").status_code == 401
    assert c.get("/threads/J1", headers={TOKEN_HEADER: "guess"}).status_code == 403
    assert c.get("/threads/J1", headers=auth_headers()).json() == {"job": "J1"}
    assert c.get("/healthz").status_code == 200
    assert TestClient(_app()).get("/snapshots").status_code == 200  # a service that did not ask keeps open reads


@pytest.mark.parametrize("module", ["lake.app", "mail_gateway.app", "orchestrator.app"])
def test_the_patient_level_services_protect_their_reads(production: None, module: str) -> None:
    import importlib

    app = importlib.import_module(module).app
    assert TestClient(app).get("/no-such-route").status_code == 401, module


def test_the_trace_store_protects_its_reads(production: None) -> None:
    from tracestore.app import create_app

    class Store:
        def count(self) -> int:
            return 0

    assert TestClient(create_app(Store())).get("/v1/traces/abc").status_code == 401  # type: ignore[arg-type]


def test_internal_clients_send_the_token_on_reads(production: None) -> None:
    import httpx
    from lake.client import LakeHttp
    from tb_common.http import ServiceClient

    seen: list[tuple[str, str | None]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, req.headers.get(TOKEN_HEADER)))
        return httpx.Response(200, json={"items": []})

    sc = ServiceClient("http://orchestrator", "orchestrator")
    sc.client = httpx.Client(transport=httpx.MockTransport(handler))
    sc.get_json("/jobs?limit=1")
    assert seen == [("GET", "box-secret-123")]
    assert LakeHttp("http://lake").client.headers.get(TOKEN_HEADER) == "box-secret-123"
