"""P-14 (E2E R1): the ODM export answered 502 for crc and smo: the orchestrator could not make the EDC signature key
(a PRODUCTION box without a KEK, P-28) and the console turned the refusal into "a TrialBox service did not answer".

A refusal that names a gap in the box's set-up is now a refusal (409) with the orchestrator's reason and its next
step. The class (RC9, the E2E route walk): an EDC route on a box whose EDC is not set up answers below 500."""

from __future__ import annotations

from typing import Any

import pytest
from edc.store import EdcError
from fastapi.testclient import TestClient

from tests.console.test_console_app import box  # noqa: F401 - the fixture is used by name
from tests.console.test_edc_pages import PW, _ready, eb  # noqa: F401 - the fixture is used by name

WHY = "the signature key /secrets/edc_sign.key: /secrets has no KEK: in PRODUCTION this key is made only wrapped " \
      "under it (`python -m tools.keys init`)"  # fmt: skip


def _no_key(*_a: Any, **_k: Any) -> Any:
    raise EdcError("edc.sign_key", WHY, 500)  # what edc.store.sign_key_of raises on the E2E's box


@pytest.fixture
def no_key(eb: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> TestClient:  # noqa: F811
    _ready(eb)
    monkeypatch.setattr(eb["svc"], "export_odm", _no_key)
    return TestClient(eb["app"])


def test_the_odm_export_says_the_key_is_not_set_up(no_key: TestClient) -> None:
    tok = no_key.post("/api/v1/session", json={"username": "crc", "password": PW}).json()["token"]
    r = no_key.get("/api/v1/studies/GZQO/edc/export/odm", headers={"authorization": f"Bearer {tok}"})
    assert r.status_code == 409, r.text
    assert "tools.keys init" in r.text and "edc.sign_key" in r.text


def test_a_service_fault_is_still_a_502(eb: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    _ready(eb)

    def broken(*_a: Any, **_k: Any) -> Any:
        raise EdcError("edc.internal", "something broke", 500)

    monkeypatch.setattr(eb["svc"], "export_odm", broken)
    c = TestClient(eb["app"])
    tok = c.post("/api/v1/session", json={"username": "crc", "password": PW}).json()["token"]
    assert c.get("/api/v1/studies/GZQO/edc/export/odm", headers={"authorization": f"Bearer {tok}"}).status_code == 502
