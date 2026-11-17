"""E-EDCB-2 (D-1044): ``POST /api/edc/events/v1`` on the console's EDC door, against the trial database.

The owner's brief (D-1060): a bad signature is 401; a wrong spec is 400; the same id twice is one re-read (the second
answers 200 with ``fresh: false``); a re-read that fails is 503 and the id is not recorded; no storage is 503.
D-1033 stands: this route is for the owner's EDC only, not a REDCap Data Entry Trigger.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

import pytest
from edc_backend import linkmap
from edc_backend import store as door
from fastapi.testclient import TestClient

from tests.console.test_console_app import box  # noqa: F401 - the fixture is used by name

SECRET = "edc-event-secret-for-tests"
EVENT = {"spec": "trialbox.edc.event.v1", "id": "evt-42", "type": "record.saved", "project_id": "proj-1",
         "record_id": "1001", "occurred_at": "2026-11-17T09:00:00+08:00", "data": {"instrument": "dm"}}  # fmt: skip


def _post(c: TestClient, doc: dict[str, Any], secret: str = SECRET) -> Any:
    raw = json.dumps(doc).encode()
    sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return c.post("/api/edc/events/v1", content=raw, headers={"x-trialbox-signature": sig})


@pytest.fixture
def door_app(box: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db_url: str) -> dict[str, Any]:  # noqa: F811
    folder = tmp_path / "edc"
    monkeypatch.setenv("TB_EDC_EVENT_DIR", str(folder))
    monkeypatch.setenv("TB_EDC_EVENT_SECRET", SECRET)
    linkmap.save(str(folder), {"studies": {"GZQO": "proj-1"}})
    reads: list[str] = []
    box["reads"] = reads
    import console.study_setup as setup

    monkeypatch.setattr(setup, "read_now", lambda h, study: reads.append(study))
    return box


def test_the_same_id_twice_is_one_reread(door_app: dict[str, Any], db_url: str) -> None:
    c = TestClient(door_app["app"])
    first, second = _post(c, EVENT), _post(c, EVENT)
    assert (first.status_code, first.json()["fresh"]) == (200, True)
    assert (second.status_code, second.json()["fresh"]) == (200, False)
    assert door_app["reads"] == ["GZQO"]
    assert [e["id"] for e in door.DoorStore(db_url).events()] == ["evt-42"]


def test_a_reread_that_fails_is_503_and_the_id_is_not_recorded(
    door_app: dict[str, Any], db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import console.study_setup as setup

    def broken(h: Any, study: str) -> None:
        raise RuntimeError("the lake is not up")

    monkeypatch.setattr(setup, "read_now", broken)
    c = TestClient(door_app["app"])
    assert _post(c, EVENT).status_code == 503
    assert door.DoorStore(db_url).events() == []
    monkeypatch.setattr(setup, "read_now", lambda h, study: door_app["reads"].append(study))
    again = _post(c, EVENT)  # the EDC sends it again: now it is taken in
    assert again.status_code == 200 and again.json()["fresh"] is True and door_app["reads"] == ["GZQO"]


def test_a_bad_signature_is_401_and_a_wrong_spec_is_400(door_app: dict[str, Any]) -> None:
    c = TestClient(door_app["app"])
    assert _post(c, EVENT, secret="not-the-secret").status_code == 401
    assert _post(c, {**EVENT, "spec": "redcap.det"}).status_code == 400
    assert door_app["reads"] == []


def test_no_storage_is_503(door_app: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_DB_URL", raising=False)
    c = TestClient(door_app["app"])
    r = _post(c, EVENT)
    assert r.status_code == 503 and door_app["reads"] == []
