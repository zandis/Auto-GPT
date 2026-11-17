"""E-EDCB-1 (D-1043): ``PUT /api/edc/map`` on the console's EDC door needs the ``redcap.connection`` permission and
the session's CSRF token. The owner's brief lists it; #813 had the check in the route but no test of the route."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.console.test_console_app import VIEWER_PW, box, login  # noqa: F401 - the fixture is used by name

MAP = {"studies": {"GZQO": "proj-1"}, "sites": {"linkou": "dag_linkou"}, "subjects": {}}


@pytest.fixture
def door(box: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:  # noqa: F811
    monkeypatch.setenv("TB_EDC_EVENT_DIR", str(tmp_path / "edc"))
    return box


def test_the_map_put_needs_the_csrf_token(door: dict[str, Any]) -> None:
    c, csrf = login(door["app"])
    assert c.put("/api/edc/map", json=MAP).status_code == 400  # no token
    assert c.put("/api/edc/map", json=MAP, headers={"x-csrf": "not-the-token"}).status_code == 400
    r = c.put("/api/edc/map", json=MAP, headers={"x-csrf": csrf})
    assert r.status_code == 200 and r.json()["studies"] == {"GZQO": "proj-1"}


def test_the_map_put_needs_the_connection_permission(door: dict[str, Any]) -> None:
    c, csrf = login(door["app"], "viewer", VIEWER_PW)
    assert c.put("/api/edc/map", json=MAP, headers={"x-csrf": csrf}).status_code == 403
    admin, _ = login(door["app"])
    assert admin.get("/api/edc/map").json()["studies"] == {}  # nothing was saved by the refused call
