"""Fixes of the console deep review of 2026-11-13 (`docs/reviews/2026-11-13-deep/console.md`). Each test failed on the
tree the review started from. Synthetic accounts only."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.console.test_api_identity import ON, _api_login, _client
from tests.console.test_console_app import (
    VIEWER_PW,
    box,  # noqa: F401 - the fixture by name
)
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


def test_every_role_has_its_own_help_text_in_every_language() -> None:
    """CON-I18N-1: Help prints ``t('help.role.' + role)``; the steward and the privacy office had no such key in any
    language, so their Help page showed the raw key ``help.role.steward``. The viewer's text said it reads the audit
    trail, which only the steward and the privacy office open (D-451)."""
    import console.app  # noqa: F401 - the pages merge their catalogues into CATALOGUES on import
    from console.auth import ROLES
    from console.i18n import CATALOGUES

    for lang, cat in CATALOGUES.items():
        for role in ROLES:
            assert f"help.role.{role}" in cat, (lang, role)
    assert "audit" not in CATALOGUES["en"]["help.role.viewer"]
    assert "監査" not in CATALOGUES["ja"]["help.role.viewer"]
    assert "稽核" not in CATALOGUES["zh-TW"]["help.role.viewer"]


def test_the_administrators_study_view_lists_no_patient_task(box: dict[str, Any]) -> None:  # noqa: F811
    """CON-ROLE-1: D-280 keeps patient rows off the administrator's study view (``/home?view=studies``), but its task
    list still named each patient a PI had marked "Need info" and linked the patient panel, which then answered 403.
    The coordinator still gets the task."""
    from tests.console.test_amendment_rescreen import _csrf
    from tests.console.test_console_app import _done_screen, _ulid, login, login_crc, name_pi

    _done_screen(box["backend"], _ulid(9931))
    box["users"].create("pi", "investigator", "review-console-pi-0001", "pi@hospa.test")
    name_pi(box, "pi")
    pi, _ = login(box["app"], "pi", "review-console-pi-0001")
    week = pi.get("/studies/GZQO/week").text
    pid = __import__("re").search(r"pid=([0-9a-f]{32})", week).group(1)
    r = pi.post(f"/studies/GZQO/patients/{pid}/mark", data={"csrf": _csrf(week), "mark": "need_info"})
    assert r.status_code in (200, 303)
    crc, _ = login_crc(box)
    assert f"pid={pid}" in crc.get("/home").text  # the coordinator's task is there
    admin, _ = login(box["app"])
    home = admin.get("/home?view=studies").text
    assert f"pid={pid}" not in home and pid[:8] not in home
    assert 'href="/studies/GZQO/week"' not in home  # the study card's list link would be 403 too
    assert 'href="/studies/GZQO/week"' in crc.get("/home").text


@pytest.mark.parametrize("role", ["cro", "viewer", "coordinator", "investigator", "admin", "steward", "privacy"])
def test_every_link_of_my_account_page_opens_for_its_role(box: dict[str, Any], role: str) -> None:  # noqa: F811
    """CON-ROLE-2: "My account" offered every role the notification settings; a CRO account got 403 there. Each
    link the page offers opens for the account that sees it."""
    import re

    from tests.console.test_role_pages import _user

    c = _user(box, f"acct-{role}", role)
    page = c.get("/account")
    assert page.status_code == 200
    for href in sorted(set(re.findall(r'href="(/[^"#?]*)', page.text))):
        if href.startswith(("/static/", "/logout")):
            continue
        assert c.get(href).status_code != 403, (role, href)


def test_the_audit_filter_row_wraps(box: dict[str, Any]) -> None:  # noqa: F811
    """CON-UX-2: the audit browser's seven filters sat in one inline-flex row that never wrapped, so the steward's
    page scrolled sideways by 188 to 713 px at 1366 px (measured in Chromium, en, ja and zh-TW). The row wraps."""
    import re

    from tests.console.test_role_pages import _user

    stw = _user(box, "stw-audit", "steward")
    page = stw.get("/audit").text
    assert 'class="inline filters" data-testid="audit-filter"' in page
    css = stw.get("/static/console.css").text
    assert re.search(r"form\.inline\.filters\s*\{[^}]*flex-wrap:\s*wrap", css)


def test_the_evidence_line_writes_a_unit_as_people_read_it() -> None:
    """CON-UX-3: the PI's evidence line printed the UCUM code (``187 mm[Hg]``, ``10*9/L``). The stored unit is
    unchanged; only the shown text is the printed form."""
    from console import coded_view

    def shown(unit: str) -> str:
        return str(coded_view.line({"value": 187, "unit": unit, "date": "2026-09-05"})["value"])

    assert shown("mm[Hg]") == "187 mmHg"
    assert shown("10*9/L") == "187 10^9/L"
    assert shown("[iU]/L") == "187 IU/L"
    assert shown("mg/dL") == "187 mg/dL"
