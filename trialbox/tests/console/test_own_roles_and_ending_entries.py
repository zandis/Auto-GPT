"""9f-1 and 9f-4 (a), D-1382: the account page lists the signed-in person's own roles per study; a delegation entry
that ends within 14 site days is warned about on the log page and on its person's own account page."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest
from console.i18n import CATALOGUES
from console.teamstore import ENDING_DAYS, Entry

from tests.console.test_console_app import (  # noqa: F401 - the fixture is used by name
    box,
    login,
)
from tests.console.test_role_pages import _user

# 00:30 on 2026-11-10 at the site; in UTC it is still 2026-11-09
TOKYO_0030 = datetime(2026, 11, 9, 15, 30, tzinfo=UTC)
TAIPEI_0030 = datetime(2026, 11, 9, 16, 30, tzinfo=UTC)


def _entry(h: Any, user: str | None, role: str, start: str, end: str | None, tasks: tuple[str, ...] = (),
           rs: str = "GZQO", name: str = "") -> int:  # fmt: skip
    return int(h.team.add_entry(rs, username=user, name=name or user or "x", role=role, tasks=tasks, start=start, end=end,
                                training_day="2026-01-01", training_ref="GCP-1", by="admin",
                                at="2026-01-01T00:00:00+00:00"))  # fmt: skip


def _noon(h: Any, day: str) -> None:
    h.clock = lambda: datetime.fromisoformat(f"{day}T03:00:00+00:00")  # noon in Tokyo, 11:00 in Taipei: the same day


def test_days_left_is_14_not_15_and_counts_the_last_day() -> None:
    def e(end: str | None, start: str = "2026-01-01") -> Entry:
        return Entry(1, "GZQO", "u", "U", "sub_pi", (), start, end, None, None, "s", "t", "s", "t")

    today = date(2026, 11, 10)
    assert ENDING_DAYS == 14
    assert e("2026-11-24").days_left(today) == 14  # 14 days ahead: warned
    assert e("2026-11-25").days_left(today) is None  # 15 days ahead: not yet
    assert e("2026-11-10").days_left(today) == 0  # the last day itself
    assert e("2026-11-09").days_left(today) is None  # over
    assert e(None).days_left(today) is None  # no end
    assert e("2026-11-20", start="2026-11-11").days_left(today) is None  # not started


def test_each_role_sees_only_its_own_roles(box: dict[str, Any]) -> None:  # noqa: F811
    h = box["app"].state.helpers
    pi = _user(box, "drsato", "investigator")
    sub = _user(box, "drkato", "investigator")
    other = _user(box, "drito", "investigator")
    _entry(h, "drsato", "pi", "2026-01-01", None)
    _entry(h, "drkato", "sub_pi", "2026-01-01", None, ("screen", "refer"))
    _entry(h, "drito", "sub_pi", "2026-01-01", None, ("enter_data",))
    pa, sa, oa = (c.get("/account").text for c in (pi, sub, other))
    assert 'data-testid="role-GZQO-pi"' in pa and 'data-testid="role-GZQO-sub_pi"' not in pa
    assert "See candidates" not in pa and "all study tasks" in pa
    assert 'data-testid="role-GZQO-sub_pi"' in sa and 'data-testid="role-GZQO-pi"' not in sa
    assert "See candidates, Ask a treating doctor" in sa and "Enter data" not in sa
    assert "Enter data" in oa and "See candidates" not in oa
    for page, others in ((pa, ("drkato", "drito")), (sa, ("drsato", "drito")), (oa, ("drsato", "drkato"))):
        assert all(n not in page for n in others)  # nobody else's name or entry


def test_an_ended_or_unnamed_entry_is_not_a_role(box: dict[str, Any]) -> None:  # noqa: F811
    h = box["app"].state.helpers
    sub = _user(box, "drkato", "investigator")
    _entry(h, "drkato", "sub_pi", "2025-01-01", "2025-12-31", ("screen",))  # over
    _entry(h, "drkato", "sub_pi", "2099-01-01", None, ("screen",))  # not yet
    page = sub.get("/account").text
    assert 'data-testid="account-roles-none"' in page and "role-GZQO" not in page


@pytest.mark.parametrize("who", ["admin", "viewer", "coordinator", "cro"])
def test_a_person_with_no_entry_or_study_gets_the_plain_sentence(box: dict[str, Any], who: str) -> None:  # noqa: F811
    if who in ("admin", "viewer"):
        c = _user(box, f"x{who}", who)
    elif who == "coordinator":
        c = _user(box, "crc9", "coordinator")
    else:
        c = _user(box, "cro9", "cro", affiliation="cro", studies="GZQO")
    r = c.get("/account")
    assert r.status_code == 200 and 'data-testid="account-roles-none"' in r.text, who
    assert "Your role in each study" in r.text


def test_a_person_scoped_to_no_known_study_sees_no_role(box: dict[str, Any]) -> None:  # noqa: F811
    h = box["app"].state.helpers
    c = _user(box, "drkato", "investigator", studies="OTHER9")
    _entry(h, "drkato", "sub_pi", "2026-01-01", None, ("screen",))
    assert (
        'data-testid="account-roles-none"' in c.get("/account").text
    )  # the log names GZQO, which this account cannot see


def test_the_warning_shows_at_14_days_and_not_at_15(box: dict[str, Any]) -> None:  # noqa: F811
    h = box["app"].state.helpers
    pi = _user(box, "drsato", "investigator")
    sub = _user(box, "drkato", "investigator")
    _entry(h, "drsato", "pi", "2026-01-01", None)
    eid = _entry(h, "drkato", "sub_pi", "2026-01-01", "2026-11-24", ("screen",), name="Dr Kato")
    _noon(h, "2026-11-10")  # the last day is 14 days off
    log = pi.get("/studies/GZQO/team").text
    assert f'data-testid="ending-{eid}"' in log and "ends in 14 days (last day 2026-11-24)" in log
    assert "Dr Kato" in log.split('data-testid="ending-soon"')[1].split("</section>")[0]
    assert 'data-testid="role-ending-GZQO-sub_pi"' in sub.get("/account").text
    _noon(h, "2026-11-09")  # 15 days off: not yet
    assert 'data-testid="ending-soon"' not in pi.get("/studies/GZQO/team").text
    assert "role-ending-" not in sub.get("/account").text
    _noon(h, "2026-11-24")  # the last day
    assert "ends today" in pi.get("/studies/GZQO/team").text
    _noon(h, "2026-11-25")  # over: the entry is ended, no warning
    assert 'data-testid="ending-soon"' not in pi.get("/studies/GZQO/team").text


@pytest.mark.parametrize(
    "tz,instant", [("Asia/Tokyo", TOKYO_0030), ("Asia/Taipei", TAIPEI_0030)], ids=["tokyo", "taipei"]
)
def test_the_warning_uses_the_site_day_not_the_servers(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    tz: str,
    instant: datetime,
) -> None:
    pytest.importorskip("zoneinfo")
    h = box["app"].state.helpers
    from console.timefmt import site_zone

    monkeypatch.setenv("TB_TZ", tz)
    assert site_zone(h.bk).key == tz
    pi = _user(box, "drsato", "investigator")
    _entry(h, "drsato", "pi", "2026-01-01", None)
    eid = _entry(h, None, "other", "2026-01-01", "2026-11-24", name="Nurse Ito")  # 14 days from the site's 11-10
    h.clock = lambda: instant
    assert h.clock().date() == date(2026, 11, 9)  # UTC still says the 9th: 15 days, no warning, if UTC were used
    assert f'data-testid="ending-{eid}"' in pi.get("/studies/GZQO/team").text


def test_the_warning_is_not_shown_to_someone_who_cannot_see_the_entry(box: dict[str, Any]) -> None:  # noqa: F811
    h = box["app"].state.helpers
    _user(box, "drsato", "investigator")
    cro = _user(box, "cro9", "cro", affiliation="cro", studies="GZQO")
    out = _user(box, "drout", "investigator", studies="OTHER9")
    viewer = _user(box, "view9", "viewer")
    eid = _entry(h, "drsato", "pi", "2026-01-01", "2026-11-24", name="Dr Sato")
    _noon(h, "2026-11-10")
    for c in (cro, out):  # the log page refuses or hides the study: nothing of the entry is in the answer
        r = c.get("/studies/GZQO/team")
        assert r.status_code in (403, 404) and "Dr Sato" not in r.text and "ending-soon" not in r.text
    assert "Dr Sato" not in cro.get("/account").text and "Dr Sato" not in out.get("/account").text
    assert "role-ending" not in viewer.get("/account").text
    assert f"ending-{eid}" not in viewer.get("/account").text


def test_the_texts_exist_in_three_languages() -> None:
    keys = [k for k in CATALOGUES["en"] if k.startswith(("team.mine.", "team.ending."))]
    assert len(keys) == 9
    for lang in ("ja", "zh-TW"):
        assert all(k in CATALOGUES[lang] and CATALOGUES[lang][k] != CATALOGUES["en"][k] for k in keys), lang
    for k in ("team.ending.days", "team.ending.today"):
        assert all("{end}" in CATALOGUES[lang][k] for lang in CATALOGUES), k


def test_a_crc_entry_with_a_ticked_task_shows_it_on_that_persons_page_only(box: dict[str, Any]) -> None:  # noqa: F811
    h = box["app"].state.helpers
    crc = _user(box, "crc7", "coordinator")
    sub = _user(box, "drkato", "investigator")
    _entry(h, "crc7", "crc", "2026-01-01", None, ("screen",))
    _entry(h, "drkato", "sub_pi", "2026-01-01", None, ("enter_data",))
    page = crc.get("/account").text
    line = page.split('data-testid="role-GZQO-crc"')[1].split("</li>")[0]
    assert "See candidates" in line  # the task label the delegation-log page uses
    other = sub.get("/account").text
    assert "role-GZQO-crc" not in other and "See candidates" not in other and "crc7" not in other


def test_a_name_with_markup_is_escaped_on_the_log_and_account_pages(box: dict[str, Any]) -> None:  # noqa: F811
    h = box["app"].state.helpers
    pi = _user(box, "drsato", "investigator")
    _entry(h, "drsato", "pi", "2026-01-01", None)
    _entry(h, None, "other", "2026-01-01", "2026-11-24", name="<script>alert(1)</script>")
    _noon(h, "2026-11-10")
    log = pi.get("/studies/GZQO/team").text
    assert "<script>alert(1)</script>" not in log and "&lt;script&gt;alert(1)&lt;/script&gt;" in log
    assert 'data-testid="ending-soon"' in log
    # the account page prints the person's own entries; a markup name on an own entry must not come through raw
    _entry(h, "drsato", "sub_pi", "2026-01-01", None, ("screen",), name="<script>alert(2)</script>")
    acc = pi.get("/account").text
    assert "alert(2)" not in acc  # the account page does not print an entry name; if it ever does, it must escape it


def test_a_monitor_sees_its_own_grant_and_ending_warning_on_the_account_page_only(box: dict[str, Any]) -> None:  # noqa: F811
    h = box["app"].state.helpers
    _user(box, "drsato", "investigator")
    mon = _user(box, "mon9", "cro", affiliation="cro", studies="GZQO")
    _entry(h, "drsato", "pi", "2026-01-01", None, name="Dr Sato")
    eid = _entry(h, "mon9", "monitor", "2026-01-01", "2026-11-24", name="CRA Nine")
    _noon(h, "2026-11-10")
    assert mon.get("/studies/GZQO/team").status_code == 403  # the log page stays closed to a monitor
    acc = mon.get("/account").text
    assert 'data-testid="role-GZQO-monitor"' in acc and 'data-testid="role-ending-GZQO-monitor"' in acc
    assert "ends in 14 days (last day 2026-11-24)" in acc
    assert "Dr Sato" not in acc and "drsato" not in acc and f"ending-{eid}" not in acc  # nothing else of the log
    assert 'data-testid="role-GZQO-pi"' not in acc
