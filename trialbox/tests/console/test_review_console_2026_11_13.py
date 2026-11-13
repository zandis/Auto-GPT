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


def test_the_feasibility_report_dates_the_site_profile_on_the_site_day() -> None:
    """CON-TZ-1: the report's "entered by ..., on ..." date was the first ten characters of a UTC timestamp, so a
    profile saved at 07:30 in Taipei (23:30 UTC the day before) was dated the day before on the report and on the
    sponsor copy. The site's calendar date is shown."""
    from zoneinfo import ZoneInfo

    from console import studies as st
    from console.sitestore import SiteProfile

    site = SiteProfile(entered_by="crc", entered_at="2026-11-13T23:30:00+00:00")
    rep = st.feas_report({"funnel": []}, None, site, {}, zone=ZoneInfo("Asia/Taipei"))
    assert rep["entered"] == {"by": "crc", "at": "2026-11-14"}
    assert st.feas_report({"funnel": []}, None, site, {}, zone=ZoneInfo("Asia/Tokyo"))["entered"]["at"] == "2026-11-14"
    assert st.feas_report({"funnel": []}, None, SiteProfile(), {}, zone=ZoneInfo("Asia/Taipei"))["entered"]["at"] == ""
