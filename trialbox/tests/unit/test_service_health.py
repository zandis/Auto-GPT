from __future__ import annotations

import importlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tb_common.config import get_config

SERVICES = [
    "mail_gateway",
    "doc_parser",
    "criteria_compiler",
    "lake",
    "orchestrator",
    "adapter",
    "embed_service",
    "llm_stub",
]
# each app builds its service once and keeps it in a module global (criteria_compiler: ``_compiler``, and so on)
SINGLETONS = ("_compiler", "_store", "_embedder", "_lake", "_gw", "_orch")


@pytest.fixture
def _fresh_config() -> Iterator[None]:
    """get_config() is cached per process: a config read earlier in the same xdist worker (without TB_RULESETS_DIR)
    pointed the compiler's repository at the committed rulesets/, which it re-materialised in place under a parallel
    test's copytree (T-650c). Read this test's environment, and leave no cached config with its folders behind."""
    get_config.cache_clear()
    yield
    get_config.cache_clear()


@pytest.mark.usefixtures("_fresh_config")
@pytest.mark.parametrize("svc", SERVICES)
def test_healthz(svc: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # every service's state under the test's own folder: the defaults (/data, fs:/data/objects, /data/lake) are the
    # box's, and a CI runner (not root) cannot write them
    monkeypatch.setenv("TB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TB_OBJECT_STORE", f"fs:{tmp_path / 'objects'}")
    monkeypatch.setenv("TB_LAKE_DIR", str(tmp_path / "lake"))
    monkeypatch.setenv("TB_AUDIT_DIR", str(tmp_path / "audit"))
    # the compiler's ruleset repository defaults to the committed rulesets/ folder, which it would re-materialise in
    # place (rmtree + rename) while parallel tests copy it: give it the test's own folder
    monkeypatch.setenv("TB_RULESETS_DIR", str(tmp_path / "rulesets"))
    # T-650c: those variables reach the service only through a fresh config (``_fresh_config``) and fresh singletons
    mod = importlib.import_module(f"{svc}.app")
    for name in SINGLETONS:
        if hasattr(mod, name):
            monkeypatch.setattr(mod, name, None)
    assert get_config().env.rulesets_path == tmp_path / "rulesets"
    with TestClient(mod.app) as client:
        resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == svc.replace("_", "-").replace("llm-stub", "llm-stub")


def test_non_idempotent_client_never_resends(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /send must not be repeated once it may have reached the gateway: a 500 (the password mail failed after
    the archive went out) or a read timeout would otherwise mail the PHI archive again with a new password."""
    import httpx
    from tb_common.http import ServiceClient, ServiceError

    monkeypatch.setattr("time.sleep", lambda s: None)
    for outcome, idempotent, calls_expected in (
        (httpx.Response(500, text="smtp failed"), False, 1),
        (httpx.ReadTimeout("slow"), False, 1),
        (httpx.ConnectError("refused"), False, 3),  # never connected: safe to try again
        (httpx.Response(500, text="smtp failed"), True, 3),
    ):
        calls: list[int] = []

        def handler(req: httpx.Request, outcome: object = outcome, calls: list[int] = calls) -> httpx.Response:
            calls.append(1)
            if isinstance(outcome, Exception):
                raise outcome
            assert isinstance(outcome, httpx.Response)
            return outcome

        c = ServiceClient("http://mail", "mail-gateway", retries=2, idempotent=idempotent)
        c.client = httpx.Client(transport=httpx.MockTransport(handler))
        with pytest.raises(ServiceError):
            c.post_raw("/send", {"x": 1})
        assert len(calls) == calls_expected, (outcome, idempotent)
