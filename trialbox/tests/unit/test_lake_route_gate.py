"""BH1-01: the lake's route gate (``services/lake/app.py``, ``_route_gate``). The criteria compiler's token reaches the
lake's reads, ``POST /query`` and ``POST /chunks/search`` only; a night's promote, a rebuild, the site's inputs and the
holds stay the orchestrator's and the adapter's. Each test here is one way round the gate. Synthetic tokens, a fake
lake, in process."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tb_common import service_auth as sa

CALLERS = ("orchestrator", "adapter", "criteria-compiler", "operator", "lake")
LEGACY_TOKEN = "an-old-shared-token-of-a-test-box-0123456789"


def _tok(service: str) -> str:
    return f"lake-gate-token-of-{service}-0123456789abcdef"


class _FakeLake:
    """Every lake call a route makes lands in ``calls``; a refused call leaves it empty."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def __getattr__(self, name: str) -> Any:
        def call(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, args))
            return {"holds": {}, "promote_built": True, "release": True}.get(name, {})

        return call

    def current(self) -> str:
        return "2026-01-05"

    def promote_built(self, snap: str, generation: str | None) -> bool:
        self.calls.append(("promote", snap))
        return True

    def release(self, holder: str) -> bool:
        self.calls.append(("release", holder))
        return True

    def holds(self) -> dict[str, str]:
        self.calls.append(("holds", ()))
        return {}

    def put_site(self, resources: dict[str, Any]) -> dict[str, int]:
        self.calls.append(("put_site", ()))
        return {}

    def hold(self, snap: str, holder: str, pin: bool = False) -> str:
        self.calls.append(("hold", holder))
        return snap


def _box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, legacy: bool = True, registry: bool = True) -> Any:
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    monkeypatch.delenv("TB_SERVICE_TOKEN_FILE", raising=False)
    if registry:
        body: dict[str, Any] = {"schema": sa.REGISTRY_SCHEMA, "services": {s: sa.token_hash(_tok(s)) for s in CALLERS}}
        if legacy:
            body["legacy"] = sa.token_hash(LEGACY_TOKEN)
        reg = tmp_path / "tokens.json"
        reg.write_text(json.dumps(body), encoding="utf-8")
        monkeypatch.setenv(sa.REGISTRY_ENV, str(reg))
        monkeypatch.setenv("TB_SERVICE_TOKEN", _tok("lake"))
    else:
        monkeypatch.delenv(sa.REGISTRY_ENV, raising=False)
        monkeypatch.setenv("TB_SERVICE_TOKEN", LEGACY_TOKEN)
    from lake import app as lake_app

    fake = _FakeLake()
    monkeypatch.setattr(lake_app, "lake", lambda: fake)
    return lake_app, fake


def _h(token: str) -> dict[str, str]:
    return {sa.TOKEN_HEADER: token}


#: the changing routes the compiler must not reach (method, path, body)
WRITES = [
    ("POST", "/promote", {"snapshot": "2026-01-05"}),
    ("POST", "/rebuild", {"snapshot": "2026-01-05"}),
    ("POST", "/site", {"resources": {"Patient": []}}),
    ("POST", "/holds", {"snapshot": "2026-01-05", "holder": "job-0001"}),
    ("DELETE", "/holds/job-0001", None),
    ("POST", "/vec/s2b", {"pid": "p", "dids": [], "query": "q"}),
]


@pytest.mark.parametrize(("method", "path", "body"), WRITES, ids=[f"{m} {p}" for m, p, _ in WRITES])
def test_the_compilers_token_reaches_no_changing_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str, path: str, body: Any
) -> None:
    app, fake = _box(tmp_path, monkeypatch)
    r = TestClient(app.app).request(method, path, json=body, headers=_h(_tok("criteria-compiler")))
    assert (r.status_code, r.json(), fake.calls) == (403, {"detail": "route_not_allowed"}, [])


