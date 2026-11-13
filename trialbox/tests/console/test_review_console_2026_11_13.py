"""Fixes of the console deep review of 2026-11-13 (`docs/reviews/2026-11-13-deep/console.md`). Each test failed on the
tree the review started from. Synthetic accounts only."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from tests.console.test_api_identity import ON, _api_login, _client
from tests.console.test_console_app import VIEWER_PW
from tests.console.test_identity import Clock, _app


def test_the_api_sign_in_says_when_its_session_ends(tmp_path: Path) -> None:
    """CON-API-2: ``POST /api/v1/session`` answered ``"expires": null`` for every session, because the session object
    has no such field. A client must know when its token stops working: the absolute end and the idle limit."""
    clock = Clock()
    app, users, _ = _app(tmp_path, clock, **ON)
    r = _api_login(_client(app), "viewer", VIEWER_PW)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["expires"] is not None
    end = datetime.fromisoformat(body["expires"])
    assert end.tzinfo is not None
    assert end == (clock() + users.absolute).replace(microsecond=0)
    assert body["idle_minutes"] == int(users.idle / timedelta(minutes=1))
