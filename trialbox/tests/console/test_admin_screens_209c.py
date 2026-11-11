# ruff: noqa: F811 - the ob fixture is imported from test_ops_pages and taken by name
"""T-209c (D-406; review ROLE-021, ROLE-022, OPS-059): the administrator's remaining screens.

Acceptance: an administrator reaches Unlock in two clicks from ``/admin`` (the Accounts tile's link, then the row's
Unlock button). Also: the backup and update tiles, the links to ``/ops/identity`` and ``/ops/flags``, the
unused-account report and its Monday mail, and the end date of a local account. Synthetic accounts only."""

from __future__ import annotations

import html
import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from console import admin_accounts, admin_i18n, notify
from console.auth import AuthError, User
from console.sitestore import NotifyPerson
from tb_common.metrics import Check, Health

from tests.console.test_console_app import login
from tests.console.test_ops_pages import PW, ob  # noqa: F401 - the fixture is used by name


def _events(audit_dir: Path, name: str) -> list[dict[str, Any]]:
    out = [json.loads(x) for f in sorted(audit_dir.glob("*.jsonl")) for x in f.read_text().splitlines() if x]
    return [e for e in out if e.get("event") == name]


def _tile(page: str, testid: str) -> str:
    start = page.index(f'data-testid="{testid}"')
    return page[start : page.index("</section>", start)]


# ---------------------------------------------------------------------------------------------- the acceptance test
def test_admin_reaches_unlock_in_two_clicks_from_admin(ob: dict[str, Any]) -> None:
    us = ob["users"]
    for _ in range(5):  # five wrong tries from one address lock the account (D-279)
        us.record_failure("coord", "198.51.100.7")
    assert us.locked_until("coord", None) is not None
    c, _ = login(ob["app"])
    admin = c.get("/admin").text
    tile = _tile(admin, "tile-accounts")
    assert 'data-testid="tile-accounts-locked"' in tile and "coord" in tile
    link = re.search(r'href="([^"]+)" data-testid="identity-link"', tile)
    assert link and link.group(1) == "/ops/identity"
    page = c.get(link.group(1))  # click 1
    assert page.status_code == 200
    form = re.search(
        r'<form method="post" action="(/ops/identity)" class="inline"><input type="hidden" name="csrf" value="([^"]+)">'
        r'<input type="hidden" name="action" value="unlock"><input type="hidden" name="username" value="coord">'
        r'<button type="submit" class="secondary" data-testid="unlock-coord">',
        page.text,
    )
    assert form, "the Unlock button of the locked row"
    r = c.post(form.group(1), data={"csrf": html.unescape(form.group(2)), "action": "unlock", "username": "coord"})
    assert r.status_code == 200 and 'data-testid="identity-done"' in r.text  # click 2: done
    assert us.locked_until("coord", None) is None
    assert [e["detail"]["user"] for e in _events(ob["audit"], "console.unlock")] == ["coord"]
    assert 'data-testid="tile-accounts-locked"' not in c.get("/admin").text


def test_the_accounts_tile_links_identity_flags_and_the_report_and_users_rows_link_identity(ob: dict[str, Any]) -> None:
    c, _ = login(ob["app"])
    tile = _tile(c.get("/admin").text, "tile-accounts")
    for href in ("/ops/users", "/ops/identity", "/admin/accounts", "/ops/flags"):
        assert f'href="{href}"' in tile, href
    assert c.get("/ops/flags").status_code == 200
    users = c.get("/ops/users").text
    assert 'id="u-coord"' in users and 'href="/ops/identity#u-coord" data-testid="users-identity-coord"' in users
    assert 'id="u-coord"' in c.get("/ops/identity").text  # the link lands on the row


