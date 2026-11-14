"""NEW-SEC-4 (D-760): the publish of a held night checks the steward who accepted it (plan v7 wave 1; found in
T-723's review).

The steward's accept (``dataops.decide``) published a held night through the adapter's ``POST /publish``, which
took any caller's service token and no person: the console's token alone published a night the gate had held. Now
the console asks the orchestrator (``POST /dataops/publish``), which checks the signed person and the matrix's
right with its one dependency (``require_actor``), as for every changing route, and starts the adapter's publish
with its own token; the adapter takes ``POST /publish`` from the orchestrator only. The actor key stays with the
orchestrator alone (``service_auth``: no other service holds it). Synthetic data only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tb_common import actor_v3
from tb_common import service_auth as sa

from tests.actor3 import signed
from tools.trialbox.svc_secrets import IDENTITIES

BODY = {"snapshot": "2026-10-02", "source": "csv", "attempt": 1}


def _token(name: str) -> str:
    return f"new-sec-4-token-of-{name}-0123456789abcdef"


def _registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc = {"schema": sa.REGISTRY_SCHEMA, "services": {n: sa.token_hash(_token(n)) for n in IDENTITIES}}
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setenv(sa.REGISTRY_ENV, str(path))


def _auth(name: str) -> dict[str, str]:
    return {sa.TOKEN_HEADER: _token(name)}


# ---------------------------------------------------------------------------------------------- the adapter
def test_the_adapter_takes_the_publish_from_the_orchestrator_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from adapter import app as adapter_app

    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    monkeypatch.delenv("TB_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("TB_SERVICE_TOKEN_FILE", raising=False)
    _registry(tmp_path, monkeypatch)
    started: list[Any] = []

    def config() -> Any:  # the handler was reached: its configuration is the first thing it asks for
        started.append(1)
        raise RuntimeError("the test's adapter has no configuration")

    monkeypatch.setattr(adapter_app, "build_config", config)
    http = TestClient(adapter_app.app, raise_server_exceptions=False)
    r = http.post("/publish", json=BODY, headers=_auth("console"))
    assert r.status_code == 403 and started == []  # the console's token alone publishes nothing
    r = http.post("/publish", json=BODY, headers=_auth("orchestrator"))
    assert r.status_code != 403 and started == [1]  # the orchestrator's passes the gate (the test's config fails)


# ---------------------------------------------------------------------------------------------- the orchestrator
class _Adapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def publish(self, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("publish", body))
        return {"run": "r1", "state": "running"}

    def publish_state(self, rid: str) -> dict[str, Any]:
        self.calls.append(("state", rid))
        return {"run": rid, "state": "done"}


@pytest.fixture
def orch_app(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, _Adapter, list[dict[str, Any]]]:
    from types import SimpleNamespace

    from orchestrator import app as oapp

    monkeypatch.setenv("TB_ENV", "TEST")  # a test box: no service token, the claim is still checked
    monkeypatch.delenv("TB_SERVICE_TOKEN", raising=False)
    adapter = _Adapter()
    events: list[dict[str, Any]] = []

    class Audit:
        def append(self, event: str, **kw: Any) -> None:
            events.append({"event": event, **kw})

    monkeypatch.setattr(oapp, "orch", lambda: SimpleNamespace(services=SimpleNamespace(adapter=adapter), audit=Audit()))
    return TestClient(oapp.app, raise_server_exceptions=False), adapter, events


def test_the_orchestrator_starts_the_publish_only_for_the_steward_who_signed(orch_app: Any) -> None:
    client, adapter, events = orch_app
    path = "/dataops/publish"
    assert client.post(path, json=BODY).status_code == 403  # nobody
    coordinator = signed("dataops.decide", "", "POST", path, BODY, sub="console:crc", role="coordinator")
    assert client.post(path, json=BODY, headers=coordinator).status_code == 403  # a role without the right
    other = signed("dataops.decide", "", "POST", path, {**BODY, "attempt": 2}, sub="console:stew", role="steward")
    assert client.post(path, json=BODY, headers=other).status_code == 403  # a claim for another body
    assert adapter.calls == []
    steward = signed("dataops.decide", "", "POST", path, BODY, sub="console:stew", role="steward")
    r = client.post(path, json=BODY, headers=steward)
    assert r.status_code == 202 and r.json() == {"run": "r1", "state": "running"}
    assert adapter.calls == [("publish", BODY)]
    started = [e for e in events if e["event"] == "dataops.publish_started"]
    assert started and started[-1]["actor"] == "console:stew" and started[-1]["detail"]["snapshot"] == "2026-10-02"
    assert client.get("/dataops/publish/r1").json() == {"run": "r1", "state": "done"}  # its state, no patient row


# ---------------------------------------------------------------------------------------------- the console
def test_the_console_signs_the_publish_as_the_steward_who_accepts() -> None:
    from console.dataops_page import adapter_promoter
    from tb_common.jobpoll import Poll

    seen: list[tuple[str, Any, dict[str, str]]] = []

    class Orch:
        def post_raw(self, path: str, body: Any, headers: dict[str, str] | None = None) -> Any:
            seen.append((path, body, dict(headers or {})))

            class R:
                @staticmethod
                def json() -> dict[str, Any]:
                    return {"run": "r1", "state": "running"}

            return R()

        def get_json(self, path: str, headers: dict[str, str] | None = None) -> Any:
            return {"run": "r1", "state": "done"}

    class Bk:
        orch = Orch()

    class Batch:
        snapshot, source, attempt = "2026-10-02", "csv", 1

    def sign(method: str, path: str, body: Any) -> dict[str, str]:
        return signed("dataops.decide", "", method, path, body, sub="console:stew", role="steward")

    promote = adapter_promoter(Bk(), Poll(interval=0.01, lost_after=1.0, sleep=lambda _s: None))
    promote(Batch(), sign)
    path, body, headers = seen[0]
    assert path == "/dataops/publish" and body == BODY
    claim = actor_v3.verify(headers[actor_v3.HEADER])
    assert claim.sub == "console:stew" and claim.action == "dataops.decide" and claim.body == actor_v3.body_hash(BODY)