@pytest.mark.parametrize(
    "path", ["/promote/", "/Promote", "/%70romote", "//promote", "/query/../promote", "/holds/../promote"]
)
def test_another_spelling_of_promote_is_refused_to_the_compiler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """A spelling the router might fold back onto ``/promote`` (a slash redirect, an escape, a dot segment) is refused
    before routing, not followed."""
    app, fake = _box(tmp_path, monkeypatch)
    c = TestClient(app.app, follow_redirects=True)
    r = c.post(path, json={"snapshot": "2026-01-05"}, headers=_h(_tok("criteria-compiler")))
    assert (r.status_code, fake.calls) == (403, [])


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_another_method_on_a_reader_route_is_refused_to_the_compiler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    app, fake = _box(tmp_path, monkeypatch)
    r = TestClient(app.app).request(method, "/query", headers=_h(_tok("criteria-compiler")))
    assert (r.status_code, fake.calls) == (403, [])


def test_options_passes_the_token_check_and_reaches_no_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``OPTIONS`` is let through before any token (``service_auth.authorize``); no lake route answers it."""
    app, fake = _box(tmp_path, monkeypatch)
    r = TestClient(app.app).options("/promote", headers=_h(_tok("criteria-compiler")))
    assert (r.status_code, fake.calls) == (405, [])


def test_a_mount_prefix_does_not_widen_the_compilers_routes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Behind a prefix (``root_path``) the gate reads the route's own path: ``/promote`` stays refused there."""
    app, fake = _box(tmp_path, monkeypatch)
    c = TestClient(app.app, root_path="/lake")
    r = c.post("/lake/promote", json={"snapshot": "2026-01-05"}, headers=_h(_tok("criteria-compiler")))
    assert (r.status_code, fake.calls) == (403, [])


def test_the_old_shared_token_does_not_promote_beside_a_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every container held the old shared token before the rotation, the compiler's too: beside a registry it is held
    to the reader routes, as the adapter's publish gate holds it (D-760 review)."""
    app, fake = _box(tmp_path, monkeypatch)
    c = TestClient(app.app)
    assert c.post("/promote", json={"snapshot": "2026-01-05"}, headers=_h(LEGACY_TOKEN)).status_code == 403
    assert c.delete("/holds/job-0001", headers=_h(LEGACY_TOKEN)).status_code == 403
    assert fake.calls == []
    assert c.get("/holds", headers=_h(LEGACY_TOKEN)).status_code == 200


def test_with_no_registry_the_shared_token_keeps_every_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A box with no registry has one token for all; nothing can be told apart, so nothing changes there."""
    app, fake = _box(tmp_path, monkeypatch, registry=False)
    r = TestClient(app.app).delete("/holds/job-0001", headers=_h(LEGACY_TOKEN))
    assert (r.status_code, fake.calls) == (200, [("release", "job-0001")])


@pytest.mark.parametrize("caller", ["orchestrator", "adapter", "operator"])
def test_the_orchestrator_the_adapter_and_the_operator_keep_promote_and_the_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caller: str
) -> None:
    app, fake = _box(tmp_path, monkeypatch)
    c = TestClient(app.app)
    assert c.post("/promote", json={"snapshot": "2026-01-05"}, headers=_h(_tok(caller))).status_code == 200
    assert c.delete("/holds/job-0001", headers=_h(_tok(caller))).status_code == 200
    assert fake.calls == [("promote", "2026-01-05"), ("release", "job-0001")]


def test_the_compiler_keeps_its_reads_and_its_searches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The gate refuses no route the compiler uses: its equivalence gate's ``POST /query``, and the reads."""
    app, fake = _box(tmp_path, monkeypatch)
    c = TestClient(app.app)
    h = _h(_tok("criteria-compiler"))
    assert c.get("/holds", headers=h).status_code == 200
    for path in ("/query", "/chunks/search"):
        r = c.post(path, json={}, headers=h)
        assert r.status_code != 403, (path, r.status_code)  # past the gate: the route answers (here, a bad body)
    assert c.get("/healthz").status_code in (200, 503)


def test_a_service_the_lake_does_not_take_is_still_refused_before_the_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, fake = _box(tmp_path, monkeypatch)
    r = TestClient(app.app).get("/holds", headers=_h(_tok("lake")))
    assert (r.status_code, fake.calls) == (403, [])