# ---------------------------------------------------------------------------------------------- backup and update
def test_backup_and_update_tiles_show_the_state_and_link_to_the_operations_tabs(ob: dict[str, Any]) -> None:
    c, csrf = login(ob["app"])
    page = c.get("/admin").text
    backup, update = _tile(page, "tile-backup"), _tile(page, "tile-update")
    assert 'class="pill bad" data-testid="tile-ops-backup"' in backup and "no backup yet" in backup
    assert 'href="/admin/ops?tab=backups"' in backup and 'data-testid="tile-backup-verified"' in backup
    assert 'data-testid="tile-update-none"' in update and 'href="/admin/ops?tab=update"' in update
    assert "0 bundles waiting" in update
    assert "come with the hospital installation" not in page and 'data-testid="admin-health-where"' in page
    c.post("/admin/ops/backup", data={"csrf": csrf, "confirm": "yes"})
    c.post("/admin/ops/backup_check", data={"csrf": csrf, "confirm": "yes"})
    backup = _tile(c.get("/admin").text, "tile-backup")
    assert 'class="pill ok" data-testid="tile-ops-backup"' in backup and re.search(r"[\d.]+ hours ago", backup)
    assert '<span class="pill ok">done</span>' in backup  # the last check, run from the console
    ja = c.post("/lang", data={"lang": "ja", "csrf": csrf}, follow_redirects=True)
    assert ja.status_code == 200
    assert "バックアップの鍵による確認" in c.get("/admin").text


# ---------------------------------------------------------------------------------------------- the report page
@pytest.mark.parametrize("who", ["coord", "viewe"])
def test_the_report_is_refused_to_other_roles(ob: dict[str, Any], who: str) -> None:
    c, _ = login(ob["app"], who, PW)
    assert c.get("/admin/accounts").status_code == 403
    assert "/admin/accounts" in [e["detail"]["action"] for e in _events(ob["audit"], "console.denied")]


def test_the_report_page_lists_unused_ending_and_open_ended_accounts(ob: dict[str, Any]) -> None:
    us = ob["users"]
    today = us.today()
    us.set_scope("cro", "cro", "GZQO", (today + timedelta(days=5)).isoformat())
    us.db.execute("UPDATE users SET created = ? WHERE username = 'viewe'",
                  ((datetime.now(UTC) - timedelta(days=90)).isoformat(),))  # fmt: skip
    c, _ = login(ob["app"])
    page = c.get("/admin/accounts")
    assert page.status_code == 200
    rows = {m.group(1): m.group(2) for m in re.finditer(r'<tr data-user="([^"]+)">(.*?)</tr>', page.text, re.S)}
    assert 'data-why="ending"' in rows["cro"] and "(5 days)" in rows["cro"]
    assert 'data-why="unused"' in rows["viewe"] and "never signed in" in rows["viewe"]
    assert 'data-why="no_end"' in rows["coord"]  # made before the end-date rule: no end date
    assert "admin" not in rows  # signed in just now, no end date needed
    assert us.activity()["admin"][1] is not None  # the sign-in is recorded (auth migration 4)
    tile = _tile(c.get("/admin").text, "tile-accounts")
    assert re.search(r"Unused \d+ · ending soon 1 · no end date \d+", tile)


def test_report_rules_on_fixed_dates() -> None:
    now = datetime(2026, 11, 9, 1, tzinfo=UTC)
    today = date(2026, 11, 9)
    users = [
        User("a.recent", "coordinator", None, expires="2027-06-30"),
        User("b.idle", "coordinator", None, expires="2027-06-30"),
        User("c.ending", "investigator", None, expires="2026-11-23"),
        User("d.open", "viewer", None),
        User("e.admin", "admin", None),
        User("f.sso", "viewer", None),
    ]
    act = {
        "a.recent": ("2026-01-01T00:00:00+00:00", "2026-11-01T00:00:00+00:00"),
        "b.idle": ("2026-01-01T00:00:00+00:00", "2026-09-10T00:00:00+00:00"),  # 60 days before now
        "c.ending": ("2026-01-01T00:00:00+00:00", "2026-11-08T00:00:00+00:00"),
        "d.open": ("2026-11-01T00:00:00+00:00", None),
        "e.admin": ("2026-01-01T00:00:00+00:00", "2026-11-08T00:00:00+00:00"),
        "f.sso": ("2026-11-01T00:00:00+00:00", "2026-11-08T00:00:00+00:00"),
    }
    rep = admin_accounts.report(users, act, ["f.sso"], now, today)
    got = {r["username"]: (r["unused"], r["ending"], r["no_end"]) for r in rep["rows"]}
    assert got == {"b.idle": (True, False, False), "c.ending": (False, True, False), "d.open": (False, False, True)}
    assert rep["unused"] == 1 and rep["ending"] == 1 and rep["no_end"] == 1
    lines = admin_accounts.mail_lines(rep, "en")
    assert lines[1].startswith("- b.idle (") and lines[1].endswith(": not used for 60 days")
    assert any("c.ending" in x and "ends 2026-11-23 (14 days)" in x for x in lines)
    assert admin_accounts.mail_lines({"rows": []}, "ja")[-1] == "- なし"


