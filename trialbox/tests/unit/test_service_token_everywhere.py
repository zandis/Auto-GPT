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