# ---------------------------------------------------------------------------------------------- end dates
def test_end_date_rule() -> None:
    today = date(2026, 11, 11)
    assert admin_accounts.end_date("coordinator", None, today) == "2027-11-11"
    assert admin_accounts.end_date("coordinator", "2027-01-31", today) == "2027-01-31"
    assert admin_accounts.end_date("admin", None, today) is None
    assert admin_accounts.end_date("viewer", "2030-01-01", today, sso=True) == "2030-01-01"
    for role in ("coordinator", "admin"):
        with pytest.raises(AuthError, match="at most 365 days"):
            admin_accounts.end_date(role, "2027-11-12", today)


def test_a_new_local_account_gets_an_end_date_within_twelve_months(ob: dict[str, Any]) -> None:
    us = ob["users"]
    c, csrf = login(ob["app"])
    r = c.post("/ops/users", data={"csrf": csrf, "action": "add", "username": "smo.a", "role": "coordinator"},
               follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    made = next(u for u in us.users() if u.username == "smo.a")
    assert made.expires == (us.today() + timedelta(days=365)).isoformat()
    far = (us.today() + timedelta(days=400)).isoformat()
    r = c.post("/ops/users", data={"csrf": csrf, "action": "add", "username": "smo.b", "role": "viewer",
                                   "expires": far})  # fmt: skip
    assert r.status_code == 400 and "at most 365 days" in r.text
    r = c.post("/ops/users", data={"csrf": csrf, "action": "scope", "username": "smo.a", "affiliation": "smo",
                                   "studies": "GZQO", "expires": ""}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and next(u for u in us.users() if u.username == "smo.a").expires
    r = c.post("/ops/users", data={"csrf": csrf, "action": "add", "username": "adm.b", "role": "admin"},
               follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and next(u for u in us.users() if u.username == "adm.b").expires is None


# ---------------------------------------------------------------------------------------------- the Monday mail
def test_the_health_mail_carries_the_report_on_mondays_only() -> None:
    hl = Health(datetime(2026, 11, 9, tzinfo=UTC), (Check("backup", "ok", "backup 3 h old", 3.0),))
    person = NotifyPerson("admin", None, "07:00", True, "zh-TW")
    rep = {"rows": [{"username": "b.idle", "role": "viewer", "unused": True, "never": True, "idle_days": None,
                     "ending": False, "no_end": False, "expires": "", "days_left": None}]}  # fmt: skip
    admin = User("admin", "admin", "admin@hospa.test")
    n = notify.build_health(admin, person, date(2026, 11, 9), hl, rep)
    assert "b.idle" in n.body and "從未登入" in n.body and "需檢視的帳號" in n.body

    class Store:
        def notify_person(self, name: str) -> NotifyPerson:
            return person

        def notice_sent(self, *a: Any) -> bool:
            return False

    class Users:
        def users(self) -> list[User]:
            return [admin]

    class H:
        store, users = Store(), Users()

        def health(self) -> Health:
            return hl

        def accounts_report(self) -> dict[str, Any]:
            return rep

    monday = notify.collect(H(), date(2026, 11, 9), ("HEALTH",))
    tuesday = notify.collect(H(), date(2026, 11, 10), ("HEALTH",))
    assert "b.idle" in monday[0].body and "b.idle" not in tuesday[0].body


def test_every_new_string_is_in_three_languages() -> None:
    assert set(admin_i18n.EN) == set(admin_i18n.JA) == set(admin_i18n.ZH)
    for cat in (admin_i18n.JA, admin_i18n.ZH):
        for k, v in cat.items():
            assert set(re.findall(r"{(\w+)}", v)) == set(re.findall(r"{(\w+)}", admin_i18n.EN[k])), k
